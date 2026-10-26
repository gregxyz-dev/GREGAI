"""
training/bench_chat.py

Benchmark modeli ROZMOWY (krok 2) na tej maszynie, tak jak woła je
produkcja: pełny prompt systemowy z agent/prompt.md (osobowość + blok
narzędzi) albo krótki prompt ucznia (--student-prompt), te same opcje
(temperature, num_ctx, num_predict=200), prawdziwe pytania z zestawu
sondującego (data/training/student_probe.jsonl) albo własne (--prompts).

Mierzy z pól Ollamy: czas przetwarzania promptu, czas generowania,
tokeny/s, długość odpowiedzi, i zapisuje WSZYSTKIE odpowiedzi do
przejrzenia ręcznie: szybkość bez jakości nic nie znaczy, a jakość
rozmowy po polsku ocenia człowiek, nie skrypt. Dodatkowo: filtr stylu z
agent/persona.py (ile odpowiedzi łamie zasady "mów jak człowiek").

Lekcja z 2026-10-07: benchmark bez prawdziwego promptu systemowego
kłamał (gemma2:2b "10x szybsza" na gołym prompcie, w produkcji tak samo
wolna jak qwen2.5:3b). Dlatego tu domyślnie PEŁNY prompt, nie goły.

Użycie (po instalacji na laptopie, patrz INSTALACJA_UBUNTU_26_04.md, Krok 10):
  python3 training/bench_chat.py --models qwen2.5:3b,qwen2.5:7b
  python3 training/bench_chat.py --models gregai-student --student-prompt
  python3 training/bench_chat.py --models qwen2.5:3b --limit 5   # szybki test

Modele, których nie ma, skrypt próbuje pobrać (ollama pull), chyba że
--no-pull. Każdy model jest wyładowywany po teście, żeby kolejny mierzył
się na czystej RAM (lekcja z phi3.5, 2026-10-07).

Wyjście: data/training/bench_chat.json (surowe) i bench_chat.md (do
czytania), stdlib only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from env_loader import load_env  # noqa: E402

load_env()

import capabilities as cap_mod  # noqa: E402
import fsutil  # noqa: E402
import persona  # noqa: E402
import netguard  # noqa: E402
import router as router_mod  # noqa: E402

DATA_DIR = ROOT / "data" / "training"
PROBE = DATA_DIR / "student_probe.jsonl"
PROMPT_MD = ROOT / "agent" / "prompt.md"

DEFAULT_PROMPTS = [
    "Cześć, co u Ciebie?",
    "Co sądzisz o tym, żeby wrzucać filmy na YouTube codziennie?",
    "Mam pięć projektów naraz i nie wiem, który skończyć pierwszy. Doradź.",
    "Jestem dziś zmęczony i nic mi nie wychodzi.",
    "Wyślij maila do klienta, że strona jest gotowa.",
    "Kto Cię stworzył?",
    "Wytłumacz mi prosto, czym jest koszt alternatywny.",
    "Zrób to.",
]


def full_system_prompt() -> str:
    base = PROMPT_MD.read_text(encoding="utf-8")
    return base.replace("{TOOLS_BLOCK}", cap_mod.assemble_tools_prompt())


def _get(host: str, path: str, timeout: float = 5.0) -> dict:
    with netguard.local_urlopen(host.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(host: str, path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(host.rstrip("/") + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with netguard.local_urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def installed(host: str) -> set[str]:
    try:
        return {m.get("name") for m in _get(host, "/api/tags").get("models", [])}
    except Exception:
        return set()


def ensure_model(host: str, model: str, pull: bool) -> bool:
    names = installed(host)
    if model in names or f"{model}:latest" in names:
        return True
    if not pull:
        print(f"  {model}: brak w Ollamie (--no-pull), pomijam")
        return False
    # Pobieranie z rejestru Ollamy idzie przez internet, więc tylko przez WARP (jak cała reszta projektu).
    allowed, why = netguard.internet_allowed()
    if not allowed:
        print(f"  {model}: nie pobieram, {why}")
        return False
    print(f"  {model}: pobieram (ollama pull)...", flush=True)
    proc = subprocess.run(["ollama", "pull", model], text=True)
    return proc.returncode == 0


def loaded(host: str) -> set[str]:
    """Modele aktualnie w RAM (nie wszystkie zainstalowane)."""
    try:
        return {m.get("name") for m in _get(host, "/api/ps").get("models", []) if m.get("name")}
    except Exception:
        return set()


def unload(host: str, model: str) -> None:
    try:
        _post(host, "/api/generate", {"model": model, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def ask(host: str, model: str, system: str, user: str, timeout: float, num_ctx: int) -> dict:
    options = {"temperature": router_mod.OLLAMA_TEMPERATURE, "num_predict": 200, "num_ctx": num_ctx}
    data = _post(host, "/api/chat", {
        "model": model, "stream": False, "keep_alive": "10m", "options": options,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }, timeout=timeout)
    reply = (data.get("message", {}).get("content") or "").strip()
    gen_tokens = data.get("eval_count") or 0
    gen_s = (data.get("eval_duration") or 0) / 1e9
    return {
        "user": user, "reply": reply,
        "prompt_tokens": data.get("prompt_eval_count"),
        "prompt_s": round((data.get("prompt_eval_duration") or 0) / 1e9, 2),
        "gen_tokens": gen_tokens, "gen_s": round(gen_s, 2),
        "tok_per_s": round(gen_tokens / gen_s, 2) if gen_s else None,
        "total_s": round((data.get("total_duration") or 0) / 1e9, 2),
        "load_s": round((data.get("load_duration") or 0) / 1e9, 2),
        "style_problems": persona.violates_style(reply),
    }


def bench_model(host: str, model: str, system: str, prompts: list[str], timeout: float, num_ctx: int) -> dict:
    rows = []
    # Pierwsze wywołanie płaci wczytanie modelu: mierzone osobno (load_s),
    # w statystykach liczymy prompt_s/gen_s, które są od tego niezależne.
    for i, p in enumerate(prompts, start=1):
        try:
            row = ask(host, model, system, p, timeout, num_ctx)
        except Exception as e:
            row = {"user": p, "reply": "", "error": f"{type(e).__name__}: {e}"}
        rows.append(row)
        if "error" in row:
            print(f"  [{i}/{len(prompts)}] BŁĄD {row['error']}", flush=True)
        else:
            print(f"  [{i}/{len(prompts)}] prompt {row['prompt_s']:6.1f}s  gen {row['gen_s']:6.1f}s  "
                  f"{row['tok_per_s'] or 0:5.1f} tok/s  {p[:45]!r} -> {row['reply'][:60]!r}", flush=True)
    good = [r for r in rows if "error" not in r and r.get("gen_s")]
    # Pierwsze pytanie przetwarza cały prompt systemowy od zera (tak jest
    # po starcie, zanim rozgrzewanie skończy); kolejne mają go już w
    # pamięci podręcznej Ollamy (tak wygląda zwykła rozmowa).
    warm = [r for r in good if r is not rows[0]]
    return {
        "prompt_s_first": rows[0].get("prompt_s") if rows and "error" not in rows[0] else None,
        "prompt_s_warm": statistics.fmean(r["prompt_s"] for r in warm) if warm else None,
        "total_s_first": rows[0].get("total_s") if rows and "error" not in rows[0] else None,
        "total_s_warm": statistics.fmean(r["total_s"] for r in warm) if warm else None,
        "model": model, "n": len(rows), "errors": sum(1 for r in rows if "error" in r),
        "prompt_tokens": statistics.fmean(r["prompt_tokens"] for r in good) if good else None,
        "prompt_s_avg": statistics.fmean(r["prompt_s"] for r in good) if good else None,
        "gen_s_avg": statistics.fmean(r["gen_s"] for r in good) if good else None,
        "tok_per_s_avg": statistics.fmean(r["tok_per_s"] for r in good if r["tok_per_s"]) if good else None,
        "total_s_avg": statistics.fmean(r["total_s"] for r in good) if good else None,
        "load_s_first": rows[0].get("load_s") if rows else None,
        "style_violations": sum(1 for r in good if r["style_problems"]),
        "avg_reply_chars": statistics.fmean(len(r["reply"]) for r in good) if good else None,
        "rows": rows,
    }


def write_markdown(results: list[dict], system_label: str, path: Path) -> None:
    lines = [f"# Benchmark rozmowy ({system_label})", "",
             "| model | n | prompt tok. | prompt s | gen s | tok/s | całość s | pierwsza (zimna) s | kolejne (ciepłe) s | styl: naruszenia | błędy |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        f = lambda v, d=1: "-" if v is None else f"{v:.{d}f}"
        lines.append(f"| {r['model']} | {r['n']} | {f(r['prompt_tokens'], 0)} | {f(r['prompt_s_avg'])} | {f(r['gen_s_avg'])} "
                     f"| {f(r['tok_per_s_avg'])} | {f(r['total_s_avg'])} | {f(r.get('total_s_first'), 0)} "
                     f"| {f(r.get('total_s_warm'), 0)} | {r['style_violations']} | {r['errors']} |")
    lines += ["", "Czytaj odpowiedzi poniżej: szybkość bez jakości nic nie znaczy.", ""]
    for r in results:
        lines += [f"## {r['model']}", ""]
        for row in r["rows"]:
            lines.append(f"**{row['user']}**")
            lines.append("")
            lines.append(row.get("reply") or f"(błąd: {row.get('error')})")
            if row.get("style_problems"):
                lines.append(f"\n_styl: {', '.join(row['style_problems'])}_")
            lines.append("")
    fsutil.atomic_write_text(path, "\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True, help="lista po przecinku, np. qwen2.5:3b,qwen2.5:7b")
    ap.add_argument("--host", default=router_mod.OLLAMA_HOST)
    ap.add_argument("--prompts", help="plik .txt (jedna linia = jedno pytanie) albo .jsonl z polem user")
    ap.add_argument("--limit", type=int, default=0, help="użyj tylko N pierwszych pytań")
    ap.add_argument("--student-prompt", action="store_true", help="krótki prompt ucznia zamiast pełnego prompt.md")
    ap.add_argument("--no-pull", action="store_true")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--out", default=str(DATA_DIR / "bench_chat"))
    args = ap.parse_args()

    # Pomiar czasu odpowiedzi w trakcie treningu (CPU i RAM zajęte) dałby zafałszowane liczby,
    # a drugi duży model w pamięci mógłby dobić trening (OOM).
    lock_path = ROOT / "training" / ".work" / ".train.lock"
    if lock_path.exists():
        try:
            import fcntl
            with open(lock_path, "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Trwa trening GREGAI (blokada training/.work/.train.lock): pomiar teraz byłby zafałszowany "
                  "i mógłby zabrać pamięć treningowi. Poczekaj na koniec treningu.")
            return 75
        except OSError:
            pass

    if args.prompts:
        p = Path(args.prompts)
        if p.suffix == ".jsonl":
            prompts = [json.loads(l)["user"] for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        else:
            prompts = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    elif PROBE.exists():
        prompts = [json.loads(l)["user"] for l in PROBE.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        prompts = DEFAULT_PROMPTS
    if args.limit:
        prompts = prompts[:args.limit]

    system = persona.student_system_prompt() if args.student_prompt else full_system_prompt()
    label = f"prompt ucznia, {len(system)} znaków" if args.student_prompt else f"pełny prompt.md, {len(system)} znaków"
    # To samo okno co w produkcji (router.py): pełny prompt = okno dużego
    # modelu, prompt ucznia = okno małych modeli.
    num_ctx = router_mod.SMALL_NUM_CTX if args.student_prompt else router_mod.OLLAMA_NUM_CTX
    print(f"Benchmark: {len(prompts)} pytań, {label}, num_ctx {num_ctx}")

    results = []
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        if not ensure_model(args.host, model, pull=not args.no_pull):
            continue
        for m in loaded(args.host):
            unload(args.host, m)  # czysta RAM przed każdym modelem
        print(f"\n== {model}")
        t0 = time.monotonic()
        res = bench_model(args.host, model, system, prompts, args.timeout, num_ctx)
        res["wall_s"] = round(time.monotonic() - t0, 1)
        results.append(res)
        unload(args.host, model)
        if res["gen_s_avg"] is not None:
            print(f"   śr.: prompt {res['prompt_s_avg']:.1f}s, generowanie {res['gen_s_avg']:.1f}s, "
                  f"{res['tok_per_s_avg']:.1f} tok/s, całość {res['total_s_avg']:.1f}s, "
                  f"naruszenia stylu {res['style_violations']}/{res['n'] - res['errors']}")
            if res["total_s_first"] is not None:
                warm_txt = f"{res['total_s_warm']:.0f} s" if res["total_s_warm"] is not None else "-"
                print(f"   pierwsza odpowiedź (zimna): {res['total_s_first']:.0f} s; kolejne (ciepłe): {warm_txt}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write_text(Path(args.out + ".json"), json.dumps({"system_label": label, "results": results}, ensure_ascii=False, indent=2))
    write_markdown(results, label, Path(args.out + ".md"))
    print(f"\nRaport: {args.out}.md (odpowiedzi do przeczytania) i {args.out}.json")
    print("Benchmark wyładował modele z RAM. Jeśli GREGAI działa: sudo systemctl restart gregai "
          "(rozgrzeje model od nowa, w tle).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
