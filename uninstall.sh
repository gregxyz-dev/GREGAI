#!/usr/bin/env bash
# uninstall.sh - GREGAI: czyszczenie systemu po instalacji (odwrotność install.sh).
#
# Użycie:
#   bash uninstall.sh              # interaktywne, pyta przed każdą rzeczą
#   bash uninstall.sh --dry-run    # pokazuje plan; NIC nie zmienia
#   bash uninstall.sh --yes        # bez pytań, poza usunięciem folderu projektu
#   bash uninstall.sh --help
#
# Co robi (w tej kolejności):
#   1. zatrzymuje i wyłącza usługi gregai / gregai-siec,
#   2. usuwa reguły ufw z komentarzem GREGAI (port 7777 i sesja SSH),
#   3. usuwa tabelę nftables gregai_warp i jej plik,
#   4. usuwa swap /swap.img i wpis w /etc/fstab,
#   5. odinstalowuje Cloudflare WARP (apt, nie snap),
#   6. odinstalowuje Ollamę (oficjalny installer, nie apt) razem z modelami,
#   7. usuwa pliki systemd, sudoers, fail2ban i logind,
#   8. usuwa klucze, źródła apt, symlink CLI, konfigurację i konto gregai,
#   9. opcjonalnie usuwa pakiety systemowe,
#  10. usuwa folder projektu - ZAWSZE po osobnym potwierdzeniu.
#
# Czego NIE rusza (świadomie):
#   - gsettings "brak usypiania" ustawionego przez install.sh --no-host,
#   - konta i plików innych programów; usuwamy tylko elementy GREGAI i Ollamy,
#   - pakietu python3 (usunięcie zepsułoby system), mimo że install.sh go doinstalowuje.
#
# Log: uninstall.log w bieżącym katalogu (data i godzina każdej akcji).
# Kopia: /tmp/gregai-uninstall.log - zostaje, gdy folder projektu też jest usuwany.
#
# Kody wyjścia: 0 = sukces, 1 = błąd, 2 = anulowane przez użytkownika,
# 130 = przerwane Ctrl+C.
[ -n "${BASH_VERSION:-}" ] || { echo "Użyj bash, nie sh: bash $0"; exit 1; }
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

DRY_RUN=0
ASSUME_YES=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help)
      awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      printf '%bNieznana opcja: %s%b\n' "$RED" "$arg" "$NC" >&2
      echo "Użyj: bash $0 [--dry-run|--yes|--help]" >&2
      exit 1
      ;;
  esac
done

if [ "$(id -u)" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
  printf '%bUruchom jako zwykły użytkownik, BEZ sudo:%b  bash uninstall.sh\n' "$RED" "$NC" >&2
  echo "Skrypt sam poprosi o hasło do sudo. Dane w ~/.config, ~/.ollama i symlink CLI" >&2
  echo "należą do Twojego konta, nie do roota." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [ ! -f "$ROOT/agent/main.py" ] || [ ! -f "$ROOT/VERSION" ]; then
  printf '%bTo nie wygląda na folder GREGAI: %s%b\n' "$RED" "$ROOT" "$NC" >&2
  exit 1
fi

RUN_USER="$(id -un)"
LOG="$(pwd)/uninstall.log"
LOG_COPY=/tmp/gregai-uninstall.log
: > "$LOG" 2>/dev/null || { echo "Nie mogę utworzyć $LOG" >&2; exit 1; }

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Każda linia logu ma datę i godzinę; na ekran kolorowo, do pliku czysty tekst.
emit() {
  local color="$1" tag="$2" plain
  shift 2
  plain="$(ts) [$tag] $*"
  printf '%b%s%b\n' "$color" "$plain" "$NC"
  printf '%s\n' "$plain" >> "$LOG" 2>/dev/null || true
}

section() {
  local plain
  plain="$(ts) == $* =="
  printf '\n%b%s%b\n' "$CYAN" "$plain" "$NC"
  printf '%s\n' "$plain" >> "$LOG" 2>/dev/null || true
}

ok() {
  if [ "$DRY_RUN" -eq 1 ]; then
    emit "$CYAN" "PLAN" "$*"
  else
    emit "$GREEN" "OK" "$*"
  fi
}
skip() { emit "$YELLOW" "SKIP" "$*"; }
warn() { emit "$YELLOW" "UWAGA" "$*"; }
fail() { emit "$RED" "ERR" "$*"; exit 1; }

cp_log() {
  [ "$LOG" = "$LOG_COPY" ] && return 0
  cp -a "$LOG" "$LOG_COPY" 2>/dev/null || true
}

on_interrupt() {
  emit "$RED" "PRZERWANO" "Ctrl+C / sygnał przerwania"
  cp_log
  exit 130
}

on_error() {
  local code="$1" line="$2"
  emit "$RED" "ERR" "nieoczekiwany błąd (kod $code, linia $line)"
  cp_log
  exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

# Tylko odczyt: sprawdzenie istnienia bez zmiany systemu i bez hałasu.
sudo_can_run() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@" >/dev/null 2>&1
  else
    sudo "$@" >/dev/null 2>&1
  fi
}

# Ścisła: błąd kończy skrypt (ERR trap -> exit 1). Wynik polecenia idzie też do logu.
run_sudo() {
  if [ "$DRY_RUN" -eq 1 ]; then
    emit "$CYAN" "DRY" "$ $*"
    return 0
  fi
  emit "$CYAN" "RUN" "$ $*"
  if [ "$(id -u)" -eq 0 ]; then
    "$@" 2>&1 | tee -a "$LOG"
  else
    sudo "$@" 2>&1 | tee -a "$LOG"
  fi
}

# Miękka: brak jednostki/reguły nie jest błędem (idempotencja).
try_sudo() {
  if [ "$DRY_RUN" -eq 1 ]; then
    emit "$CYAN" "DRY" "$ $*"
    return 0
  fi
  emit "$CYAN" "RUN" "$ $*"
  if [ "$(id -u)" -eq 0 ]; then
    "$@" >/dev/null 2>&1 || true
  else
    sudo "$@" >/dev/null 2>&1 || true
  fi
}

confirm() {
  local question="$1"
  if [ "$DRY_RUN" -eq 1 ]; then
    emit "$CYAN" "DRY" "pytanie: $question"
    return 0
  fi
  if [ "$ASSUME_YES" -eq 1 ]; then
    emit "$GREEN" "AUTO" "$question"
    return 0
  fi
  if [ ! -t 0 ]; then
    emit "$YELLOW" "SKIP" "$question (brak terminala; uruchom: bash uninstall.sh)"
    return 1
  fi
  printf '%b%s [t/N]%b ' "$YELLOW" "$question" "$NC"
  local answer=""
  read -r answer || { echo; emit "$RED" "ANULOWANO" "przerwane wejście"; exit 2; }
  case "$answer" in
    t|T|tak|Tak|y|Y|yes|YES)
      emit "$GREEN" "TAK" "$question"
      return 0
      ;;
    *)
      emit "$RED" "ANULOWANO" "$question"
      exit 2
      ;;
  esac
}

# Folder projektu usuwamy zawsze po osobnym pytaniu, nawet z --yes.
confirm_project() {
  local question="To usunie CAŁY projekt, notatki, pamięć i .env. Na pewno?"
  if [ "$DRY_RUN" -eq 1 ]; then
    emit "$CYAN" "DRY" "pytanie: $question"
    return 0
  fi
  if [ ! -t 0 ]; then
    emit "$YELLOW" "SKIP" "$question (brak terminala; folder projektu zostaje)"
    return 1
  fi
  printf '%b%s [t/N]%b ' "$YELLOW" "$question" "$NC"
  local answer=""
  read -r answer || { echo; emit "$RED" "ANULOWANO" "przerwane wejście"; exit 2; }
  case "$answer" in
    t|T|tak|Tak|y|Y|yes|YES) return 0 ;;
    *)
      emit "$YELLOW" "NIE" "folder projektu zostaje"
      return 1
      ;;
  esac
}

file_exists() { [ -e "$1" ] || [ -L "$1" ]; }
tree_exists() { [ -e "$1" ] || [ -L "$1" ]; }

remove_file() {
  local path="$1"
  if file_exists "$path"; then
    run_sudo rm -f "$path"
    if [ "$DRY_RUN" -eq 1 ]; then
      emit "$CYAN" "PLAN" "usunięto by: $path"
    else
      ok "usunięto $path"
    fi
  else
    skip "brak $path"
  fi
}

remove_tree() {
  local path="$1"
  if tree_exists "$path"; then
    run_sudo rm -rf "$path"
    if [ "$DRY_RUN" -eq 1 ]; then
      emit "$CYAN" "PLAN" "usunięto by: $path"
    else
      ok "usunięto $path"
    fi
  else
    skip "brak $path"
  fi
}

dpkg_installed() {
  have dpkg-query && dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'ok installed'
}

unit_present() {
  [ -f /etc/systemd/system/gregai.service ] \
    || [ -f /etc/systemd/system/gregai-siec.service ] \
    || [ -f /etc/systemd/system/gregai-siec.timer ] \
    || { have systemctl && systemctl cat gregai.service >/dev/null 2>&1; }
}

nft_present() {
  local nft_bin="$1"
  [ -n "$nft_bin" ] && sudo_can_run "$nft_bin" list table inet gregai_warp
}

trap on_interrupt INT TERM
trap 'on_error "$?" "$LINENO"' ERR

section "GREGAI uninstall"
emit "$CYAN" "INFO" "folder projektu: $ROOT"
if [ "$DRY_RUN" -eq 1 ]; then
  emit "$CYAN" "INFO" "tryb: DRY-RUN (żadna zmiana nie jest wykonywana)"
else
  emit "$CYAN" "INFO" "tryb: rzeczywisty"
fi
cp_log

# --- 1. Usługi GREGAI ------------------------------------------------------
section "1. Usługi GREGAI"
if ! have systemctl; then
  skip "systemctl nie jest dostępny"
elif ! unit_present; then
  skip "usługi GREGAI nie są zainstalowane"
else
  try_sudo systemctl stop gregai
  try_sudo systemctl disable gregai
  try_sudo systemctl stop gregai-siec.timer
  try_sudo systemctl disable gregai-siec.timer
  try_sudo systemctl stop gregai-siec.service
  try_sudo systemctl daemon-reload
  try_sudo systemctl reset-failed gregai gregai-siec.service gregai-siec.timer
  ok "usługi gregai zatrzymane i wyłączone"
fi

# --- 2. ufw ---------------------------------------------------------------
section "2. Reguły ufw GREGAI"
if ! have ufw; then
  skip "ufw nie jest zainstalowany"
elif [ "$DRY_RUN" -eq 1 ]; then
  emit "$CYAN" "DRY" "$ ufw status numbered | usunięcie reguł z komentarzem GREGAI (port 7777, sesja SSH)"
  emit "$CYAN" "PLAN" "usunięto by reguły ufw GREGAI"
else
  UFW_NUMS="$(sudo ufw status numbered 2>/dev/null | awk -F'[][]' '/# GREGAI/{print $2}' | sort -rn || true)"
  if [ -z "$UFW_NUMS" ]; then
    skip "brak reguł ufw GREGAI"
  else
    for n in $UFW_NUMS; do
      # Numery malejąco: usunięcie wyższej reguły nie przesuwa niższej.
      run_sudo ufw --force delete "$n"
    done
    ok "reguły ufw GREGAI usunięte"
  fi
fi

# --- 3. nftables ----------------------------------------------------------
section "3. Zapora WARP (nftables)"
NFT_BIN=""
if have nft; then
  NFT_BIN="$(command -v nft)"
elif [ -x /usr/sbin/nft ]; then
  NFT_BIN=/usr/sbin/nft
fi
if [ -z "$NFT_BIN" ]; then
  skip "nft nie jest dostępny"
elif [ "$DRY_RUN" -eq 1 ]; then
  emit "$CYAN" "DRY" "$ $NFT_BIN delete table inet gregai_warp"
  emit "$CYAN" "PLAN" "usunięto by tabelę nftables gregai_warp"
elif ! nft_present "$NFT_BIN"; then
  skip "tabela nftables gregai_warp nie istnieje"
else
  run_sudo "$NFT_BIN" delete table inet gregai_warp
  ok "tabela nftables gregai_warp usunięta"
fi
remove_file /etc/gregai/warp-killswitch.nft
if [ -d /etc/gregai ]; then
  try_sudo rmdir /etc/gregai 2>/dev/null || true
fi

# --- 4. swap --------------------------------------------------------------
section "4. Swap"
SWAP_FILE=/swap.img
SWAP_ACTIVE=0
if have swapon; then
  if swapon --show=NAME,TYPE --noheadings 2>/dev/null | awk '$1=="/swap.img" && $2=="file"{found=1} END{exit !found}'; then
    SWAP_ACTIVE=1
  fi
fi
FSTAB_HAS_SWAP=0
if grep -qE '^/swap\.img[[:space:]]' /etc/fstab 2>/dev/null; then
  FSTAB_HAS_SWAP=1
fi
if [ -e "$SWAP_FILE" ] || [ "$SWAP_ACTIVE" -eq 1 ] || [ "$FSTAB_HAS_SWAP" -eq 1 ]; then
  if confirm "Usunąć swap 8 GB ($SWAP_FILE) i wpis w /etc/fstab?"; then
    if [ "$SWAP_ACTIVE" -eq 1 ]; then
      run_sudo swapoff "$SWAP_FILE"
    fi
    remove_file "$SWAP_FILE"
    if [ "$FSTAB_HAS_SWAP" -eq 1 ]; then
      run_sudo sed -i '\|^/swap\.img[[:space:]]|d' /etc/fstab
    else
      skip "brak wpisu /swap.img w /etc/fstab"
    fi
    ok "swap 8 GB usunięty"
  else
    skip "swap zostaje"
  fi
else
  skip "swap GREGAI nie jest skonfigurowany"
fi

# --- 5. Cloudflare WARP ---------------------------------------------------
section "5. Cloudflare WARP"
WARP_FOUND=0
have warp-cli && WARP_FOUND=1
dpkg_installed cloudflare-warp && WARP_FOUND=1
[ -f /etc/apt/sources.list.d/cloudflare-client.list ] && WARP_FOUND=1
[ -f /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg ] && WARP_FOUND=1
if [ "$WARP_FOUND" -eq 0 ]; then
  skip "WARP nie jest zainstalowany"
elif confirm "Odinstalować Cloudflare WARP i usunąć jego źródła apt?"; then
  # timeout + </dev/null: warp-cli potrafi zawisnąć albo o coś dopytać, gdy
  # daemon nie odpowiada; rejestracja i tak znika razem z pakietem.
  try_sudo timeout 10 warp-cli registration delete </dev/null
  try_sudo timeout 10 warp-cli unregister </dev/null
  try_sudo timeout 10 warp-cli disconnect </dev/null
  try_sudo systemctl stop warp-svc
  try_sudo systemctl disable warp-svc
  if dpkg_installed cloudflare-warp; then
    if have apt-get; then
      run_sudo apt-get remove -y cloudflare-warp
    else
      warn "apt-get nie jest dostępny - usuń pakiet cloudflare-warp ręcznie"
    fi
  fi
  remove_file /etc/apt/sources.list.d/cloudflare-client.list
  remove_file /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
  ok "WARP odinstalowany"
else
  skip "WARP zostaje"
fi

# --- 6. Ollama ------------------------------------------------------------
# Oficjalny instalator Ollamy (curl ... | sh) nie ma potwierdzonego
# --uninstall, więc usuwamy te same pliki, które on tworzy.
section "6. Ollama"
OLLAMA_FOUND=0
have ollama && OLLAMA_FOUND=1
[ -f /etc/systemd/system/ollama.service ] && OLLAMA_FOUND=1
[ -f /etc/systemd/system/ollama.service.d/gregai.conf ] && OLLAMA_FOUND=1
[ -e /usr/local/lib/ollama ] && OLLAMA_FOUND=1
[ -e /usr/share/ollama ] && OLLAMA_FOUND=1
[ -e /var/lib/ollama ] && OLLAMA_FOUND=1
[ -e "${HOME:-}/.ollama" ] && OLLAMA_FOUND=1
if [ "$OLLAMA_FOUND" -eq 0 ]; then
  skip "Ollama nie jest zainstalowana"
elif confirm "Odinstalować Ollamę i usunąć jej modele?"; then
  try_sudo systemctl stop ollama
  try_sudo systemctl disable ollama
  remove_file /etc/systemd/system/ollama.service.d/gregai.conf
  remove_file /etc/systemd/system/ollama.service
  if [ -d /etc/systemd/system/ollama.service.d ]; then
    try_sudo rmdir /etc/systemd/system/ollama.service.d 2>/dev/null || true
  fi
  remove_file /usr/local/bin/ollama
  remove_tree /usr/local/lib/ollama
  remove_tree /usr/share/ollama
  remove_tree /var/lib/ollama
  remove_tree "${HOME:-}/.ollama"
  try_sudo systemctl daemon-reload
  if have getent && { getent passwd ollama >/dev/null 2>&1 || getent group ollama >/dev/null 2>&1; }; then
    if confirm "Usunąć użytkownika i grupę systemową ollama (utworzone przez instalator Ollamy)?"; then
      try_sudo userdel ollama
      try_sudo groupdel ollama
      if getent passwd ollama >/dev/null 2>&1 || getent group ollama >/dev/null 2>&1; then
        warn "konto/grupa ollama nadal istnieje (proces w użyciu?) - sprawdź: getent passwd ollama"
      else
        ok "konto ollama usunięte"
      fi
    else
      skip "konto ollama zostaje"
    fi
  fi
  ok "Ollama i modele usunięte"
else
  skip "Ollama zostaje"
fi

# --- 7. systemd, sudoers, fail2ban, logind --------------------------------
section "7. Pliki systemowe"
UNITS_REMOVED=0
for unit in gregai.service gregai-siec.service gregai-siec.timer; do
  if [ -f "/etc/systemd/system/$unit" ]; then
    UNITS_REMOVED=1
  fi
  remove_file "/etc/systemd/system/$unit"
done
if [ "$UNITS_REMOVED" -eq 1 ]; then
  try_sudo systemctl daemon-reload
fi

if [ -f /etc/sudoers.d/gregai-sysop ] || [ -f /etc/sudoers.d/gregai-panic ]; then
  if confirm "Usunąć reguły sudo GREGAI (/etc/sudoers.d/gregai-*)?"; then
    remove_file /etc/sudoers.d/gregai-sysop
    remove_file /etc/sudoers.d/gregai-panic
  else
    skip "sudoers GREGAI zostają"
  fi
else
  skip "brak reguł sudo GREGAI"
fi

if [ -f /etc/fail2ban/jail.d/gregai-ssh.conf ]; then
  if confirm "Usunąć regułę fail2ban GREGAI dla SSH?"; then
    remove_file /etc/fail2ban/jail.d/gregai-ssh.conf
    if have systemctl && systemctl is-active --quiet fail2ban 2>/dev/null; then
      try_sudo systemctl reload fail2ban
    fi
  else
    skip "fail2ban GREGAI zostaje"
  fi
else
  skip "brak reguły fail2ban GREGAI"
fi

LOGIND_REMOVED=0
if [ -f /etc/systemd/logind.conf.d/gregai.conf ]; then
  if confirm "Usunąć ustawienie logind GREGAI (brak usypiania po zamknięciu klapy)?"; then
    remove_file /etc/systemd/logind.conf.d/gregai.conf
    LOGIND_REMOVED=1
  else
    skip "logind GREGAI zostaje"
  fi
else
  skip "brak ustawienia logind GREGAI"
fi
if [ "$LOGIND_REMOVED" -eq 1 ]; then
  # Bez restartu systemd-logind: install.sh tego nie robi, bo przy otwartej
  # sesji restart wylogowuje z pulpitu. Zmiana zadziała po restarcie komputera.
  warn "logind: zmiana zadziała po restarcie komputera (nie restartuję sesji)"
fi

# --- 8. Klucze, apt, CLI, konfiguracja, konto -------------------------------
section "8. Klucze, źródła apt, CLI, konfiguracja i konto"
remove_file /usr/share/keyrings/gregai.gpg
remove_file "${HOME:-}/.local/bin/gregai"
remove_tree "${HOME:-}/.gregai"

STATE_DIR="${XDG_CONFIG_HOME:-${HOME:-}/.config}/gregai"
if [ -e "$STATE_DIR" ]; then
  if confirm "Usunąć konfigurację GREGAI ($STATE_DIR)?"; then
    remove_tree "$STATE_DIR"
  else
    skip "konfiguracja $STATE_DIR zostaje"
  fi
else
  skip "brak $STATE_DIR"
fi

if [ -e /var/lib/gregai ]; then
  if confirm "Usunąć katalog domowy usługi /var/lib/gregai?"; then
    remove_tree /var/lib/gregai
  else
    skip "/var/lib/gregai zostaje"
  fi
else
  skip "brak /var/lib/gregai"
fi

if have getent && { getent passwd gregai >/dev/null 2>&1 || getent group gregai >/dev/null 2>&1; }; then
  if confirm "Usunąć użytkownika i grupę systemową gregai?"; then
    if [ "$RUN_USER" != "gregai" ] && id -nG "$RUN_USER" 2>/dev/null | tr ' ' '\n' | grep -qx gregai; then
      try_sudo gpasswd -d "$RUN_USER" gregai
    fi
    try_sudo userdel gregai
    try_sudo groupdel gregai
    if getent passwd gregai >/dev/null 2>&1 || getent group gregai >/dev/null 2>&1; then
      warn "konto/grupa gregai nadal istnieje (proces w użyciu?) - sprawdź: getent passwd gregai"
    else
      ok "konto i grupa gregai usunięte (przy zadaniach wymagających grupy wyloguj się i zaloguj ponownie)"
    fi
  else
    skip "konto i grupa gregai zostają"
  fi
else
  skip "brak konta i grupy gregai"
fi

# --- 9. Pakiety opcjonalne ------------------------------------------------
section "9. Pakiety systemowe"
if have apt-get && have dpkg-query; then
  # python3 zostaje świadomie: usunięcie zepsułoby Ubuntu. To samo dotyczy
  # pakietów, których GREGAI tylko używa, a nie instaluje.
  PACKAGES=(python3-venv git curl rsync smartmontools nftables ufw fail2ban)
  TO_REMOVE=()
  for pkg in "${PACKAGES[@]}"; do
    if dpkg_installed "$pkg"; then
      TO_REMOVE+=("$pkg")
    fi
  done
  if [ "${#TO_REMOVE[@]}" -eq 0 ]; then
    skip "brak pakietów z listy GREGAI do usunięcia"
  elif confirm "Usunąć pakiety: ${TO_REMOVE[*]}? (bez autoremove)"; then
    run_sudo apt-get remove -y "${TO_REMOVE[@]}"
    ok "pakiety usunięte"
  else
    skip "pakiety zostają"
  fi
else
  skip "apt-get/dpkg-query niedostępne"
fi

# --- 10. Folder projektu (zawsze osobne pytanie) --------------------------
section "10. Folder projektu"
if [ -d "$ROOT" ] && confirm_project; then
  # Log musi przeżyć usunięcie folderu: kopia leży poza projektem.
  cp_log
  if [ "$DRY_RUN" -eq 0 ]; then
    LOG="$LOG_COPY"
    emit "$CYAN" "INFO" "od tej chwili log jest zapisywany w $LOG_COPY"
  fi
  run_sudo rm -rf "$ROOT"
  ok "usunięto $ROOT"
else
  skip "folder projektu zostaje: $ROOT"
fi

# --- 11. Podsumowanie -----------------------------------------------------
section "11. Podsumowanie"
ok "zakończono uninstall.sh"
if [ "$LOG" = "$LOG_COPY" ]; then
  emit "$CYAN" "INFO" "log: $LOG"
else
  emit "$CYAN" "INFO" "log: $LOG"
  emit "$CYAN" "INFO" "kopia: $LOG_COPY"
fi
cp_log
exit 0
