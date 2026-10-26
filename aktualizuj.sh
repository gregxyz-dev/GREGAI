#!/usr/bin/env bash
# aktualizuj.sh - uruchom PO wgraniu nowej wersji GREGAI na laptop.
#
# Robi cztery rzeczy, idempotentnie (można odpalać ile razy chcesz):
#   1. Wykrywa własną ścieżkę - działa, gdziekolwiek leży folder GREGAI.
#   2. Jeśli folder zmienił miejsce od ostatniego razu: wypisuje starą i NOWĄ
#      ścieżkę i przepina usługi systemd (gregai, gregai-siec) na nową, żeby
#      nie wskazywały w próżnię.
#   3. Poprawia w .env wpis SYSOP_ROOTS, jeśli wskazywał starą ścieżkę projektu.
#   3b. (1.18.0) Migruje .env do nowego kodu tak samo jak install.sh: brakujący
#      KORYTO, stary dzienny limit Claude 50 -> 300; ostrzega, gdy SYSOP_MODE
#      w .env nie pasuje do reguł sudo (wtedy trzeba bash install.sh).
#   4. Restartuje gregai i (1.19.0) SPRAWDZA, że naprawdę wstał: czeka do 60 s
#      na odpowiedź /api/status i aktywną usługę; gdy nie - pokazuje ostatnie
#      linie dziennika i kończy się błędem (dawniej "nowy kod aktywny" padało
#      zawsze, nawet gdy main.py wywracał się przy imporcie).
# Na końcu zawsze wypisuje aktualną ścieżkę projektu.
#
# 1.19.0 - bezpieczna aktualizacja z paczki i powrót:
#   bash aktualizuj.sh ~/Pobrane/GREGAI-1.19.0.zip   (albo: gregai update PLIK.zip)
#     rozpakowuje paczkę OBOK projektu, sprawdza ją (GREGAI.sha256, składnia
#     Pythona i skryptów), robi kopię obecnego kodu w
#     ~/.local/share/gregai/kopie/<wersja>-<data>, podmienia kod (notatki/,
#     memory/, data/, backups/ i .env NIETKNIĘTE; nowe notatki z paczki
#     dopisywane tylko, gdy takiego pliku jeszcze nie ma), restartuje i czeka
#     na odpowiedź. GREGAI nie wstał -> automatyczny powrót do kopii.
#   bash aktualizuj.sh --rollback   (albo: gregai rollback)
#     ręczny powrót do kodu sprzed ostatniej aktualizacji z paczki.
#
# Ścieżkę z ostatniego uruchomienia trzyma POZA projektem
# (~/.config/gregai/sciezka), żeby przetrwała nadpisanie folderu nową paczką
# i żeby wykryć przeniesienie; zapisuje ją dopiero po udanym przepięciu (przerwane
# sudo nie gubi wykrycia przeniesienia). Nie dotyka zabezpieczeń (WARP, ufw, apparmor).
set -uo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Uruchom jako zwykły użytkownik, BEZ sudo:  bash aktualizuj.sh"
  echo "(sudo skrypt wywoła sam; uruchomiony jako root zostawiłby w projekcie pliki roota)."
  exit 1
fi

MODE=normal
ZIP=""
case "${1:-}" in
  "") ;;
  --rollback|rollback|cofnij) MODE=rollback ;;
  # 1.29.0 (kontrola): wewnętrzny etap po podmianie kodu - kroki "po wgraniu" (migracje
  # .env, ostrzeżenia, restart z automatycznym powrotem) robi już NOWY skrypt.
  --po-paczce) MODE=zip; POST_ZIP=1; SNAP="${GREGAI_AKT_SNAP:-}" ;;
  -h|--help)
    echo "Użycie: bash aktualizuj.sh [PLIK.zip | --rollback]"
    echo "  bez argumentu  po ręcznym wgraniu nowej wersji: przepięcie usług, .env, restart i sprawdzenie"
    echo "  PLIK.zip       bezpieczna aktualizacja z paczki (kopia obecnego kodu, automatyczny powrót)"
    echo "  --rollback     powrót do kodu sprzed ostatniej aktualizacji z paczki"
    exit 0 ;;
  *.zip|*.ZIP)
    MODE=zip
    ZIP="$(realpath -e "$1" 2>/dev/null || true)"
    [ -n "$ZIP" ] && [ -f "$ZIP" ] || { echo "Nie ma takiej paczki: $1"; exit 1; } ;;
  *) echo "Nieznany argument: $1 (bash aktualizuj.sh --help)"; exit 2 ;;
esac

ROOT="${GREGAI_AKT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)}"
# Aktualizacja z paczki i powrót PODMIENIAJĄ ten skrypt w trakcie działania, a
# bash czyta skrypt kawałkami - podmiana w połowie wykonałaby przypadkowy
# fragment nowego pliku. Dlatego najpierw kopia skryptu poza projektem i
# uruchomienie jej (ROOT przekazany jawnie).
if [ "$MODE" != normal ] && [ -z "${GREGAI_AKT_COPY:-}" ]; then
  _copy="$(mktemp "${TMPDIR:-/tmp}/gregai-aktualizuj.XXXXXX")"
  cp "$ROOT/aktualizuj.sh" "$_copy"
  GREGAI_AKT_COPY="$_copy" GREGAI_AKT_ROOT="$ROOT" exec bash "$_copy" "$@"
fi
[ -n "${GREGAI_AKT_COPY:-}" ] && trap 'rm -f "$GREGAI_AKT_COPY"' EXIT

STATE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gregai"
STATE="$STATE_DIR/sciezka"
need_sudo() { if [ "$(id -u)" -ne 0 ]; then sudo "$@"; else "$@"; fi; }
# ROOT bezpiecznie wstawiony po prawej stronie polecenia sed (znaki \ / & |).
ROOT_ESC="$(printf '%s' "$ROOT" | sed -e 's/[\\/&|]/\\&/g')"

PORT=7777
SNAP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/gregai/kopie"

unit_present() { need_sudo systemctl list-unit-files gregai.service >/dev/null 2>&1 && need_sudo systemctl cat gregai >/dev/null 2>&1; }

# GREGAI naprawdę wstał: usługa aktywna i /api/status odpowiada, do 60 s (1.29.0: duży
# zbiór notatek i sprzątanie po awarii przy starcie potrafią trwać dłużej niż 25 s).
health_ok() {
  for _ in $(seq 1 60); do
    if systemctl is-active --quiet gregai 2>/dev/null \
       && curl -fsS --max-time 3 -o /dev/null "http://127.0.0.1:$PORT/api/status" 2>/dev/null; then
      sleep 2   # usługa, która pada przy starcie, bywa "active" przez pierwszą sekundę
      systemctl is-active --quiet gregai 2>/dev/null && return 0
    fi
    sleep 1
  done
  return 1
}

journal_tail() {
  echo "   Ostatnie linie dziennika (journalctl -u gregai):"
  need_sudo journalctl -u gregai -n 25 --no-pager 2>/dev/null | sed 's/^/     /' || true
}

restart_and_check() {  # $1 = opis, co ma być aktywne
  if ! need_sudo systemctl restart gregai; then
    echo "UWAGA: systemctl restart gregai się nie powiódł."
    journal_tail
    return 1
  fi
  if health_ok; then
    echo "GREGAI zrestartowany i odpowiada - $1."
    return 0
  fi
  echo "UWAGA: GREGAI po restarcie NIE odpowiada (usługa nieaktywna albo brak odpowiedzi na porcie $PORT po 60 s)."
  journal_tail
  return 1
}

# --- Kod a dane użytkownika (1.19.0) -----------------------------------------
# "Kod" to wszystko z paczki POZA: .env*, data/, memory/, notatki/, backups/,
# training/.work/ (modele z treningu), *.gguf i __pycache__. Te zostają zawsze.
code_copy() {  # $1 = skąd, $2 = dokąd
  (cd "$1" && tar -cf - --exclude='./.env*' --exclude=./data --exclude=./memory --exclude=./notatki \
      --exclude=./backups --exclude=./training/.work --exclude='*.gguf' --exclude='__pycache__' \
      --exclude='./.gregai-*' .) | (cd "$2" && tar -xf -) || return 1
  if [ -f "$1/.env.example" ]; then cp -p "$1/.env.example" "$2/.env.example" || return 1; fi
}

# Pliki, które były w starej paczce (jej GREGAI.sha256), a nie ma ich w nowej:
# usuwamy WYŁĄCZNIE takie (nigdy pliku, którego paczka nie dostarczyła) i nigdy
# nic z danych użytkownika.
remove_stale() {  # $1 = stary manifest, $2 = nowy manifest, $3 = katalog
  [ -f "$1" ] && [ -f "$2" ] || return 0
  python3 - "$1" "$2" "$3" <<'PY'
import os, sys
def names(p):
    out = set()
    for line in open(p, encoding="utf-8", errors="replace"):
        parts = line.rstrip("\n").split("  ", 1)
        if len(parts) == 2:
            out.add(parts[1].lstrip("*"))
    return out
old, new, root = names(sys.argv[1]), names(sys.argv[2]), os.path.realpath(sys.argv[3])
keep = ("data/", "memory/", "notatki/", "backups/", "training/.work/")
for rel in sorted(old - new):
    if rel.startswith(keep) or rel.startswith(".env") or rel.startswith("/") or ".." in rel.split("/"):
        continue
    path = os.path.realpath(os.path.join(root, rel))
    if path.startswith(root + os.sep) and os.path.isfile(path):
        os.remove(path)
        print("   usunięty (nie ma go w nowej wersji):", rel)
PY
}

snapshot_current() {  # -> ścieżka kopii na stdout
  local ver snap
  ver="$(cat "$ROOT/VERSION" 2>/dev/null | tr -cd '0-9A-Za-z.-' || true)"
  snap="$SNAP_DIR/${ver:-nieznana}-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$snap" && code_copy "$ROOT" "$snap" || { rm -rf "$snap"; return 1; }
  printf '%s\n' "$snap" > "$SNAP_DIR/ostatnia"
  # Trzy najnowsze kopie wystarczą (każda to sam kod, kilka MB).
  ls -1dt "$SNAP_DIR"/*/ 2>/dev/null | tail -n +4 | while read -r old; do rm -rf "$old"; done
  printf '%s\n' "$snap"
}

# 1.32.9 (audyt tura 13): od 1.32.8 zadania stałe zapisują terminy ze strefą (+01:00). Kod sprzed
# 1.32.8 porównuje je z czasem bez strefy i każde zadanie po cichu staje (TypeError co tick).
# Po powrocie do starszego kodu zdejmujemy strefę z tych dwóch pól (czas lokalny zostaje ten sam).
downgrade_compat() {
  local v; v="$(cat "$ROOT/VERSION" 2>/dev/null || echo 0)"
  [ "$(printf '%s\n%s\n' "$v" "1.32.8" | sort -V | head -1)" = "1.32.8" ] && return 0
  local f
  for f in "$ROOT"/data/standing_tasks/*.md; do
    [ -f "$f" ] || continue
    sed -i -E 's/^((nastepne|ostatnie)_sprawdzenie:[[:space:]]*[0-9T:-]+)[+-][0-9]{2}:[0-9]{2}[[:space:]]*$/\1/' "$f" 2>/dev/null || true
  done
}

restore_code() {  # $1 = kopia, z której przywracamy
  local snap="$1" cur_manifest
  cur_manifest="$(mktemp)"; cp "$ROOT/GREGAI.sha256" "$cur_manifest" 2>/dev/null || : > "$cur_manifest"
  code_copy "$snap" "$ROOT" || { rm -f "$cur_manifest"; return 1; }
  remove_stale "$cur_manifest" "$snap/GREGAI.sha256" "$ROOT"
  rm -f "$cur_manifest"
  downgrade_compat

  chmod +x "$ROOT/gregai" 2>/dev/null || true
}

if [ "$MODE" = rollback ]; then
  echo "== GREGAI: powrót do poprzedniej wersji kodu =="
  SNAP="$(cat "$SNAP_DIR/ostatnia" 2>/dev/null || true)"
  if [ -z "$SNAP" ] || [ ! -f "$SNAP/VERSION" ]; then
    echo "Brak kopii do powrotu ($SNAP_DIR). Kopia powstaje przy aktualizacji z paczki: gregai update PLIK.zip"
    exit 1
  fi
  echo "Obecna wersja: $(cat "$ROOT/VERSION" 2>/dev/null || echo '?')  ->  wracam do: $(cat "$SNAP/VERSION") ($SNAP)"
  restore_code "$SNAP" || { echo "UWAGA: przywracanie kodu nie powiodło się."; exit 1; }
  if unit_present; then
    restart_and_check "działa kod $(cat "$ROOT/VERSION")" || exit 1
  fi
  echo "Gotowe. Notatki, pamięć, data/ i .env nie były ruszane."
  exit 0
fi

if [ "$MODE" = zip ] && [ -z "${POST_ZIP:-}" ]; then
  echo "== GREGAI: aktualizacja z paczki $ZIP =="
  mkdir -p "$HOME/.cache"
  STAGE="$(mktemp -d "$HOME/.cache/gregai-aktualizacja.XXXXXX")"
  trap 'rm -rf "$STAGE"; [ -n "${GREGAI_AKT_COPY:-}" ] && rm -f "$GREGAI_AKT_COPY"' EXIT
  # zipfile z Pythona (zawsze jest), nie unzip: ścieżki z ".." i bezwzględne są przez niego odcinane.
  if ! python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$ZIP" "$STAGE" 2>/dev/null; then
    echo "Paczka jest uszkodzona albo to nie zip: $ZIP"; exit 1
  fi
  SRC="$STAGE"
  if [ ! -f "$SRC/VERSION" ]; then
    # Paczka z jednym katalogiem w środku (GREGAI/...).
    SRC="$(find "$STAGE" -mindepth 2 -maxdepth 2 -name VERSION -printf '%h\n' 2>/dev/null | head -1)"
  fi
  if [ -z "$SRC" ] || [ ! -f "$SRC/VERSION" ] || [ ! -f "$SRC/agent/main.py" ]; then
    echo "To nie wygląda na paczkę GREGAI (brak VERSION albo agent/main.py)."; exit 1
  fi
  NEW_VER="$(cat "$SRC/VERSION")"; CUR_VER="$(cat "$ROOT/VERSION" 2>/dev/null || echo '?')"
  echo "Obecna wersja: $CUR_VER  ->  nowa: $NEW_VER"
  # 1.32.9 (audyt tura 13): cofnięcie wersji przez paczkę zip - świadomie, z ostrzeżeniem.
  if [ "$CUR_VER" != "?" ] && [ "$(printf '%s\n%s\n' "$NEW_VER" "$CUR_VER" | sort -V | head -1)" = "$NEW_VER" ] && [ "$NEW_VER" != "$CUR_VER" ]; then
    echo "UWAGA: paczka ma STARSZĄ wersję ($NEW_VER) niż zainstalowana ($CUR_VER) - to cofnięcie wersji."
  fi
  if [ ! -f "$SRC/GREGAI.sha256" ]; then
    echo "Paczka nie ma GREGAI.sha256 - nie da się sprawdzić, czy jest kompletna. Nie aktualizuję."; exit 1
  fi
  if ! (cd "$SRC" && sha256sum -c --quiet GREGAI.sha256 >/dev/null 2>&1); then
    echo "Paczka NIE zgadza się z GREGAI.sha256 (uszkodzona albo zmieniona po spakowaniu). Nie aktualizuję."
    (cd "$SRC" && sha256sum -c --quiet GREGAI.sha256 2>&1 | head -5 | sed 's/^/   /')
    exit 1
  fi
  # 1.32.2 (audyt tura 7): plik spoza GREGAI.sha256 (np. agent/json.py, który podmieniłby
  # moduł json Pythona) nie wchodzi - sha256sum -c sprawdza tylko pliki z listy.
  if ! python3 - "$SRC" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1])
listed = set()
for line in (src / "GREGAI.sha256").read_text(encoding="utf-8").splitlines():
    _h, _, name = line.partition("  ")
    if name:
        listed.add(name)
extra = sorted(str(p.relative_to(src)) for p in src.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.name != "GREGAI.sha256"
               and str(p.relative_to(src)) not in listed)
if extra:
    print("   pliki spoza listy sum kontrolnych:", ", ".join(extra[:5]))
    sys.exit(1)
PY
  then echo "Paczka zawiera pliki spoza GREGAI.sha256. Nie aktualizuję."; exit 1; fi
  # Ta sama wersja, inna zawartość: straż uznałaby nowe sumy za próbę przykrycia podmiany
  # kodu (pieczęć wiąże sumy z numerem wersji). Wydanie z inną treścią ma nowy numer.
  if [ "$NEW_VER" = "$CUR_VER" ] && [ -f "$ROOT/GREGAI.sha256" ] && ! cmp -s "$SRC/GREGAI.sha256" "$ROOT/GREGAI.sha256"; then
    echo "Paczka ma tę samą wersję ($NEW_VER), ale inną zawartość niż zainstalowana. Nie aktualizuję:"
    echo "straż uznałaby nowe sumy kontrolne za próbę przykrycia podmiany kodu. Poproś o paczkę z nowym numerem wersji."
    exit 1
  fi
  # Składnia bez zapisu __pycache__ (ast.parse) i bez uruchamiania czegokolwiek.
  if ! python3 - "$SRC" <<'PY'
import ast, pathlib, sys
bad = []
for p in sorted(pathlib.Path(sys.argv[1]).glob("**/*.py")):
    if "__pycache__" in p.parts or ".work" in p.parts:
        continue
    try:
        ast.parse(p.read_bytes(), str(p))
    except SyntaxError as e:
        bad.append(f"{p.name}:{e.lineno}")
if bad:
    print("   błędy składni:", ", ".join(bad[:5]))
    sys.exit(1)
PY
  then echo "Paczka ma błędy składni Pythona. Nie aktualizuję."; exit 1; fi
  for sh in "$SRC"/install.sh "$SRC"/aktualizuj.sh "$SRC"/check.sh "$SRC"/gregai; do
    if [ -f "$sh" ] && ! bash -n "$sh" 2>/dev/null; then echo "Błąd składni w $(basename "$sh"). Nie aktualizuję."; exit 1; fi
  done
  echo "Paczka sprawdzona (sumy kontrolne, składnia)."
  SNAP="$(snapshot_current)" || { echo "Nie udało się zrobić kopii obecnego kodu. Nie aktualizuję."; exit 1; }
  echo "Kopia obecnego kodu: $SNAP"
  if ! code_copy "$SRC" "$ROOT"; then
    echo "UWAGA: podmiana kodu się nie powiodła - wracam do kopii."
    restore_code "$SNAP"; exit 1
  fi
  # 1.32.17 (audyt tura 19): code_copy pisze pliki *.py strumieniowo, w miejscu
  # (tar|tar), nie przez plik tymczasowy + rename. Przerwanie W ŚRODKU (Ctrl+C,
  # zanik zasilania, zamknięcie laptopa) zostawia plik .py obcięty w połowie, a
  # jedyne automatyczne przywracanie dotąd działało tylko, gdy "code_copy" samo
  # zwróci błąd albo gdy usługa nie wstanie PO zakończeniu całego skryptu -
  # przerwanie samego skryptu w środku kopiowania nie trafiało w żadną z tych
  # ścieżek. Szybki sanity-check całego katalogu agent/ (jak już robi się dla
  # paczki źródłowej) łapie też ten przypadek, zanim ktokolwiek spróbuje
  # wystartować usługę na obciętym kodzie.
  if ! python3 -c "
import pathlib, py_compile, sys
bad = []
for p in pathlib.Path('$ROOT/agent').rglob('*.py'):
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        bad.append(f'{p}: {e}')
if bad:
    print('\n'.join(bad), file=sys.stderr)
    sys.exit(1)
"; then
    echo "UWAGA: kod po podmianie nie jest kompletny (obcięty/uszkodzony plik .py) - wracam do kopii."
    restore_code "$SNAP"; exit 1
  fi
  remove_stale "$SNAP/GREGAI.sha256" "$SRC/GREGAI.sha256" "$ROOT"
  # Nowe notatki z paczki (wiedza, szkoła) tylko tam, gdzie takiego pliku jeszcze nie ma:
  # Twoje zmiany w notatkach z paczki zostają.
  if [ -d "$SRC/notatki" ]; then
    mkdir -p "$ROOT/notatki"
    (cd "$SRC/notatki" && tar -cf - .) | (cd "$ROOT/notatki" && tar -xf - --skip-old-files) \
      || echo "UWAGA: nie udało się dopisać nowych notatek z paczki (kod jest podmieniony)."
    # 1.29.0 (kontrola): notatka z paczki, której NIE zmieniałeś (suma = suma ze starej
    # paczki), dostaje nową wersję - np. poprawione fakty w wiedzy. Twoje zmiany zostają.
    if [ -f "$SNAP/GREGAI.sha256" ] && [ -f "$SRC/GREGAI.sha256" ]; then
      python3 - "$SNAP/GREGAI.sha256" "$SRC/GREGAI.sha256" "$SRC" "$ROOT" <<'PYEOF' || echo "UWAGA: nie udało się odświeżyć notatek z paczki."
import hashlib, shutil, sys
from pathlib import Path
def manifest(p):
    out = {}
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        h, _, name = line.partition("  ")
        if name:
            out[name] = h
    return out
old, new = manifest(sys.argv[1]), manifest(sys.argv[2])
src, root = Path(sys.argv[3]), Path(sys.argv[4])
n = 0
for name, h_new in new.items():
    if not name.startswith("notatki/") or old.get(name) in (None, h_new):
        continue
    dst = root / name
    try:
        if dst.is_file() and hashlib.sha256(dst.read_bytes()).hexdigest() == old[name]:
            shutil.copy2(src / name, dst)
            n += 1
    except OSError:
        pass
if n:
    print(f"Odświeżone notatki z paczki (nietknięte przez Ciebie): {n}")
PYEOF
    fi
  fi
  for d in data memory; do mkdir -p "$ROOT/$d"; done
  chmod +x "$ROOT/gregai" 2>/dev/null || true
  echo "Kod podmieniony na $NEW_VER. Dalej: usługi, .env, restart i sprawdzenie."
  # Kroki po wgraniu wykonuje NOWY skrypt (jego migracje .env i ostrzeżenia), z tą samą
  # kopią do automatycznego powrotu.
  if [ -f "$ROOT/aktualizuj.sh" ] && bash -n "$ROOT/aktualizuj.sh" 2>/dev/null; then
    _post="$(mktemp "${TMPDIR:-/tmp}/gregai-aktualizuj.XXXXXX")"
    cp "$ROOT/aktualizuj.sh" "$_post"
    rm -rf "$STAGE"
    [ -n "${GREGAI_AKT_COPY:-}" ] && rm -f "$GREGAI_AKT_COPY"
    trap - EXIT
    GREGAI_AKT_COPY="$_post" GREGAI_AKT_ROOT="$ROOT" GREGAI_AKT_SNAP="$SNAP" exec bash "$_post" --po-paczce
  fi
fi

echo "== GREGAI: aktualizacja po wgraniu =="

PREV="$(cat "$STATE" 2>/dev/null || true)"
mkdir -p "$STATE_DIR"
FAIL=0

MOVED=0
if [ -n "$PREV" ] && [ "$PREV" != "$ROOT" ]; then
  MOVED=1
  echo
  echo "Folder GREGAI zmienił miejsce:"
  echo "  stara ścieżka: $PREV"
  echo "  NOWA ścieżka:  $ROOT"
  echo "(kolejne zmiany wgrywaj już pod: $ROOT)"
fi

# Przepnij usługę na aktualną ścieżkę, jeśli istnieje i wskazuje gdzie indziej.
# Zmieniamy TYLKO dwie linie (WorkingDirectory, ExecStart) w gotowym pliku
# usługi z install.sh - reszta (After/Wants/Nice/zabezpieczenia) bez zmian.
CHANGED=0
fix_unit() {  # $1 = nazwa pliku usługi, $2 = skrypt względem ROOT
  local file="/etc/systemd/system/$1" script="$2"
  [ -f "$file" ] || return 0
  local cur
  cur="$(need_sudo sed -n -E 's|^WorkingDirectory=(.*)$|\1|p' "$file" 2>/dev/null | head -1)"
  if [ -n "$cur" ] && [ "$cur" != "$ROOT" ]; then
    # Nowy, świeżo rozpakowany folder nie ma Twoich ustawień (.env) ani danych: przepięta
    # usługa wystartowałaby bez klucza API, tokenu i pamięci, a skrypt skłamałby, że wszystko gra.
    if [ ! -f "$ROOT/.env" ]; then
      if [ -n "${NO_ENV_SHOWN:-}" ]; then FAIL=1; return 0; fi  # 1.29.0: ta sama rada raz, nie per usługa
      NO_ENV_SHOWN=1
      echo "UWAGA: w $ROOT nie ma pliku .env (Twoje ustawienia i klucze), a usługa działa teraz z: $cur"
      echo "       Usług nie przepinam, żeby nie wystartowały bez Twoich ustawień i danych."
      echo "       Skopiuj do $ROOT plik .env oraz katalogi data, memory i notatki ze starego folderu"
      echo "       (np. cp -a \"$cur/.env\" \"$cur/data\" \"$cur/memory\" \"$cur/notatki\" \"$ROOT/\") i uruchom mnie jeszcze raz."
      FAIL=1
      return 0
    fi
    # Te same warunki co w install.sh (bad_location), poza sprawdzeniem zapisu: znaki,
    # których systemd nie przyjmie bezpiecznie, dysk wymienny/USB, katalog tymczasowy
    # i system plików bez uprawnień Linuksa.
    if ! LC_ALL=C.UTF-8 bash -c '[[ "$1" =~ ^[[:alnum:]\ _./+@,=\(\)-]+$ ]]' _ "$ROOT"; then
      echo "UWAGA: ścieżka $ROOT ma znaki specjalne; usługi nie przepięte. Uruchom: bash \"$ROOT/install.sh\" (skopiuje projekt w bezpieczne miejsce)."
      FAIL=1
      return 0
    fi
    local fs
    fs="$(findmnt -no FSTYPE -T "$ROOT" 2>/dev/null | head -1 || true)"
    case "$ROOT" in
      /media/*|/run/media/*|/tmp/*|/var/tmp/*|/dev/shm/*|/proc/*|/sys/*|/snap/*) fs="tmp" ;;
    esac
    case "$fs" in
      tmp|vfat|msdos|exfat|ntfs|ntfs3|fuseblk|iso9660|udf|cifs|smb3|nfs|nfs4|9p|vboxsf|fuse.*)
        echo "UWAGA: $ROOT leży na dysku wymiennym, w katalogu tymczasowym albo na systemie plików bez uprawnień Linuksa; usługa nie przetrwałaby restartu."
        echo "       Usługi nie przepięte. Uruchom: bash \"$ROOT/install.sh\" (skopiuje projekt do istniejącej instalacji albo ~/Dokumenty/GREGAI)."
        FAIL=1
        return 0 ;;
    esac
    # Dysk USB z systemem plików Linuksa (np. ext4 zamontowany w /mnt): sprawdzamy tylko poza katalogiem domowym.
    local src
    src="$(findmnt -no SOURCE -T "$ROOT" 2>/dev/null | head -1 | sed 's/\[.*$//' || true)"
    if [[ "$ROOT" != "$HOME"/* ]] && [ -n "$src" ] && [ -b "$src" ] && lsblk -no RM,HOTPLUG "$src" 2>/dev/null | grep -q '1'; then
      echo "UWAGA: $ROOT leży na dysku wymiennym/USB ($src); usługa nie wystartowałaby bez niego."
      echo "       Usługi nie przepięte. Uruchom: bash \"$ROOT/install.sh\" (skopiuje projekt do istniejącej instalacji albo ~/Dokumenty/GREGAI)."
      FAIL=1
      return 0
    fi
    echo "Przepinam $1: $cur -> $ROOT"
    if need_sudo sed -i -E \
      -e "s|^WorkingDirectory=.*|WorkingDirectory=$ROOT_ESC|" \
      -e "s|^ExecStart=.*|ExecStart=/usr/bin/python3 \"$ROOT_ESC/$script\"|" \
      -e "s|^ReadWritePaths=.*|ReadWritePaths=\"$ROOT_ESC/data\"|" \
      "$file"; then
      CHANGED=1
    else
      echo "UWAGA: nie udało się przepiąć $1."
      FAIL=1
    fi
  fi
}
fix_unit gregai.service agent/main.py
fix_unit gregai-siec.service agent/siec.py
if [ "$CHANGED" = 1 ]; then
  if need_sudo systemctl daemon-reload; then echo "Usługi przepięte na nową ścieżkę."; else echo "UWAGA: systemctl daemon-reload nie powiódł się."; FAIL=1; fi
fi

# SYSOP_ROOTS w .env: po przeniesieniu folderu wskazuje starą ścieżkę (narzędzia
# plikowe działałyby na starym folderze). Poprawiamy tylko wpis równy dokładnie
# starej ścieżce projektu; własne, świadomie dopisane katalogi zostają.
if [ -f "$ROOT/.env" ] && [ -n "$PREV" ] && [ "$PREV" != "$ROOT" ]; then
  CUR_ROOTS="$(grep -E '^[[:space:]]*(export[[:space:]]+)?SYSOP_ROOTS[[:space:]]*=' "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '\r' | tr -d "\"'")"
  case ":$CUR_ROOTS:" in
    *":$PREV:"*)
      NEW_ROOTS=":$CUR_ROOTS:"
      NEW_ROOTS="${NEW_ROOTS//":$PREV:"/":$ROOT:"}"   # cudzysłowy: dosłowne dopasowanie, bez globów
      NEW_ROOTS="${NEW_ROOTS#:}"; NEW_ROOTS="${NEW_ROOTS%:}"
      sed -i -E "/^[[:space:]]*(export[[:space:]]+)?SYSOP_ROOTS[[:space:]]*=/d" "$ROOT/.env"
      if [ -s "$ROOT/.env" ] && [ -n "$(tail -c1 "$ROOT/.env")" ]; then echo >> "$ROOT/.env"; fi   # .env bez końcowej nowej linii
      printf 'SYSOP_ROOTS=%s\n' "$NEW_ROOTS" >> "$ROOT/.env"
      echo "SYSOP_ROOTS w .env przepięty na nową ścieżkę."
      ;;
  esac
fi

# Migracje .env (1.18.0, audyt systemu): do 1.17.x robił je wyłącznie
# install.sh, więc "gregai update" zostawiał np. CLOUD_DAILY_LIMIT=50 - Claude,
# od 1.17.0 główny dostawca, kończył limit w godzinę i rozmowa schodziła do
# darmowej puli wbrew kolejności koryta. Te same reguły co w install.sh
# (zmieniamy tylko znane stare wartości, świadome wpisy użytkownika zostają);
# zapis atomowy, prawa pliku zachowane.
ENV_FILE="$ROOT/.env"
envval() { grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- \
  | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/^["'"'"']//; s/["'"'"']$//' || true; }
set_env() {
  KEY="$1" VAL="$2" python3 - "$ENV_FILE" <<'PY'
import os, re, sys, tempfile
path, key, val = sys.argv[1], os.environ["KEY"], os.environ["VAL"]
with open(path, encoding="utf-8", errors="surrogateescape") as f:
    lines = f.read().splitlines(keepends=True)
pat = re.compile(r"^[ \t]*(export[ \t]+)?" + re.escape(key) + r"[ \t]*=")
out, placed = [], False
for line in lines:
    if pat.match(line):
        if not placed:
            out.append(f"{key}={val}\n")
            placed = True
        continue
    out.append(line)
if not placed:
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    out.append(f"{key}={val}\n")
mode = os.stat(path).st_mode & 0o777
fd, tmp = tempfile.mkstemp(prefix=".env-", suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
try:
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write("".join(out))
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
PY
}
# 1.19.0 (audyt systemu): .env zapisany w Windows (BOM na początku, CRLF) - grep
# nie widział pierwszego wpisu ("\xEF\xBB\xBFKORYTO=..."), skrypt dopisywał
# domyślny KORYTO, a env_loader (ostatni wpis wygrywa) brał domyślny zamiast
# Twojego. Ta sama normalizacja co w install.sh, przed jakąkolwiek migracją.
if [ -f "$ENV_FILE" ] && { grep -q $'\r' "$ENV_FILE" || head -c3 "$ENV_FILE" | grep -q $'\xEF\xBB\xBF'; }; then
  sed -i -e 's/\r$//' -e '1s/^\xEF\xBB\xBF//' "$ENV_FILE" && echo ".env: usunięto znaki CR/BOM (plik zapisany w Windows)."
fi
if [ -f "$ENV_FILE" ]; then
  if [ -z "$(envval KORYTO)" ]; then
    set_env KORYTO anthropic,darmowe,lokalnie && echo ".env: dopisano KORYTO=anthropic,darmowe,lokalnie (kolejność dostawców od 1.17.0)."
  fi
  if [ "$(envval CLOUD_DAILY_LIMIT)" = "50" ]; then
    set_env CLOUD_DAILY_LIMIT 300 && echo ".env: CLOUD_DAILY_LIMIT 50 -> 300 (Claude jest teraz głównym dostawcą, nie ostatnią rezerwą)."
  fi
  # Tryb SYSOP a reguły sudo: tryb pełny potrzebuje jednej reguły ALL, strażniczy
  # wąskiej listy. Plik sudoers pisze tylko install.sh (tu tylko sprawdzamy).
  SUDOERS=/etc/sudoers.d/gregai-sysop
  MODE_NOW="$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')"
  if [ "$(envval SYSOP_ENABLED)" != "0" ] && unit_present && ! need_sudo test -f "$SUDOERS" 2>/dev/null; then
    echo "UWAGA: SYSOP włączony w .env, ale nie ma reguł sudo ($SUDOERS): zmiany systemowe (restart usług,"
    echo "       aktualizacje) będą padać na braku uprawnień. Uruchom: bash \"$ROOT/install.sh\""
  fi
  if [ "$(envval SYSOP_ENABLED)" != "0" ] && need_sudo test -f "$SUDOERS" 2>/dev/null; then
    if need_sudo grep -qE 'ALL=\(ALL\) NOPASSWD: ALL' "$SUDOERS" 2>/dev/null; then SUDO_SHAPE=pelny; else SUDO_SHAPE=strazniczy; fi
    WANT=strazniczy; [ "$MODE_NOW" = "pelny" ] && WANT=pelny
    if [ "$SUDO_SHAPE" != "$WANT" ]; then
      echo "UWAGA: SYSOP_MODE w .env to '$WANT', a reguły sudo ($SUDOERS) są w kształcie '$SUDO_SHAPE'."
      echo "       Uruchom: bash \"$ROOT/install.sh\" (przepisze reguły sudo pod obecny tryb)."
    fi
  fi
fi

# 1.19.0: szablony plików systemowych (usługa, reguły sudo, zapora WARP) mają
# numer (GREGAI_SZABLON w install.sh, jedno źródło). Starszy numer w pliku =
# nowa wersja kodu czegoś od nich oczekuje, a pisze je tylko install.sh.
WANT_TPL="$(grep -m1 -E '^GREGAI_SZABLON=[0-9]+' "$ROOT/install.sh" 2>/dev/null | cut -d= -f2)"
if [ -n "$WANT_TPL" ] && unit_present; then
  STALE=""
  for f in /etc/systemd/system/gregai.service /etc/sudoers.d/gregai-panic; do
    have_tpl="$(need_sudo grep -m1 -oE 'gregai-szablon: [0-9]+' "$f" 2>/dev/null | grep -oE '[0-9]+' || true)"
    if [ "${have_tpl:-0}" -lt "$WANT_TPL" ]; then STALE="${STALE:+$STALE, }$f"; fi
  done
  if [ -n "$STALE" ]; then
    echo "UWAGA: pliki systemowe z poprzedniej wersji instalatora: $STALE"
    echo "       Ta wersja potrzebuje ich nowego kształtu (np. osobne reguły gregaipanicmode, zapora WARP)."
    echo "       Uruchom raz: bash \"$ROOT/install.sh\""
    case "$STALE" in *gregai.service*)
      echo "       Od 1.32.4 zapora WARP w jądrze jest obowiązkowa: do czasu uruchomienia install.sh"
      echo "       usługa działa na starym kształcie (bez wymuszonej zapory). Zrób to od razu." ;;
    esac
  fi
fi

# httpx[http2] - od 1.30.6 POTRZEBNE ZAWSZE: wyszukiwarka (DuckDuckGo) i Groq
# przepuszczają tylko HTTP/2, a stdlib (HTTP/1.1) odrzucają jako bota (DDG oddaje
# 202 + stronę-wyzwanie). Starsze instalacje miały httpx tylko przy kluczu Groqa,
# więc dociągamy przy aktualizacji. Ten sam użytkownik co usługa (aktualizuj.sh
# uruchamiasz jako Ty, nie przez sudo), instalacja do ~/.local - system nietknięty.
if [ "$FAIL" = 0 ] && ! python3 -c 'import httpx, h2' 2>/dev/null; then
  echo "Dociągam httpx[http2] (wyszukiwarka i Groq wymagają HTTP/2)..."
  python3 -m pip install --user --break-system-packages --quiet 'httpx[http2]' 2>/dev/null \
    || python3 -m pip install --user --quiet 'httpx[http2]' 2>/dev/null \
    || echo "UWAGA: nie udało się zainstalować httpx[http2] - wyszukiwarka spadnie na HTTP/1.1 i bywa blokowana. Zainstaluj ręcznie: python3 -m pip install --user 'httpx[http2]', albo: bash \"$ROOT/install.sh\""
  python3 -c 'import httpx, h2' 2>/dev/null && echo "HTTP/2 gotowy (httpx[http2])."
fi

# Restart gregai, żeby nowy kod był żywy.
# Gdy przepięcie usług się nie udało, usługa wskazuje jeszcze STARY folder:
# restart uruchomiłby stary kod i skłamał, że nowy jest aktywny.
if [ "$FAIL" != 0 ]; then
  echo "UWAGA: usługi nie zostały przepięte na $ROOT, więc nie restartuję gregai (wystartowałby kod ze starego folderu)."
  if [ -n "${NO_ENV_SHOWN:-}" ]; then
    echo "Napraw to: skopiuj ustawienia i dane (polecenie cp wyżej), potem uruchom mnie jeszcze raz."
  else
    echo "Napraw to: bash \"$ROOT/install.sh\""
  fi
elif unit_present; then
  if ! restart_and_check "nowy kod ($(cat "$ROOT/VERSION" 2>/dev/null || echo '?')) aktywny"; then
    FAIL=1
    if [ "$MODE" = zip ] && [ -n "${SNAP:-}" ]; then
      echo "Wracam automatycznie do poprzedniej wersji ($SNAP)..."
      if restore_code "$SNAP" && restart_and_check "działa poprzednia wersja $(cat "$ROOT/VERSION" 2>/dev/null)"; then
        echo "Powrót udany: GREGAI działa na poprzedniej wersji. Nowa paczka NIE została zainstalowana."
        # 1.29.0: ta kopia to dokładnie wersja, która teraz działa - "gregai rollback"
        # ma prowadzić do WCZEŚNIEJSZEJ, więc wskaźnik przesuwamy na poprzednią kopię.
        rm -rf "$SNAP"
        _prev_snap="$(ls -1dt "$SNAP_DIR"/*/ 2>/dev/null | head -1)"
        if [ -n "$_prev_snap" ]; then printf '%s\n' "${_prev_snap%/}" > "$SNAP_DIR/ostatnia"; else rm -f "$SNAP_DIR/ostatnia"; fi
      else
        echo "UWAGA: powrót też nie postawił GREGAI. Sprawdź: journalctl -u gregai -n 50; potem: bash \"$ROOT/install.sh\""
      fi
    else
      echo "Sprawdź: journalctl -u gregai -n 50. Wersja z paczką ma automatyczny powrót: gregai update PLIK.zip"
    fi
  fi
else
  echo "Usługa gregai jeszcze nie istnieje - najpierw jednorazowo (z tego folderu): bash \"$ROOT/install.sh\""
fi

# Dowiązanie polecenia `gregai` (install.sh je tworzy) ma wskazywać aktualny folder.
chmod +x "$ROOT/gregai" 2>/dev/null || true
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
# 1.29.0: tylko gdy usługi wskazują ten folder - inaczej `gregai` prowadziłby do nieskonfigurowanej kopii.
if [ "$FAIL" = 0 ] && [ -f "$ROOT/gregai" ] && mkdir -p "$BIN_DIR" 2>/dev/null && ln -sfn "$ROOT/gregai" "$BIN_DIR/gregai" 2>/dev/null; then
  echo "Polecenie gregai wskazuje: $ROOT/gregai"
fi

[ "$FAIL" = 0 ] && printf '%s\n' "$ROOT" > "$STATE"

# 1.32.2 (audyt tura 7): nowe ustawienia z .env.example, których nie ma w Twoim .env -
# nic nie dopisujemy po cichu, tylko mówimy, że są (puste znaczą to samo co domyślne).
if [ -f "$ROOT/.env" ] && [ -f "$ROOT/.env.example" ]; then
  _nowe="$(python3 - "$ROOT/.env.example" "$ROOT/.env" <<'PY' 2>/dev/null
import re, sys
def keys(p):
    out = []
    for line in open(p, encoding="utf-8-sig", errors="replace"):
        m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=", line)
        if m:
            out.append(m.group(1))
    return out
have = set(keys(sys.argv[2]))
print(" ".join(k for k in dict.fromkeys(keys(sys.argv[1])) if k not in have))
PY
)"
  if [ -n "$_nowe" ]; then
    echo
    echo "Nowe ustawienia w .env.example (u Ciebie domyślne): $_nowe"
    echo "  Opis każdego jest w $ROOT/.env.example. Dopisz do .env tylko te, które chcesz zmienić."
  fi
fi

echo
echo "Aktualna ścieżka projektu GREGAI:"
echo "  $ROOT"
echo
echo "Tryby w okienku czatu (http://localhost:7777): wpisz 'freeram' albo 'fullon'."
[ "$MOVED" = 1 ] && [ "$FAIL" = 0 ] && echo "Pamiętaj: od teraz wgrywaj zmiany pod $ROOT"
exit "$FAIL"
