#!/usr/bin/env bash
# install.sh - GREGAI: JEDNA komenda, z DOWOLNEGO folderu.
# Ubuntu 22.04-26.04, z pulpitem albo bez (patrz INSTALACJA_UBUNTU_26_04.md):
#
#     bash /dowolna/sciezka/GREGAI/install.sh
#     albo:  cd /dowolna/sciezka/GREGAI && bash install.sh
#
# Folder projektu możesz przenieść gdziekolwiek (inny katalog, inna nazwa) i
# uruchomić to samo polecenie: skrypt sam wykrywa swoją ścieżkę, przepina
# usługi systemd na nią, poprawia ścieżki w .env (SYSOP_ROOTS), wypisuje
# NOWĄ ścieżkę i niczego nie kasuje w starym miejscu. Jedyny wyjątek to
# miejsca, w których usługa nie przetrwałaby restartu (dysk USB/wymienny,
# katalog tymczasowy, system plików FAT/exFAT/NTFS bez uprawnień Linuksa):
# wtedy skrypt SAM kopiuje projekt (z .env i danymi) do istniejącej instalacji, a bez niej do ~/Dokumenty/GREGAI (albo
# $GREGAI_HOME) i instaluje stamtąd.
#
# Opcje:
#   --train    po instalacji uruchom w TLE trening: router, planer, uczeń
#              (gotowe i aktualne modele pomija; przerwany trening wznawia od ostatniej epoki)
#              (według szacunku 2-3 doby na tym CPU, nice 19, log: data/training/train_all.log)
#   --no-host  pomiń ustawienia laptopa (brak usypiania na zasilaczu, klapa, swap 8 GB)
#   --here     zainstaluj dokładnie w tym folderze, nawet gdy wygląda na złe miejsce
#   --od-zera  zainstaluj w nowym folderze od zera, choć stara instalacja (z .env
#              i danymi) jest gdzie indziej (bez tego install.sh zatrzymuje się)
#   --yes      bez pytań (klucz Anthropic pominięty, trening bez potwierdzenia)
#   --help     ten opis
#
# Co robi, po kolei (każdy krok sprawdza, czy już nie jest zrobiony, więc
# można uruchamiać wielokrotnie):
#   1. pakiety systemowe: python3 (>=3.10), python3-venv, git, curl, rsync, smartmontools
#   2. Cloudflare WARP - OBOWIĄZKOWY (świadoma decyzja bezpieczeństwa tego
#      projektu od 2026-10-09, nie techniczny wymóg "osobistego asystenta"
#      w ogóle - wyjaśnienie w README.md, sekcja "Bezpieczeństwo"): cały
#      ruch komputera do internetu szyfrowany przez Cloudflare, DNS 1.1.1.1
#      + blokada złośliwych domen; bez działającego WARP skrypt się
#      zatrzymuje, a GREGAI i tak nie wychodzi do internetu (agent/netguard.py)
#   3. Ollama (oficjalny instalator z ollama.com, już przez WARP)
#   4. foldery projektu: notatki/, memory/, data/
#   5. .env (prawa 600 od pierwszej chwili): tryb dostępu (GREGAI_LAN z .env
#      wygrywa; .env.example ustawia 0 = tylko http://localhost:7777 na tej
#      maszynie; serwer bez pulpitu: wpisz GREGAI_LAN=1) + token
#   6. modele: OLLAMA_MODEL z .env (pull) oraz wytrenowane router, uczeń i planer z GGUF, jeśli są
#   7. usługa systemd gregai.service dla TEGO użytkownika i TEJ ścieżki,
#      start przy rozruchu (po warp-svc), restart po awarii
#   8. kontrola: /api/system_info odpowiada, WARP i chmura widoczne
#   9. warstwa systemowa (agent/sysop.py): sudo TYLKO na konkretne
#      polecenia dla konkretnych usług (SYSOP_UNITS niżej), SYSOP_ENABLED=1;
#      zapora ufw włączona; router domowy zapamiętany (agent/homenet.py);
#      sudo też na GREGAIPANICMODE (zablokuj sieć, wyłącz komputer - tylko
#      dosłowna fraza użytkownika w czacie, patrz agent/tryby.py) - od 1.19.0
#      w osobnym pliku /etc/sudoers.d/gregai-panic, instalowanym ZAWSZE
#      (także przy SYSOP_ENABLED=0)
#  7b. (1.19.0) zapora WARP na poziomie jądra (nftables): procesy usługi
#      gregai (i wszystko, co uruchomią, także przez sudo) wychodzą tylko
#      przez interfejs CloudflareWARP, do sieci lokalnej albo na localhost;
#      obowiązkowa od 1.32.4 (bez niej instalacja się zatrzymuje, usługa nie startuje)
#
# Poza katalogiem projektu dotyka m.in.: zapory ufw (włącza ją: blokuje
# przychodzące, wypuszcza wychodzące), /etc/systemd/system/gregai.service,
# /etc/systemd/system/gregai-siec.{service,timer},
# /etc/systemd/system/ollama.service.d/gregai.conf, /etc/sudoers.d/gregai-sysop,
# /etc/sudoers.d/gregai-panic, /etc/gregai/warp-killswitch.nft (tabela nftables
# inet gregai_warp, ładowana przy każdym starcie usługi gregai),
# ~/.config/gregai/sciezka (zapamiętana ścieżka projektu), trybu DNS klienta WARP
# (blokada złośliwych domen), domyślnej polityki ufw (wychodzące dozwolone),
# pakietów (w tym cloudflare-warp z /etc/apt/sources.list.d/cloudflare-client.list)
# i Ollamy; bez --no-host także: /etc/systemd/logind.conf.d/gregai.conf, swapu
# (/swap.img + /etc/fstab) i ustawienia braku usypiania (gsettings). Biblioteka
# huawei-lte-api (pip --user) tylko gdy w .env są dane routera. Starą usługę
# webai i jej regułę sudo odsuwa (końcówka .stare), niczego nie kasuje.
# Uruchamiane przez `sh install.sh` (dash) skrypt by się wysypał: wymagany bash.
[ -n "${BASH_VERSION:-}" ] || { echo "Użyj bash, nie sh:  bash $0"; exit 1; }
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Uruchom jako zwykły użytkownik, BEZ sudo:  bash install.sh"
  echo "(o hasło do sudo skrypt zapyta sam). Powód: usługa GREGAI, jej pliki i"
  echo "rejestracja Cloudflare WARP muszą należeć do Twojego konta, nie do roota."
  exit 1
fi

DO_TRAIN=0; DO_HOST=1; FORCE_HERE=0; ASSUME_YES=0; FROM_SCRATCH=0
ARGS=("$@")
for _a in "$@"; do
  case "$_a" in
    --train) DO_TRAIN=1 ;;
    --no-host) DO_HOST=0 ;;
    --here) FORCE_HERE=1 ;;
    --od-zera) FROM_SCRATCH=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Nieznana opcja: $_a  (bash install.sh --help)"; exit 2 ;;
  esac
done
[ "${GREGAI_SKIP_HOST:-0}" = "1" ] && DO_HOST=0
INTERACTIVE=0; [ -t 0 ] && [ "$ASSUME_YES" = "0" ] && INTERACTIVE=1

# Numer szablonu plików systemowych (usługa, sudoers, zapora WARP). Zmieniasz
# kształt któregoś z nich -> podbij numer: aktualizuj.sh porówna go z plikami
# na dysku i powie, że trzeba uruchomić install.sh (1.19.0, audyt systemu).
GREGAI_SZABLON=5
log()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mOK\033[0m %s\n' "$*"; }
warn() { printf '   \033[33mUWAGA\033[0m %s\n' "$*"; }
need_sudo() { if [ "$(id -u)" -ne 0 ]; then sudo "$@"; else "$@"; fi; }
# Zapis treści ze STDIN do pliku z prawami roota, BEZ `tee`. Ubuntu 26.04 ma
# `tee` z uutils coreutils (Rust), które pod sudo nie potrafi zapisać pliku
# (Permission denied, os error 13) - zgłoszenie Grzegorza z GREGAI2. Przekierowanie
# robi powłoka roota (sh -c '... > plik'), `cat` tylko przepuszcza STDIN, więc
# działa niezależnie od tego, czyje (GNU czy uutils) jest `tee`/`cat`.
sudo_write()  { need_sudo sh -c 'cat > "$1"'  sh "$1"; }
sudo_append() { need_sudo sh -c 'cat >> "$1"' sh "$1"; }

# Ścieżka projektu = miejsce tego skryptu, gdziekolwiek leży (realpath: bez
# symlinków, żeby usługa wskazywała prawdziwy katalog).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RUN_USER="$(id -un)"
SERVICE=/etc/systemd/system/gregai.service
PORT=7777
STATE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gregai"
STATE="$STATE_DIR/sciezka"
PREV_ROOT="$(cat "$STATE" 2>/dev/null || true)"

# Czy ten folder nadaje się na stałe miejsce usługi startującej przy rozruchu?
# Zwraca 0 i wypisuje powód, gdy NIE.
path_chars_ok() {
  local LC_ALL=C.UTF-8
  [[ "$1" =~ ^[[:alnum:]\ _./+@,=\(\)-]+$ ]]
}

bad_location() {
  local path="$1" fs src
  case "$path" in
    /media/*|/run/media/*|/tmp/*|/var/tmp/*|/dev/shm/*|/proc/*|/sys/*|/snap/*)
      echo "to dysk wymienny albo katalog tymczasowy (znika albo nie jest podłączony przy starcie systemu)"; return 0 ;;
  esac
  # Litery (także polskie: "Mój folder"), cyfry, spacja i kilka bezpiecznych znaków; bez
  # $ " ' \ ; : (dwukropek rozdziela SYSOP_ROOTS) i znaków sterujących.
  if ! path_chars_ok "$path"; then
    echo "ścieżka ma znaki specjalne, których usługa systemd nie przyjmie bezpiecznie"; return 0
  fi
  fs="$(findmnt -no FSTYPE -T "$path" 2>/dev/null | head -1 || true)"
  case "$fs" in
    vfat|msdos|exfat|ntfs|ntfs3|fuseblk|iso9660|udf|cifs|smb3|nfs|nfs4|9p|vboxsf|fuse.*)
      echo "system plików $fs nie ma uprawnień Linuksa (.env musi mieć prawa 600)"; return 0 ;;
  esac
  src="$(findmnt -no SOURCE -T "$path" 2>/dev/null | head -1 | sed 's/\[.*$//' || true)"
  # Dysk wymienny sprawdzamy tylko poza katalogiem domowym (dom leży na dysku systemu).
  if [[ "$path" != "$HOME"/* ]] && [ -n "$src" ] && [ -b "$src" ] && lsblk -no RM,HOTPLUG "$src" 2>/dev/null | grep -q '1'; then
    echo "dysk $src jest wymienny/USB (usługa nie wystartuje, gdy go zabraknie)"; return 0
  fi
  [ -w "$path" ] || { echo "brak zapisu w tym folderze"; return 0; }
  return 1
}

# Skopiuj projekt do bezpiecznego miejsca i kontynuuj stamtąd (exec). Kod
# nadpisuje stary kod w celu; dane użytkownika (.env, data, memory, notatki,
# wytrenowane modele) NIGDY nie nadpisują tego, co już jest w celu.
relocate_and_continue() {
  # 1.32.2 (przegląd poprawek): domyślnie do ISTNIEJĄCEJ instalacji (kopia z pendrive'a
  # aktualizuje ją, dane zostają), a bez niej do ~/Dokumenty/GREGAI - jak w INSTALACJA.
  local why="$1" target="${GREGAI_HOME:-}"
  if [ -z "$target" ]; then
    if [ -n "$PREV_ROOT" ] && [ -d "$PREV_ROOT" ] && [ -f "$PREV_ROOT/install.sh" ]; then target="$PREV_ROOT"
    else target="$HOME/Dokumenty/GREGAI"; fi
  fi
  if [ -n "${GREGAI_RELOCATED_FROM:-}" ]; then
    echo "Miejsce docelowe $ROOT też nie nadaje się ($why). Ustaw GREGAI_HOME na zwykły katalog w domu."; exit 1
  fi
  [ "$target" != "$ROOT" ] || return 0
  case "$target/" in "$ROOT"/*) echo "Cel $target leży wewnątrz $ROOT - wskaż inny (GREGAI_HOME)."; exit 1;; esac
  case "$ROOT/" in "$target"/*) echo "$ROOT leży wewnątrz celu $target - wskaż inny (GREGAI_HOME)."; exit 1;; esac
  log "Ten folder nie nadaje się na stałe miejsce GREGAI"
  echo "   $ROOT"
  echo "   Powód: $why."
  echo "   Kopiuję projekt do: $target (oryginał zostaje nietknięty)."
  command -v rsync >/dev/null || need_sudo apt-get install -y -qq rsync
  mkdir -p "$target"
  rsync -a --exclude=/.env --exclude=/data/ --exclude=/memory/ --exclude=/notatki/ --exclude=/training/.work/ "$ROOT/" "$target/"
  local d
  for d in data memory notatki training/.work; do
    if [ -d "$ROOT/$d" ]; then mkdir -p "$target/$d"; rsync -a --ignore-existing "$ROOT/$d/" "$target/$d/"; fi
  done
  if [ -f "$ROOT/.env" ] && [ ! -f "$target/.env" ]; then install -m 600 "$ROOT/.env" "$target/.env"; fi
  [ -f "$target/.env" ] && chmod 600 "$target/.env"
  ok "skopiowano. Dalej instaluję z: $target"
  export GREGAI_RELOCATED_FROM="$ROOT"
  exec bash "$target/install.sh" "${ARGS[@]}"
}

if [ "$FORCE_HERE" != "1" ] && why="$(bad_location "$ROOT")"; then
  relocate_and_continue "$why"
elif [ "$FORCE_HERE" = "1" ] && why="$(bad_location "$ROOT")"; then
  echo "UWAGA (--here): $why. Instaluję mimo to, na Twoją odpowiedzialność."
fi

ENV_FILE="$ROOT/.env"

# 1.32.2 (audyt tura 7): świeżo rozpakowana paczka w NOWYM miejscu, a stara instalacja ma
# Twoje ustawienia i dane - bez tego zatrzymania usługa przepięłaby się na pusty folder
# (nowy token, bez klucza API, bez pamięci i notatek). Ta sama rada co w aktualizuj.sh.
if [ -n "$PREV_ROOT" ] && [ "$PREV_ROOT" != "$ROOT" ] && [ -f "$PREV_ROOT/.env" ] && [ ! -f "$ROOT/.env" ]; then
  echo "UWAGA: GREGAI jest zainstalowany w: $PREV_ROOT (tam są Twoje ustawienia .env i dane),"
  echo "       a ten folder ($ROOT) ich nie ma. Nie przepinam usług na pusty folder."
  echo "  Nowa wersja kodu na starym miejscu:  gregai update <paczka.zip>"
  echo "  Przeniesienie z danymi:              cp -a \"$PREV_ROOT\"/{.env,data,memory,notatki} \"$ROOT\"/ && bash \"$ROOT/install.sh\""
  echo "  Świadomie od zera w tym folderze:    bash \"$ROOT/install.sh\" --od-zera"
  if [ "$FROM_SCRATCH" = 1 ]; then echo "  (--od-zera: instaluję od zera w tym folderze)"; else exit 1; fi
fi

if [ -n "$PREV_ROOT" ] && [ "$PREV_ROOT" != "$ROOT" ]; then
  log "Folder GREGAI zmienił miejsce"
  echo "   stara ścieżka: $PREV_ROOT"
  echo "   NOWA ścieżka:  $ROOT"
  echo "   Usługi systemd zostaną przepięte na nową ścieżkę. Starego folderu nie ruszam:"
  echo "   po sprawdzeniu, że wszystko działa, możesz go usunąć sam."
fi

# Ustaw KEY=VALUE w .env: pierwszy aktywny wpis tego klucza dostaje nową wartość,
# pozostałe znikają, żeby nigdy nie było dwóch wartości naraz.
# Wartość idzie zmienną środowiska, nie argumentem polecenia: klucz API nie
# pojawia się w `ps`. Pierwszy wpis zostaje na swoim miejscu, duplikaty znikają;
# brak końcowego znaku nowej linii w .env nie skleja wpisów.
set_env() {
  KEY="$1" VAL="$2" python3 - "$ENV_FILE" <<'PY'
import os, re, sys, tempfile
path, key, val = sys.argv[1], os.environ["KEY"], os.environ["VAL"]
try:
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        lines = f.read().splitlines(keepends=True)
except FileNotFoundError:
    lines = []
pat = re.compile(r"^[ \t]*(export[ \t]+)?" + re.escape(key) + r"[ \t]*=")  # jak agent/env_loader.py
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
# Zapis atomowy (plik tymczasowy obok + os.replace), prawa dotychczasowego
# pliku zachowane (nowy: 600): przerwany zapis nie zostawi obciętego .env z
# kluczem API.
try:
    mode = os.stat(path).st_mode & 0o777
except FileNotFoundError:
    mode = 0o600
# mkstemp: nowy plik (O_EXCL, 0600) o nieprzewidywalnej nazwie; stała nazwa ".env.tmp"
# pozwalała podłożyć dowiązanie albo cudzy plik w niezamkniętym folderze.
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
# Dopisywanie przez printf >> wymaga, żeby plik kończył się znakiem nowej linii
# (ręcznie edytowany .env często nie kończy się nim).
ensure_nl() { if [ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ]; then echo >> "$ENV_FILE"; fi; }
# Wartość klucza (ostatni wpis wygrywa - tak samo jak w agent/env_loader.py);
# bez xargs, żeby spacje w ścieżkach przetrwały.
# Te same kształty linii, które czyta agent/env_loader.py: także `export KLUCZ=` i `KLUCZ = wartość`.
envval() { grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- \
  | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/^["'"'"']//; s/["'"'"']$//' || true; }
# Polecenie jako właściciel usługi (gdy skrypt odpalono przez sudo, nie jako root).
# 1.32.9: znacznik dla straży (agent/straz.py _after_install), że pliki systemowe zmienił instalator.
straz_mark() { as_user mkdir -p "$ROOT/data/straz" 2>/dev/null && as_user touch "$ROOT/data/straz/instalacja" 2>/dev/null || true; }
as_user() { if [ "$(id -u)" -eq 0 ] && [ "$RUN_USER" != "root" ]; then sudo -u "$RUN_USER" -H "$@"; else "$@"; fi; }

log "1/9 Pakiety systemowe"
if ! command -v python3 >/dev/null; then
  need_sudo apt-get update -qq || warn "apt-get update nie powiódł się; próbuję instalować z lokalnej listy pakietów"
  need_sudo apt-get install -y -qq python3
fi
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 - <<'EOF' || { echo "Potrzebny Python 3.10+, jest $PYV"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF
missing=()
# dpkg -s zwraca 0 także dla pakietu po usunięciu (config-files) albo niedokończonego
# (unpacked); liczy się tylko status "ok installed".
pkg_ok() { local st; st="$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true)"; [[ "$st" == *"ok installed"* ]]; }
for p in python3-venv git curl rsync; do pkg_ok "$p" || missing+=("$p"); done
if [ ${#missing[@]} -gt 0 ]; then
  need_sudo apt-get update -qq || warn "apt-get update nie powiódł się; próbuję instalować z lokalnej listy pakietów"
  need_sudo apt-get install -y -qq "${missing[@]}"
fi
# smartmontools: tylko do kontroli stanu dysku w check.sh (nie jest potrzebny do działania).
if ! command -v smartctl >/dev/null; then
  need_sudo apt-get install -y -qq smartmontools || warn "Nie zainstalowano smartmontools (kontrola dysku w check.sh pokaże błąd; reszta działa)"
fi
ok "python3 $PYV, venv, git, curl, rsync"

log "2/9 Cloudflare WARP (obowiązkowy)"
# Twarda zasada projektu (2026-10-09, cyberbezpieczeństwo = priorytet):
# cały ruch tego komputera do internetu idzie szyfrowanym tunelem do
# Cloudflare (darmowy WARP, to samo co aplikacja "1.1.1.1 z WARP"), DNS
# 1.1.1.1 z blokadą złośliwych domen. Bez domeny, bez strony, bez konta,
# nic nie jest wystawiane do internetu. Krok jest PRZED Ollamą, żeby już
# pobieranie Ollamy i modeli szło przez WARP. Nie da się go pominąć: bez
# działającego WARP instalacja się zatrzymuje, a sam GREGAI i tak nie
# wyjdzie do internetu (agent/netguard.py, fail-closed).
# Warunki korzystania Cloudflare akceptujesz SAM przy `warp-cli
# registration new` - skrypt nie robi tego za Ciebie.
# Odpowiedź do zmiennej, nie `curl | grep -q`: przy pipefail grep kończący się
# wcześniej mógłby dać curlowi SIGPIPE i fałszywe "WARP wyłączony".
# --noproxy: pytamy trasą tej maszyny; proxy z sieci lokalnej leży poza tunelem i dałoby fałszywe warp=off.
warp_on() { local t; t="$(curl -fsS --noproxy '*' --max-time 10 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null || true)"; grep -q '^warp=\(on\|plus\)' <<<"$t"; }
# Ponowna kontrola tuż przed kolejnym pobieraniem: WARP mógł się rozłączyć od
# kroku 2 (zawieszenie laptopa, zmiana sieci), a zasada nie kończy się na
# jednym sprawdzeniu.
# Trzy próby: pojedyncze spóźnione żądanie nie ma przerywać kilkunastominutowej instalacji.
warp_guard() {
  local _
  for _ in 1 2 3; do
    if warp_on; then return 0; fi
    sleep 3
  done
  warn "WARP rozłączył się w trakcie instalacji (zasada projektu: internet tylko przez WARP). Połącz: warp-cli connect, potem ponownie: bash \"$ROOT/install.sh\""
  exit 1
}
if ! command -v warp-cli >/dev/null; then
  command -v gpg >/dev/null || need_sudo apt-get install -y -qq gnupg
  CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
  # 1.19.0: przy set -e nieudane pobranie klucza kończyło instalację bez słowa.
  if ! curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
    | need_sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg; then
    warn "Nie udało się pobrać klucza repozytorium Cloudflare WARP (pkg.cloudflareclient.com). Sprawdź internet i uruchom ponownie: bash \"$ROOT/install.sh\""
    exit 1
  fi
  # Pakiet .deb jest ten sam dla wszystkich wydań Ubuntu; gdy repozytorium nie ma
  # jeszcze wpisu dla nazwy kodowej świeżego systemu, próbujemy starszych LTS.
  TRIED=" "
  for CN in "$CODENAME" noble jammy; do
    [ -n "$CN" ] || continue
    case "$TRIED" in *" $CN "*) continue ;; esac
    TRIED="$TRIED$CN "
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $CN main" \
      | sudo_write /etc/apt/sources.list.d/cloudflare-client.list
    # `apt-get update` zwraca błąd, gdy ZAWIEDZIE którekolwiek repozytorium (np. obce PPA),
    # a lista Cloudflare mogła się mimo to pobrać: decyduje instalacja pakietu.
    need_sudo apt-get update -qq || true
    if need_sudo apt-get install -y -qq cloudflare-warp; then break; fi
  done
  if ! command -v warp-cli >/dev/null; then
    # Nieudane repozytorium zostawione w systemie psułoby każde kolejne
    # `apt-get update` (także aktualizacje przez SYSOP) - sprzątamy je.
    need_sudo rm -f /etc/apt/sources.list.d/cloudflare-client.list /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
  fi
fi
if ! command -v warp-cli >/dev/null; then
  warn "Instalacja Cloudflare WARP (pakiet cloudflare-warp) nie powiodła się. Bez WARP instalacja nie pójdzie dalej."
  warn "Sprawdź połączenie z internetem i: sudo apt-get update && sudo apt-get install cloudflare-warp"
  exit 1
fi
need_sudo systemctl enable --now warp-svc >/dev/null 2>&1 || true
# </dev/null: żadne polecenie poza rejestracją nie może zawisnąć na pytaniu.
# `timeout 5`: pojedyncze wywołanie warp-cli, które samo się zawiesza (a nie
# tylko odpowiada błędem), nie ma zamienić 60 prób w kilkuminutowe
# czekanie - bez tego retry poniżej nie chroni przed zawieszonym poleceniem.
# 60 prób, nie 30 (zgłoszenie Grzegorza 2026-10-19: demon bywa wolniejszy przy
# starcie na tym CPU, zwłaszcza w trakcie instalacji robiącej coś jeszcze -
# `systemctl status warp-svc` już pokazywał "active", a ta kontrola i tak
# zgłaszała błąd, bo nie zdążyła w 30 s).
WARP_STATUS_OUT=""
WARP_STATUS_OK=0
for _ in $(seq 1 60); do
  # UWAGA (zgłoszenie Grzegorza 2026-10-19, "wywala skrypt nic nie pisząc"):
  # pod `set -e` (włączone na początku pliku) samo `VAR="$(polecenie)"` jako
  # odrębna linia przerywa CAŁY skrypt bez żadnego komunikatu, gdy
  # `polecenie` wróci niezerowym kodem - a `warp-cli status` na
  # niezarejestrowanym urządzeniu wraca właśnie tak. Przypisanie MUSI być
  # warunkiem `if`, nie osobną linią - to jedyny sposób, żeby `set -e` go
  # nie potraktował jako nieobsłużony błąd.
  if WARP_STATUS_OUT="$(timeout 5 warp-cli status </dev/null 2>&1)"; then
    WARP_STATUS_OK=1
    break
  fi
  # Niezerowy kod wyjścia NIE znaczy jeszcze "demon nie odpowiada" - na
  # świeżej instalacji (zgłoszenie Grzegorza 2026-10-19: "bash ./install.sh"
  # na czystej maszynie) demon ŻYJE i ODPOWIADA, tylko urządzenie nie jest
  # jeszcze zarejestrowane ("Please accept the WARP Terms of Service") -
  # to nie jest błąd, to normalny stan przed krokiem rejestracji NIŻEJ,
  # który pyta Cię o zgodę. Prawdziwy brak odpowiedzi demona wygląda inaczej
  # (warp-cli pisze wprost o niemożności połączenia z daemonem/warp-svc) -
  # TYLKO to zostaje jako powód do dalszych prób/przerwania.
  if [ -n "$WARP_STATUS_OUT" ]; then
    case "$WARP_STATUS_OUT" in
      *onnect*daemon*|*daemon*onnect*|*"warp-svc running"*) ;;  # naprawdę brak odpowiedzi - próbuj dalej
      *) WARP_STATUS_OK=1; break ;;  # demon ŻYJE, odpowiedział czymkolwiek innym (np. o rejestracji)
    esac
  fi
  sleep 1
done
if [ "$WARP_STATUS_OK" -ne 1 ]; then
  # Pokazujemy PRAWDZIWĄ odpowiedź warp-cli (nie samo "nie odpowiada"): jeśli
  # usługa i tak jest "active" w systemd, to zwykle oznacza zawieszony/
  # zrestartowany od środka proces kontrolny demona (nie crash procesu) -
  # restart usługi zwykle to leczy.
  warn "warp-cli nie zwrócił statusu w 60 s. Ostatnia odpowiedź: ${WARP_STATUS_OUT:-brak}"
  warn "systemctl status warp-svc pokazuje usługę jako aktywną? To zwykle oznacza, że demon"
  warn "sam się zawiesił (proces żyje, ale nie odpowiada) - pomaga: sudo systemctl restart warp-svc,"
  warn "potem ponownie: bash install.sh. Jeśli systemctl też pokazuje usługę jako nieaktywną:"
  warn "sudo systemctl status warp-svc"
  exit 1
fi
if ! warp-cli registration show </dev/null >/dev/null 2>&1; then
  if [ -t 0 ]; then
    echo "   Rejestracja WARP: klient pokaże warunki korzystania Cloudflare - przeczytaj i zdecyduj sam."
    warp-cli registration new || true
  fi
  if ! warp-cli registration show </dev/null >/dev/null 2>&1; then
    warn "WARP nie jest zarejestrowany. Bez niego instalacja nie pójdzie dalej (zasada projektu)."
    warn "W terminalu: warp-cli registration new && warp-cli connect, potem ponownie: bash install.sh"
    exit 1
  fi
fi
# Tryb "warp" (pełny tunel): klient zostawiony wcześniej w trybie samego DNS (doh) łączy
# się, ale ruch nie idzie tunelem i kontrola warp=on niżej by nie przeszła.
warp-cli mode warp </dev/null >/dev/null 2>&1 || true
warp-cli dns families malware </dev/null >/dev/null 2>&1 || true
warp-cli connect </dev/null >/dev/null 2>&1 || true
for _ in $(seq 1 30); do warp_on && break; sleep 1; done
if ! warp_on; then
  warn "WARP nie łączy się (warp-cli status: $(warp-cli status </dev/null 2>&1 | head -1))."
  warn "Bez niego instalacja nie pójdzie dalej (zasada projektu). Sprawdź sieć i: warp-cli mode warp && warp-cli connect"
  exit 1
fi
ok "WARP połączony (warp=on): ruch do internetu szyfrowany przez Cloudflare, DNS 1.1.1.1 + blokada złośliwych domen"

log "3/9 Ollama"
# Polecenie ollama (pull, create, list) ma rozmawiać z Ollamą na TEJ maszynie,
# nawet gdy w powłoce został OLLAMA_HOST wskazujący inny serwer (create wysyła plik modelu).
export OLLAMA_HOST=http://127.0.0.1:11434
# Przerwany instalator zostawia sam plik wykonywalny bez usługi: sprawdzamy też usługę.
if ! command -v ollama >/dev/null || ! systemctl cat ollama.service >/dev/null 2>&1; then
  # Oficjalny instalator Ollamy (zakłada usługę systemd ollama.service).
  warp_guard
  if ! curl -fsSL https://ollama.com/install.sh | sh; then
    warn "Instalator Ollamy (ollama.com/install.sh) się nie powiódł - wyżej jego komunikat. Uruchom ponownie: bash \"$ROOT/install.sh\""
    exit 1
  fi
fi
# Ustawienia Ollamy pod GREGAI (plik dodatkowy, oryginalna usługa nietknięta):
# - tylko 127.0.0.1: rozmowy idą do Ollamy bez szyfrowania, więc nie może
#   słuchać w sieci (to i tak jej domyślne zachowanie, tu zapisane wprost),
# - jedna rozmowa naraz (jeden użytkownik): Ollama nie rezerwuje pamięci na
#   kontekst kilku równoległych rozmów, czyli mniej RAM przy dużym modelu,
# - okno 16384 tokenów, takie samo jak OLLAMA_NUM_CTX w agent/router.py:
#   `ollama run` w terminalu nie przeładuje wtedy modelu z innym oknem (co
#   skasowałoby przetworzony prompt GREGAI). Podwojone z 8192 (2026-10-19),
#   żeby historia rozmowy nie była ucinana w dłuższych wymianach.
OLLAMA_DROPIN=/etc/systemd/system/ollama.service.d/gregai.conf
DROPIN_TMP="$(mktemp)"
cat > "$DROPIN_TMP" <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_CONTEXT_LENGTH=16384"
# 1.32.10 (audyt tura 14): 8 GB RAM bez swapu - najwyżej 2 modele naraz, pamięć podręczna
# kontekstu w 8 bitach (ok. 0,3 GB zamiast 0,6 GB przy 16k), a przy braku pamięci jądro zabija
# najpierw Ollamę (wstanie sama), nie pulpit ani GREGAI.
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
OOMScoreAdjust=500
# 1.23.0 (audyt): Ollama wychodzi do internetu tylko przez WARP (pobieranie modeli),
# żeby polecenie "curl 127.0.0.1:11434/api/pull" nie omijało zapory WARP.
# systemd 251+ (Ubuntu 24.04); starszy systemd ignoruje to ustawienie z ostrzeżeniem.
RestrictNetworkInterfaces=lo CloudflareWARP
EOF
if ! need_sudo cmp -s "$DROPIN_TMP" "$OLLAMA_DROPIN" 2>/dev/null; then
  need_sudo mkdir -p "$(dirname "$OLLAMA_DROPIN")"
  need_sudo cp "$DROPIN_TMP" "$OLLAMA_DROPIN"
  need_sudo chmod 644 "$OLLAMA_DROPIN"
  need_sudo systemctl daemon-reload
  need_sudo systemctl restart ollama >/dev/null 2>&1 || true
fi
rm -f "$DROPIN_TMP"
need_sudo systemctl enable --now ollama >/dev/null 2>&1 || true
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break; sleep 1; done
OLLAMA_VER="$(curl -fsS http://127.0.0.1:11434/api/version 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || true)"
if [ -z "$OLLAMA_VER" ]; then
  warn "Ollama nie odpowiada na 127.0.0.1:11434. Sprawdź: systemctl status ollama; journalctl -u ollama -n 30"
  warn "Jeśli jej instalator został przerwany, uruchom ten skrypt ponownie: bash \"$ROOT/install.sh\""
  exit 1
fi
ok "ollama $OLLAMA_VER"

log "4/9 Foldery projektu i ustawienia laptopa (laptop, który nie zasypia)"
mkdir -p "$ROOT/notatki" "$ROOT/memory" "$ROOT/data" "$ROOT/data/training"
chmod 700 "$ROOT/notatki" "$ROOT/memory" "$ROOT/data" "$ROOT/data/training"   # notatki, rozmowy, ślady decyzji, zbiory treningowe: tylko właściciel
ok "notatki/ memory/ data/ (prawa 700: tylko właściciel; pliki notatek zostają 644, żeby edytory działały)"
if [ "$DO_HOST" = "1" ]; then
  # 1. Bez usypiania na zasilaczu (sesja pulpitu; w sesji bez dbus pomijamy).
  if command -v gsettings >/dev/null 2>&1 && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    if gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null; then
      ok "brak usypiania na zasilaczu (na baterii bez zmian)"
    else warn "nie udało się ustawić braku usypiania (gsettings); zrób to w Ustawieniach -> Zasilanie"; fi
  else
    warn "brak sesji pulpitu: pominięto ustawienie braku usypiania (Ustawienia -> Zasilanie)"
  fi
  # 2. Zamknięcie klapy na zasilaczu nie usypia (zadziała po restarcie; logind
  #    NIE jest restartowany przy otwartej sesji - to wylogowuje z pulpitu).
  LOGIND_CONF=/etc/systemd/logind.conf.d/gregai.conf
  LOGIND_TMP="$(mktemp)"; printf '[Login]\nHandleLidSwitchExternalPower=ignore\n' > "$LOGIND_TMP"
  if ! need_sudo cmp -s "$LOGIND_TMP" "$LOGIND_CONF" 2>/dev/null; then
    need_sudo mkdir -p "$(dirname "$LOGIND_CONF")" && need_sudo cp "$LOGIND_TMP" "$LOGIND_CONF" && need_sudo chmod 644 "$LOGIND_CONF" \
      && ok "klapa na zasilaczu nie usypia (po następnym restarcie)" || warn "nie udało się zapisać $LOGIND_CONF"
  else ok "klapa na zasilaczu nie usypia"; fi
  rm -f "$LOGIND_TMP"
  # 3. Swap 8 GB (zapas, gdy duży model, przeglądarka i pulpit zbiegną się w czasie).
  SWAP_KB="$(awk '/^SwapTotal/ {print $2}' /proc/meminfo)"
  if [ "${SWAP_KB:-0}" -ge $((7 * 1024 * 1024)) ]; then
    ok "swap: $((SWAP_KB / 1024 / 1024)) GB"
  else
    # `|| true`: pod `set -euo pipefail` niezerowy kod `swapon` (np. brak
    # wsparcia swapu w jądrze) w bare-assignment zabiłby cały skrypt bez
    # komunikatu - ta sama klasa błędu, co kontrola WARP wyżej (2026-10-19).
    SW="$(swapon --show=NAME,TYPE --noheadings 2>/dev/null | awk '$2=="file"{print $1; exit}' || true)"; SW="${SW:-/swap.img}"
    USED_KB="$(awk '/^SwapTotal/ {t=$2} /^SwapFree/ {f=$2} END {print t-f}' /proc/meminfo)"
    AVAIL_KB="$(awk '/^MemAvailable/ {print $2}' /proc/meminfo)"
    # Miejsce na dysku: 8 GB pliku swapu (to, co już zajmuje plik, liczy się jako wolne) + 1 GB zapasu.
    FREE_KB="$(df --output=avail -k "$(dirname "$SW")" 2>/dev/null | tail -1 | tr -d ' ' || true)"
    CUR_KB="$(( $(stat -c %s "$SW" 2>/dev/null || echo 0) / 1024 ))"
    # swapoff przenosi zajęty swap do RAM: tylko gdy RAM to udźwignie z zapasem 1 GB.
    if [ $(( ${FREE_KB:-0} + CUR_KB )) -lt $(( 9 * 1024 * 1024 )) ]; then
      warn "za mało wolnego miejsca na dysku na swap 8 GB w $SW (potrzeba ok. 9 GB); pominięto"
    elif [ "${USED_KB:-0}" -lt $(( ${AVAIL_KB:-0} - 1024 * 1024 )) ]; then
      need_sudo swapoff "$SW" 2>/dev/null || true
      if need_sudo fallocate -l 8G "$SW" && need_sudo chmod 600 "$SW" && need_sudo mkswap "$SW" >/dev/null && need_sudo swapon "$SW"; then
        grep -qE "^${SW}[[:space:]]" /etc/fstab || echo "$SW none swap sw 0 0" | sudo_append /etc/fstab
        ok "swap 8 GB ($SW), wpis w /etc/fstab"
      else
        need_sudo swapon "$SW" 2>/dev/null || true   # nie zostawiamy systemu bez swapu, jeśli plik da się jeszcze włączyć
        if [ "$CUR_KB" -eq 0 ] && ! grep -qE "^${SW}[[:space:]]" /proc/swaps; then
          need_sudo rm -f "$SW"   # plik założony w tym przebiegu, a nie działa (np. ZFS/btrfs): nie zostawiamy 8 GB śmieci
        fi
        warn "nie udało się założyć swapu 8 GB w $SW (reszta instalacji idzie dalej)"
      fi
    else
      warn "zajęty swap jest za duży, by go bezpiecznie przestawić teraz; pominięto (zrób to po restarcie: bash install.sh)"
    fi
  fi
else
  ok "ustawienia laptopa pominięte (--no-host)"
fi

log "5/9 .env (tryb dostępu + token + klucz chmury)"
if [ ! -f "$ENV_FILE" ]; then
  if [ -f "$ROOT/.env.example" ]; then
    install -m 600 "$ROOT/.env.example" "$ENV_FILE"; ok ".env utworzony z .env.example (ustalone domyślne)"
  else
    (umask 077; : > "$ENV_FILE")
  fi
fi
chmod 600 "$ENV_FILE"   # sekrety (token, klucz API) nigdy nie leżą z szerszymi prawami
# 1.20.0: kopia .env przed migracjami (sed -i niżej); trzymamy 3 ostatnie, prawa 600.
if [ -s "$ENV_FILE" ]; then
  (umask 077; cp -p "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)") 2>/dev/null || true
  ls -1t "$ENV_FILE".bak.* 2>/dev/null | tail -n +4 | xargs -r rm -f
fi
# .env zapisany w Windows (CRLF, ewentualnie BOM) psuł odczyt wartości w tym skrypcie
# ("1\r" nie jest "1"); normalizujemy do LF. sed -i zachowuje prawa pliku.
if grep -q $'\r' "$ENV_FILE" || head -c3 "$ENV_FILE" | grep -q $'\xEF\xBB\xBF'; then
  sed -i -e 's/\r$//' -e '1s/^\xEF\xBB\xBF//' "$ENV_FILE"
  ok ".env: usunięto znaki CR/BOM (plik z Windows)"
fi
ensure_nl
# Projekt nazywał się SIECAI do 2026-10-09: nazwy kluczy w .env przeniesionym
# ze starego laptopa (SIECAI_LAN, SIECAI_DEMO, SIECAI_IMAP_*...) zmieniamy na
# GREGAI_*. Dotyka tylko nazw kluczy i komentarzy, nigdy wartości.
if grep -qE '^\s*#?\s*SIECAI_' "$ENV_FILE" || grep -qE '^\s*#.*SIECAI' "$ENV_FILE"; then
  # Gdy w .env jest JUŻ nowy klucz (np. dopisany ręcznie GREGAI_LAN=0), stary
  # (SIECAI_LAN=1) jest usuwany, a nie przemianowywany - inaczej byłyby dwa.
  for old in $(grep -oE '^[[:space:]]*SIECAI_[A-Z0-9_]+' "$ENV_FILE" | tr -d ' \t' | sort -u || true); do
    if grep -qE "^[[:space:]]*GREGAI_${old#SIECAI_}=" "$ENV_FILE"; then
      sed -i -E "/^[[:space:]]*${old}=/d" "$ENV_FILE"
    fi
  done
  sed -i -E 's/^(\s*#?\s*)SIECAI_/\1GREGAI_/; /^\s*#/ s/SIECAI/GREGAI/g' "$ENV_FILE"
  ok "klucze .env przemianowane: SIECAI_* -> GREGAI_*"
fi
# Z projektu usunięto na stałe (2026-10-12): głos (Piper/Whisper), tryb demo i
# poczta/kalendarz. Ich klucze w .env przeniesionym ze starego laptopa są martwe.
DEAD_KEYS='(PIPER|WHISPER)_[A-Z_]+|GREGAI_(DEMO|CALENDAR_URL|IMAP_[A-Z_]+)'
if grep -qE "^[[:space:]]*($DEAD_KEYS)=" "$ENV_FILE"; then
  sed -i -E "/^[[:space:]]*($DEAD_KEYS)=/d" "$ENV_FILE"
  ok "usunięto z .env martwe klucze (głos, tryb demo, poczta, kalendarz)"
fi
# Do 2026-10-12 rozmówca nazywał się WEBAI, a modele webai-router, webai-student
# i webai-planner. Takie wpisy w .env ze starego laptopa wskazywałyby modele,
# których tu nie ma (wytrenowanych modeli i tak nie przenosimy).
if grep -qE '^[[:space:]]*(ROUTER|STUDENT|PLANNER)_MODEL=.*webai-' "$ENV_FILE"; then
  sed -i -E '/^[[:space:]]*(ROUTER|STUDENT|PLANNER)_MODEL=.*webai-/d' "$ENV_FILE"
  ok "usunięto z .env wpisy starych modeli (webai-*); nowe powstaną po treningu jako gregai-*"
fi
# Tryb dostępu. Wpis GREGAI_LAN w .env zawsze wygrywa (świadoma decyzja
# użytkownika). Bez wpisu zawsze 0: nasłuch tylko na localhost, nic nie jest
# wystawione do sieci (GREGAI jest do użytku z tego jednego laptopa). Komputer
# bez pulpitu, z którego łączysz się z innej maszyny, dostaje tylko ostrzeżenie:
# GREGAI_LAN=1 (z tokenem) wpisujesz wtedy SAM.
LAN="$(envval GREGAI_LAN)"
if [ -z "$LAN" ]; then
  if [ "$(systemctl get-default 2>/dev/null || true)" = "graphical.target" ]; then
    LAN=0
    printf '\n# Komputer z pulpitem: GREGAI tylko na tej maszynie, http://localhost:7777 (install.sh)\nGREGAI_LAN=0\n' >> "$ENV_FILE"
  else
    LAN=0
    printf '\n# GREGAI tylko na tej maszynie, http://localhost:7777 (install.sh). Dostęp z innego komputera: GREGAI_LAN=1 (z tokenem)\nGREGAI_LAN=0\n' >> "$ENV_FILE"
    warn "To nie jest komputer z pulpitem: GREGAI słucha tylko na localhost. Chcesz łączyć się z innego komputera? Wpisz GREGAI_LAN=1 w .env i uruchom ponownie: bash \"$ROOT/install.sh\""
  fi
elif [ "$LAN" = "1" ] && [ "$(systemctl get-default 2>/dev/null || true)" = "graphical.target" ]; then
  # GREGAI_LAN=1 mógł przyjść z .env ze starego komputera bez pulpitu.
  warn "GREGAI_LAN=1 w .env na komputerze Z PULPITEM: panel (z tokenem) będzie dostępny z sieci domowej."
  warn "Jeśli używasz GREGAI tylko na tym laptopie, ustaw GREGAI_LAN=0 w .env i uruchom ponownie: bash \"$ROOT/install.sh\""
fi
# Do 2026-10-12 token nazywał się CLOUDE_TOKEN (nagłówek X-Cloude-Token). Wartość
# ze starego .env zostaje, zmienia się tylko nazwa klucza.
if grep -qE '^[[:space:]]*CLOUDE_TOKEN=' "$ENV_FILE"; then
  if grep -qE '^[[:space:]]*(export[[:space:]]+)?GREGAI_TOKEN[[:space:]]*=.+' "$ENV_FILE"; then
    sed -i -E '/^[[:space:]]*CLOUDE_TOKEN=/d' "$ENV_FILE"
  else
    sed -i -E '/^[[:space:]]*GREGAI_TOKEN=[[:space:]]*$/d; s/^[[:space:]]*CLOUDE_TOKEN=/GREGAI_TOKEN=/' "$ENV_FILE"
  fi
  ok "klucz .env przemianowany: CLOUDE_TOKEN -> GREGAI_TOKEN"
fi
# Token: wymagany od każdego żądania spoza tej maszyny (GREGAI_LAN=1) i od
# wszystkiego, co przyszło przez pośrednika (agent/main.py, _authorized).
if ! grep -qE '^[[:space:]]*(export[[:space:]]+)?GREGAI_TOKEN[[:space:]]*=.+' "$ENV_FILE"; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf 'GREGAI_TOKEN=%s\n' "$TOKEN" >> "$ENV_FILE"
  warn "wygenerowano token dostępu (potrzebny tylko z innego urządzenia albo przez pośrednika):"
  echo "         $TOKEN"
fi
# Duży model i jego okno (2026-10-12: Qwen2.5-3B, zejście z 7B dla szybkości; okno
# 16384 od 2026-10-19, podwojone z 8192, żeby historia rozmowy nie była ucinana w
# dłuższych wymianach - patrz "Co nowego" w README). .env ze starego laptopa ma
# stary, mały model (np. gemma2:2b) i okno 4096, w którym pełny prompt GREGAI się
# nie mieści. Zmieniane są tylko te znane stare wartości; inny, świadomie wpisany
# model zostaje (także qwen2.5:1.5b wpisany po to, żeby było szybciej: ROADMAP_1.0.md).
CUR_MODEL="$(envval OLLAMA_MODEL)"
case "$CUR_MODEL" in
  ""|gemma2:2b|gemma2:2b-*|llama3.2|llama3.2:1b|llama3.2:3b|phi3:mini|phi3.5|phi3.5:*)
    set_env OLLAMA_MODEL qwen2.5:3b
    ok "OLLAMA_MODEL=qwen2.5:3b${CUR_MODEL:+ (było: $CUR_MODEL)}" ;;
esac
CUR_CTX="$(envval OLLAMA_NUM_CTX)"
if [ -n "$CUR_CTX" ] && { ! [[ "$CUR_CTX" =~ ^[0-9]+$ ]] || [ "$CUR_CTX" -lt 16384 ]; }; then
  set_env OLLAMA_NUM_CTX 16384
  ok "OLLAMA_NUM_CTX=16384 (było: $CUR_CTX)"
fi
# Ustalone domyślne (jeśli .env nie ma ich jeszcze). Koryto (1.17.0,
# agent/koryto.py): JEDNA kolejność etapów dla całego myślenia - Claude
# (Anthropic, płatny) pierwszy, darmowa pula druga, lokalny model ostatni
# (decyzja Grzegorza 2026-10-21). Stare JUGGLER_MODE/CLOUD_FALLBACK w .env są
# ignorowane przez kod (zostają, nic nie psują). Dzienny limit Claude 300
# (był 50 jako rezerwa; jako główny dostawca 50 kończyłoby się w godzinę).
# Dowolny shell SYSOP wyłączony (stałe narzędzia) - chyba że SYSOP_MODE=pelny.
[ -n "$(envval KORYTO)" ] || set_env KORYTO anthropic,darmowe,lokalnie
if [ "$(envval CLOUD_DAILY_LIMIT)" = "50" ]; then set_env CLOUD_DAILY_LIMIT 300; ok "CLOUD_DAILY_LIMIT=300 (było 50 z czasów, gdy Claude był ostatnią rezerwą)"; fi
[ -n "$(envval CLOUD_DAILY_LIMIT)" ] || set_env CLOUD_DAILY_LIMIT 300
[ -n "$(envval SYSOP_SHELL)" ] || set_env SYSOP_SHELL 0
# Klucze żonglera (chmura darmowa, agent/juggler.py) - ten sam wzorzec co
# Anthropic niżej: pytamy tylko w terminalu i tylko gdy klucza brak, bez echa,
# trafia wyłącznie do .env na tym komputerze. Każdy osobno - pusty Enter = pomiń,
# ten jeden dostawca po prostu wypada z puli, reszta (w tym lokalny model) działa.
_ask_juggler_key() {  # $1 = nazwa zmiennej w .env, $2 = etykieta, $3 = strona z kluczem
  grep -qE "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=.+" "$ENV_FILE" && return 0
  [ "$INTERACTIVE" = "1" ] || return 0
  echo "   Klucz $2 ($3) - jeden z darmowych dostawców żonglera."
  echo "   Wklej go i naciśnij Enter (nie będzie widoczny). Sam Enter = pomiń; dopiszesz później w .env."
  read -rsp "   $1: " _KEY || _KEY=""
  echo
  if [ -n "$_KEY" ]; then
    set_env "$1" "$_KEY"; ok "klucz $2 zapisany w .env (prawa 600)"
  fi
  unset _KEY
}
_ask_juggler_key GROQ_API_KEY "Groq" "console.groq.com/keys"
_ask_juggler_key GEMINI_API_KEY "Google Gemini" "aistudio.google.com/apikey"
_ask_juggler_key OPENROUTER_API_KEY "OpenRouter" "openrouter.ai/keys"
_ask_juggler_key HUGGINGFACE_API_KEY "Hugging Face" "huggingface.co/settings/tokens"
_ask_juggler_key CLOUDFLARE_API_KEY "Cloudflare Workers AI" "developers.cloudflare.com (Workers AI -> Use REST API)"
unset -f _ask_juggler_key
# Cloudflare to JEDYNY dostawca żonglera z DRUGIM wymaganym wpisem:
# account_id (agent/juggler.py: _EXTRA_ENV). To NIE sekret - wchodzi wprost
# w adres URL, jak w panelu Cloudflare - stąd zwykłe echo (read -rp), nie
# ciche read -rsp jak przy kluczach wyżej. Pytamy TYLKO, gdy powyżej
# faktycznie podano CLOUDFLARE_API_KEY (inaczej cały dostawca i tak jest
# pomijany, pytanie o samo ID byłoby bez sensu).
if [ -n "$(envval CLOUDFLARE_API_KEY)" ] && [ -z "$(envval CLOUDFLARE_ACCOUNT_ID)" ] && [ "$INTERACTIVE" = "1" ]; then
  echo "   Cloudflare Account ID (ten sam panel co klucz, widoczny obok \"Use REST API\")."
  echo "   Wpisz i naciśnij Enter. Sam Enter = pomiń; bez tego Cloudflare w puli nie zadziała, dopiszesz później w .env."
  read -rp "   CLOUDFLARE_ACCOUNT_ID: " _ACCOUNT_ID || _ACCOUNT_ID=""
  if [ -n "$_ACCOUNT_ID" ]; then
    set_env CLOUDFLARE_ACCOUNT_ID "$_ACCOUNT_ID"; ok "CLOUDFLARE_ACCOUNT_ID zapisany w .env"
  else
    warn "brak CLOUDFLARE_ACCOUNT_ID: klucz Cloudflare zapisany, ale dostawca nieaktywny, dopóki nie dopiszesz ID ręcznie w .env"
  fi
  unset _ACCOUNT_ID
fi
# httpx[http2] - teraz POTRZEBNE ZAWSZE, nie tylko dla Groqa. Dwa serwisy, które
# GREGAI odpytuje, odrzucają żądania stdlib (HTTP/1.1) jako ruch bota i przepuszczają
# tylko HTTP/2: api.groq.com (Cloudflare, 1.8.0) ORAZ DuckDuckGo (1.30.6 - zgłoszenie
# Grzegorza: wyszukiwarka oddawała 202 + stronę-wyzwanie "anomaly" na HTTP/1.1, a na
# HTTP/2 normalne wyniki; potwierdzone na żywym WARP curlem --http1.1 vs HTTP/2).
# Bez tej biblioteki wyszukiwanie w sieci wraca na HTTP/1.1 i bywa blokowane, a Groq
# w puli nie odpowiada; reszta działa. Instalacja tylko dla użytkownika usługi
# (~/.local), system Pythona nietknięty.
if ! as_user python3 -c 'import httpx, h2' 2>/dev/null; then
  warp_guard
  dpkg -s python3-pip >/dev/null 2>&1 || need_sudo apt-get install -y -qq python3-pip
  as_user python3 -m pip install --user --break-system-packages --quiet 'httpx[http2]' 2>/dev/null \
    || as_user python3 -m pip install --user --quiet 'httpx[http2]' \
    || warn "nie udało się zainstalować httpx[http2] (wyszukiwarka spadnie na HTTP/1.1 i bywa blokowana; Groq w puli nie zadziała; reszta tak)"
fi
as_user python3 -c 'import httpx, h2' 2>/dev/null && ok "HTTP/2 gotowy (httpx[http2]) - wyszukiwarka i Groq"
if ! grep -qE '^[[:space:]]*(export[[:space:]]+)?(GROQ|GEMINI|OPENROUTER|HUGGINGFACE|CLOUDFLARE)_API_KEY[[:space:]]*=.+' "$ENV_FILE"; then
  warn "brak żadnego klucza darmowej puli: etap 'darmowe' koryta nieaktywny (zostaje Claude, jeśli ma klucz, i lokalny model). Dopisz GROQ_API_KEY/GEMINI_API_KEY/OPENROUTER_API_KEY/HUGGINGFACE_API_KEY/CLOUDFLARE_API_KEY (+CLOUDFLARE_ACCOUNT_ID) w $ENV_FILE i: sudo systemctl restart gregai"
fi
# Klucz Anthropic (Claude, PŁATNY - od 1.17.0 GŁÓWNY dostawca, pierwszy etap
# koryta). Pytamy tylko w terminalu i tylko gdy go brak; wpisywany bez echa,
# trafia wyłącznie do .env na tym komputerze.
if ! grep -qE '^[[:space:]]*(export[[:space:]]+)?ANTHROPIC_API_KEY[[:space:]]*=.+' "$ENV_FILE"; then
  if [ "$INTERACTIVE" = "1" ]; then
    echo "   Klucz Anthropic (console.anthropic.com) włącza Claude jako GŁÓWNEGO dostawcę (płatny, domyślnie Haiku; bez niego koryto zaczyna od darmowej puli)."
    echo "   Wklej go i naciśnij Enter (nie będzie widoczny). Sam Enter = pomiń; dopiszesz później w .env."
    read -rsp "   ANTHROPIC_API_KEY: " _KEY || _KEY=""
    echo
    if [ -n "$_KEY" ]; then
      case "$_KEY" in sk-ant-*) ;; *) warn "klucz zwykle zaczyna się od sk-ant-; zapisuję, ale sprawdź go" ;; esac
      set_env ANTHROPIC_API_KEY "$_KEY"; ok "klucz Anthropic zapisany w .env (prawa 600)"
    fi
    unset _KEY
  fi
  grep -qE '^[[:space:]]*(export[[:space:]]+)?ANTHROPIC_API_KEY[[:space:]]*=.+' "$ENV_FILE" \
    || warn "brak klucza Anthropic: pierwszy etap koryta (Claude) nieaktywny - rozmowa zaczyna od darmowej puli, potem lokalnie. Dopisz ANTHROPIC_API_KEY=... w $ENV_FILE i: sudo systemctl restart gregai"
fi
chmod 600 "$ENV_FILE"
# Most do routera Huawei HiLink (agent/router_bridge.py, tylko odczyt)
# potrzebuje biblioteki huawei-lte-api. Instalowana TYLKO, gdy w .env są
# dane routera (ROUTER_USER i ROUTER_PASSWORD); bez nich ta funkcja jest po
# prostu wyłączona. Instalacja tylko dla użytkownika usługi (~/.local),
# system Pythona nietknięty.
if [ -n "$(envval ROUTER_USER)" ] && [ -n "$(envval ROUTER_PASSWORD)" ]; then
  if ! as_user python3 -c 'import huawei_lte_api' 2>/dev/null; then
    warp_guard
    dpkg -s python3-pip >/dev/null 2>&1 || need_sudo apt-get install -y -qq python3-pip
    # --break-system-packages zna pip z Ubuntu 24.04+; starszy (22.04) go nie zna,
    # więc w razie błędu druga próba idzie bez niego.
    as_user python3 -m pip install --user --break-system-packages --quiet huawei-lte-api 2>/dev/null \
      || as_user python3 -m pip install --user --quiet huawei-lte-api \
      || warn "nie udało się zainstalować huawei-lte-api (most do routera nie zadziała, reszta tak)"
  fi
  as_user python3 -c 'import huawei_lte_api' 2>/dev/null && ok "most do routera HiLink gotowy (huawei-lte-api)"
fi
if [ "$LAN" = "1" ]; then
  ok ".env gotowy (GREGAI_LAN=1: dostęp z sieci domowej z tokenem; prawa 600)"
else
  ok ".env gotowy (GREGAI_LAN=0: tylko ta maszyna, http://localhost:$PORT; prawa 600)"
fi

log "6/9 Modele (pobieranie przez WARP)"
MODEL="$(envval OLLAMA_MODEL)"
MODEL="${MODEL:-qwen2.5:3b}"   # ten sam domyślny co w agent/router.py
if ! ollama list 2>/dev/null | awk -v m="$MODEL" 'NR>1 {n=$1; sub(/:latest$/, "", n); w=m; sub(/:latest$/, "", w); if (n == w) f=1} END {exit !f}' ; then
  warp_guard
  # 1.32.12 (audyt tura 16): nieudane pobranie 2 GB modelu (zerwane WARP, brak miejsca) nie
  # przerywa instalacji w połowie - usługa, reguły sudo i zapora i tak powstają, a model
  # dociągniesz jednym poleceniem.
  ollama pull "$MODEL" || { warn "nie udało się pobrać modelu $MODEL (WARP? miejsce na dysku?). GREGAI wstanie bez modelu lokalnego; pobierz potem: ollama pull $MODEL"; MODEL_MISSING=1; }
fi
[ "${MODEL_MISSING:-0}" = 1 ] || ok "model rozmowy: $MODEL"
# Wytrenowane modele (router, uczeń, planer) po przeniesieniu projektu na nową maszynę:
# ich wpisy w .env zostały, ale Ollama na nowej maszynie ich nie zna. Każdy wraca z GGUF,
# który zostawił trening (training/.work/<katalog>/<nazwa>-f16.gguf), tą samą kwantyzacją
# co przy eksporcie z domyślnym QUANTIZE (q8_0; f16 jest dwa razy wolniejszy na CPU). Bez GGUF router.py nie
# użyje takiego modelu (manifest) i GREGAI dalej działa bez niego.
import_trained_model() {
  local name="$1" dir="$ROOT/training/.work/$2" script="$3"
  [ -n "$name" ] || return 0
  # Nazwa dokładnie (z ewentualnym :latest), nie przedrostek: gregai-router-candidate to inny model.
  if ollama list 2>/dev/null | awk -v r="$name" '{n=$1; sub(/:latest$/, "", n); if (n == r) f=1} END {exit !f}'; then
    ok "model $name już w Ollamie"
    return 0
  fi
  local gguf="$dir/${name}-f16.gguf"
  if [ ! -f "$gguf" ]; then
    warn "$name jest w .env, ale ani w Ollamie, ani jako GGUF w training/.work/$2/."
    warn "GREGAI działa bez niego, dopóki nie uruchomisz: bash training/$script"
    return 0
  fi
  # FROM względem Modelfile (leży obok GGUF): ścieżka projektu może mieć spacje.
  printf 'FROM ./%s\n' "$(basename "$gguf")" > "$dir/Modelfile.import"
  cat >> "$dir/Modelfile.import" <<'EOF'
TEMPLATE """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
{{ .Response }}<|im_end|>
"""
PARAMETER stop <|im_start|>
PARAMETER stop <|im_end|>
PARAMETER stop <|endoftext|>
EOF
  if (cd "$dir" && { ollama create "$name" -f Modelfile.import --quantize q8_0 || ollama create "$name" -f Modelfile.import; }); then
    ok "model $name zaimportowany z przeniesionego GGUF"
  else
    warn "import modelu $name z GGUF nie powiódł się; GREGAI działa bez niego. Uruchom: bash training/$script"
  fi
}
env_value() { grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d "\"'" | xargs || true; }
import_trained_model "$(env_value ROUTER_MODEL)" out run.sh
import_trained_model "$(env_value STUDENT_MODEL)" student run_student.sh
import_trained_model "$(env_value PLANNER_MODEL)" planner run_planner.sh

log "7/9 Usługa systemd (użytkownik: $RUN_USER, katalog: $ROOT)"
# Czy ta maszyna miała już usługę GREGAI (kolejne uruchomienie install.sh, np.
# po przeniesieniu folderu)? Od tego zależy, czy SYSOP_ENABLED=0 w .env jest
# świadomą decyzją użytkownika (zostaje), czy resztką po starym laptopie.
SERVICE_EXISTED=0
if need_sudo test -f "$SERVICE"; then SERVICE_EXISTED=1; fi
# Stara nazwa usługi (do 2026-10-12 usługa nazywała się webai): zdejmujemy ją,
# żeby dwie kopie nie walczyły o port 7777 i żeby stara reguła sudo nie została.
# Nic nie kasujemy: pliki dostają końcówkę .stare (systemd i sudo takich plików
# nie czytają), więc wszystko da się cofnąć.
if need_sudo test -f /etc/systemd/system/webai.service; then
  need_sudo systemctl disable --now webai >/dev/null 2>&1 || true
  need_sudo mv -f /etc/systemd/system/webai.service /etc/systemd/system/webai.service.stare
  need_sudo systemctl daemon-reload
  ok "stara usługa webai wyłączona (plik odsunięty: webai.service.stare)"
fi
if need_sudo test -f /etc/sudoers.d/webai-sysop; then  # katalog sudoers.d jest tylko dla roota
  need_sudo mv -f /etc/sudoers.d/webai-sysop /etc/sudoers.d/webai-sysop.stare \
    && ok "stara reguła sudo odsunięta: webai-sysop.stare"
fi
# --- 7b. Zapora WARP na poziomie jądra (1.19.0, audyt systemu) ---------------
# Strażnik internetu w kodzie (agent/netguard.py) blokuje GREGAI, gdy WARP nie
# działa - ale polecenia shella (sys_shell, w trybie pełnym od razu) to osobne
# programy, a lista "co wychodzi do sieci" w sysop.py z natury jest niepełna.
# Ta tabela nftables dotyczy WYŁĄCZNIE procesów usługi gregai (cgroup
# system.slice/gregai.service, także ich potomków przez sudo): ruch wychodzący
# wolno tylko przez interfejs CloudflareWARP, na localhost i do sieci
# prywatnych (10/8, 172.16/12, 192.168/16, link-local, fc00::/7). Wszystko
# inne z tych procesów - odrzucone przez jądro. Reszta systemu bez zmian.
# Ścieżka cgroup jest rozwiązywana przy ładowaniu reguły, a cgroup usługi
# powstaje na nowo przy każdym starcie, więc tabela jest ładowana przy KAŻDYM
# starcie usługi (ExecStartPre z "+", jako root, już w cgroup usługi).
# Obowiązkowa (1.32.4): bez wyłącznika; ExecStartPre bez "-" - bez tabeli usługa nie wstaje.
KILL_NFT=/etc/gregai/warp-killswitch.nft
KILLSWITCH_LINE="# zapora WARP (nftables): wyłączona albo niedostępna - patrz install.sh, krok 7b"
write_killswitch() {  # $1 = ścieżka cgroup do reguły, $2 = plik docelowy
  local cg="$1"
  printf '%s\n' \
    "# GREGAI (install.sh, gregai-szablon: $GREGAI_SZABLON): ruch wychodzący usługi gregai tylko przez WARP," \
    "# localhost i sieci prywatne. Ładowane przy każdym starcie usługi (ExecStartPre)." \
    "table inet gregai_warp {}" \
    "delete table inet gregai_warp" \
    "table inet gregai_warp {" \
    "  chain output {" \
    "    type filter hook output priority filter; policy accept;" \
    "    socket cgroupv2 level 2 \"$cg\" oifname { \"lo\", \"CloudflareWARP\" } accept" \
    "    socket cgroupv2 level 2 \"$cg\" ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } meta l4proto { tcp, udp } th dport 53 counter drop" \
    "    socket cgroupv2 level 2 \"$cg\" ip daddr { 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 } accept" \
    "    socket cgroupv2 level 2 \"$cg\" ip6 daddr { fe80::/10, fc00::/7 } meta l4proto { tcp, udp } th dport 53 counter drop" \
    "    socket cgroupv2 level 2 \"$cg\" ip6 daddr { ::1, fe80::/10, fc00::/7 } accept" \
    "    socket cgroupv2 level 2 \"$cg\" counter drop" \
    "  }" \
    "}" | sudo_write "$2"
}
# 1.32.4 (decyzja Grzegorza, 2026-10-25): zapora WARP w jądrze jest OBOWIĄZKOWA. Nie ma już
# wyłącznika GREGAI_KILLSWITCH=0, a usługa bez załadowanej tabeli nie wystartuje (ExecStartPre
# bez "-"). Gdy jądro albo nft jej nie obsługuje, instalacja zatrzymuje się z wyjaśnieniem.
if [ "$(envval GREGAI_KILLSWITCH)" = "0" ]; then
  warn "GREGAI_KILLSWITCH=0 w .env jest ignorowane: zapora WARP w jądrze jest obowiązkowa (od 1.32.4)."
fi
KILL_OK=0
if true; then
  if ! command -v nft >/dev/null && [ ! -x /usr/sbin/nft ]; then warp_guard; need_sudo apt-get install -y -qq nftables >/dev/null 2>&1 || true; fi
  if command -v nft >/dev/null || [ -x /usr/sbin/nft ]; then
    need_sudo mkdir -p /etc/gregai
    # Sprawdzenie na sucho (nft -c) tym samym kształtem reguł na cgroup, który
    # na pewno istnieje (system.slice, poziom 1 zamiast 2) - cgroup usługi
    # może jeszcze nie istnieć przy pierwszej instalacji.
    # need_sudo mktemp: plik NALEŻY do roota. Inaczej (user-owned w /tmp) root nie
    # może go nadpisać - jądro blokuje zapis cudzego pliku w katalogu ze "sticky"
    # bitem (fs.protected_regular), stąd "cannot create ...: Permission denied" na
    # Ubuntu 26.04 (zgłoszenie Grzegorza, GREGAI2). sed -i to omijał (tworzy nowy
    # plik i podmienia), ale sudo_write/tee zapisują wprost - więc temp musi być roota.
    KILL_TEST="$(need_sudo mktemp)"
    write_killswitch "system.slice" "$KILL_TEST"
    need_sudo sed -i 's/level 2 "system.slice"/level 1 "system.slice"/' "$KILL_TEST"
    if need_sudo /usr/sbin/nft -c -f "$KILL_TEST" >/dev/null 2>&1; then
      write_killswitch "system.slice/gregai.service" "$KILL_NFT"
      need_sudo chmod 644 "$KILL_NFT"
      KILLSWITCH_LINE="ExecStartPre=+/usr/sbin/nft -f $KILL_NFT"
      KILL_OK=1
      ok "zapora WARP (nftables): usługa gregai wychodzi tylko przez WARP, localhost i sieć lokalną ($KILL_NFT)"
    else
      warn "zapora WARP (nftables) nie przeszła sprawdzenia (nft -c): jądro albo nft bez dopasowania 'socket cgroupv2'."
      need_sudo rm -f "$KILL_NFT"
    fi
    need_sudo rm -f "$KILL_TEST"
  else
    warn "brak nft (pakiet nftables), a nie udało się go zainstalować."
  fi
fi
if [ "$KILL_OK" != 1 ]; then
  # 1.32.9 (audyt tura 13): stara usługa (szablon 4, "ExecStartPre=-+" albo bez linii zapory)
  # wystartowałaby bez zapory - zatrzymujemy ją, zamiast zostawić GREGAI w sieci bez ochrony.
  if [ -f "$SERVICE" ]; then
    need_sudo systemctl stop gregai 2>/dev/null || true
    warn "Usługa gregai zatrzymana: bez zapory WARP w jądrze nie może działać."
  fi
  warn "Zapora WARP w jądrze jest obowiązkowa, a nie da się jej tu włączyć - instalacja zatrzymana, usługa gregai nie startuje bez niej."
  warn "Sprawdź: sudo apt install nftables; uname -r (jądro z cgroup v2: Ubuntu 26.04 ma je domyślnie); potem: bash install.sh"
  exit 1
fi
# Tryb pełny SYSOP (wyizolowane Ubuntu): bez PrivateTmp (polecenia shella mają
# widzieć prawdziwy /tmp) i z AF_PACKET (tcpdump, arping). Strażniczy: jak było.
if [ "$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')" = "pelny" ]; then
  UNIT_PRIVATE_TMP=no; UNIT_FAMILIES="AF_UNIX AF_INET AF_INET6 AF_NETLINK AF_PACKET"
else
  UNIT_PRIVATE_TMP=yes; UNIT_FAMILIES="AF_UNIX AF_INET AF_INET6 AF_NETLINK"
fi
sudo_write "$SERVICE" <<EOF
[Unit]
Description=GREGAI - osobista inteligencja strategiczna (HTTP na localhost + Ollama)
# gregai-szablon: $GREGAI_SZABLON
After=network-online.target ollama.service warp-svc.service
Wants=network-online.target warp-svc.service
# Bez limitu startów: po naprawie usterki (np. zajęty port) usługa wstaje sama, a ręczny
# restart nigdy nie kończy się komunikatem "Start request repeated too quickly".
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$ROOT
ExecStart=/usr/bin/python3 "$ROOT/agent/main.py"
Restart=always
RestartSec=3
# 1.32.17 (audyt tura 19): domyślny TimeoutStopSec systemd (90s) kłóci się z
# sysop.sys_update_apply, który woła "apt-get upgrade" jako dziecko tej usługi
# z WŁASNYM limitem do 1800s i własną logiką SIGTERM(15s)->SIGKILL (sysop.py).
# "systemctl restart gregai" w trakcie takiej aktualizacji (np. zaplanowana
# aktualizacja kodu GREGAI akurat w tym momencie) szedł inną drogą: domyślny
# KillMode=control-group wysyła SIGTERM do CAŁEJ grupy na raz, a po 90s SIGKILL
# całej grupy - niezależnie od wewnętrznej logiki 15s w sysop.py. dpkg ubity
# SIGKILL-em w środku rozpakowywania pakietu zostawia system w połowie
# skonfigurowany (dokładnie to, czego sysop.py próbuje uniknąć). Limit niżej
# dopasowany do najdłuższej operacji zleconej przez samego agenta.
TimeoutStopSec=1850
# Zapora WARP na poziomie jądra (7b wyżej), obowiązkowa od 1.32.4: bez "-", więc błąd ładowania
# reguł zatrzymuje start usługi; "+" = jako root, już w cgroup tej usługi.
$KILLSWITCH_LINE
# print() z agenta ma trafiać do journala od razu (journalctl -u gregai).
Environment=PYTHONUNBUFFERED=1
# Trening (training/run.sh) i GREGAI dzielą CPU; nice daje pierwszeństwo rozmowie.
Nice=-5
# Utwardzenie, które nie przeszkadza sudo ani zwykłej pracy agenta (NoNewPrivileges
# odpada, bo SYSOP woła sudo). ProtectKernelModules też odpada: ukrywa
# /usr/lib/modules także przed potomkiem "sudo apt-get upgrade", a aktualizacja
# jądra albo initramfs (update-initramfs, depmod) musi je widzieć.
PrivateTmp=$UNIT_PRIVATE_TMP
ProtectControlGroups=yes
LockPersonality=yes
RestrictRealtime=yes
ProtectHostname=yes
SystemCallArchitectures=native
# Gniazda: IPv4/IPv6 (Ollama, chmura, apt), UNIX (sudo, D-Bus), NETLINK (ip, ss, ping).
RestrictAddressFamilies=$UNIT_FAMILIES
# Klucze i poświadczenia użytkownika niewidoczne dla agenta i jego potomków (także po
# "tak" dla polecenia shella); "-" = brak katalogu nie jest błędem. Jądro to wymusza,
# a nie tylko lista wzorców w sysop.py. 1.19.0: ta sama lista co _PRIVATE_HOME w
# agent/sysop.py (profile przeglądarek, gh, gcloud, poczta, Signal).
InaccessiblePaths=-"$HOME/.ssh" -"$HOME/.gnupg" -"$HOME/.local/share/keyrings" -"$HOME/.password-store" -"$HOME/.aws" -"$HOME/.netrc" -"$HOME/.git-credentials" -"$HOME/.docker" -"$HOME/.kube" -"$HOME/.pki"
InaccessiblePaths=-"$HOME/.mozilla" -"$HOME/snap/firefox" -"$HOME/.config/google-chrome" -"$HOME/.config/chromium" -"$HOME/.config/BraveSoftware" -"$HOME/.config/gh" -"$HOME/.config/gcloud" -"$HOME/.thunderbird" -"$HOME/.config/Signal" -"$HOME/.bash_history" -"$HOME/.zsh_history" -"$HOME/.config/rclone" -"$HOME/.python_history" -"$HOME/.psql_history" -"$HOME/.mysql_history"

[Install]
WantedBy=multi-user.target
EOF
# Strażnik: w pliku usługi mają być wyłącznie komentarze, nagłówki sekcji i dyrektywy
# Klucz=wartość. Heredoc bez cudzysłowu wykonuje `...` i $(...), więc zabłąkany znak
# w komentarzu mógłby wstawić tu wyjście obcego polecenia (albo je uruchomić).
UNIT_BAD="$(need_sudo cat "$SERVICE" | grep -vE '^(#|\[[A-Za-z]+\]$|[A-Za-z]+=|$)' || true)"
if [ -n "$UNIT_BAD" ]; then
  warn "$SERVICE zawiera linie, które nie są dyrektywami systemd (błąd w install.sh): ${UNIT_BAD%%$'\n'*}"
  exit 1
fi
# Skan sieci domowej (agent/siec.py, tylko odczyt) co 15 min. Poza domem
# siec.py sam nic nie skanuje (agent/homenet.py: brama + jej MAC).
sudo_write /etc/systemd/system/gregai-siec.service <<EOF
[Unit]
Description=GREGAI - skan sieci domowej (tylko odczyt, tylko w domu)
After=network-online.target
# Skan to 254 pingi i radio Wi-Fi poza oszczędzaniem przez kilka sekund: na baterii
# czekamy na zasilacz (systemd pomija uruchomienie, timer idzie dalej).
ConditionACPower=true

[Service]
Type=oneshot
User=$RUN_USER
WorkingDirectory=$ROOT
# Zawieszony skan nie może blokować timera na zawsze.
TimeoutStartSec=300
Nice=10
# Ta usługa nie woła sudo, więc może być utwardzona mocniej niż gregai.service: tylko
# ping (bez uprawnień, przez net.ipv4.ping_group_range), ip neigh i zapis w $ROOT/data.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths="$ROOT/data"
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
CapabilityBoundingSet=
ProtectControlGroups=yes
ProtectKernelTunables=yes
ProtectKernelLogs=yes
ProtectClock=yes
ProtectHostname=yes
LockPersonality=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
SystemCallArchitectures=native
ExecStart=/usr/bin/python3 "$ROOT/agent/siec.py"
EOF
sudo_write /etc/systemd/system/gregai-siec.timer <<'EOF'
[Unit]
Description=GREGAI - skan sieci domowej co 15 minut

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
AccuracySec=5min

[Install]
WantedBy=timers.target
EOF
need_sudo systemctl daemon-reload
need_sudo systemctl enable --now gregai-siec.timer >/dev/null 2>&1 || warn "nie udało się włączyć gregai-siec.timer (skan sieci)"
need_sudo systemctl enable gregai >/dev/null 2>&1 || warn "nie udało się włączyć usługi gregai na stałe (systemctl enable gregai) - sprawdź: journalctl -xe"
# Port 7777 zajęty przez coś innego niż usługa (np. ręcznie uruchomiony python3 agent/main.py
# z poprzedniego folderu): usługa nie mogłaby się zbindować i restartowałaby się w pętli.
if ! systemctl is-active --quiet gregai 2>/dev/null && command -v ss >/dev/null \
   && [ -n "$(ss -ltnH "sport = :$PORT" 2>/dev/null || true)" ]; then
  warn "Port $PORT jest już zajęty przez inny proces (nie przez usługę gregai), np. ręcznie uruchomiony agent/main.py."
  warn "Usługa gregai jest już zapisana i włączona, ale reguły sudo i zapora ufw jeszcze nie - dokończy je ponowne uruchomienie instalatora."
  warn "Zobacz kto: ss -ltnp 'sport = :$PORT' ; zatrzymaj go i uruchom ponownie: bash \"$ROOT/install.sh\""
  exit 1
fi
straz_mark  # 1.32.9: straż przyjmie przebudowane pliki systemowe bez fałszywego alarmu
# 1.32.12 (audyt tura 16): nieudany start usługi nie urywa instalacji po cichu (bez reguł sudo
# i zapory ufw) - ostrzeżenie, dalsze kroki idą, a na końcu wynik 1.
if need_sudo systemctl restart gregai; then
  ok "gregai.service włączona i uruchomiona"
else
  warn "usługa gregai nie wystartowała. Zobacz: journalctl -u gregai -n 30 (częsty powód: reguły zapory WARP nie ładują się przy prawdziwym starcie)."
  HEALTH_FAIL=1
fi
mkdir -p "$STATE_DIR" && printf '%s\n' "$ROOT" > "$STATE" && ok "ścieżka projektu zapamiętana: $ROOT"

log "8/9 Kontrola"
# Żądanie z tej samej maszyny nie wymaga tokenu (main.py, _authorized), więc
# token nie trafia do argumentów polecenia.
INFO="$(mktemp)"; chmod 600 "$INFO"
# 1.32.2 (audyt tura 7): 60 s jak w aktualizuj.sh (pierwszy start bywa wolniejszy niż 15 s),
# a brak odpowiedzi NIE przerywa instalacji: krok 9 (reguły sudo, zapora, panicmode) musi
# się wykonać, inaczej usługa działałaby bez zapory i bez wyłącznika awaryjnego.
HEALTH_FAIL=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/system_info" >"$INFO" 2>/dev/null; then break; fi
  sleep 1
done
if [ -s "$INFO" ]; then
  # Odpowiedź mógł dać inny proces na porcie: usługa też musi być aktywna (po chwili, bo
  # przy zajętym porcie startuje i od razu pada).
  sleep 3
  if ! systemctl is-active --quiet gregai 2>/dev/null; then
    warn "Na porcie $PORT ktoś odpowiada, ale usługa gregai nie jest aktywna. Kończę pozostałe kroki, potem sprawdź: systemctl status gregai; journalctl -u gregai -n 50"
    HEALTH_FAIL=1
  fi
  [ "$HEALTH_FAIL" = 1 ] || INFO="$INFO" python3 - <<'EOF' || { warn "odpowiedź /api/system_info nie jest poprawnym JSON (na porcie $PORT odpowiada coś innego niż GREGAI?)"; HEALTH_FAIL=1; }
import json, os
d = json.load(open(os.environ["INFO"]))
h = d.get("host", {})
print("   RAM:", h.get("ram_total_mb"), "MB, wolne:", h.get("ram_available_mb"), "MB; CPU:", h.get("cpu_model"), h.get("cpu_logical_cores"), "wątków; dysk wolny:", h.get("disk_free_gb"), "GB")
print("   model rozmowy:", d.get("ollama_model"), "| router:", d.get("router", {}).get("reason"))
print("   chmura:", d.get("cloud", {}).get("reason"))
print("   WARP:", d.get("warp", {}).get("reason"))
EOF
  rm -f "$INFO"
  if [ "$HEALTH_FAIL" = 1 ]; then
    :
  elif [ "$LAN" = "1" ]; then
    # `|| true`: ta sama ochrona co przy swapon wyżej - kosmetyczny adres IP
    # w komunikacie końcowym nie ma prawa ubić instalacji, która już się udała.
    IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    ok "GREGAI odpowiada. W przeglądarce na innym komputerze: http://${IP:-<IP-laptopa>}:$PORT (poprosi o token)"
  else
    ok "GREGAI odpowiada. Na tym komputerze, w przeglądarce: http://localhost:$PORT (bez tokenu)"
  fi
else
  warn "GREGAI nie odpowiedziało w 60 s. Kończę pozostałe kroki (zapora, reguły), potem sprawdź: journalctl -u gregai -n 50"
  HEALTH_FAIL=1
  rm -f "$INFO"
fi

log "9/9 Warstwa systemowa (SYSOP): stałe narzędzia z poziomami"
# Reguły sudo TYLKO na konkretne polecenia zmiany (restart usług, aktualizacje),
# bez hasła, dla użytkownika usługi. Odczyt (journalctl, systemctl status,
# apt list) nie wymaga sudo. Nic poza tą listą nie dostaje uprawnień roota:
# agent/sysop.py i tak blokuje polecenia destrukcyjne, a to jest druga
# warstwa, po stronie systemu.
#
# Usługi: LISTA DOZWOLONYCH (cyberbezpieczeństwo, 2026-10-09), nie
# "systemctl * dowolna-usługa". Wcześniejsza wersja z gwiazdką pozwalała
# procesowi GREGAI przez sudo zatrzymać też warp-svc albo zaporę (blokada
# w sysop.py była wtedy jedyną barierą). Teraz system sam nie pozwoli.
# Kolejną usługę dopisujesz tu ŚWIADOMIE i uruchamiasz install.sh ponownie.
SYSOP_UNITS="gregai ollama"
UNIT_RULES=""
for u in $SYSOP_UNITS; do
  for a in start stop restart reload enable disable; do
    UNIT_RULES="${UNIT_RULES:+$UNIT_RULES, }/usr/bin/systemctl $a $u, /usr/bin/systemctl $a $u.service, /usr/bin/systemctl --no-block $a $u.service"
  done
done
# GREGAIPANICMODE (prośba Grzegorza, 2026-10-19; agent/tryby.py: panicmode,
# user_only w capabilities.py - TYLKO dosłowna fraza "gregaipanicmode"
# wpisana przez niego, nigdy decyzja modelu/routera/planera). Dwa kroki, w
# TEJ kolejności w panicmode(): najpierw cofnij regułę zapory wpuszczającą
# GREGAI z każdej sieci prywatnej (dokładnie to polecenie, co pętla "Zapora"
# niżej przy GREGAI_LAN=0, te same sieci), potem wyłącz cały komputer -
# nie tylko usługę GREGAI. Osobna, wąska lista: żadne inne polecenie ufw
# (np. "ufw disable") ani żadna inna forma wyłączenia komputera nie dostaje
# sudo przez ten wpis.
PANIC_RULES=""
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
  PANIC_RULES="${PANIC_RULES:+$PANIC_RULES, }/usr/sbin/ufw delete allow from $net to any port $PORT proto tcp"
done
# 1.30.31: dwie mocniejsze formy na wypadek blokady wyłączenia (inhibitor) -
# agent/tryby.py próbuje ich po kolei, gdy zwykłe poweroff odmówi.
PANIC_RULES="$PANIC_RULES, /usr/bin/systemctl poweroff, /usr/bin/systemctl poweroff -i, /usr/bin/systemctl poweroff --force"
# 1.19.0 (audyt systemu): reguły GREGAIPANICMODE w OSOBNYM pliku, instalowanym
# ZAWSZE - także przy SYSOP_ENABLED=0. Dawniej leżały w gregai-sysop, a ten
# znika przy wyłączonym SYSOP; panicmode odpowiadał "wyłączam komputer" i nic
# nie robił. Wyłącznik awaryjny ma działać niezależnie od narzędzi systemowych.
PANIC_SUDOERS=/etc/sudoers.d/gregai-panic
PANIC_TMP="$PANIC_SUDOERS.nowy"
printf '%s\n' \
  "# GREGAIPANICMODE (agent/tryby.py) - gregai-szablon: $GREGAI_SZABLON" \
  "# Tylko dosłowna fraza \"gregaipanicmode\" w czacie: cofnij reguły zapory" \
  "# wpuszczające GREGAI z sieci prywatnych, potem wyłącz komputer. Nic więcej." \
  "$RUN_USER ALL=(root) NOPASSWD: $PANIC_RULES" | sudo_write "$PANIC_TMP"
need_sudo chmod 440 "$PANIC_TMP"
if need_sudo visudo -cf "$PANIC_TMP" >/dev/null; then
  need_sudo mv -f "$PANIC_TMP" "$PANIC_SUDOERS"
  ok "sudoers: $PANIC_SUDOERS (gregaipanicmode: zapora + poweroff; działa też przy wyłączonym SYSOP)"
else
  need_sudo rm -f "$PANIC_TMP"
  warn "reguły sudo dla gregaipanicmode niepoprawne - nie zainstalowane (panicmode powie wprost, że nie może wyłączyć komputera)"
fi
SUDOERS=/etc/sudoers.d/gregai-sysop
# Świadome wyłączenie SYSOP (SYSOP_ENABLED=0 w .env na maszynie, która już miała
# usługę) zostaje: bez stałych uprawnień sudo, bez nadpisywania ustawienia.
# Świeża instalacja (także z .env przeniesionym ze starego laptopa) włącza SYSOP.
SYSOP_KEEP_OFF=0
if [ "$SERVICE_EXISTED" = 1 ] && [ "$(envval SYSOP_ENABLED)" = "0" ]; then SYSOP_KEEP_OFF=1; fi
if [ "$SYSOP_KEEP_OFF" = 1 ]; then
  warn "SYSOP_ENABLED=0 w .env zostaje (świadoma decyzja): bez narzędzi systemowych i bez reguł sudo. Włączenie: SYSOP_ENABLED=1 w .env, potem bash install.sh"
  # Reguły z wcześniejszej instalacji nie mogą zostać: wyłączony SYSOP = zero stałych uprawnień sudo.
  if need_sudo test -f "$SUDOERS"; then need_sudo rm -f "$SUDOERS" && ok "usunięto stare reguły sudo ($SUDOERS)"; fi
else
# Najpierw plik tymczasowy (nazwa z kropką: sudo takich plików w sudoers.d
# nie czyta), sprawdzenie visudo, dopiero potem podmiana. Błędny plik od razu
# w sudoers.d wyłączyłby sudo w całym systemie.
SUDOERS_TMP="$SUDOERS.nowy"
# Tryb PEŁNY SYSOP (1.17.0, SYSOP_MODE=pelny w .env; agent/sysop.py "Tryb
# PEŁNY"): decyzja Grzegorza 2026-10-21 - GREGAI na WYIZOLOWANYM Ubuntu ma
# "korzystać z całego Ubuntu pod siebie, pełen dostęp". Wtedy sudo bez hasła
# dla WSZYSTKIEGO (jedna reguła ALL), nie tylko dla listy wyżej. Włączasz to
# świadomie wpisem w .env i ponownym install.sh; powrót: SYSOP_MODE=strazniczy
# (albo usunięcie wpisu) + install.sh - plik sudoers wraca do wąskiej listy.
SYSOP_MODE_NOW="$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')"
if [ "$SYSOP_MODE_NOW" = "pelny" ]; then
sudo_write "$SUDOERS_TMP" <<EOF
# gregai-szablon: $GREGAI_SZABLON
# GREGAI (agent/sysop.py) - TRYB PEŁNY (SYSOP_MODE=pelny w .env): wyizolowane
# Ubuntu przeznaczone wyłącznie dla GREGAI, pełen dostęp do systemu.
# Powrót do wąskiej listy: SYSOP_MODE=strazniczy w .env i bash install.sh.
$RUN_USER ALL=(ALL) NOPASSWD: ALL
EOF
else
sudo_write "$SUDOERS_TMP" <<EOF
# gregai-szablon: $GREGAI_SZABLON
# GREGAI (agent/sysop.py): zmiany po potwierdzeniu użytkownika w rozmowie.
# Tylko usługi: $SYSOP_UNITS (lista w install.sh, SYSOP_UNITS).
# GREGAIPANICMODE ma osobny plik: /etc/sudoers.d/gregai-panic.
$RUN_USER ALL=(root) NOPASSWD: $UNIT_RULES
$RUN_USER ALL=(root) NOPASSWD: /usr/bin/apt-get update -q, /usr/bin/apt-get upgrade -y -q -o Dpkg\:\:Options\:\:=--force-confdef -o Dpkg\:\:Options\:\:=--force-confold
EOF
fi
need_sudo chmod 440 "$SUDOERS_TMP"
if need_sudo visudo -cf "$SUDOERS_TMP" >/dev/null; then
  need_sudo mv -f "$SUDOERS_TMP" "$SUDOERS"
  if [ "$SYSOP_MODE_NOW" = "pelny" ]; then
    warn "sudoers: $SUDOERS - TRYB PEŁNY: $RUN_USER ma sudo bez hasła do WSZYSTKIEGO (SYSOP_MODE=pelny). Tylko na wyizolowanym Ubuntu przeznaczonym dla GREGAI."
  else
    ok "sudoers: $SUDOERS (systemctl tylko dla: $SYSOP_UNITS; apt-get update/upgrade)"
  fi
else
  need_sudo rm -f "$SUDOERS_TMP"
  warn "reguły sudo dla SYSOP niepoprawne - nie zainstalowane (GREGAI nie zrestartuje usług ani nie zaktualizuje systemu)"
fi
# Plan zakłada SYSOP włączony: świeża instalacja ustawia to zawsze (także gdy ze
# starego laptopa przyszło SYSOP_ENABLED=0). Wyłączenie na stałe: SYSOP_ENABLED=0
# w .env po instalacji i restart usługi; kolejne install.sh tego nie cofa.
ensure_nl
grep -q "Warstwa systemowa (agent/sysop.py)" "$ENV_FILE" || \
  printf '\n# Warstwa systemowa (agent/sysop.py): odczyt od razu, zmiany po potwierdzeniu, niebezpieczne zablokowane.\n' >> "$ENV_FILE"
set_env SYSOP_ENABLED 1
set_env SYSOP_USE_SUDO 1
fi
if [ "$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')" = "pelny" ]; then
  warn "SYSOP_MODE=pelny w .env: TRYB PEŁNY - dowolny shell zawsze, pliki w całym systemie, każda usługa, sudo do wszystkiego; polecenia nieodwracalne za jednym potwierdzeniem (SYSOP_PYTAJ=$(envval SYSOP_PYTAJ | tr '[:upper:]' '[:lower:]'), puste = niebezpieczne). Powrót: SYSOP_MODE=strazniczy + bash install.sh"
elif [ "$(envval SYSOP_SHELL)" = "1" ]; then
  warn "SYSOP_SHELL=1 w .env: wolne polecenia powłoki (po Twoim potwierdzeniu). Klasyfikator to lista znanych furtek, nie dowód ich braku. Wyłączenie: SYSOP_SHELL=0"
fi
# Katalogi dla narzędzi plikowych: tylko projekt (nie cały katalog domowy -
# tam są klucze SSH, profil przeglądarki). Własne katalogi możesz dopisać w
# .env świadomie (oddzielone ":"); nie nadpisujemy ich, chyba że wskazują na
# nieistniejące miejsca albo inną kopię projektu (np. ze starego laptopa).
ROOTS="$(envval SYSOP_ROOTS)"
HOME_REAL="$(realpath "$HOME")"
valid_roots=()
IFS=: read -r -a _roots <<< "$ROOTS"
for r in "${_roots[@]:-}"; do
  [ -n "$r" ] || continue
  rr="$(realpath -m "${r/#\~/$HOME}" 2>/dev/null || echo "")"
  # Odrzucamy: puste, nieistniejące, "/", cały katalog domowy albo katalog, który
  # go zawiera (tam są klucze SSH, profil przeglądarki).
  if [ -z "$rr" ] || [ ! -d "$rr" ] || [ "$rr" = "/" ] \
     || [ "$rr" = "$HOME_REAL" ] || [[ "$HOME_REAL/" == "$rr/"* ]]; then
    continue
  fi
  # Wpis wskazujący INNĄ kopię projektu GREGAI (po przeniesieniu folderu stara
  # kopia może jeszcze istnieć) jest nieaktualny: narzędzia plikowe miałyby
  # działać na starym folderze.
  if [ -f "$rr/agent/main.py" ] && [ "$rr" != "$ROOT" ]; then
    continue
  fi
  valid_roots+=("$r")
done
# Zostają własne, poprawne katalogi (SYSOP_ROOTS zastępuje domyślny folder GREGAI,
# nie jest do niego dopisywane); gdy żaden nie przetrwał: folder tego projektu.
if [ "${#valid_roots[@]}" -eq 0 ]; then NEW_ROOTS="$ROOT"; else NEW_ROOTS="$(IFS=:; echo "${valid_roots[*]}")"; fi
[ "$NEW_ROOTS" = "$ROOTS" ] || set_env SYSOP_ROOTS "$NEW_ROOTS"
straz_mark
need_sudo systemctl restart gregai || { warn "restart usługi gregai po zmianie trybu SYSOP nie powiódł się: journalctl -u gregai -n 30"; HEALTH_FAIL=1; }
# 1.18.0: w trybie pełnym agent/sysop.py ignoruje SYSOP_ROOTS (cały system) -
# wypisywanie "katalogi: ..." sugerowałoby ograniczenie, którego nie ma.
if [ "$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')" = "pelny" ]; then
  ok "SYSOP: SYSOP_ENABLED=$(envval SYSOP_ENABLED), TRYB PEŁNY - narzędzia plikowe widzą cały system (SYSOP_ROOTS nieużywane)"
else
  ok "SYSOP: SYSOP_ENABLED=$(envval SYSOP_ENABLED), sudo dla zmian, katalogi: $(envval SYSOP_ROOTS)"
fi

# Zapora: na Ubuntu Desktop ufw jest zainstalowany, ale WYŁĄCZONY. Nic nie
# musi wchodzić z sieci (GREGAI słucha tylko na localhost), więc: blokuj
# przychodzące, wypuszczaj wychodzące. Przy GREGAI_LAN=1 (komputer bez
# pulpitu) wpuszczamy port GREGAI tylko z sieci prywatnych.
if ! command -v ufw >/dev/null; then warp_guard; need_sudo apt-get install -y -qq ufw; fi
# IPV6=yes (domyślne na Ubuntu): bez tego ufw nie zarządza ip6tables i port po IPv6 zostaje otwarty.
if [ -f /etc/default/ufw ] && ! grep -q '^IPV6=yes' /etc/default/ufw; then
  warn "W /etc/default/ufw brak IPV6=yes: zapora nie obejmuje IPv6. Ustaw IPV6=yes i uruchom: sudo ufw reload"
fi
need_sudo ufw default deny incoming >/dev/null
# 1.19.0: domyślna polityka wychodzących tylko przy pierwszym włączeniu zapory -
# świadome "deny outgoing" ustawione przez Ciebie zostaje (ostrzegamy, bo wtedy
# GREGAI potrzebuje Twoich reguł dla WARP).
if ! need_sudo env LC_ALL=C ufw status | grep -q '^Status: active'; then
  need_sudo ufw default allow outgoing >/dev/null
elif need_sudo env LC_ALL=C ufw status verbose | grep -qE '(deny|reject) \(outgoing\)'; then
  warn "ufw: domyślnie BLOKUJESZ ruch wychodzący (Twoje ustawienie zostaje). WARP i GREGAI potrzebują wtedy Twoich reguł 'allow out'."
fi
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
  if [ "$LAN" = "1" ]; then
    need_sudo ufw allow from "$net" to any port "$PORT" proto tcp comment 'GREGAI - tylko siec prywatna' >/dev/null
  else
    # GREGAI_LAN=0: reguły LAN z wcześniejszej instalacji z GREGAI_LAN=1 nie mogą zostać.
    need_sudo ufw delete allow from "$net" to any port "$PORT" proto tcp >/dev/null 2>&1 || true
  fi
done
# 1.20.0: instalacja przez SSH nie może odciąć sama siebie. Przed włączeniem zapory
# zezwalamy na SSH z adresu, z którego jesteśmy połączeni (jeśli to sesja SSH).
if [ -n "${SSH_CONNECTION:-}" ]; then
  SSH_CLIENT_IP="$(awk '{print $1}' <<<"$SSH_CONNECTION")"; SSH_LOCAL_PORT="$(awk '{print $4}' <<<"$SSH_CONNECTION")"
  if [[ "$SSH_CLIENT_IP" =~ ^[0-9A-Fa-f:.]+$ ]] && [[ "$SSH_LOCAL_PORT" =~ ^[0-9]+$ ]]; then
    need_sudo ufw allow from "$SSH_CLIENT_IP" to any port "$SSH_LOCAL_PORT" proto tcp comment 'GREGAI - sesja SSH instalacji' >/dev/null \
      && ok "zapora: zezwolono na SSH z $SSH_CLIENT_IP (ta sesja)"
  fi
fi
need_sudo ufw --force enable >/dev/null
# Ubuntu uruchamia sshd przez ssh.socket (ssh.service jest "inactive" do pierwszego
# połączenia), więc sprawdzamy też gniazdo; istniejąca reguła dla portu 22 wycisza ostrzeżenie.
if systemctl is-active --quiet ssh ssh.socket sshd 2>/dev/null && ! need_sudo env LC_ALL=C ufw status 2>/dev/null | grep -qE '^(22(/tcp)?|OpenSSH)( |$)'; then
  warn "Działa serwer SSH: zapora blokuje nowe połączenia przychodzące, także SSH. Jeśli łączysz się tu zdalnie, zezwól świadomie, np.: sudo ufw allow from 192.168.0.0/16 to any port 22 proto tcp"
fi
if need_sudo env LC_ALL=C ufw status | grep -q '^Status: active'; then ok "zapora ufw: włączona (przychodzące zablokowane)"; else warn "zapora ufw się nie włączyła: sudo ufw enable"; fi

# 1.30.0 (Twierdza): jeśli działa serwer SSH, stawiamy fail2ban - zgadywanie hasła
# SSH kończy się blokadą adresu. Bez SSH nic nie instalujemy (po co). GREGAI_FAIL2BAN=0
# w .env pomija ten krok. Konfigurację piszemy jako drop-in, oryginałów nie ruszamy.
if [ "$(envval GREGAI_FAIL2BAN)" = "0" ]; then
  warn "GREGAI_FAIL2BAN=0 w .env: pomijam ochronę logowania SSH (fail2ban)."
elif systemctl is-active --quiet ssh ssh.socket sshd 2>/dev/null; then
  if ! command -v fail2ban-server >/dev/null; then warp_guard; need_sudo apt-get install -y -qq fail2ban >/dev/null 2>&1 || true; fi
  # backend=systemd wymaga modułu python3-systemd (inaczej jail [sshd] cicho nie wstaje).
  if ! python3 -c 'import systemd.journal' >/dev/null 2>&1; then warp_guard; need_sudo apt-get install -y -qq python3-systemd >/dev/null 2>&1 || true; fi
  if command -v fail2ban-server >/dev/null; then
    F2B_JAIL=/etc/fail2ban/jail.d/gregai-ssh.conf
    F2B_TMP="$(mktemp)"
    # backend=systemd: Ubuntu 25.04+ nie ma /var/log/auth.log (patrz straz.py).
    # journalmatch obejmuje ssh.service (Ubuntu) i sshd.service - inaczej 1.30.1
    # (red-team): daemon wstaje, ale jail nic nie łapie, a użytkownik słyszy "aktywne".
    cat > "$F2B_TMP" <<'F2B'
# GREGAI (install.sh, krok "Twierdza"): blokada zgadywania hasla SSH.
[sshd]
enabled = true
backend = systemd
journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd
maxretry = 5
findtime = 10m
bantime = 1h
F2B
    if ! need_sudo cmp -s "$F2B_TMP" "$F2B_JAIL" 2>/dev/null; then
      need_sudo mkdir -p /etc/fail2ban/jail.d
      need_sudo cp "$F2B_TMP" "$F2B_JAIL"
      need_sudo systemctl enable --now fail2ban >/dev/null 2>&1 || true
      need_sudo systemctl restart fail2ban >/dev/null 2>&1 || true
    fi
    rm -f "$F2B_TMP"
    sleep 1
    # 1.30.1 (red-team): sprawdzamy SAM JAIL, nie tylko usługę - jail może nie wstać,
    # a demon i tak jest "active". "gregai check" (kontrola 33) powtarza to pytanie.
    if need_sudo fail2ban-client status sshd >/dev/null 2>&1; then
      ok "ochrona SSH (fail2ban): jail [sshd] działa, zgadywanie hasła kończy się blokadą"
    elif systemctl is-active --quiet fail2ban 2>/dev/null; then
      warn "fail2ban działa, ale jail [sshd] nie wstał: sudo fail2ban-client status sshd; sprawdź python3-systemd i journalmatch."
    else
      warn "fail2ban zainstalowany, ale nieaktywny: sudo systemctl status fail2ban"
    fi
  else
    warn "nie udało się zainstalować fail2ban (brak sieci?): ochronę SSH dołóż później: sudo apt install fail2ban"
  fi
fi

# Router domowy (agent/homenet.py): zapamiętujemy go świadomie TERAZ, przy
# instalacji w domu. Bez tego skan sieci i odczyt routera HiLink zostają
# wyłączone (bezpieczniej niż zapamiętać przypadkową sieć w tle).
if PIN_MSG="$(python3 "$ROOT/agent/homenet.py" --pin 2>&1)"; then
  ok "router domowy: $PIN_MSG"
else
  warn "router domowy nie zapamiętany: $PIN_MSG"
  warn "skan sieci i odczyt routera ruszą po (w domu): cd \"$ROOT\" && python3 agent/homenet.py --pin"
fi

echo
warp_on && ok "WARP nadal połączony" || warn "WARP rozłączył się w trakcie: warp-cli connect (GREGAI do tego czasu bez internetu)"

if [ "${GREGAI_SKIP_CHECK:-0}" != "1" ]; then
  log "Kontrola końcowa (check.sh)"
  bash "$ROOT/check.sh" || { warn "check.sh zgłosił uwagi powyżej; popraw je i uruchom ponownie: bash \"$ROOT/install.sh\""; CHECK_FAIL=1; }
fi

if [ "$DO_TRAIN" = "1" ]; then
  log "Trening modeli w tle: router, planer, uczeń"
  GO=1
  if [ "$INTERACTIVE" = "1" ]; then
    echo "   Trening trwa według szacunku 2-3 doby na tym CPU (finetune.py wypisze prawdziwy czas) i zajmuje większość RAM."
    echo "   Zamknij przeglądarkę i inne programy. GREGAI w tym czasie odpowiada wolniej."
    read -rp "   Zacząć teraz? [t/N] " _ans || _ans=""
    case "$_ans" in t|T|y|Y|tak) ;; *) GO=0 ;; esac
  fi
  mkdir -p "$ROOT/training/.work"
  if [ "$GO" = "1" ] && ! flock -n "$ROOT/training/.work/.train.lock" true 2>/dev/null; then
    warn "inny trening GREGAI już działa (blokada training/.work/.train.lock); nie uruchamiam drugiego"
    GO=0
  fi
  if [ "$GO" = "1" ]; then
    mkdir -p "$ROOT/data/training"
    TLOG="$ROOT/data/training/train_all.log"
    (umask 077; : > "$TLOG")   # log zawiera wyniki ocen na prawdziwych wiadomościach: prawa 600
    nohup bash -c '
      cd "$1" || exit 1
      unset BASE_MODEL MODEL_NAME   # każdy skrypt używa własnych domyślnych nazw i modeli bazowych
      export BATCH=1 GRAD_ACCUM=8 NO_RESTART=1
      for pair in run.sh:router run_planner.sh:planner run_student.sh:student; do
        s="${pair%%:*}"
        # Po przerwie (prąd, restart) nie trenujemy od nowa tego, co już jest gotowe i aktualne.
        if [ -z "${FORCE_TRAIN:-}" ] && python3 training/model_status.py "${pair##*:}" > /dev/null 2>&1; then
          echo "== $s pominięty: model ${pair##*:} jest już wytrenowany i aktualny (wymuszenie: FORCE_TRAIN=1 bash install.sh --train)"
          continue
        fi
        echo "== $s start $(date)"
        nice -n 19 bash "training/$s" || echo "== BŁĄD: $s zakończył się niepowodzeniem"
      done
      echo "== restart gregai, żeby wczytał nowe modele"
      sudo -n systemctl restart gregai || echo "== zrestartuj ręcznie: sudo systemctl restart gregai"
      echo "== KONIEC $(date)"
    ' _ "$ROOT" > "$TLOG" 2>&1 < /dev/null &
    disown 2>/dev/null || true
    ok "trening ruszył w tle (log: $TLOG; postęp: tail -f \"$TLOG\")"
  else
    ok "trening nie ruszył; uruchomisz go później: bash \"$ROOT/install.sh\" --train"
  fi
fi

# Jedno polecenie `gregai` (1.11.0): dowiązanie w ~/.local/bin, żeby działało z
# każdego folderu (gregai status|check|update|logs|open...). Sam plik leży w
# projekcie, więc po przeniesieniu folderu aktualizuj.sh przepina dowiązanie.
chmod +x "$ROOT/gregai" 2>/dev/null || true
BIN_DIR="$(as_user bash -c 'echo "${XDG_BIN_HOME:-$HOME/.local/bin}"')"
if as_user mkdir -p "$BIN_DIR" 2>/dev/null && as_user ln -sfn "$ROOT/gregai" "$BIN_DIR/gregai" 2>/dev/null; then
  ok "polecenie gregai: $BIN_DIR/gregai -> $ROOT/gregai"
  case ":${PATH}:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR nie jest w PATH tej powłoki; po ponownym zalogowaniu będzie (Ubuntu dodaje ~/.local/bin sam), do tego czasu: bash \"$ROOT/gregai\"" ;; esac
else
  warn "nie udało się dopisać dowiązania $BIN_DIR/gregai; używaj: bash \"$ROOT/gregai\""
fi

VERSION_TXT="$(cat "$ROOT/VERSION" 2>/dev/null || echo '?')"
echo
if [ "${CHECK_FAIL:-0}" = 1 ] || [ "${HEALTH_FAIL:-0}" = 1 ]; then
  printf '\033[1;33m== GREGAI %s zainstalowany, ale kontrola zgłosiła błędy (szczegóły wyżej)\033[0m\n' "$VERSION_TXT"
else
  printf '\033[1;32m== GREGAI %s zainstalowany\033[0m\n' "$VERSION_TXT"
fi
echo "   Ścieżka projektu:  $ROOT"
[ -n "${GREGAI_RELOCATED_FROM:-}" ] && echo "   (skopiowany z:     $GREGAI_RELOCATED_FROM; ten folder możesz zostawić albo usunąć po sprawdzeniu)"
[ -n "$PREV_ROOT" ] && [ "$PREV_ROOT" != "$ROOT" ] && echo "   Poprzednia ścieżka: $PREV_ROOT (kolejne zmiany wgrywaj już pod nową)"
echo "   Adres GREGAI:       http://localhost:$PORT"
echo
echo "Przeniesiesz folder gdzie indziej? Ta sama komenda w nowym miejscu:  bash <nowa ścieżka>/install.sh"
echo "Po wgraniu nowej wersji kodu (bez przenoszenia):                      bash \"$ROOT/aktualizuj.sh\""
echo "Jedno polecenie do wszystkiego (stan, kontrola, logi, restart):        gregai help"
echo
echo "Opcjonalnie (Krok 10, INSTALACJA_UBUNTU_26_04.md):"
echo "  bash \"$ROOT/install.sh\" --train                                          # router + planer + uczeń w tle"
echo "  cd \"$ROOT\" && python3 training/bench_chat.py --models qwen2.5:3b --limit 3   # czasy modelu"
echo "GREGAI rozgrzewa teraz duży model w tle (kilka minut, stan: http://localhost:$PORT/debug)."
if [ "${HEALTH_FAIL:-0}" = 1 ]; then
  warn "Instalacja zakończona, ale GREGAI nie odpowiedziało przy kontroli. Sprawdź: journalctl -u gregai -n 50; potem: gregai check"
  exit 1
fi
if [ "${CHECK_FAIL:-0}" = 1 ]; then
  warn "Instalacja zakończona, ale check.sh zgłosił błędy (lista wyżej). Po poprawkach: gregai check"
  exit 1
fi
