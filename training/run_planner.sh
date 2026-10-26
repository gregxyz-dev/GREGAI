#!/usr/bin/env bash
# training/run_planner.sh - trening PLANERA pętli agenta (zadania
# wielokrokowe KROK/GOTOWE/PYTANIE), od epizodów do włączonego
# PLANNER_MODEL w .env:
#
#     bash training/run_planner.sh
#
# Etapy: venv (wspólny z run.sh) -> build_planner_dataset.py (epizody
# wzorcowe training/planner_seed.jsonl + epizody z użycia
# data/training/episodes.jsonl) -> finetune.py --task planner -> llama.cpp
# -> export_planner.py (GGUF, ollama create, ocena przez Ollamę na
# planner_eval.jsonl, bramka trafność >= 0.85 i format >= 0.95, manifest z
# zestawem narzędzi, .env, restart). Raport: data/training/planner_eval_report.md.
#
# Po co: dziś planerem jest model rozmowy z ~1000-tokenową instrukcją na
# każdy krok (zmierzone 125 s na dwukrokowe zadanie). Wytrenowany 0.5B z
# chudym promptem ma format w wagach i powinien odpowiadać wyraźnie szybciej (szacunek, bez pomiaru).
#
# Katalog narzędzi jest częścią promptu: po włączeniu SYSOP albo
# dodaniu zdolności manifest unieważnia planer i trening trzeba powtórzyć
# (ten skrypt; 0.5B: rząd kilku godzin, nie zmierzono - finetune.py wypisuje
# przewidywany czas po pierwszych krokach; patrz INSTALACJA_UBUNTU_26_04.md).
#
# Zmienne: BASE_MODEL (Qwen/Qwen2.5-0.5B-Instruct), EPOCHS (4), MAX_LEN (1536),
#          BATCH (1), GRAD_ACCUM (8) - efektywna partia 8, mało pamięci (laptop z
#          pulpitem); przy dużym zapasie RAM BATCH=4 GRAD_ACCUM=2 bywa szybsze,
#          QUANTIZE (q8_0), MODEL_NAME (gregai-planner), SKIP_INSTALL=1, NO_ENABLE=1,
#          NO_RESTART=1 (bez restartu GREGAI po włączeniu; łańcuch install.sh --train restartuje raz na końcu)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/training/.work"
VENV="$WORK/venv"
PY="$VENV/bin/python"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-0.5B-Instruct}"
EPOCHS="${EPOCHS:-4}"
MAX_LEN="${MAX_LEN:-1536}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
QUANTIZE="${QUANTIZE:-q8_0}"
MODEL_NAME="${MODEL_NAME:-gregai-planner}"
mkdir -p "$WORK"

# Jeden trening naraz: dwa równoległe zjadłyby RAM i zabiłyby się nawzajem (OOM).
exec 9>"$WORK/.train.lock"
flock -n 9 || { echo "Inny trening GREGAI już działa (blokada $WORK/.train.lock). Poczekaj, aż się skończy."; exit 75; }

# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
warp_required
preflight

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

log "1/5 Środowisko treningowe"
ensure_training_env
# Klon llama.cpp teraz, nie po godzinach treningu: brak sieci wychodzi od razu.
ensure_llama_cpp

log "2/5 Zbiór planera (epizody wzorcowe + epizody z użycia)"
check_resume_prompt "$WORK/planner" "$PY" "$ROOT/training/export_planner.py" --check-prompt
resume_or_build "$WORK/planner" "$PY" "$ROOT/training/build_planner_dataset.py"

DTYPE_ARGS=()
if [ "${BF16:-0}" = "1" ]; then DTYPE_ARGS+=(--dtype bf16); fi

log "3/5 Zwalniam RAM w Ollamie i trenuję planer ($BASE_MODEL, $EPOCHS epok, max_len $MAX_LEN)"
"$PY" "$ROOT/training/eval_router.py" --unload-only
warp_required   # model bazowy z Hugging Face pobiera się tuż po tym
"$PY" "$ROOT/training/finetune.py" --task planner --base "$BASE_MODEL" --epochs "$EPOCHS" --max-len "$MAX_LEN" \
  --batch "$BATCH" --grad-accum "$GRAD_ACCUM" \
  --train "$ROOT/data/training/planner_train.jsonl" --eval "$ROOT/data/training/planner_eval.jsonl" \
  --out "$WORK/planner" ${DTYPE_ARGS[@]+"${DTYPE_ARGS[@]}"}

log "4/5 llama.cpp do konwersji GGUF (pobrany w kroku 1)"
ensure_llama_cpp

log "5/5 GGUF -> Ollama ($MODEL_NAME, $QUANTIZE) -> ocena -> bramka -> włączenie"
EXTRA=()
if [ -n "${NO_ENABLE:-}" ]; then EXTRA+=(--no-enable); fi
if [ -n "${NO_RESTART:-}" ]; then EXTRA+=(--no-restart); fi
"$PY" "$ROOT/training/export_planner.py" --merged "$WORK/planner/merged" --llama-cpp "$WORK/llama.cpp" \
  --python "$PY" --model-name "$MODEL_NAME" --quantize "$QUANTIZE" ${EXTRA[@]+"${EXTRA[@]}"}

log "Gotowe. Raport: $ROOT/data/training/planner_eval_report.md"
