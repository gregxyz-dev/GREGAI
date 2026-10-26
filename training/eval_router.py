"""
training/eval_router.py

Ocena WYTRENOWANEGO routera (albo dowolnego modelu w Ollamie) na zestawie
kontrolnym data/training/router_golden.jsonl, DOKŁADNIE tak, jak woła go
produkcja: ten sam prompt systemowy (router.router_system_prompt), te same
opcje (temperature, num_predict, num_ctx, stop, keep_alive) i ta sama
definicja poprawności (router.parse_routing_reply). Czysty stdlib - działa
bez środowiska treningowego, więc można nim też zmierzyć DOWOLNY model z
Ollamy, np. produkcyjny qwen2.5:3b z pełnym promptem (--full-prompt), żeby
mieć punkt odniesienia na tym samym zestawie.

Raport: trafność narzędzia, odsetek odpowiedzi trzymających format, dokładność
argumentu (tam, gdzie etykieta go ma), czasy z pól Ollamy
(prompt_eval_duration = przetwarzanie promptu, eval_duration = generowanie),
macierz pomyłek i lista błędów. Zapis do data/training/eval_report.json
(albo --out). Używany też przez export.py jako BRAMKA: router trafia do
.env tylko, gdy trafność >= próg.

Użycie:
  python training/eval_router.py --model gregai-router
  python training/eval_router.py --model qwen2.5:3b --full-prompt   # odniesienie
  python training/eval_router.py --unload-only                      # zwolnij RAM
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from env_loader import load_env  # noqa: E402

load_env()

import fsutil  # noqa: E402
import netguard  # noqa: E402
import router as router_mod  # noqa: E402

DATA_DIR = ROOT / "data" / "training"
GOLDEN = DATA_DIR / "router_golden.jsonl"
EVAL = DATA_DIR / "router_eval.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _post(host: str, path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(host.rstrip("/") + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with netguard.local_urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(host: str, path: str, timeout: float = 5.0) -> dict:
    with netguard.local_urlopen(host.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_unload_all(host: str) -> list[str]:
    """Wyładowuje z RAM wszystkie modele, które Ollama akurat trzyma
    (keep_alive=0). Powód: 2026-10-07 phi3.5 (3.9GB) siedzący w RAM obok
    gemma2:2b sprawił, że test, który sam z siebie trwał 33s, przekroczył
    90s. Przed treningiem (który sam potrzebuje ~3-4GB) i przed pomiarem
    chcemy czystej karty."""
    unloaded = []
    try:
        for m in _get(host, "/api/ps").get("models", []):
            name = m.get("name")
            if not name:
                continue
            _post(host, "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
            unloaded.append(name)
    except Exception as e:
        print(f"  (nie udało się wyładować modeli: {e})")
    return unloaded


def model_installed(host: str, model: str) -> bool:
    try:
        names = {m.get("name") for m in _get(host, "/api/tags").get("models", [])}
    except Exception:
        return False
    return model in names or f"{model}:latest" in names


def ask(host: str, model: str, system: str, user: str, timeout: float) -> tuple[str, dict]:
    options = {
        "temperature": router_mod.OLLAMA_TEMPERATURE,
        "num_predict": router_mod._ROUTING_NUM_PREDICT,
        "num_ctx": router_mod.model_settings(model)["num_ctx"],
        "stop": router_mod._ROUTING_STOP,
    }
    data = _post(host, "/api/chat", {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False, "options": options, "keep_alive": router_mod.model_settings(model)["keep_alive"],
    }, timeout=timeout)
    reply = data.get("message", {}).get("content", "")
    timing = {
        "prompt_tokens": data.get("prompt_eval_count"),
        "prompt_ms": (data.get("prompt_eval_duration") or 0) / 1e6,
        "gen_ms": (data.get("eval_duration") or 0) / 1e6,
        "total_ms": (data.get("total_duration") or 0) / 1e6,
    }
    return reply, timing


def evaluate(model: str, records: list[dict], host: str, system: str | None = None,
             timeout: float = 120.0, verbose: bool = True) -> dict:
    system = system or router_mod.router_system_prompt()
    rows, confusion = [], defaultdict(Counter)
    ok = fmt_ok = arg_ok = arg_total = 0
    brak_ok = brak_total = 0  # osobno BRAK (zwykła rozmowa): router, który wszystko kieruje do narzędzi, ma dobrą ogólną trafność przy zepsutej rozmowie
    for i, r in enumerate(records, start=1):
        expected = router_mod.parse_routing_reply(r["assistant"])
        exp_tool = expected[0] if expected else "?"
        try:
            reply, timing = ask(host, model, system, r["user"], timeout)
            error = None
        except Exception as e:
            reply, timing, error = "", {}, str(e)
        got = router_mod.parse_routing_reply(reply)
        got_tool = got[0] if got else None
        confusion[exp_tool][got_tool or "(bez formatu)"] += 1
        correct = got is not None and got_tool == exp_tool
        if exp_tool == "BRAK":
            brak_total += 1
            brak_ok += 1 if correct else 0
        if got is not None:
            fmt_ok += 1
        if correct:
            ok += 1
            if expected and expected[1]:
                arg_total += 1
                if (got[1] or "").strip().lower() == expected[1].strip().lower():
                    arg_ok += 1
        rows.append({"user": r["user"], "expected": r["assistant"], "reply": reply.strip(),
                     "correct": correct, "error": error, **timing})
        if verbose:
            mark = "OK " if correct else "BAD"
            print(f"  [{i:3d}/{len(records)}] {mark} {timing.get('prompt_ms', 0):7.0f}ms  {r['user']!r:60} -> {reply.strip()!r}"
                  + (f"  (oczekiwano {r['assistant']!r})" if not correct else ""), flush=True)
    n = max(1, len(records))
    prompt_ms = [x["prompt_ms"] for x in rows if x.get("prompt_ms")]
    total_ms = [x["total_ms"] for x in rows if x.get("total_ms")]
    return {
        "model": model, "n": len(records), "system_prompt_chars": len(system),
        "accuracy": ok / n, "format_ok": fmt_ok / n,
        "brak_n": brak_total, "brak_accuracy": (brak_ok / brak_total) if brak_total else None,
        "arg_exact": (arg_ok / arg_total) if arg_total else None,
        "prompt_ms_avg": statistics.fmean(prompt_ms) if prompt_ms else None,
        "prompt_ms_median": statistics.median(prompt_ms) if prompt_ms else None,
        "total_ms_avg": statistics.fmean(total_ms) if total_ms else None,
        "prompt_tokens_avg": statistics.fmean([x["prompt_tokens"] for x in rows if x.get("prompt_tokens")]) if prompt_ms else None,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "errors": [x for x in rows if not x["correct"]],
        "rows": rows,
    }


def pct(x) -> str:
    return "-" if x is None else f"{x:.1%}"


def print_summary(rep: dict) -> None:
    tokens = round(rep["prompt_tokens_avg"]) if rep.get("prompt_tokens_avg") else "?"
    print(f"\nModel: {rep['model']}  (prompt systemowy {rep['system_prompt_chars']} znaków, ~{tokens} tokenów z wiadomością)")
    print(f"Trafność narzędzia: {pct(rep['accuracy'])}   format OK: {pct(rep['format_ok'])}   "
          f"argument dokładnie: {pct(rep['arg_exact'])}   n={rep['n']}")
    if rep.get("brak_n"):
        print(f"Rozmowa bez narzędzia (BRAK): {pct(rep.get('brak_accuracy'))} z {rep['brak_n']}")
    if rep["prompt_ms_avg"]:
        print(f"Czas przetwarzania promptu: śr. {rep['prompt_ms_avg'] / 1000:.1f}s, mediana {rep['prompt_ms_median'] / 1000:.1f}s;"
              f" całe wywołanie śr. {rep['total_ms_avg'] / 1000:.1f}s")
    print("Macierz pomyłek (oczekiwano -> dostano: ile):")
    for exp, got in sorted(rep["confusion"].items()):
        print(f"  {exp:16} " + ", ".join(f"{g}: {n}" for g, n in sorted(got.items(), key=lambda kv: -kv[1])))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="nazwa modelu w Ollamie (np. gregai-router)")
    ap.add_argument("--host", default=router_mod.OLLAMA_HOST)
    ap.add_argument("--golden", default=str(GOLDEN))
    ap.add_argument("--also-eval", action="store_true", help="dolicz też router_eval.jsonl")
    ap.add_argument("--full-prompt", action="store_true",
                    help="użyj PEŁNEGO promptu narzędzi (jak krok 1 bez routera) - punkt odniesienia")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out", default=str(DATA_DIR / "eval_report.json"))
    ap.add_argument("--unload-only", action="store_true", help="tylko wyładuj modele z RAM i wyjdź")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.unload_only:
        gone = ollama_unload_all(args.host)
        print("Wyładowano z RAM:", ", ".join(gone) if gone else "(nic nie było wczytane)")
        return 0
    if not args.model:
        ap.error("--model jest wymagane (albo --unload-only)")
    if not model_installed(args.host, args.model):
        print(f"Model {args.model!r} nie jest zainstalowany w Ollamie ({args.host}).")
        return 2

    records = read_jsonl(Path(args.golden))
    if args.also_eval and EVAL.exists():
        records += read_jsonl(EVAL)
    system = router_mod._routing_system_prompt() if args.full_prompt else router_mod.router_system_prompt()
    print(f"Oceniam {args.model} na {len(records)} przykładach ({'PEŁNY prompt narzędzi' if args.full_prompt else 'prompt routera'})...")
    t0 = time.monotonic()
    rep = evaluate(args.model, records, args.host, system=system, timeout=args.timeout, verbose=not args.quiet)
    rep["wall_seconds"] = round(time.monotonic() - t0, 1)
    rep["full_prompt"] = args.full_prompt
    print_summary(rep)
    fsutil.atomic_write_text(Path(args.out), json.dumps(rep, ensure_ascii=False, indent=2))  # prywatny: zawiera prawdziwe wiadomości (--also-eval)
    print(f"Raport: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
