"""
training/export_planner.py

Ostatni etap treningu PLANERA pętli agenta (patrz run_planner.sh):
scalony model (finetune.py --task planner) -> GGUF -> `ollama create` ->
ocena przez Ollamę na data/training/planner_eval.jsonl DOKŁADNIE tak, jak
pyta produkcja (router._planner_ask: chudy prompt agentloop.
planner_system_prompt(trained=True), num_predict PLANNER_NUM_PREDICT, stop
na końcu linii) -> bramka -> manifest -> PLANNER_MODEL w .env -> restart.

Bramka (--min-accuracy, --min-format): trafność to ten sam rodzaj
(KROK/GOTOWE/PYTANIE) i dla KROK to samo narzędzie, format to odsetek
odpowiedzi, które agentloop.parse_action w ogóle rozumie. Model, który
nie przejdzie, zostaje w Ollamie pod nazwą kandydata (gregai-planner-candidate)
do obejrzenia; planer produkcyjny, .env i manifest nie są ruszane: pętla
dalej używa dotychczasowego planera albo OLLAMA_MODEL z pełną instrukcją.

Manifest (data/training/planner_manifest.json) zapisuje model, ZESTAW
NARZĘDZI katalogu i skrót chudego promptu; router.planner_status()
wyłącza planer, gdy którekolwiek się zmieni (np. po zmianie
SYSOP_ENABLED: inny katalog = trening do powtórzenia).

Czysty stdlib; importuje agent/ (agentloop, router) i training/export.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "training"))

from env_loader import load_env  # noqa: E402

load_env()

import agentloop  # noqa: E402
import eval_router  # noqa: E402
import export  # noqa: E402
import fsutil  # noqa: E402
import router as router_mod  # noqa: E402

DATA_DIR = ROOT / "data" / "training"
EVAL = DATA_DIR / "planner_eval.jsonl"


def ask_planner(host: str, model: str, system: str, user: str, timeout: float) -> tuple[str, dict]:
    options = {"temperature": router_mod.OLLAMA_TEMPERATURE, "num_predict": agentloop.PLANNER_NUM_PREDICT,
               "num_ctx": router_mod.model_settings(model)["num_ctx"], "stop": ["\n"]}
    data = eval_router._post(host, "/api/chat", {
        "model": model, "stream": False, "keep_alive": router_mod.model_settings(model)["keep_alive"], "options": options,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }, timeout=timeout)
    reply = (data.get("message", {}).get("content") or "").strip()
    timing = {"prompt_ms": (data.get("prompt_eval_duration") or 0) / 1e6,
              "gen_ms": (data.get("eval_duration") or 0) / 1e6,
              "total_ms": (data.get("total_duration") or 0) / 1e6}
    return reply, timing


def evaluate_planner(model: str, records: list[dict], host: str, timeout: float = 300.0) -> dict:
    system = agentloop.planner_system_prompt(trained=True)
    rows = []
    for i, r in enumerate(records, start=1):
        expected = agentloop.parse_action(r["assistant"])
        try:
            reply, timing = ask_planner(host, model, system, r["user"], timeout)
            error = None
        except Exception as e:
            reply, timing, error = "", {}, f"{type(e).__name__}: {e}"
        got = agentloop.parse_action(reply)
        hit = got is not None and expected is not None and got[0] == expected[0] and (got[0] != "KROK" or got[1] == expected[1])
        arg_hit = None
        if hit and expected[0] == "KROK" and expected[2]:
            arg_hit = got[2].strip().lower() == expected[2].strip().lower()
        rows.append({"goal": r.get("goal"), "state": r["user"], "expected": r["assistant"], "reply": reply, "error": error,
                     "format_ok": got is not None, "hit": hit, "arg_hit": arg_hit, **timing})
        mark = "OK " if hit else ("fmt" if got is None else "BAD")
        print(f"  [{i:2d}/{len(records)}] {mark} {timing.get('total_ms', 0) / 1000:5.1f}s  {(r.get('goal') or '')[:40]!r} -> {reply[:60]!r}"
              + (f"  (oczekiwano {r['assistant'][:50]!r})" if not hit else ""), flush=True)
    n = max(1, len(rows))
    timed = [x for x in rows if x.get("total_ms")]
    args_scored = [x for x in rows if x["arg_hit"] is not None]
    return {
        "model": model, "n": len(rows),
        "accuracy": sum(1 for x in rows if x["hit"]) / n,
        "format_ok": sum(1 for x in rows if x["format_ok"]) / n,
        "arg_exact": (sum(1 for x in args_scored if x["arg_hit"]) / len(args_scored)) if args_scored else None,
        "total_s_avg": statistics.fmean(x["total_ms"] for x in timed) / 1000 if timed else None,
        "prompt_s_avg": statistics.fmean(x["prompt_ms"] for x in timed) / 1000 if timed else None,
        "rows": rows,
    }


def write_report(rep: dict, path: Path) -> None:
    def pct(x):
        return "-" if x is None else f"{x:.0%}"
    lines = [f"# Planer pętli agenta: {rep['model']}", "",
             f"n={rep['n']}, trafność {pct(rep['accuracy'])}, format {pct(rep['format_ok'])}, argument dokładnie {pct(rep['arg_exact'])}, "
             f"śr. czas {rep['total_s_avg'] and round(rep['total_s_avg'], 2)} s (prompt {rep['prompt_s_avg'] and round(rep['prompt_s_avg'], 2)} s)", "",
             "Każdy punkt: cel, stan (wykonane kroki), odpowiedź PLANERA, pod spodem oczekiwana linia.", ""]
    for x in rep["rows"]:
        mark = "OK" if x["hit"] else "BŁĄD"
        lines += [f"## [{mark}] {x.get('goal') or ''}", "", "```", x["state"], "```", "",
                  f"planer: `{x['reply'] or '(pusto / błąd: ' + str(x.get('error')) + ')'}`", "",
                  f"> oczekiwano: `{x['expected']}`", ""]
    fsutil.atomic_write_text(path, "\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default=str(ROOT / "training" / ".work" / "planner" / "merged"))
    ap.add_argument("--llama-cpp", default=str(ROOT / "training" / ".work" / "llama.cpp"))
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--model-name", default="gregai-planner")
    ap.add_argument("--quantize", default="q8_0")
    ap.add_argument("--min-accuracy", type=float, default=0.85)
    ap.add_argument("--min-format", type=float, default=0.95)
    ap.add_argument("--host", default=router_mod.OLLAMA_HOST)
    ap.add_argument("--skip-convert", action="store_true")
    ap.add_argument("--skip-create", action="store_true")
    ap.add_argument("--no-enable", action="store_true", help="oceń i zapisz raport, ale nie włączaj w .env")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--check-prompt", action="store_true",
                    help="tylko sprawdź, czy zbiór powstał z obecnym promptem, i zakończ (run_planner.sh przed wznowieniem treningu)")
    args = ap.parse_args()

    def check_prompt() -> str:
        sha1 = hashlib.sha1(agentloop.planner_system_prompt(trained=True).encode("utf-8")).hexdigest()
        export.ensure_built_with_current_prompt(
            DATA_DIR / "planner_stats.json", "system_prompt_sha1", sha1,
            "planer", "python3 training/build_planner_dataset.py")
        return sha1

    if args.check_prompt:
        check_prompt()
        return 0
    export.check_env_writable()

    merged = Path(args.merged)
    work = merged.parent
    final_gguf = work / f"{args.model_name}-f16.gguf"
    quant = None if args.quantize.lower() == "none" else args.quantize

    prompt_sha1 = check_prompt()

    eval_name = args.model_name if args.skip_create else export.candidate_name(args.model_name)
    gguf = work / f"{eval_name}-f16.gguf"  # do bramki GGUF ma nazwę kandydata (export.promote_gguf)
    if args.skip_convert and not gguf.exists() and final_gguf.exists():
        gguf = final_gguf
    if not args.skip_create:
        if not args.skip_convert:
            if not (merged / "config.json").exists():
                raise SystemExit(f"Brak scalonego planera w {merged} - najpierw finetune.py --task planner")
            export.convert_to_gguf(args.python, Path(args.llama_cpp), merged, gguf)
        quant_used = export.ollama_create(eval_name, gguf, quant, work)
    else:
        quant_used = "(istniejący)"

    if not eval_router.model_installed(args.host, eval_name):
        raise SystemExit(f"Ollama nie widzi modelu {eval_name!r} po imporcie")

    eval_router.ollama_unload_all(args.host)
    records = eval_router.read_jsonl(EVAL) if EVAL.exists() else []
    if not records:
        raise SystemExit("Brak data/training/planner_eval.jsonl - najpierw build_planner_dataset.py")
    system_chars = len(agentloop.planner_system_prompt(trained=True))
    print(f"\nOcena {eval_name} na {len(records)} punktach decyzyjnych (chudy prompt planera, {system_chars} znaków)...")
    rep = evaluate_planner(eval_name, records, args.host)
    fsutil.atomic_write_text(DATA_DIR / "planner_eval_report.json", json.dumps(rep, ensure_ascii=False, indent=2))
    write_report(rep, DATA_DIR / "planner_eval_report.md")
    arg_txt = "-" if rep["arg_exact"] is None else f"{rep['arg_exact']:.1%}"
    print(f"\nTrafność: {rep['accuracy']:.1%} (próg {args.min_accuracy:.0%}), format: {rep['format_ok']:.1%} (próg {args.min_format:.0%}), "
          f"argument dokładnie: {arg_txt}, śr. czas {rep['total_s_avg'] and round(rep['total_s_avg'], 2)} s")
    print(f"Raport do przeczytania: {DATA_DIR / 'planner_eval_report.md'}")

    passed = rep["accuracy"] >= args.min_accuracy and rep["format_ok"] >= args.min_format
    if not passed or args.no_enable:
        why = "--no-enable" if args.no_enable and passed else "bramka nie przeszła"
        print(f"\nPlaner NIE został włączony ({why}). Kandydat {eval_name} zostaje w Ollamie; model {args.model_name}, .env i "
              "manifest bez zmian; pętla agenta działa jak przedtem. Dopisz epizody do training/planner_seed.jsonl (albo zbierz więcej "
              "zadań w rozmowie) i uruchom run_planner.sh ponownie.")
        return 3 if not passed else 0

    if eval_name != args.model_name:
        export.promote_model(eval_name, args.model_name, args.host)
        export.promote_gguf(gguf, final_gguf)

    manifest = {
        "model": args.model_name,
        "tools": router_mod.planner_tools(),
        "instruction_sha1": hashlib.sha1(agentloop.PLANNER_INSTRUCTION_SHORT.encode("utf-8")).hexdigest(),
        "prompt_sha1": prompt_sha1,
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "quantization": quant_used,
        "eval": {k: rep[k] for k in ("n", "accuracy", "format_ok", "arg_exact", "total_s_avg")},
    }
    try:
        tr = json.loads((work / "train_report.json").read_text(encoding="utf-8"))
        manifest.update({"base": tr.get("base"), "train_examples": tr.get("train_examples")})
    except Exception:
        pass
    fsutil.atomic_write_text(DATA_DIR / "planner_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    action = export.update_env(args.model_name, key="PLANNER_MODEL")
    print(f"\nBRAMKA PRZESZŁA. Manifest: {DATA_DIR / 'planner_manifest.json'}; .env: {action} PLANNER_MODEL={args.model_name}")
    print("Wyłączenie: usuń PLANNER_MODEL z .env i zrestartuj GREGAI. Po włączeniu SYSOP (inny katalog narzędzi) trening powtórz.")
    if not args.no_restart and export.restart_gregai():
        print("GREGAI restartuje się z planerem. Sprawdź /api/system_info: planner.enabled, i daj zadanie dwuetapowe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
