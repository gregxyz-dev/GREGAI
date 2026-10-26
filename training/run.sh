#!/usr/bin/env bash
# training/run.sh - samo-trening routera GREGAI, od danych do działającego
# modelu w Ollamie i włączonego w .env. JEDNA komenda, uruchamiana na
# laptopie, na którym działa GREGAI i Ollama:
#
#     bash training/run.sh
#
# Co robi (każdy etap to osobny skrypt, można je odpalać pojedynczo):
#   1. venv w training/.work/venv + biblioteki ML (tylko tutaj, serwer
#      GREGAI dalej jest czystym stdlib) - za pierwszym razem kilka minut
#      i ~1.5-2.5 GB na dysku (torch CPU jest duży).
#   2. build_dataset.py  - zbiór treningowy z WŁASNYCH danych GREGAI.
#   3. eval_router.py --unload-only - zwolnienie RAM w Ollamie.
#   4. finetune.py       - LoRA na Qwen2.5-1.5B-Instruct (pobierany z
#                          Hugging Face za pierwszym razem, ~3 GB), CPU.
#   5. export.py         - GGUF (konwerter z klonu llama.cpp, pobranego w
#                          kroku 1), `ollama create`, ocena na zestawie
#                          kontrolnym, i DOPIERO gdy przejdzie bramkę:
#                          manifest + ROUTER_MODEL w .env + restart GREGAI.
#
# Zmienne (opcjonalne):  BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct (tylko na 8 GB
#                        RAM; domyślnie 1.5B)  EPOCHS=3 (domyślnie)
#                        QUANTIZE=q8_0 (domyślnie; np. q4_K_M)  MODEL_NAME=gregai-router
#                        SKIP_INSTALL=1 (gdy venv już gotowy)
#                        LLAMACPP_REF=<tag albo gałąź> (przypięcie wersji llama.cpp;
#                        domyślnie najnowsza, użyty commit: .work/llama.cpp.rev)
#                        BATCH=1 GRAD_ACCUM=8 (domyślnie; ten sam efektywny
#                        rozmiar partii co 4 x 2, a dużo mniej pamięci: na
#                        laptopie z pulpitem i przeglądarką 4 x 2 kończy się
#                        zabiciem procesu przez OOM. Przy dużym zapasie RAM
#                        BATCH=4 GRAD_ACCUM=2 bywa trochę szybsze)
#                        NO_RESTART=1 (nie restartuj GREGAI po włączeniu modelu;
#                        używa tego łańcuch install.sh --train, który restartuje raz na końcu)
#
# Szacunki na Dell Latitude E7270 (i7-6600U, 2 rdzenie / 4 wątki, bez GPU, 16 GB RAM):
#   instalacja ~5-10 min (raz), pobranie bazy ~3 GB (raz), konwersja+import
#   ~1-2 min, ocena ~1-2 min. Sam trening 1.5B w fp32 to ok. 600 tysięcy
#   tokenów (ok. 1400 przykładów x 150 tokenów x 3 epoki) po ~6 GFLOP każdy, a ten
#   procesor daje realnie kilkadziesiąt GFLOPS: rząd kilkunastu godzin (0.5B: kilka razy krócej).
#   Tego nie zmierzono na tej maszynie: finetune.py wypisuje przewidywany czas po
#   pierwszych krokach ("zostało ~X min"), to jest wiarygodna liczba. W trakcie treningu GREGAI dalej działa, ale
#   odpowiada wolniej (CPU zajęty) - najlepiej odpalić, gdy nie rozmawiasz.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/training/.work"
VENV="$WORK/venv"
PY="$VENV/bin/python"
# Domyślnie 1.5B - to jest ZABLOKOWANA decyzja (2026-10-08: router =
# Qwen2.5-1.5B). Na maszynie 8 GB (stary laptop) zejdź świadomie:
# BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct bash training/run.sh
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
EPOCHS="${EPOCHS:-3}"
BATCH="${BATCH:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
QUANTIZE="${QUANTIZE:-q8_0}"
MODEL_NAME="${MODEL_NAME:-gregai-router}"
mkdir -p "$WORK"

# Jeden trening naraz: dwa równoległe zjadłyby RAM i zabiłyby się nawzajem (OOM).
exec 9>"$WORK/.train.lock"
flock -n 9 || { echo "Inny trening GREGAI już działa (blokada $WORK/.train.lock). Poczekaj, aż się skończy."; exit 75; }

# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
warp_required
preflight

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

log "1/5 Środowisko treningowe ($VENV)"
ensure_training_env
# Klon llama.cpp teraz, nie dopiero po kilku godzinach treningu: brak sieci albo
# GitHuba wychodzi od razu, a nie po zmarnowanym treningu.
ensure_llama_cpp
"$PY" -c "import torch, transformers, peft; print('torch', torch.__version__, '| transformers', transformers.__version__, '| peft', peft.__version__, '| wątki', torch.get_num_threads())"

log "2/5 Zbiór treningowy z danych GREGAI"
check_resume_prompt "$WORK/out" "$PY" "$ROOT/training/export.py" --check-prompt
resume_or_build "$WORK/out" "$PY" "$ROOT/training/build_dataset.py"

log "3/5 Zwalniam RAM w Ollamie"
"$PY" "$ROOT/training/eval_router.py" --unload-only

log "4/5 Trening LoRA ($BASE_MODEL, $EPOCHS epok, CPU)"
warp_required   # model bazowy z Hugging Face pobiera się tuż po tym (po minutach pip i budowania zbioru WARP mógł zniknąć)
"$PY" "$ROOT/training/finetune.py" --base "$BASE_MODEL" --epochs "$EPOCHS" \
  --batch "$BATCH" --grad-accum "$GRAD_ACCUM" --out "$WORK/out"

log "5/5 GGUF -> Ollama ($MODEL_NAME, $QUANTIZE) -> ocena -> włączenie"
EXTRA=()
if [ -n "${NO_RESTART:-}" ]; then EXTRA+=(--no-restart); fi
"$PY" "$ROOT/training/export.py" --merged "$WORK/out/merged" --llama-cpp "$WORK/llama.cpp" \
  --python "$PY" --model-name "$MODEL_NAME" --quantize "$QUANTIZE" ${EXTRA[@]+"${EXTRA[@]}"}

log "Gotowe. Raporty: $ROOT/data/training/ (dataset_stats.json, eval_report.json, router_manifest.json)"
