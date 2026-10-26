#!/usr/bin/env bash
# training/_common.sh - wspólne kroki run.sh, run_planner.sh i run_student.sh.
# Ładowany przez `source`, nie uruchamiany osobno. Wymaga zmiennych WORK, VENV, PY.

# WARP jest obowiązkowy także tutaj (zasada projektu: cały ruch do internetu
# tylko przez Cloudflare WARP). Trening ściąga pakiety z PyPI i PyTorch, model
# bazowy z Hugging Face i llama.cpp z GitHuba, więc bez WARP nie rusza.
# Odpowiedź do zmiennej, nie `curl | grep -q` (SIGPIPE przy pipefail).
# --noproxy: pytamy trasą tej maszyny (proxy z sieci lokalnej leży poza tunelem).
warp_required() {
  local t
  t="$(curl -fsS --noproxy '*' --max-time 10 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null || true)"
  if ! grep -q '^warp=\(on\|plus\)' <<<"$t"; then
    echo "WARP nie jest połączony (zasada projektu: internet tylko przez Cloudflare WARP)."
    echo "Sprawdź: warp-cli status ; połącz: warp-cli connect ; potem uruchom trening ponownie."
    exit 1
  fi
}

# Polecenie ollama (create, cp, rm) ma rozmawiać z Ollamą na TEJ maszynie, nawet gdy
# w powłoce został OLLAMA_HOST wskazujący inny serwer (create wysyła plik modelu).
# Postać URL: tę samą zmienną czyta też agent (router.py wymaga schematu).
export OLLAMA_HOST=http://127.0.0.1:11434

# Kontrola przed wielogodzinną pracą: Ollama odpowiada (eksport na końcu jej potrzebuje, a
# brak wychodziłby dopiero po treningu) i jest miejsce na dysku (biblioteki, model bazowy,
# scalony model, GGUF). Argument: ile GB wolnego miejsca wymagać.
preflight() {
  local need_gb="${1:-15}" free_kb
  if ! curl -fsS --noproxy '*' --max-time 5 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    echo "Ollama nie odpowiada na $OLLAMA_HOST (sprawdź: systemctl status ollama). Eksport na końcu treningu jej potrzebuje."
    exit 1
  fi
  free_kb="$(df -Pk "$WORK" | awk 'NR==2 {print $4}')"
  if [ "${free_kb:-0}" -lt $((need_gb * 1024 * 1024)) ]; then
    echo "Za mało miejsca na dysku w $WORK: wolne $(( ${free_kb:-0} / 1024 / 1024 )) GB, potrzeba ok. $need_gb GB (biblioteki, model bazowy, GGUF)."
    exit 1
  fi
  # Trening to dni pracy dwóch rdzeni: na baterii skończyłby się po godzinie z pustym
  # akumulatorem. FORCE=1 wymusza (np. gdy odczyt zasilacza zawodzi).
  if [ "${FORCE:-0}" != "1" ] && on_battery; then
    echo "Laptop pracuje z baterii: trening (dni obliczeń) ma sens tylko na zasilaczu. Podłącz zasilacz albo uruchom z FORCE=1."
    exit 1
  fi
}

# Czy laptop jest na baterii: zasilacz (type=Mains) z online=0. Brak informacji = zasilacz.
on_battery() {
  local p
  for p in /sys/class/power_supply/*; do
    [ -r "$p/type" ] || continue
    if [ "$(cat "$p/type" 2>/dev/null)" = "Mains" ] && [ "$(cat "$p/online" 2>/dev/null)" = "0" ]; then
      return 0
    fi
  done
  return 1
}

# finetune.py podmienia punkt kontrolny w dwóch krokach (stary -> checkpoint.old, nowy -> checkpoint):
# przerwanie między nimi zostawia tylko checkpoint.old, do którego wracamy (jak robi to finetune.py).
restore_old_checkpoint() {
  local out="$1"
  if [ -z "${FRESH:-}" ] && [ ! -d "$out/checkpoint" ] && [ -f "$out/checkpoint.old/state.json" ]; then
    mv "$out/checkpoint.old" "$out/checkpoint" && echo "Odzyskuję poprzedni punkt kontrolny ($out/checkpoint.old)."
  fi
}

# Punkt kontrolny przerwanego treningu (finetune.py zapisuje go po każdej epoce). Gdy jest, zbiór
# zostaje taki, jaki był: zbudowany od nowa miałby inny podpis (nowe wpisy w śladzie decyzji) i
# trening ruszyłby od zera. FRESH=1 kasuje punkt i zaczyna od początku.
# Użycie: resume_or_build <katalog wyniku treningu> <polecenie budujące zbiór...>
resume_or_build() {
  local out="$1"
  shift
  if [ -n "${FRESH:-}" ]; then rm -rf "${out:?}/checkpoint" "${out:?}/checkpoint.old"; fi
  restore_old_checkpoint "$out"
  if [ -f "$out/checkpoint/state.json" ]; then
    echo "Jest punkt kontrolny przerwanego treningu ($out/checkpoint): zbiór bez zmian, trening zostanie wznowiony (FRESH=1 zaczyna od zera)."
  else
    "$@"
  fi
}

# Wznawiany trening na zbiorze zbudowanym z innym promptem niż obecny w kodzie (zmieniony katalog
# narzędzi albo opis) skończyłby się odrzuceniem przy eksporcie, po godzinach pracy. Sprawdzamy
# to od razu. Użycie: check_resume_prompt <katalog wyniku> <polecenie sprawdzające...>
check_resume_prompt() {
  local out="$1"
  shift
  restore_old_checkpoint "$out"
  if [ -z "${FRESH:-}" ] && [ -f "$out/checkpoint/state.json" ]; then
    "$@" || {
      echo "Punkt kontrolny w $out należy do zbioru zbudowanego z innym promptem niż obecny w kodzie." >&2
      echo "Zacznij od zera (stary punkt zostanie skasowany):  FRESH=1 bash training/$(basename "$0")" >&2
      exit 1
    }
  fi
}

# venv + biblioteki ML (tylko tutaj; serwer GREGAI zostaje czystym stdlib).
# Po odtworzeniu venv (np. po aktualizacji Pythona w systemie) znacznik
# .deps_ok jest zdejmowany, bo nowe środowisko nie ma bibliotek.
ensure_training_env() {
  # Przerwane `python3 -m venv` (Ctrl-C, brak miejsca) zostawia bin/python bez pip:
  # samo -x go nie wykryje, a każde kolejne uruchomienie padałoby na pip install.
  if [ ! -x "$PY" ] || ! "$PY" -m pip --version >/dev/null 2>&1; then
    rm -rf "${VENV:?}"
    python3 -m venv "$VENV"
    rm -f "$WORK/.deps_ok"
  fi
  if [ -z "${SKIP_INSTALL:-}" ] && [ ! -f "$WORK/.deps_ok" ]; then
    warp_required   # za chwilę pobieranie z PyPI i PyTorch
    "$PY" -m pip install --upgrade pip wheel >/dev/null
    # Wersja CPU torcha: kilkukrotnie mniejsza niż domyślna z CUDA, a GPU tu nie ma.
    "$PY" -m pip install --index-url https://download.pytorch.org/whl/cpu torch
    # transformers >= 4.56: finetune.py woła from_pretrained(..., dtype=...).
    "$PY" -m pip install "transformers>=4.56" "peft>=0.13" accelerate safetensors numpy sentencepiece protobuf tokenizers
    touch "$WORK/.deps_ok"
  fi
}

# llama.cpp (tylko konwerter HF -> GGUF). Przerwany klon zostawia katalog bez
# konwertera, więc przed ponowną próbą jest usuwany. Klon jest jednorazowy (kolejne
# uruchomienia go nie odświeżają), a użyty commit trafia do training/.work/llama.cpp.rev.
# Domyślnie bierze najnowszy kod; LLAMACPP_REF=<tag albo gałąź> (np. b1234) przypina
# wersję, którą już sprawdziłeś: WARP szyfruje połączenie, ale nie gwarantuje, że
# kod na GitHubie jest ten, który znasz, a konwerter działa z Twoimi prawami.
ensure_llama_cpp() {
  if [ ! -f "$WORK/llama.cpp/convert_hf_to_gguf.py" ]; then
    warp_required   # klon z GitHuba też tylko przez WARP
    rm -rf "${WORK:?}/llama.cpp"
    if [ -n "${LLAMACPP_REF:-}" ]; then
      git clone --depth 1 --branch "$LLAMACPP_REF" https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
    else
      git clone --depth 1 https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
    fi
    git -C "$WORK/llama.cpp" rev-parse HEAD > "$WORK/llama.cpp.rev"
    echo "llama.cpp: commit $(cat "$WORK/llama.cpp.rev")"
  fi
  if ! "$PY" -c "import gguf" 2>/dev/null; then
    "$PY" -m pip install "$WORK/llama.cpp/gguf-py" >/dev/null
  fi
}
