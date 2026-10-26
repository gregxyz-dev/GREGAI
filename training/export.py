"""
training/export.py

Ostatni etap samo-treningu: scalony model z finetune.py -> GGUF -> Ollama
-> ocena -> (jeśli przeszła) włączenie w GREGAI. Kolejno:

1. convert_hf_to_gguf.py z llama.cpp (sklonowane przez run.sh do
   training/.work/llama.cpp): katalog merged/ -> jeden plik .gguf (F16).
2. Modelfile z TYM SAMYM szablonem ChatML, który finetune.py renderował
   w treningu (patrz render_prompt tam) + `ollama create <nazwa>-candidate
   --quantize q8_0`. Jeśli ta wersja Ollamy nie zna --quantize, import
   bez kwantyzacji (F16, ~1GB dla 0.5B, wciąż malutki). Nowy model powstaje
   pod nazwą KANDYDATA, nie pod produkcyjną: gdyby powstał od razu pod
   produkcyjną, nieudany retrening (bramka niżej) podmieniłby działający
   model gorszym, a manifest i .env dalej wskazywałyby na niego.
3. Ocena na zestawie kontrolnym (training/eval_router.py, golden) przez
   PRAWDZIWĄ Ollamę, dokładnie tak, jak zrobi to produkcja.
4. BRAMKA: trafność >= --min-accuracy (domyślnie 0.85) ORAZ format
   >= --min-format (0.95) ORAZ trafność na rozmowie bez narzędzia
   (BRAK) >= --min-brak (0.85). Dopiero wtedy kandydat jest PRZEPISYWANY na
   nazwę produkcyjną (`ollama cp` + `ollama rm`) i:
   - data/training/router_manifest.json (lista narzędzi z treningu,
     nazwa modelu, wyniki) - bez tego router.py routera nie włączy,
   - ROUTER_MODEL=<nazwa> w .env (idempotentnie: podmienia istniejącą
     linię albo dopisuje; .env NIGDY nie jest nadpisywany w całości),
   - POST /api/restart do GREGAI (localhost, bez tokenu), żeby nowy
     router ruszył od razu.
   Gdy bramka nie przechodzi: kandydat ZOSTAJE w Ollamie (można go obejrzeć
   ręcznie: eval_router.py --model ...-candidate), a model produkcyjny,
   .env i manifest są nietknięte - produkcja działa dokładnie jak przedtem.

Czysty stdlib + subprocess (convert odpala się w venv treningowym przez
`--python`, patrz run.sh).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_loader import load_env  # noqa: E402

load_env()

import fsutil  # noqa: E402
import netguard  # noqa: E402
import router as router_mod  # noqa: E402
import eval_router  # noqa: E402

DATA_DIR = ROOT / "data" / "training"
ENV_PATH = ROOT / ".env"
GREGAI_URL = "http://127.0.0.1:7777"

# Identyczne z finetune.render_prompt/render_answer: {{ .System }} ->
# system, {{ .Prompt }} -> user, odpowiedź po "<|im_start|>assistant\n".
#
# Sprawdzone na żywo 2026-10-07 na Ollamie 0.35.1 użytkownika: nowsze
# wersje Ollamy wolą szablon Jinja WBUDOWANY w GGUF (convert_hf_to_gguf.py
# przepisuje go z tokenizer_config.json Qwen2.5) i /api/show pokazuje
# właśnie jego, nie ten poniżej. To nie problem: dla rozmowy
# system+user oba renderują bajt w bajt ten sam tekst
# ("<|im_start|>system\n...<|im_end|>\n<|im_start|>user\n...<|im_end|>\n
# <|im_start|>assistant\n"), czyli dokładnie render_prompt z finetune.py.
# Ten TEMPLATE zostaje jako zabezpieczenie dla starszych wersji Ollamy.
MODELFILE_TEMPLATE = '''TEMPLATE """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
{{ .Response }}<|im_end|>
"""
PARAMETER stop <|im_start|>
PARAMETER stop <|im_end|>
PARAMETER stop <|endoftext|>
'''


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=False, text=True, **kw)


def convert_to_gguf(python: str, llama_cpp: Path, merged: Path, out_file: Path) -> None:
    script = llama_cpp / "convert_hf_to_gguf.py"
    if not script.exists():
        raise SystemExit(f"Brak {script} - run.sh powinien był sklonować llama.cpp do {llama_cpp}")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    # Konwerter to cudzy kod z GitHuba: dostaje środowisko bez kluczy API i haseł z .env
    # (ten proces je wczytał razem z modułami agenta), tylko to, czego potrzebuje Python.
    keep = ("PATH", "HOME", "USER", "LANG", "LANGUAGE", "TMPDIR", "VIRTUAL_ENV", "PYTHONIOENCODING")
    clean_env = {k: v for k, v in os.environ.items() if k in keep or k.startswith("LC_")}
    proc = run([python, script, merged, "--outfile", out_file, "--outtype", "f16"], env=clean_env)
    if proc.returncode != 0 or not out_file.exists():
        raise SystemExit(f"Konwersja do GGUF nie powiodła się (kod {proc.returncode})")
    print(f"GGUF: {out_file} ({out_file.stat().st_size / 1e6:.0f} MB)")


def ollama_create(model_name: str, gguf: Path, quantize: str | None, work: Path) -> str:
    if shutil.which("ollama") is None:
        raise SystemExit("Nie znaleziono polecenia `ollama` w PATH - czy Ollama jest zainstalowana?")
    modelfile = work / "Modelfile"
    # FROM względem Modelfile (GGUF leży obok): ścieżka projektu może mieć spacje.
    source = f"./{gguf.name}" if gguf.resolve().parent == work.resolve() else str(gguf.resolve())
    fsutil.atomic_write_text(modelfile, f"FROM {source}\n" + MODELFILE_TEMPLATE, mode=0o644)
    cmd = ["ollama", "create", model_name, "-f", modelfile]
    if quantize:
        proc = run(cmd + ["--quantize", quantize], cwd=work)
        if proc.returncode == 0:
            return quantize
        print(f"`ollama create --quantize {quantize}` nie powiodło się (kod {proc.returncode}); próbuję bez kwantyzacji (F16).")
    proc = run(cmd, cwd=work)
    if proc.returncode != 0:
        raise SystemExit(f"`ollama create` nie powiodło się (kod {proc.returncode})")
    return "f16"


CANDIDATE_SUFFIX = "-candidate"


def candidate_name(model_name: str) -> str:
    """Nazwa, pod którą nowo wytrenowany model czeka na bramkę jakości."""
    return model_name + CANDIDATE_SUFFIX


def ensure_built_with_current_prompt(stats_path: Path, key: str, current_sha1: str, what: str, builder: str) -> None:
    """Zbiór treningowy powstał z promptem z chwili budowy. Jeśli kod ma dziś
    inny prompt (zmieniony katalog narzędzi, opis, instrukcja), model nauczyłby
    się odpowiadać na prompt, którego produkcja już nie wysyła, a manifest
    zapisałby hash bieżącego. Zatrzymujemy się przed kosztowną konwersją.
    Brak pliku statystyk (stary zbiór, ręczny import) nie blokuje."""
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(stats, dict):
        return
    built = stats.get(key)
    if key == "system_prompt" and isinstance(built, str):
        built = hashlib.sha1(built.encode("utf-8")).hexdigest()
    if isinstance(built, str) and built and built != current_sha1:
        raise SystemExit(
            f"Zbiór treningowy ({what}) powstał z innym promptem niż obecny w kodzie - model uczyłby się na nieaktualnym. "
            f"Zbuduj dane od nowa ({builder}) i wytrenuj ponownie."
        )


PREVIOUS_SUFFIX = "-prev"


def promote_model(candidate: str, final: str, host: str | None = None) -> None:
    """Kandydat, który przeszedł bramkę, zastępuje model produkcyjny
    (`ollama cp` kopiuje po nazwie, warstwy zostają współdzielone, więc to
    nie dubluje plików), po czym nazwa kandydata jest zwalniana. Dotychczasowy
    model produkcyjny zostaje jako <nazwa>-prev (jedna wersja wstecz), bo
    bramka sprawdza próg, a nie to, czy nowy jest lepszy od poprzedniego:
    powrót to `ollama cp <nazwa>-prev <nazwa>` i przywrócenie wpisu w .env."""
    if host and eval_router.model_installed(host, final):
        previous = final + PREVIOUS_SUFFIX
        if run(["ollama", "cp", final, previous]).returncode == 0:
            print(f"  poprzednia wersja zachowana jako {previous} (powrót: ollama cp {previous} {final})")
        else:
            print(f"  (nie udało się zachować poprzedniej wersji jako {previous}; idę dalej)")
    proc = run(["ollama", "cp", candidate, final])
    if proc.returncode != 0:
        raise SystemExit(f"`ollama cp {candidate} {final}` nie powiodło się (kod {proc.returncode}); "
                         f"model produkcyjny, .env i manifest bez zmian")
    if run(["ollama", "rm", candidate]).returncode != 0:
        print(f"  (nie udało się usunąć kandydata {candidate}; można ręcznie: ollama rm {candidate})")


def promote_gguf(candidate_gguf: Path, final_gguf: Path) -> None:
    """GGUF kandydata staje się GGUF-em produkcyjnym dopiero po przejściu
    bramki. install.sh importuje `<model>-f16.gguf` przy przeniesieniu projektu
    na nową maszynę, więc plik pod nazwą produkcyjną musi być zawsze tym, który
    bramkę przeszedł; niezaliczony zostaje pod nazwą kandydata."""
    if candidate_gguf != final_gguf and candidate_gguf.exists():
        os.replace(candidate_gguf, final_gguf)


_ENV_COMMENTS = {
    "ROUTER_MODEL": (
        "# Wytrenowany router do kroku 1 (decyzja TOOL/BRAK), wynik training/run.sh.\n"
        "# Patrz agent/router.py (ROUTER_MODEL) i training/README.md. Pusty = wyłączony.\n"
    ),
    "STUDENT_MODEL": (
        "# Uczeń rozmowy (krok 2): mały model z osobowością GREGAI w wagach, wynik\n"
        "# training/run_student.sh. Patrz agent/router.py (STUDENT_MODEL). Pusty = wyłączony.\n"
    ),
    "PLANNER_MODEL": (
        "# Planer pętli agenta (zadania wielokrokowe KROK/GOTOWE/PYTANIE): wynik\n"
        "# training/run_planner.sh. Patrz agent/router.py (PLANNER_MODEL). Pusty = OLLAMA_MODEL z pełną instrukcją.\n"
    ),
}


def update_env(model_name: str, key: str = "ROUTER_MODEL") -> str:
    """Ustawia JEDNĄ linię KEY=..., resztę .env zostawia bajt w bajt (tam są
    sekrety użytkownika) i zapisuje go atomowo (zachowuje prawa pliku, 600).
    Czynny wpis (pierwszy) jest podmieniany, jego duplikaty znikają; gdy
    czynnego nie ma, zakomentowany przykład `# KEY=...` zamienia się w
    czynny; gdy nie ma żadnego, blok z komentarzem trafia na koniec. Używane
    dla ROUTER_MODEL (router), STUDENT_MODEL (uczeń, export_student.py) i
    PLANNER_MODEL (planer, export_planner.py)."""
    # Bajty, nie tekst UTF-8: .env zapisany w innym kodowaniu (np. Windows-1250, komentarz
    # z polskimi znakami) nie może wywrócić aktualizacji PO podmianie modelu, a reszta pliku
    # ma zostać bajt w bajt.
    text = ENV_PATH.read_bytes().decode("utf-8", "surrogateescape") if ENV_PATH.exists() else ""
    line = f"{key}={model_name}"
    # Te same kształty linii, które czyta agent/env_loader.py (`export KLUCZ=`, `KLUCZ = x`).
    active = re.compile(rf"^[ \t]*(export[ \t]+)?{re.escape(key)}[ \t]*=")
    commented = re.compile(rf"^[ \t]*#[ \t]*{re.escape(key)}[ \t]*=")
    out: list[str] = []
    done = False
    for current in text.split("\n"):
        if active.match(current):
            if not done:
                out.append(line)
                done = True
            continue
        out.append(current)
    if not done:
        for i, current in enumerate(out):
            if commented.match(current):
                out[i] = line
                done = True
                break
    if done:
        new, action = "\n".join(out), "podmieniono"
    else:
        block = "\n" + _ENV_COMMENTS.get(key, f"# {key}: ustawione przez training/export.\n") + f"{line}\n"
        new, action = text.rstrip("\n") + "\n" + block, "dopisano"
    if new != text:
        fsutil.atomic_write_text(ENV_PATH, new, errors="surrogateescape")
    return action


def check_env_writable() -> None:
    """update_env działa na samym końcu, PO podmianie modelu w Ollamie. Brak uprawnień do
    .env (albo do jego katalogu: zapis jest atomowy, przez plik obok) wyszedłby dopiero
    wtedy: model już nowy, a wpis i manifest stare. Sprawdzamy to na początku."""
    if not os.access(ENV_PATH.parent, os.W_OK) or (ENV_PATH.exists() and not os.access(ENV_PATH, os.R_OK | os.W_OK)):
        raise SystemExit(f"Brak uprawnień do zapisu {ENV_PATH} (albo jego katalogu). Napraw prawa "
                         f"(np. sudo chown \"$USER\" {ENV_PATH}) i uruchom trening ponownie, zanim zacznie się długa praca.")


def restart_gregai() -> bool:
    try:
        req = urllib.request.Request(GREGAI_URL + "/api/restart", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        with netguard.local_urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("restarting") is True
    except Exception as e:
        print(f"  (GREGAI nie odpowiedziało na /api/restart: {e} - zrestartuj usługę gregai.service ręcznie)")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merged", default=str(ROOT / "training" / ".work" / "out" / "merged"))
    ap.add_argument("--llama-cpp", default=str(ROOT / "training" / ".work" / "llama.cpp"))
    ap.add_argument("--python", default=sys.executable, help="python z venv treningowego (do convert_hf_to_gguf.py)")
    ap.add_argument("--model-name", default="gregai-router")
    ap.add_argument("--quantize", default="q8_0", help="np. q8_0, q4_K_M; 'none' = zostaw F16")
    ap.add_argument("--min-accuracy", type=float, default=0.85)
    ap.add_argument("--min-format", type=float, default=0.95)
    ap.add_argument("--min-brak", type=float, default=0.85,
                    help="najmniejsza trafność na przykładach BEZ narzędzia (zwykła rozmowa)")
    ap.add_argument("--host", default=router_mod.OLLAMA_HOST)
    ap.add_argument("--skip-convert", action="store_true", help="GGUF już jest, tylko importuj/oceń")
    ap.add_argument("--skip-create", action="store_true", help="model już w Ollamie, tylko oceń/włącz")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--check-prompt", action="store_true",
                    help="tylko sprawdź, czy zbiór powstał z obecnym promptem, i zakończ (run.sh przed wznowieniem treningu)")
    args = ap.parse_args()

    def check_prompt() -> None:
        ensure_built_with_current_prompt(
            DATA_DIR / "dataset_stats.json", "system_prompt",
            hashlib.sha1(router_mod.router_system_prompt().encode("utf-8")).hexdigest(),
            "router", "python3 training/build_dataset.py")

    if args.check_prompt:
        check_prompt()
        return 0
    check_env_writable()

    merged = Path(args.merged)
    work = merged.parent
    final_gguf = work / f"{args.model_name}-f16.gguf"
    quant = None if args.quantize.lower() == "none" else args.quantize

    check_prompt()

    # Nowy model czeka na bramkę pod nazwą kandydata; --skip-create ocenia
    # model, który już jest w Ollamie pod nazwą produkcyjną. Jego GGUF też ma
    # nazwę kandydata do czasu zaliczenia bramki (promote_gguf).
    eval_name = args.model_name if args.skip_create else candidate_name(args.model_name)
    gguf = work / f"{eval_name}-f16.gguf"
    if args.skip_convert and not gguf.exists() and final_gguf.exists():
        gguf = final_gguf
    if not args.skip_create:
        if not args.skip_convert:
            if not (merged / "config.json").exists():
                raise SystemExit(f"Brak scalonego modelu w {merged} - najpierw finetune.py")
            convert_to_gguf(args.python, Path(args.llama_cpp), merged, gguf)
        quant_used = ollama_create(eval_name, gguf, quant, work)
    else:
        quant_used = "(istniejący)"

    if not eval_router.model_installed(args.host, eval_name):
        raise SystemExit(f"Ollama nie widzi modelu {eval_name!r} po imporcie")

    # Czysta karta w RAM przed pomiarem (patrz eval_router.ollama_unload_all).
    eval_router.ollama_unload_all(args.host)

    golden = eval_router.read_jsonl(eval_router.GOLDEN)
    print(f"\nOcena {eval_name} na zestawie kontrolnym ({len(golden)} przykładów)...")
    rep = eval_router.evaluate(eval_name, golden, args.host)
    eval_router.print_summary(rep)
    fsutil.atomic_write_text(DATA_DIR / "eval_report.json", json.dumps(rep, ensure_ascii=False, indent=2))

    brak_acc = rep.get("brak_accuracy")
    passed = (rep["accuracy"] >= args.min_accuracy and rep["format_ok"] >= args.min_format
              and (brak_acc is None or brak_acc >= args.min_brak))
    if not passed:
        brak_txt = "" if brak_acc is None else f", rozmowa bez narzędzia {brak_acc:.1%} (próg {args.min_brak:.0%})"
        print(f"\nBRAMKA NIE PRZESZŁA: trafność {rep['accuracy']:.1%} (próg {args.min_accuracy:.0%}), "
              f"format {rep['format_ok']:.1%} (próg {args.min_format:.0%}){brak_txt}.")
        print(f"Kandydat {eval_name} zostaje w Ollamie do obejrzenia, ale model {args.model_name}, .env i manifest "
              "NIE zostały zmienione - GREGAI działa dalej dokładnie jak przedtem. Popraw dane (training/seed_examples.json, "
              "więcej realnych rozmów w decision_log) albo zwiększ --epochs i uruchom run.sh ponownie.")
        return 3

    if eval_name != args.model_name:
        promote_model(eval_name, args.model_name, args.host)
        promote_gguf(gguf, final_gguf)

    system = router_mod.router_system_prompt()
    train_report = {}
    try:
        train_report = json.loads((work / "train_report.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    manifest = {
        "model": args.model_name,
        "tools": sorted(router_mod.TOOL_NAMES),
        "system_prompt_sha1": hashlib.sha1(system.encode("utf-8")).hexdigest(),
        "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "base": train_report.get("base"),
        "train_examples": train_report.get("train_examples"),
        "quantization": quant_used,
        "golden": {"n": rep["n"], "accuracy": rep["accuracy"], "format_ok": rep["format_ok"],
                   "brak_accuracy": rep.get("brak_accuracy"), "arg_exact": rep["arg_exact"], "prompt_ms_avg": rep["prompt_ms_avg"],
                   "total_ms_avg": rep["total_ms_avg"]},
    }
    fsutil.atomic_write_text(DATA_DIR / "router_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    action = update_env(args.model_name)
    print(f"\nBRAMKA PRZESZŁA. Manifest: {DATA_DIR / 'router_manifest.json'}; .env: {action} ROUTER_MODEL={args.model_name}")
    if not args.no_restart:
        if restart_gregai():
            print("GREGAI restartuje się z nowym routerem. Sprawdź /debug -> router_status i ślad decyzji "
                  "(extra.router_model) przy kolejnych wiadomościach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
