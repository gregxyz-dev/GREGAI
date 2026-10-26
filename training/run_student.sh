#!/usr/bin/env bash
# training/run_student.sh - destylacja osobowości GREGAI do małego modelu
# rozmowy (UCZEŃ), od danych do włączonego STUDENT_MODEL w .env:
#
#     bash training/run_student.sh
#
# Etapy: venv (wspólny z run.sh) -> build_distill_dataset.py (seed + zbiór
# nauczyciela training/teacher/*.jsonl + pary z chmury) -> finetune.py
# --task student -> llama.cpp -> export_student.py
# (GGUF, ollama create, ocena stylu/polskości/czasu, bramka, manifest,
# .env, restart). Raport z odpowiedziami ucznia do PRZECZYTANIA:
# data/training/student_eval_report.md - to Ty oceniasz, czy brzmi jak GREGAI.
#
# Baza: na maszynie 16 GB RAM domyślnie Qwen2.5-1.5B-Instruct (fp32, ~6 GB
# w treningu). 3B tylko z BF16=1 (bf16 na CPU bez AVX512 jest wolne, ale
# mieści się w pamięci). 7B na CPU 16 GB się NIE mieści w treningu.
# Na 8 GB (stary laptop): BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct (kilka razy krócej
# i szybciej niż 1.5B; bramka w export_student.py zdecyduje, czy uczeń jest
# wystarczająco dobry, żeby go włączyć). Czas 1.5B na i7-6600U: kilkanaście do
# kilkudziesięciu godzin (nie zmierzono; finetune.py wypisuje przewidywany czas po
# pierwszych krokach).
#
# MAX_LEN 768, nie 512: zbiór nauczyciela ma dialogi z historią (system
# ~300 tokenów + poprzednie tury + pytanie + odpowiedź); przy 512 część
# z nich wypadłaby z treningu (finetune.py wypisuje "Pominięto N").
#
# Zmienne: BASE_MODEL, EPOCHS (3), MAX_LEN (768), BATCH (1), GRAD_ACCUM (8),
#          QUANTIZE (q8_0), MODEL_NAME (gregai-student), SKIP_INSTALL=1, NO_ENABLE=1,
#          NO_RESTART=1 (bez restartu GREGAI po włączeniu; łańcuch install.sh --train restartuje raz na końcu)
#
# RAM w treningu to w większości AKTYWACJE (batch x max_len x warstwy), nie
# same wagi modelu - zmierzone 2026-10-08: ten sam ~14 GB anon-rss (z logu
# OOM killera) niezależnie od tego, czy BASE_MODEL to 0.5B czy 1.5B, przy
# BATCH=4/MAX_LEN=768. Dlatego domyślnie BATCH=1 GRAD_ACCUM=8 (efektywna partia 8,
# jak przy 4 x 2). Gdy proces mimo to ginie (dmesg/journalctl -k pokazuje "Out of
# memory: Killed process ... python"), zmniejsz MAX_LEN; przy dużym zapasie RAM
# BATCH=4 GRAD_ACCUM=2 bywa szybsze.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/training/.work"
VENV="$WORK/venv"
PY="$VENV/bin/python"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
EPOCHS="${EPOCHS:-3}"
MAX_LEN="${MAX_LEN:-768}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
QUANTIZE="${QUANTIZE:-q8_0}"
MODEL_NAME="${MODEL_NAME:-gregai-student}"
mkdir -p "$WORK"

# Jeden trening naraz: dwa równoległe zjadłyby RAM i zabiłyby się nawzajem (OOM).
exec 9>"$WORK/.train.lock"
flock -n 9 || { echo "Inny trening GREGAI już działa (blokada $WORK/.train.lock). Poczekaj, aż się skończy."; exit 75; }

# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
warp_required
preflight

log() { printf '\n\033[1;35m== %s\033[0m\n' "$*"; }

log "1/5 Środowisko treningowe"
ensure_training_env
# Klon llama.cpp teraz, nie po godzinach treningu: brak sieci wychodzi od razu.
ensure_llama_cpp

log "2/5 Zbiór destylacyjny (seed + nauczyciel + pary z chmury)"
check_resume_prompt "$WORK/student" "$PY" "$ROOT/training/export_student.py" --check-prompt
resume_or_build "$WORK/student" "$PY" "$ROOT/training/build_distill_dataset.py"

DTYPE_ARGS=()
if [ "${BF16:-0}" = "1" ]; then DTYPE_ARGS+=(--dtype bf16); fi

log "3/5 Zwalniam RAM w Ollamie i trenuję ucznia ($BASE_MODEL, $EPOCHS epok, max_len $MAX_LEN, batch $BATCH x $GRAD_ACCUM)"
"$PY" "$ROOT/training/eval_router.py" --unload-only
warp_required   # model bazowy z Hugging Face pobiera się tuż po tym
"$PY" "$ROOT/training/finetune.py" --task student --base "$BASE_MODEL" --epochs "$EPOCHS" --max-len "$MAX_LEN" \
  --batch "$BATCH" --grad-accum "$GRAD_ACCUM" \
  --train "$ROOT/data/training/student_train.jsonl" --eval "$ROOT/data/training/student_eval.jsonl" \
  --out "$WORK/student" --eval-limit 10 ${DTYPE_ARGS[@]+"${DTYPE_ARGS[@]}"}

log "4/5 llama.cpp do konwersji GGUF (pobrany w kroku 1)"
ensure_llama_cpp

log "5/5 GGUF -> Ollama ($MODEL_NAME, $QUANTIZE) -> ocena -> włączenie"
EXTRA=()
if [ -n "${NO_ENABLE:-}" ]; then EXTRA+=(--no-enable); fi
if [ -n "${NO_RESTART:-}" ]; then EXTRA+=(--no-restart); fi
"$PY" "$ROOT/training/export_student.py" --merged "$WORK/student/merged" --llama-cpp "$WORK/llama.cpp" \
  --python "$PY" --model-name "$MODEL_NAME" --quantize "$QUANTIZE" ${EXTRA[@]+"${EXTRA[@]}"}

log "Gotowe. Przeczytaj: $ROOT/data/training/student_eval_report.md"
