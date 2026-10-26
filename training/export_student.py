"""
training/export_student.py

Ostatni etap destylacji: scalony UCZEŃ (finetune.py --task student) ->
GGUF -> Ollama -> ocena -> (jeśli przeszła) włączenie w GREGAI jako
STUDENT_MODEL. Bliźniak export.py (router), z inną oceną: rozmowa nie ma
jednej poprawnej odpowiedzi, więc bramka mierzy to, co da się zmierzyć:

- styl (agent/persona.py: violates_style): odsetek odpowiedzi bez
  zakazanych fraz, myślników, nazw narzędzi; próg --min-style (0.90),
- brak pustych odpowiedzi oraz najwyżej --max-not-polish (2%) odpowiedzi
  nie po polsku (prosty test na polskie znaki/słowa; jedna wpadka na
  kilkadziesiąt pytań nie przekreśla całego, wielogodzinnego treningu),
- czas: średni czas całej odpowiedzi w sekundach, do porównania z
  dzisiejszym krokiem 2 (bench_chat.py) - raportowany, nie bramkowany,
- oraz PLIK z odpowiedziami do przeczytania (student_eval_report.md):
  ostateczną ocenę jakości rozmowy podejmuje człowiek. Dlatego gdy
  bramka przechodzi, uczeń jest włączany, ale raport i tak leży obok:
  jeśli odpowiedzi Ci się nie podobają, wystarczy usunąć STUDENT_MODEL z
  .env (albo --no-enable tutaj) i GREGAI wraca do pełnego promptu.

Współdzielone z export.py: konwersja, import do Ollamy (najpierw pod nazwą
kandydata, na produkcyjną dopiero po bramce), update_env, restart. Prompt systemowy = persona.student_system_prompt() (ten sam co
w treningu i produkcji; manifest zapisuje jego skrót, router.py
wyłącza ucznia, gdy prompt się zmieni bez retreningu).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_loader import load_env  # noqa: E402

load_env()

import persona  # noqa: E402
import router as router_mod  # noqa: E402
import eval_router  # noqa: E402
import export  # noqa: E402
import fsutil  # noqa: E402

DATA_DIR = ROOT / "data" / "training"
PROBE = DATA_DIR / "student_probe.jsonl"
EVAL = DATA_DIR / "student_eval.jsonl"

_POLISH_HINT = re.compile(
    r"[ąćęłńóśźż]|\b(nie|jest|się|że|jak|co|tak|na|ale|dla|czy|po|mam|masz|oraz|przez|można|jeśli|są|być|ze|od|bo|za)\b",
    re.IGNORECASE)
_ENGLISH_HINT = re.compile(r"\b(the|and|you|your|is|are|this|that|with|for|have|can|will|of)\b", re.IGNORECASE)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
# Cytaty, kod i bloki kodu mogą być w obcym języku zupełnie poprawnie
# (tłumaczenie, polecenie): oceniamy tekst PO ich wycięciu.
_QUOTED = re.compile(r"```.*?```|`[^`]*`|„[^”]*”|\"[^\"]*\"", re.DOTALL)
_WORD = re.compile(r"[^\W\d_]+")


def looks_polish(reply: str) -> bool:
    """Bramka łapie odpowiedzi w obcym języku (angielski, chiński, do którego
    Qwen potrafi się zsunąć) i bełkot, a nie krótkie poprawne odpowiedzi bez
    słów funkcyjnych ("29.", "Tak.", "Dwa."). Po wycięciu cytatów i kodu:
    CJK = nie; do dwóch słów = tak; trzy słowa lub więcej bez ŻADNEJ polskiej
    wskazówki = nie; wyraźnie angielska (4+ angielskich słów funkcyjnych i
    ponad dwa razy więcej niż polskich wskazówek) = nie."""
    if not reply or _CJK.search(reply):
        return False
    text = _QUOTED.sub(" ", reply)
    if len(_WORD.findall(text)) <= 2:
        return True
    polish, english = len(_POLISH_HINT.findall(text)), len(_ENGLISH_HINT.findall(text))
    if polish == 0:
        return False
    return not (english >= 4 and english > 2 * polish)


def ask_student(host: str, model: str, system: str, user: str, timeout: float,
                history: list[dict] | None = None) -> tuple[str, dict]:
    options = {"temperature": router_mod.OLLAMA_TEMPERATURE, "num_predict": 200, "num_ctx": router_mod.model_settings(model)["num_ctx"]}
    # Historia jak w router._ollama_chat: poprzednie tury między systemem a
    # bieżącym pytaniem (zbiór nauczyciela ma dialogi z polem history).
    messages = [{"role": "system", "content": system}]
    for turn in history or []:
        messages.append({"role": "assistant" if turn.get("role") == "assistant" else "user",
                         "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user})
    data = eval_router._post(host, "/api/chat", {
        "model": model, "stream": False, "keep_alive": router_mod.model_settings(model)["keep_alive"], "options": options,
        "messages": messages,
    }, timeout=timeout)
    reply = (data.get("message", {}).get("content") or "").strip()
    timing = {"prompt_ms": (data.get("prompt_eval_duration") or 0) / 1e6,
              "gen_ms": (data.get("eval_duration") or 0) / 1e6,
              "total_ms": (data.get("total_duration") or 0) / 1e6,
              "gen_tokens": data.get("eval_count")}
    return reply, timing


def evaluate_student(model: str, records: list[dict], host: str, timeout: float = 300.0) -> dict:
    system = persona.student_system_prompt()
    rows = []
    for i, r in enumerate(records, start=1):
        try:
            reply, timing = ask_student(host, model, system, r["user"], timeout, history=r.get("history"))
            error = None
        except Exception as e:
            reply, timing, error = "", {}, f"{type(e).__name__}: {e}"
        problems = persona.violates_style(reply)
        polish = looks_polish(reply)
        rows.append({"user": r["user"], "expected": r.get("assistant"), "reply": reply, "error": error,
                     "style_problems": problems, "polish": polish, "with_history": bool(r.get("history")), **timing})
        mark = "OK " if reply and not problems and polish else "BAD"
        print(f"  [{i:2d}/{len(records)}] {mark} {timing.get('total_ms', 0) / 1000:6.1f}s  {r['user'][:50]!r} -> {reply[:70]!r}"
              + (f"  [{', '.join(problems)}]" if problems else ""), flush=True)
    good = [x for x in rows if x["reply"]]
    n = max(1, len(rows))
    return {
        "model": model, "n": len(rows),
        "empty": sum(1 for x in rows if not x["reply"]),
        "not_polish": sum(1 for x in good if not x["polish"]),
        "style_ok": sum(1 for x in good if not x["style_problems"]) / n,
        "total_s_avg": statistics.fmean(x["total_ms"] for x in good) / 1000 if good else None,
        "gen_s_avg": statistics.fmean(x["gen_ms"] for x in good) / 1000 if good else None,
        "avg_chars": round(statistics.fmean(len(x["reply"]) for x in good)) if good else 0,
        "rows": rows,
    }


def write_report(rep: dict, path: Path) -> None:
    lines = [f"# Uczeń rozmowy: {rep['model']}", "",
             f"n={rep['n']}, styl czysty {rep['style_ok']:.0%}, puste {rep['empty']}, nie po polsku {rep['not_polish']}, "
             f"śr. {rep['avg_chars']} znaków, śr. czas {rep['total_s_avg'] and round(rep['total_s_avg'], 1)} s", "",
             "Każda para: pytanie, odpowiedź UCZNIA, pod spodem wzorcowa odpowiedź z danych (jeśli była).", ""]
    for x in rep["rows"]:
        head = f"**{x['user']}**" + (" _(z historią rozmowy)_" if x.get("with_history") else "")
        lines += [head, "", x["reply"] or f"(pusto / błąd: {x.get('error')})"]
        if x.get("style_problems"):
            lines.append(f"\n_styl: {', '.join(x['style_problems'])}_")
        if x.get("expected"):
            lines += ["", f"> wzorzec: {x['expected']}"]
        lines.append("")
    fsutil.atomic_write_text(path, "\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default=str(ROOT / "training" / ".work" / "student" / "merged"))
    ap.add_argument("--llama-cpp", default=str(ROOT / "training" / ".work" / "llama.cpp"))
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--model-name", default="gregai-student")
    ap.add_argument("--quantize", default="q8_0")
    ap.add_argument("--min-style", type=float, default=0.90)
    ap.add_argument("--max-not-polish", type=float, default=0.02,
                    help="największy dopuszczalny odsetek odpowiedzi nie po polsku (puste odpowiedzi zawsze odrzucają)")
    ap.add_argument("--host", default=router_mod.OLLAMA_HOST)
    ap.add_argument("--skip-convert", action="store_true")
    ap.add_argument("--skip-create", action="store_true")
    ap.add_argument("--no-enable", action="store_true", help="oceń i zapisz raport, ale nie włączaj w .env")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--check-prompt", action="store_true",
                    help="tylko sprawdź, czy zbiór powstał z obecnym promptem, i zakończ (run_student.sh przed wznowieniem treningu)")
    args = ap.parse_args()

    def check_prompt() -> None:
        export.ensure_built_with_current_prompt(
            DATA_DIR / "student_stats.json", "system_prompt",
            hashlib.sha1(persona.student_system_prompt().encode("utf-8")).hexdigest(),
            "uczeń", "python3 training/build_distill_dataset.py")

    if args.check_prompt:
        check_prompt()
        return 0
    export.check_env_writable()

    merged = Path(args.merged)
    work = merged.parent
    final_gguf = work / f"{args.model_name}-f16.gguf"
    quant = None if args.quantize.lower() == "none" else args.quantize

    check_prompt()

    eval_name = args.model_name if args.skip_create else export.candidate_name(args.model_name)
    gguf = work / f"{eval_name}-f16.gguf"  # do bramki GGUF ma nazwę kandydata (export.promote_gguf)
    if args.skip_convert and not gguf.exists() and final_gguf.exists():
        gguf = final_gguf
    if not args.skip_create:
        if not args.skip_convert:
            if not (merged / "config.json").exists():
                raise SystemExit(f"Brak scalonego ucznia w {merged} - najpierw finetune.py --task student")
            export.convert_to_gguf(args.python, Path(args.llama_cpp), merged, gguf)
        quant_used = export.ollama_create(eval_name, gguf, quant, work)
    else:
        quant_used = "(istniejący)"

    if not eval_router.model_installed(args.host, eval_name):
        raise SystemExit(f"Ollama nie widzi modelu {eval_name!r} po imporcie")

    eval_router.ollama_unload_all(args.host)
    records = eval_router.read_jsonl(EVAL) if EVAL.exists() else []
    if not records and PROBE.exists():
        records = [{"user": r["user"]} for r in eval_router.read_jsonl(PROBE)]
    if not records:
        raise SystemExit("Brak data/training/student_eval.jsonl - najpierw build_distill_dataset.py")
    print(f"\nOcena {eval_name} na {len(records)} pytaniach (prompt ucznia, {len(persona.student_system_prompt())} znaków)...")
    rep = evaluate_student(eval_name, records, args.host)
    fsutil.atomic_write_text(DATA_DIR / "student_eval_report.json", json.dumps(rep, ensure_ascii=False, indent=2))
    write_report(rep, DATA_DIR / "student_eval_report.md")
    print(f"\nStyl czysty: {rep['style_ok']:.1%} (próg {args.min_style:.0%}), puste: {rep['empty']}, nie po polsku: {rep['not_polish']} (próg {args.max_not_polish:.0%}), "
          f"śr. czas {rep['total_s_avg'] and round(rep['total_s_avg'], 1)} s, śr. {rep['avg_chars']} znaków")
    print(f"Raport do przeczytania: {DATA_DIR / 'student_eval_report.md'}")

    passed = (rep["style_ok"] >= args.min_style and rep["empty"] == 0
              and rep["not_polish"] <= args.max_not_polish * rep["n"])
    if not passed or args.no_enable:
        why = "--no-enable" if args.no_enable and passed else "bramka nie przeszła"
        print(f"\nUczeń NIE został włączony ({why}). Kandydat {eval_name} zostaje w Ollamie; model {args.model_name}, .env i manifest bez zmian. "
              "Przeczytaj raport, popraw dane (training/distill_seed.jsonl, pary z chmury) i uruchom run_student.sh ponownie.")
        return 3 if not passed else 0

    if eval_name != args.model_name:
        export.promote_model(eval_name, args.model_name, args.host)
        export.promote_gguf(gguf, final_gguf)

    manifest = {
        "model": args.model_name,
        "system_prompt_sha1": hashlib.sha1(persona.student_system_prompt().encode("utf-8")).hexdigest(),
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "quantization": quant_used,
        "eval": {k: rep[k] for k in ("n", "empty", "not_polish", "style_ok", "total_s_avg", "avg_chars")},
    }
    try:
        tr = json.loads((work / "train_report.json").read_text(encoding="utf-8"))
        manifest.update({"base": tr.get("base"), "train_examples": tr.get("train_examples")})
    except Exception:
        pass
    fsutil.atomic_write_text(DATA_DIR / "student_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    action = export.update_env(args.model_name, key="STUDENT_MODEL")
    print(f"\nBRAMKA PRZESZŁA. Manifest: {DATA_DIR / 'student_manifest.json'}; .env: {action} STUDENT_MODEL={args.model_name}")
    print("Jeśli po przeczytaniu raportu odpowiedzi Ci się nie podobają: usuń STUDENT_MODEL z .env i zrestartuj GREGAI.")
    if not args.no_restart and export.restart_gregai():
        print("GREGAI restartuje się z uczniem. Sprawdź /debug: stage 'uczen_rozmowa', extra.style_problems.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
