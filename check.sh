#!/usr/bin/env bash
# check.sh - kontrole GREGAI na prawdziwym laptopie, po `bash install.sh`
# (liczbę kontroli pokazuje banner na starcie i wynik na końcu, nie ten
# komentarz - żeby nie trzeba było pamiętać o jego aktualizacji):
#
#     cd ~/Dokumenty/GREGAI && bash check.sh
#
# Niczego nie zmienia, tylko sprawdza i podpowiada, co poprawić. Zapyta raz
# o hasło (sudo): stan dysku, zapora i reguły sudo wymagają uprawnień.
# Kod wyjścia: 0 = wszystko OK, 1 = coś do poprawy.
# Nigdy nie wypisuje sekretów z .env (klucze, tokeny, hasła).
set -uo pipefail
export LC_ALL=C.UTF-8   # komunikaty narzędzi po angielsku (stałe do porównań), polskie znaki dalej działają

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$ROOT/.env"
PORT=7777
PASS=0
FAIL=0
FAILED=()

ok()   { PASS=$((PASS + 1)); printf '  \033[32mOK  \033[0m %2d. %s\n' "$1" "$2"; }
bad()  { FAIL=$((FAIL + 1)); FAILED+=("$1"); printf '  \033[31mBŁĄD\033[0m %2d. %s\n        -> %s\n' "$1" "$2" "$3"; }
RUN_USER="${SUDO_USER:-$(id -un)}"
# Czy WSZYSTKIE adresy z listy to ta maszyna (127.0.0.1 / ::1)? Pusta = nie.
all_local() {
  [ -n "${1// /}" ] || return 1
  local a
  for a in $1; do case "$a" in 127.0.0.1:*|\[::1\]:*) ;; *) return 1 ;; esac; done
}
# Te same kształty linii, które czyta agent/env_loader.py: także `export KLUCZ=` i `KLUCZ = wartość`.
envval() { grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'\r" | xargs || true; }

# Kontrole nie zapisują do prawdziwego dziennika Koryta (1.20.0).
export KORYTO_DZIENNIK_PLIK="$(mktemp -u /tmp/gregai-koryto-XXXXXX.json)"
printf '\n\033[1;36m== GREGAI: 68 kontrole (%s)\033[0m\n\n' "$(date '+%Y-%m-%d %H:%M')"
sudo -v || { echo "Bez sudo nie da się sprawdzić wszystkiego. Uruchom ponownie i podaj hasło."; exit 1; }

# 1. System
. /etc/os-release 2>/dev/null || true
# install.sh obsługuje Ubuntu 22.04-26.04 (plan: 26.04 LTS), więc tyle samo akceptujemy tutaj.
OS_MAJOR="${VERSION_ID:-}"; OS_MAJOR="${OS_MAJOR%%.*}"
if [ "${ID:-}" = "ubuntu" ] && [[ "$OS_MAJOR" =~ ^[0-9]+$ ]] && [ "$OS_MAJOR" -ge 22 ]; then ok 1 "System: ${PRETTY_NAME:-Ubuntu}"
else bad 1 "System: ${PRETTY_NAME:-nieznany}" "GREGAI jest sprawdzany na Ubuntu 22.04-26.04 (plan: 26.04 LTS)"; fi

# 2. Szyfrowanie dysku (LUKS): musi być w łańcuchu urządzeń systemu plików "/"
# (zaszyfrowany pendrive podpięty obok niczego nie dowodzi).
ROOT_SRC="$(findmnt -no SOURCE / 2>/dev/null | head -1)"; ROOT_SRC="${ROOT_SRC%%\[*}"
if [ -n "$ROOT_SRC" ] && lsblk -srno TYPE "$ROOT_SRC" 2>/dev/null | grep -qx crypt; then ok 2 "Dysk systemowy zaszyfrowany (LUKS)"
else bad 2 "Dysk systemowy NIE jest zaszyfrowany" "szyfrowanie wybiera się przy instalacji systemu (Krok 4, punkt 6)"; fi

# 3. Stan dysku (SMART)
DISK="$(lsblk -dno NAME,TYPE,RM 2>/dev/null | awk '$2=="disk" && $3==0 && $1 !~ /^(zram|loop|ram)/ {print $1; exit}')"
if ! command -v smartctl >/dev/null; then
  bad 3 "Stan dysku: brak smartctl" "sudo apt install -y smartmontools"
elif SMART="$(sudo env LC_ALL=C smartctl -H "/dev/${DISK:-sda}" 2>/dev/null || true)"; [ -n "$DISK" ] && printf '%s' "$SMART" | grep -qE 'PASSED|Health Status: OK'; then
  ok 3 "Stan dysku /dev/$DISK: PASSED"
else
  bad 3 "Stan dysku /dev/${DISK:-?}: nie PASSED" "sudo smartctl -a /dev/${DISK:-sda} (trzymaj kopię danych na starym laptopie)"
fi

# 4. RAM i swap
RAM_GB="$(awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo)"
SWAP_GB="$(awk '/SwapTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo)"
if [ "${RAM_GB:-0}" -ge 15 ] && [ "${SWAP_GB:-0}" -ge 7 ]; then ok 4 "RAM ${RAM_GB} GB, swap ${SWAP_GB} GB"
elif [ "${RAM_GB:-0}" -ge 8 ] && [ "${SWAP_GB:-0}" -ge 7 ]; then ok 4 "RAM ${RAM_GB} GB, swap ${SWAP_GB} GB (działa; 16 GB zalecane pod duży model i trening)"
else bad 4 "RAM ${RAM_GB:-?} GB, swap ${SWAP_GB:-?} GB" "za mało - minimum 8 GB RAM i 7 GB swap (16 GB zalecane; Krok 6, punkt 4)"; fi

# 5. WARP: status klienta
WARP_STATUS="$(warp-cli status </dev/null 2>/dev/null | head -1)"
if printf '%s' "$WARP_STATUS" | grep -q '\bConnected\b'; then ok 5 "Cloudflare WARP: $WARP_STATUS"
else bad 5 "Cloudflare WARP: ${WARP_STATUS:-brak warp-cli}" "warp-cli connect (albo bash install.sh, jeśli nie zainstalowany)"; fi

# 6. WARP: ruch naprawdę idzie przez Cloudflare
# Odpowiedź do zmiennej, nie `curl | grep -q`: przy pipefail wczesne wyjście grepa dałoby SIGPIPE i fałszywy błąd.
# 1.19.0: zapytanie do Cloudflare tylko przy połączonym kliencie (kontrola 5) -
# przy rozłączonym WARP poszłoby zwykłym łączem, obok niego.
TRACE=""
if printf '%s' "$WARP_STATUS" | grep -q '\bConnected\b'; then
  TRACE="$(curl -fsS --noproxy '*' --max-time 10 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null || true)"
fi
if grep -q '^warp=\(on\|plus\)' <<<"$TRACE"; then
  ok 6 "Ruch do internetu przez WARP (warp=on)"
else
  bad 6 "Ruch NIE idzie przez WARP (albo brak internetu)" "warp-cli connect, potem: curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp"
fi

# 7. Zapora (ufw aktywna, domyślnie blokuje przychodzące, bez obcych reguł ALLOW IN) oraz AppArmor.
# 1.19.0: LIMIT IN ("ufw limit 22") też wpuszcza (z limitem prób), więc liczy się jak ALLOW IN.
# Dozwolone: ALLOW IN z sieci prywatnych (10/8, 172.16/12, 192.168/16), a port $PORT tylko
# przy GREGAI_LAN=1. Reguła wpuszczająca "Anywhere" (także IPv6) albo publiczny adres to błąd.
LAN="$(envval GREGAI_LAN)"
UFW="$(sudo env LC_ALL=C ufw status verbose 2>/dev/null || true)"
UFW_EXTRA="$(printf '%s\n' "$UFW" | awk -v port="$PORT" -v lan="$LAN" '
  /^--/ { rules = 1; next }
  !rules || !/(ALLOW|LIMIT) IN/ { next }
  { line = $0; sub(/[ \t]*#.*$/, "", line)
    kw = (index(line, "ALLOW IN") ? "ALLOW IN" : "LIMIT IN")
    i = index(line, kw); to = substr(line, 1, i - 1); from = substr(line, i + length(kw))
    gsub(/^[ \t]+|[ \t]+$/, "", to); gsub(/^[ \t]+|[ \t]+$/, "", from)
    web  = (to ~ ("^" port "(/tcp)?( \\(v6\\))?$"))
    priv = (from ~ /^(10\.[0-9.]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9.]+|192\.168\.[0-9.]+)(\/[0-9]+)?$/)
    if ((web && lan != "1") || !priv) print "  " to " <- " from }')"
if ! printf '%s' "$UFW" | grep -q '^Status: active'; then
  bad 7 "Zapora ufw: wyłączona" "sudo ufw enable"
elif ! printf '%s' "$UFW" | grep -q '^Default: deny (incoming)'; then
  bad 7 "Zapora ufw: aktywna, ale domyślnie NIE blokuje przychodzących" "sudo ufw default deny incoming"
elif [ -n "$UFW_EXTRA" ]; then
  bad 7 "Zapora ufw: nieoczekiwane reguły ALLOW/LIMIT IN (GREGAI_LAN=${LAN:-0}):$(printf '\n%s' "$UFW_EXTRA")" "sudo ufw status numbered, potem sudo ufw delete <nr> (reguły portu $PORT przy GREGAI_LAN=0 usunie też bash install.sh)"
elif ! sudo aa-status --enabled >/dev/null 2>&1; then
  bad 7 "AppArmor: wyłączony" "sudo systemctl enable --now apparmor (na Ubuntu jest domyślnie włączony)"
else ok 7 "Zapora ufw: aktywna, przychodzące zablokowane, brak obcych reguł; AppArmor włączony"; fi

# 8. Ollama działa i słucha tylko lokalnie
OLLAMA_LISTEN="$(ss -ltnH 'sport = :11434' 2>/dev/null | awk '{print $4}' | sort -u | xargs)"
if ! systemctl is-active --quiet ollama; then
  bad 8 "Ollama nie działa" "sudo systemctl restart ollama; journalctl -u ollama -n 30"
elif all_local "$OLLAMA_LISTEN"; then
  ok 8 "Ollama działa, słucha tylko lokalnie ($OLLAMA_LISTEN)"
else
  bad 8 "Ollama słucha: ${OLLAMA_LISTEN:-nigdzie}" "ma być tylko 127.0.0.1:11434 - uruchom ponownie bash install.sh"
fi

# 9. Ustawienia Ollamy pod GREGAI (+ okno kontekstu, w którym mieści się
#    pełny prompt GREGAI razem z historią rozmowy - kontrola 18 niżej
#    liczy to naprawdę, to tu jest tylko minimalny, bezpieczny próg)
DROPIN=/etc/systemd/system/ollama.service.d/gregai.conf
CTX="$(envval OLLAMA_NUM_CTX)"; CTX="${CTX:-16384}"
if ! grep -q 'OLLAMA_NUM_PARALLEL=1' "$DROPIN" 2>/dev/null || ! grep -q 'OLLAMA_HOST=127.0.0.1:11434' "$DROPIN" 2>/dev/null \
   || ! grep -q 'OLLAMA_CONTEXT_LENGTH=16384' "$DROPIN" 2>/dev/null; then
  bad 9 "Brak ustawień Ollamy GREGAI ($DROPIN)" "bash install.sh"
elif ! [[ "$CTX" =~ ^[0-9]+$ ]] || [ "$CTX" -lt 16384 ]; then
  bad 9 "OLLAMA_NUM_CTX=$CTX w .env: pełny prompt GREGAI się nie mieści" "bash install.sh (ustawi 16384)"
else
  ok 9 "Ollama: tylko 127.0.0.1, jedna rozmowa naraz, okno $CTX tokenów"
fi

# 10. Model rozmowy pobrany
MODEL="$(envval OLLAMA_MODEL)"; MODEL="${MODEL:-qwen2.5:3b}"
# Ollama wypisuje model bez tagu jako "nazwa:latest": porównujemy bez ":latest" po obu stronach.
if ollama list 2>/dev/null | awk -v m="$MODEL" 'NR>1 {n=$1; sub(/:latest$/, "", n); w=m; sub(/:latest$/, "", w); if (n == w) f=1} END {exit !f}'; then ok 10 "Model rozmowy pobrany: $MODEL"
else bad 10 "Model $MODEL nie jest pobrany" "ollama pull $MODEL"; fi

# 11. Usługa GREGAI (i czy wskazuje TEN folder - po przeniesieniu projektu mogła zostać na starym)
UNIT_WD="$(systemctl show -p WorkingDirectory --value gregai 2>/dev/null)"
if [ -n "$UNIT_WD" ] && [ "$UNIT_WD" != "$ROOT" ]; then
  bad 11 "Usługa gregai wskazuje inny folder: $UNIT_WD (ten skrypt leży w $ROOT)" "bash \"$ROOT/install.sh\" (przepnie usługę na ten folder)"
elif systemctl is-active --quiet gregai && systemctl is-enabled --quiet gregai && systemctl is-enabled --quiet gregai-siec.timer; then
  ok 11 "Usługi: gregai działa i startuje z systemem, skan sieci domowej (gregai-siec.timer) włączony"
else
  bad 11 "Usługi: gregai $(systemctl is-active gregai 2>/dev/null)/$(systemctl is-enabled gregai 2>/dev/null), gregai-siec.timer $(systemctl is-enabled gregai-siec.timer 2>/dev/null)" "bash install.sh; journalctl -u gregai -n 50"
fi

# 12. Port 7777 tylko lokalnie (chyba że świadomie GREGAI_LAN=1)
WEB_LISTEN="$(ss -ltnH "sport = :$PORT" 2>/dev/null | awk '{print $4}' | sort -u | xargs)"
if [ -z "$WEB_LISTEN" ]; then
  bad 12 "Nic nie słucha na porcie $PORT" "journalctl -u gregai -n 50"
elif [ "$LAN" = "1" ]; then
  ok 12 "Port $PORT: $WEB_LISTEN (GREGAI_LAN=1: w sieci, z tokenem; używasz GREGAI tylko na tym laptopie? ustaw GREGAI_LAN=0)"
elif all_local "$WEB_LISTEN"; then
  ok 12 "Port $PORT tylko lokalnie ($WEB_LISTEN)"
else
  bad 12 "Port $PORT otwarty na sieć: $WEB_LISTEN" "w .env GREGAI_LAN=0, potem: bash install.sh (restartuje usługę i usuwa reguły LAN w ufw)"
fi

# 13. GREGAI odpowiada
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$PORT/api/status")"
if [ "$CODE" = "200" ]; then ok 13 "GREGAI odpowiada: http://localhost:$PORT"
else bad 13 "GREGAI nie odpowiada (HTTP $CODE)" "journalctl -u gregai -n 50"; fi

# 14. Żądanie przez pośrednika bez tokenu musi zostać odrzucone
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'CF-Connecting-IP: 203.0.113.7' -H 'X-Forwarded-For: 203.0.113.7' "http://127.0.0.1:$PORT/api/status")"
if [ "$CODE" = "403" ]; then ok 14 "Żądanie z zewnątrz bez tokenu: odrzucone (403)"
else bad 14 "Żądanie z zewnątrz bez tokenu: HTTP $CODE (oczekiwane 403)" "stary agent/main.py? rozpakuj GREGAI.zip ponownie i: sudo systemctl restart gregai"; fi

# 15. Strażnik internetu (agent/netguard.py) widzi WARP
NG="$(curl -s --max-time 15 "http://127.0.0.1:$PORT/api/system_info" | python3 -c 'import sys,json
try:
    w = json.load(sys.stdin).get("warp") or {}
    print("tak" if w.get("connected") else "nie|" + (w.get("reason") or "brak pola warp"))
except Exception as e:
    print("nie|brak odpowiedzi")' 2>/dev/null)"
if [ "$NG" = "tak" ]; then ok 15 "Strażnik internetu: WARP połączony, GREGAI może wychodzić do sieci"
else bad 15 "Strażnik internetu: ${NG#nie|}" "warp-cli connect; jeśli WARP działa, a to dalej błąd: sudo systemctl restart gregai"; fi

# 16. .env: tylko dla właściciela
PERM="$(stat -c '%a %U' "$ENV_FILE" 2>/dev/null)"
if [ "${PERM%% *}" = "600" ] && [ "${PERM#* }" = "$RUN_USER" ]; then ok 16 ".env: prawa 600, właściciel $RUN_USER"
else bad 16 ".env: ${PERM:-brak pliku}" "chmod 600 \"$ENV_FILE\""; fi

# 17. Reguły sudo: poprawne, bez "dowolnej usługi"; GREGAI odmawia osłabienia zabezpieczeń
SUDOERS=/etc/sudoers.d/gregai-sysop
# Żywy przykład błędu (audyt 1.8.20, runda 2): agent/sysop.py rozpoznawał nazwę
# programu/czasownika/jednostki do porównania z listami zakazanych BEZ zmiany
# wielkości liter - "WARP-CLI DISCONNECT"/"sudo UFW DISABLE"/"SYSTEMCTL STOP
# gregai"/"systemctl stop GREGAI" (wielkimi literami) nie trafiały w żadną z
# tych list (wszystkie pisane małymi literami) i spadały do słabszego trybu
# "zmiana" (karta potwierdzenia) zamiast "zablokowane na stałe" - dokładnie to
# samo polecenie, tylko inaczej wpisane. Cztery pierwsze warianty niżej to
# dokładnie te przypadki; trzy bazowe (bez wielkich liter) zostają jako
# pierwotna kontrola.
SYSOP_OK="$(cd "$ROOT/agent" && python3 -c 'import sysop
bad = [c for c in (
    "warp-cli disconnect", "sudo ufw disable", "sudo systemctl stop warp-svc",
    "WARP-CLI DISCONNECT", "sudo UFW DISABLE", "SYSTEMCTL STOP gregai", "systemctl stop GREGAI",
    "sudo ip link set CloudflareWARP down", "sudo tee /etc/resolv.conf", "shutdown -h now",
) if sysop.classify_shell(c)[0] != sysop.DESTRUCTIVE]
print("tak" if not bad else "nie: " + ", ".join(bad))' 2>/dev/null)"
# Treść reguł sudo sprawdzana wprost: KAŻDA linia musi być regułą dla użytkownika
# usługi, a KAŻDE polecenie to systemctl (start/stop/restart/reload/enable/disable)
# dla gregai albo ollama, dokładnie apt-get update -q / upgrade -y -q (z opcjami dpkg
# zachowującymi pliki konfiguracyjne użytkownika; sudo pokazuje je bez ukośników)
# albo jedna z reguł GREGAIPANICMODE (install.sh: PANIC_RULES - ufw delete allow
# dla trzech sieci prywatnych i systemctl poweroff; do 1.16.2 ta kontrola ich
# NIE znała, więc od 1.8.15 na każdym laptopie zgłaszała "coś poza dozwoloną
# listą" - niespójność check.sh z install.sh, naprawiona w 1.17.0).
# TRYB PEŁNY (1.17.0, SYSOP_MODE=pelny w .env): plik ma być DOKŁADNIE jedną
# regułą "ALL=(ALL) NOPASSWD: ALL" dla użytkownika usługi - i niczym więcej.
# 1.19.0: reguły GREGAIPANICMODE leżą w osobnym /etc/sudoers.d/gregai-panic,
# instalowanym zawsze (także przy SYSOP_ENABLED=0): ma istnieć, przejść visudo
# i zawierać WYŁĄCZNIE polecenia panicmode (ufw x3 + trzy formy poweroff od 1.30.31). Stare gregai-sysop z tymi
# regułami w środku nadal przechodzi (sprzed 1.19.0, install.sh je przepisze).
PANIC_SUDOERS=/etc/sudoers.d/gregai-panic
PANIC_OK="$(sudo cat "$PANIC_SUDOERS" 2>/dev/null | RUN_USER="$RUN_USER" PORT="$PORT" python3 -c '
import os, re, sys
port = os.environ["PORT"]
want = {f"/usr/sbin/ufw delete allow from {net} to any port {port} proto tcp" for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")}
want |= {"/usr/bin/systemctl poweroff", "/usr/bin/systemctl poweroff -i", "/usr/bin/systemctl poweroff --force"}
got, bad = set(), []
for raw in sys.stdin.read().splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    m = re.fullmatch(r"(\S+) ALL=\(root\) NOPASSWD: (.+)", line)
    if not m or m.group(1) != os.environ["RUN_USER"]:
        bad.append("obca linia: " + line[:50]); continue
    for c in m.group(2).split(", "):
        (got.add(c) if c in want else bad.append(c[:50]))
print("tak" if got == want and not bad else "nie: " + ("; ".join(bad[:2]) or "brak reguł panicmode"))
' 2>/dev/null)"
if ! sudo test -f "$PANIC_SUDOERS"; then PANIC_STATE="brak $PANIC_SUDOERS (gregaipanicmode nie wyłączy komputera)"
elif ! sudo visudo -cf "$PANIC_SUDOERS" >/dev/null 2>&1; then PANIC_STATE="$PANIC_SUDOERS niepoprawny"
elif [ "$PANIC_OK" != "tak" ]; then PANIC_STATE="$PANIC_SUDOERS: ${PANIC_OK#nie: }"
else PANIC_STATE=""; fi
SUDOERS_OK="$(sudo cat "$SUDOERS" 2>/dev/null | RUN_USER="$RUN_USER" SYSOP_MODE_ENV="$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')" PORT="$PORT" python3 -c '
import os, re, sys
unit = re.compile(r"/usr/bin/systemctl (--no-block )?(start|stop|restart|reload|enable|disable) (gregai|ollama)(\.service)?")
port = os.environ["PORT"]
fixed = {"/usr/bin/apt-get update -q",
         "/usr/bin/apt-get upgrade -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold",
         "/usr/bin/systemctl poweroff", "/usr/bin/systemctl poweroff -i", "/usr/bin/systemctl poweroff --force"}
fixed |= {f"/usr/sbin/ufw delete allow from {net} to any port {port} proto tcp" for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")}
full = os.environ["SYSOP_MODE_ENV"] == "pelny"
bad, rules = [], 0
for raw in sys.stdin.read().splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    line = line.replace("\\:", ":")  # w pliku sudoers dwukropek jest zapisany jako \:
    if full:
        rules += 1
        if line != os.environ["RUN_USER"] + " ALL=(ALL) NOPASSWD: ALL":
            bad.append("obca linia: " + line[:50])
        continue
    m = re.fullmatch(r"(\S+) ALL=\(root\) NOPASSWD: (.+)", line)
    if not m or m.group(1) != os.environ["RUN_USER"]:
        bad.append("obca linia: " + line[:50])
        continue
    rules += 1
    bad += [c[:50] for c in m.group(2).split(", ") if not (unit.fullmatch(c) or c in fixed)]
if full and rules != 1:
    bad.append("tryb pełny: oczekiwana dokładnie jedna reguła, jest %d" % rules)
print("tak" if rules and not bad else "nie: " + ("; ".join(bad[:3]) if bad else "brak reguł"))
' 2>/dev/null)"
if [ -n "$PANIC_STATE" ]; then
  bad 17 "Reguły gregaipanicmode: $PANIC_STATE" "bash install.sh (odtworzy /etc/sudoers.d/gregai-panic)"
elif [ "$(envval SYSOP_ENABLED)" = "0" ] && ! sudo test -f "$SUDOERS"; then
  ok 17 "SYSOP wyłączony (SYSOP_ENABLED=0): brak reguł sudo poza gregaipanicmode, GREGAI niczego w systemie nie zmieni"
elif [ "$(envval SYSOP_ENABLED)" = "0" ]; then
  bad 17 "SYSOP wyłączony w .env, ale reguły sudo z wcześniejszej instalacji nadal obowiązują ($SUDOERS)" "bash install.sh (usunie je, bo SYSOP_ENABLED=0 zostaje)"
elif ! sudo test -f "$SUDOERS"; then
  bad 17 "Brak $SUDOERS" "bash install.sh"
elif ! sudo visudo -cf "$SUDOERS" >/dev/null 2>&1; then
  bad 17 "$SUDOERS niepoprawny" "bash install.sh (odtworzy go)"
elif [ "$SUDOERS_OK" != "tak" ]; then
  bad 17 "$SUDOERS zawiera coś poza dozwoloną listą (${SUDOERS_OK#nie: })" "bash install.sh (odtworzy plik: systemctl dla gregai i ollama, apt-get update/upgrade, gregaipanicmode; w trybie pełnym jedna reguła ALL)"
elif [ "$SYSOP_OK" != "tak" ]; then
  bad 17 "SYSOP nie rozpoznaje osłabienia zabezpieczeń jako niebezpiecznego (${SYSOP_OK:-błąd importu})" "rozpakuj GREGAI.zip ponownie"
elif [ "$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')" = "pelny" ]; then
  ok 17 "TRYB PEŁNY SYSOP: sudo bez hasła do wszystkiego (świadomy wpis SYSOP_MODE=pelny); osłabienie zabezpieczeń nadal rozpoznawane jako niebezpieczne (karta)"
else
  ok 17 "sudo tylko dla gregai/ollama, apt, gregaipanicmode; GREGAI odmawia: rozłączenia WARP, wyłączenia zapory"
fi

# 18. Budżet pamięci rozmowy: pełny prompt systemowy (prompt.md + capabilities.py)
#     musi zostawiać miejsce na HISTORIĘ rozmowy, nie tylko "zmieścić się" w
#     oknie modelu samemu. Liczone na symulowanej, realistycznej 10-turowej
#     rozmowie przez prawdziwą funkcję agent/router.py:_build_messages (nie
#     przybliżenie w znakach) - żeby złapać dokładnie ten błąd: prompt się
#     "mieści", ale historia rozmowy i tak jest ucinana do zera przy każdej
#     nowej wiadomości (odkryte i naprawione 2026-10-19, patrz "Co nowego").
#     Od 1.8.22 prompt dostaje przy każdej wiadomości blok „Teraz” (agent/
#     awareness.py, do MAX_BLOCK_CHARS znaków) - liczony tutaj w najgorszym
#     przypadku (pełny limit), żeby budżet historii był sprawdzany razem z nim.
HISTORY_TURNS="$(cd "$ROOT/agent" && python3 -c '
import main as main_mod, router as router_mod, awareness as awareness_mod
sp = main_mod.get_system_prompt() + awareness_mod._max_block_sample()
user_msg = ("Potrzebuje, zebys mi sledzil ten temat caly czas i dawal znac, "
            "kiedy warto zareagowac - to jest dla mnie wazne strategicznie i "
            "finansowo, wiec chce miec pewnosc, ze nic mi nie umknie z tego, "
            "co ustalilismy wczesniej w rozmowie. ")
assistant_msg = ("Jasne, rozumiem kontekst i pilnuje tego w tle. Sprawdzilem "
                 "najpierw lokalne notatki, potem - bo tam nic nie bylo - "
                 "przeszukalem siec, i teraz mam pelny obraz sytuacji z tym "
                 "tematem: oto co znalazlem i co z tego wynika dla Twoich "
                 "celow krotko- i dlugoterminowych, biorac pod uwage budzet "
                 "operacyjny i to, co juz wiemy z poprzednich rozmow. ")
hist = []
for _ in range(10):
    hist.append({"role": "user", "content": user_msg})
    hist.append({"role": "assistant", "content": assistant_msg})
msgs = router_mod._build_messages(sp, hist, "Aktualne pytanie.", router_mod.OLLAMA_NUM_CTX, 400)
print(len(msgs) - 2)
' 2>/dev/null)"
if [[ "$HISTORY_TURNS" =~ ^[0-9]+$ ]] && [ "$HISTORY_TURNS" -ge 9 ]; then
  ok 18 "Budżet pamięci rozmowy: $HISTORY_TURNS/10 tur historii przetrwa w realistycznej rozmowie"
else
  bad 18 "Budżet pamięci rozmowy: tylko ${HISTORY_TURNS:-błąd}/10 tur historii przetrwa" "prompt.md lub capabilities.py narosły - przytnij najdłuższe opisy narzędzi (agent/capabilities.py, pole prompt=) albo sekcje prompt.md; albo podnieś OLLAMA_NUM_CTX (patrz agent/router.py)"
fi

# 19. Szybka ścieżka capabilities.find_keyword_match() omija Ollamę na KAŻDEJ
#     wiadomości (patrz router.py) - gołe, wieloznaczne słowo w jej wzorcach
#     psuje więc zwykłą rozmowę, nie tylko jedno narzędzie. Audyt 2026-10-19
#     (patrz "Co nowego w 1.8.20" w README) znalazł to w kilku zdolnościach
#     naraz: "kurs" (notowanie ALE "kurs programowania"), "śledź/pilnuj" bez
#     ciągłości (najgorszy skutek: tworzy TRWAŁE zadanie w tle, nie tylko
#     błędną odpowiedź), "zasięg/sygnał" (sieć ALE YouTube/metafora - realne
#     ryzyko akurat dla Ciebie), "jakie typy" (grafu ALE czegokolwiek), i
#     kilka narzędzi SYSOP ("journal", "timery", "procesy", "backup").
MARKET_CHECK="$(cd "$ROOT/agent" && python3 -c '
import capabilities as cap_mod

def hits(key, msg):
    m = cap_mod.find_keyword_match(msg)
    return m is not None and m[0] == key

def hits_sysop_raw(key, msg):
    for pat in cap_mod._SYSOP_KEYWORDS.get(key, []):
        if pat.search(msg[:cap_mod.KEYWORD_SCAN_CHARS]):
            return True
    return False

false_positives = [
    ("market_quote", "Zapisalem sie na kurs programowania w Pythonie."),
    ("market_quote", "Zmienilem kurs firmy, idziemy w inna strone."),
    ("market_quote", "jaki kurs walut polecasz sledzic"),
    ("standing_task_new", "Lubie sledz w oleju, a Ty?"),
    ("standing_task_new", "Pilnuj dzieci, ja wychodze na chwile."),
    ("network_status", "jaki mam teraz zasieg na ostatnim filmie na YouTube?"),
    ("network_status", "to byl mocny sygnal, ze powinienem zmienic prace."),
    ("graph_overview", "jakie typy kawy pijasz rano?"),
]
sysop_false_positives = [
    ("sys_processes", "Jakie procesy sadowe moga mi grozic po tej transakcji?"),
    ("sys_logs", "Czytalem dzis artykul w Wall Street Journal"),
    ("sys_timers", "Mam juz odliczanie timery w kuchni na jajka."),
    ("sys_backup", "Zrob kopie zapasowa tego planu na papierze, zanim go zgubisz."),
]
ok = not any(hits(key, msg) for key, msg in false_positives)
ok = ok and not any(hits_sysop_raw(key, msg) for key, msg in sysop_false_positives)

calls = {}
cap_mod.tools_mod.market_quote = lambda symbol: calls.setdefault("symbol", symbol) or {
    "speech": f"{symbol}: 1.0", "card": {"type": "market_quote", "query": symbol, "data": {"Close": "1.0"}}}
m = cap_mod.find_keyword_match("Jaki jest kurs aapl.us?")
if m is not None and m[0] == "market_quote":
    cap_mod.CAPABILITIES["market_quote"].call(None, "Jaki jest kurs aapl.us?", m[1])
ok = ok and calls.get("symbol") == "aapl.us"
ok = ok and hits("standing_task_new", "sledz gielde caly czas i daj znac kiedy wchodzic")
ok = ok and hits("network_status", "jaki mam zasieg?")
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$MARKET_CHECK" = "OK" ]; then
  ok 19 "Szybka ścieżka narzędzi: ignoruje zwykłą rozmowę (kurs/śledź/zasięg/typy/...), rozpoznaje prawdziwe komendy"
else
  bad 19 "Szybka ścieżka narzędzi: ${MARKET_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/capabilities.py (keywords= tych zdolności)"
fi

# 20. sysop.classify_shell(): klasyfikator blokad "na stałe" (destructive) nie
#     może dać się obejść samą wielkością liter. Odkryte audytem 2026-10-19:
#     prawie każde porównanie "czy to ten program/czasownik" (warp-cli, ufw,
#     systemctl, apt, kill/pkill, visudo, iptables, poweroff...) było wrażliwe
#     na wielkość liter, więc "WARP-CLI DISCONNECT"/"UFW DISABLE"/"SYSTEMCTL
#     stop gregai"/"VISUDO" (wielkimi literami) spadały do słabszego trybu
#     "zmiana" (karta potwierdzenia) albo nawet "odczyt", zamiast zostać
#     zablokowane na stałe jak ich odpowiedniki małymi literami. Sprawdzamy
#     też, że bezpieczne, znane podkomendy (np. "warp-cli STATUS") nie
#     zaczęły być przez to nadmiernie blokowane.
SYSOP_CASE_CHECK="$(cd "$ROOT/agent" && python3 -c '
import sysop

must_block = [
    "WARP-CLI DISCONNECT", "UFW DISABLE", "SYSTEMCTL stop gregai",
    "APT remove cloudflare-warp", "PKILL -f warp", "AA-DISABLE x",
    "VISUDO", "IPTABLES -F", "POWEROFF",
]
must_stay_safe = [
    "warp-cli status", "WARP-CLI STATUS", "Warp-Cli Status",
    "systemctl status gregai", "SYSTEMCTL STATUS gregai",
    "ufw status", "UFW STATUS",
]
ok = all(sysop.classify_shell(c)[0] == sysop.DESTRUCTIVE for c in must_block)
ok = ok and all(sysop.classify_shell(c)[0] != sysop.DESTRUCTIVE for c in must_stay_safe)
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$SYSOP_CASE_CHECK" = "OK" ]; then
  ok 20 "SYSOP: blokady na stałe (WARP/zapora/sudo/...) nie da się obejść wielkością liter"
else
  bad 20 "SYSOP: ${SYSOP_CASE_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/sysop.py (_security_block, bases/words_lower)"
fi

# 21. Blok „Teraz” (agent/awareness.py, 1.8.22): zegar z dzisiejszą datą,
#     wersja lokalna i chmurowa, i granica między nimi: do żonglera/chmury
#     NIGDY nie idzie treść notatek z memory/ ani nazwa zadania stałego
#     (prompt.md, "Zabezpieczenia absolutne": do chmury sama rozmowa, bez
#     notatek). Liczone na prawdziwym vault tego komputera (bez zapisu).
TERAZ_CHECK="$(cd "$ROOT/agent" && python3 -c '
import datetime, main as main_mod, awareness as aw
today = datetime.date.today().isoformat()
v = main_mod.get_vault()
local, cloud = aw.local_block(v), aw.cloud_block()
ok = aw.HEADER in local and aw.HEADER in cloud and today in local and today in cloud
ok = ok and len(local) <= aw.MAX_BLOCK_CHARS and len(cloud) <= aw.MAX_BLOCK_CHARS
ok = ok and "Pamiętasz" not in cloud
items, _ = aw.memories(v)
ok = ok and all(body[:40] not in cloud for _, body in items)
tasks = [z for z, _ in aw.standing_mod.active_tasks()]
ok = ok and all(z[:40] not in cloud for z in tasks if z)
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$TERAZ_CHECK" = "OK" ]; then
  ok 21 "Blok „Teraz”: dzisiejsza data w prompcie, treść notatek tylko dla modelu lokalnego"
else
  bad 21 "Blok „Teraz”: ${TERAZ_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/awareness.py (local_block/cloud_block)"
fi

# 22. Namysł (agent/namysl.py, 1.9.0): pełny przebieg sześciu faz przez
#     PRAWDZIWE router.route() z podstawionymi modelami (bez Ollamy, bez
#     sieci, bez zapisu do śladu ani ustawień): krytyka ma trafić do poprawy,
#     a materiał z notatek NIGDY nie może pójść do dostawcy sieciowego bez
#     zgody w ustawieniach. To kontrola samej konstrukcji, nie jakości modeli.
NAMYSL_CHECK="$(cd "$ROOT/agent" && python3 -c '
import os
import router as r, juggler as j, namysl as n, netguard as ng, trace as t
class Note:
    title, text, ntype, slug, path = "Notatka testowa", "# Notatka testowa\ntype: Note\n\nMarża 400 zł.", "Note", "x", ""
class V:
    notes = {}
    def search(self, q, limit=5): return [Note()]
def local(system, history, message, **kw):
    if "etapem ROZPOZNANIA" in system: return "CEL: ocena\nRODZAJ: decyzja\nPYTANIA: a\nNOTATKI: marża\nPLIKI: -\nSIEC: -\nWIKI: -\nKURS: -\nPULAPKI: x"
    if "recenzentem" in system: return "WERDYKT: popraw\n- zmyślona liczba"
    if "etap POPRAWY" in system: return "POPRAWIONA odpowiedź (notatka: Notatka testowa)."
    if "etap SZKICU" in system: return "SZKIC."
    return "lokalnie"
seen = []
def cloud(system, msgs, message, timeout=60.0, preferred_provider=None, exclude_provider=None, **kw):
    seen.append(message)
    if "etapem ROZPOZNANIA" in system: return ("CEL: ocena\nRODZAJ: decyzja\nPYTANIA: a\nNOTATKI: marża\nPLIKI: -\nSIEC: -\nWIKI: -\nKURS: -\nPULAPKI: x", "groq")
    return ("chmura", "groq")
r._ollama_chat = local; j.chat = cloud; r.ollama_available = lambda: True
r._router_manifest_ok = lambda: (False, "t"); r.BIG_MODEL_ROUTING = False
r._student_manifest_ok = lambda: (False, "t")
ng.internet_allowed = lambda fresh=False: (False, "test"); t.record = lambda *a, **k: None
# Koryto (1.17.0): etapy sieciowe wyłączone wpisem KORYTO, nie trybem żonglera.
os.environ["KORYTO"] = "lokalnie"; j.providers_pool = lambda etap=None: []
a = r.route(V(), "SYS", [], "Czy warto teraz kupować iPhone 13 do odsprzedaży?")
c = a.get("card") or {}
ok = c.get("type") == "namysl" and "POPRAWIONA" in a.get("speech", "") and [f["nazwa"] for f in c.get("fazy", [])] == list(n.FAZY)
os.environ["KORYTO"] = "darmowe,lokalnie"; j.providers_pool = lambda etap=None: ["groq", "gemini"]
b = r.route(V(), "SYS", [], "Czy warto teraz kupować iPhone 13 do odsprzedaży?")
cb = b.get("card") or {}
ok = ok and cb.get("type") == "namysl" and cb["fazy"][0]["kto"] == "groq" and cb["fazy"][2]["kto"] == "lokalnie"
ok = ok and not any("Marża 400" in m for m in seen)
# 1.30.12: pytanie analityczne, ktore szybka sciezka skierowalaby na goly lookup
# (market_quote/research_web/wiki/search_brain), ma trafic do Namyslu (synteza), nie
# zwrocic surowej listy/notowania. Gdyby brak przekierowania - typ karty bylby inny.
d = r.route(V(), "SYS", [], "Wyszukaj w internecie i przeanalizuj, co wplywa na kurs BTC w tym miesiacu")
ok = ok and (d.get("card") or {}).get("type") == "namysl"
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$NAMYSL_CHECK" = "OK" ]; then
  ok 22 "Namysł: sześć faz przez router.route(), krytyka trafia do poprawy, notatki nie idą do sieci bez zgody"
else
  bad 22 "Namysł: ${NAMYSL_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/namysl.py (run, _Models.may_use_cloud)"
fi

# 23. Źródła (agent/sources.py, 1.9.0/1.9.1): foldery dodawane z interfejsu i
#     pliki wgrane do rozmowy nie mogą obejść reguł bezpieczeństwa plików: nigdy
#     "/", katalog domowy ani katalogi systemowe/prywatne jako źródło; nazwa
#     wgranego pliku bez ścieżki, bez .env i tylko z obsługiwanym rozszerzeniem.
#     Do tego izolacja rozmów (1.9.1): folder dodany w jednej rozmowie nie
#     istnieje dla innej. Stan i wgrane w katalogu tymczasowym - prawdziwy
#     data/sources.json nie jest dotykany.
SOURCES_CHECK="$(cd "$ROOT/agent" && python3 -c '
import os, tempfile, shutil, sources as s
from pathlib import Path
home = os.path.expanduser("~")
bad = ["/", home, os.path.dirname(home.rstrip("/")) or "/", "/etc", "/root", "/proc", os.path.join(home, ".ssh"), "wzgledna/sciezka", ""]
ok = all(not s._validate(p)[0] for p in bad)
ok = ok and s.safe_upload_name("../../etc/passwd.txt") == "passwd.txt"
ok = ok and s.safe_upload_name(".env") is None and s.safe_upload_name("zdjecie.png") is None and s.safe_upload_name("raport.pdf") == "raport.pdf"
tmp = Path(tempfile.mkdtemp(prefix="gregai-check23-"))
try:
    s.DATA_DIR = tmp / "data"; s.STATE_PATH = tmp / "data" / "sources.json"; s.UPLOAD_DIR = tmp / "data" / "wgrane"
    folder = tmp / "Faktury"; folder.mkdir()
    ok = ok and s.add("faktury", str(folder))["ok"]
    ok = ok and s.folders("ogolna") == [] and s.folders("youtube") == [] and len(s.folders("faktury")) == 1
    ok = ok and s.chat_id("../x") == "x" and s.chat_id("") == "ogolna"
    ok = ok and s.resolve_in_chat("faktury", str(folder / "a.txt")) is not None and s.resolve_in_chat("ogolna", str(folder / "a.txt")) is None
    up = s.save_upload("faktury", "raport.pdf", b"%PDF")
    ok = ok and up["ok"] and Path(up["path"]).parent.name == "faktury" and not s.status("ogolna")["wgrane"]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$SOURCES_CHECK" = "OK" ]; then
  ok 23 "Źródła: ani /, ani katalog domowy, ani foldery prywatne; indywidualne dla każdej rozmowy; nazwy wgranych bezpieczne"
else
  bad 23 "Źródła: ${SOURCES_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/sources.py (_validate, chat_id, resolve_in_chat)"
fi

# 24. Jedno wyjście do sieci (1.10.0): każdy ruch HTTP(S) do internetu w agent/
#     przechodzi przez netguard.urlopen()/netguard.fetch_http2() (WARP, fail-closed;
#     httpx HTTP/2 w netguard.py dla wyszukiwarki, 1.30.6) albo przez udokumentowany
#     wyjątek dla Groq w juggler.py (httpx z HTTP/2, te same zasady, trust_env=False).
#     Gołe urllib.request.urlopen / http.client poza netguard.py to
#     regres bezpieczeństwa - ta kontrola go łapie. socket.create_connection
#     wolno tylko w router_bridge.py (router w sieci domowej, nie internet).
NET_LEAKS="$(cd "$ROOT/agent" && grep -nE 'urllib\.request\.urlopen\(|http\.client\.|socket\.create_connection\(' *.py \
  | grep -vE '^(netguard|router_bridge)\.py:' \
  | grep -vE '^[a-z_]+\.py:[0-9]+:\s*#' \
  | grep -vE 'netguard(_mod)?\.(local_)?urlopen' || true)"
HTTPX_OUTSIDE="$(cd "$ROOT/agent" && grep -lE 'httpx\.Client\(' *.py | grep -vE '^(juggler|netguard)\.py$' || true)"
if [ -z "$NET_LEAKS" ] && [ -z "$HTTPX_OUTSIDE" ] && grep -q 'trust_env=False' "$ROOT/agent/juggler.py"; then
  ok 24 "Sieć: ruch do internetu tylko przez netguard (urlopen + httpx HTTP/2 dla wyszukiwarki) i udokumentowany httpx dla Groq (trust_env=False)"
else
  bad 24 "Sieć: bezpośrednie wyjście do sieci poza netguard.py: ${NET_LEAKS:-}${HTTPX_OUTSIDE:-}" "każde zapytanie do internetu ma iść przez netguard_mod.urlopen(); sprawdź wskazane linie"
fi

# 25. Pamięć rozmowy, bezpiecznik dostawców i warstwowa historia (1.10.0), na
#     atrapach i w katalogu tymczasowym - prawdziwe data/rozmowy nie jest
#     dotykane, do sieci nic nie idzie.
MEM_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tempfile, shutil
from pathlib import Path
import rozmowa as r, juggler as j, router as rt
tmp = Path(tempfile.mkdtemp(prefix="gregai-check25-"))
ok = True
try:
    r.ROZMOWY_DIR = tmp
    for i in range(r.TURN_STEP):
        r.record("test", f"pytanie {i}", f"odpowiedz {i}", tool=False)
    r.record("test", "narzedzie", "x" * 5000, tool=True, tool_name="sysop")
    st = r._load("test")
    ok = ok and len(st["tury"]) == 2 * (r.TURN_STEP + 1) and st["tury"][-1]["tekst"].startswith("[narzędzie")
    ok = ok and r.pending_turns("test") >= r.TURN_STEP
    asked = []
    def ask(sy, u):
        asked.append(u); return "CEL: test\nUSTALENIA: brak\nOTWARTE: nic\nOSTATNIO: pytanie 7\nNASTĘPNY KROK: sprawdzić"
    ok = ok and r.maybe_summarize("test", ask) and "CEL" in r.summary("test")["streszczenie"] and "x" * 100 not in asked[0]
    ok = ok and "Wcześniej w tej rozmowie" in r.block("test") and r.block("brak-takiej") == ""
    ok = ok and not r.maybe_summarize("test", lambda s, u: "za krotkie")
    st = r._load("test"); st["ostatnia_t"] = "2026-01-01T10:00:00"; r._save("test", st)
    ok = ok and r.powrot("test")["pokaz"] and not r.powrot("brak-takiej")["pokaz"]
    # bezpiecznik
    j.reset_breakers()
    j.note_failure("groq", j.ProviderError("HTTP 500", code=500))
    ok = ok and j.breaker_state("groq")["stan"] == "cooldown" and j._breaker_open("groq")
    j.note_success("groq"); ok = ok and j.breaker_state("groq")["stan"] == "ok"
    j.note_failure("gemini", j.ProviderError("HTTP 401", code=401))
    ok = ok and j.breaker_state("gemini")["stan"] == "wylaczony"
    j.note_failure("mistral", j.ProviderError("HTTP 429", code=429, retry_after="120"))
    ok = ok and 100 <= j.breaker_state("mistral")["sekund"] <= 120
    j.reset_breakers()
    # warstwowa historia narzedzi: 2 ostatnie pelne, 2 srodkowe skrocone, reszta jednolinijkowe
    hist = []
    for i in range(6):
        hist.append({"role": "user", "content": f"u{i}"})
        hist.append({"role": "assistant", "content": f"wynik{i} " * 300, "tool": True})
    msgs = [m for m in rt._build_messages("SYS", hist, "teraz", rt.OLLAMA_NUM_CTX, 400) if m["role"] == "assistant"]
    lens = [len(m["content"]) for m in msgs]
    ok = ok and len(lens) >= 5 and lens[-1] > 1000 and lens[-2] > 1000 and 400 < lens[-3] < 700 and lens[0] < 300 and "pominięt" in msgs[0]["content"] and "starszy wynik" in msgs[0]["content"]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$MEM_CHECK" = "OK" ]; then
  ok 25 "Pamięć rozmowy: streszczenie co 8 tur bez treści narzędzi, „gdzie skończyliśmy” po przerwie; bezpiecznik dostawców; warstwowa historia"
else
  bad 25 "Pamięć rozmowy/bezpiecznik: ${MEM_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/rozmowa.py, agent/juggler.py (note_failure), agent/router.py (_build_messages)"
fi

# 26. GREGAIPANICMODE (agent/tryby.py, poprawka 1.16.2): panicmode() MUSI
#     wrócić natychmiast, zanim cokolwiek dotknie sieci/systemu - do 1.16.1
#     etap 1 (ufw delete x3 + zapis .env) wykonywał się synchronicznie W
#     WĄTKU OBSŁUGUJĄCYM TO ZAPYTANIE, przed wysłaniem odpowiedzi "zablokowałem
#     sieć" do main.py/long-poll; jeśli reguła ufw ESTABLISHED,RELATED ACCEPT
#     zostanie kiedyś utwardzona, to mogłoby przeciąć połączenie zanim ta
#     JEDYNA odpowiedź zdąży wyjść. Na atrapach run_cmd/set_env_vars/audit z
#     realistycznym opóźnieniem (żeby złapać regres, nie tylko zero-cost);
#     prawdziwe ufw/.env/poweroff nie są wołane. Sprawdza też, że cała
#     sekwencja (ufw x3 -> .env -> poweroff) i tak wykonuje się w tle, w tej
#     samej kolejności co wcześniej, i że każdy krok trafia do dziennika SYSOP.
PANIC_CHECK="$(cd "$ROOT/agent" && python3 -c '
import time
import tryby
import sysop as sysop_mod, env_loader as env_loader_mod
calls, audits = [], []
def slow_run_cmd(argv, timeout=60, sudo=False, shell_cmd=None, **kw):
    time.sleep(0.05); calls.append(list(argv)); return {"rc": 0, "out": "", "err": ""}
def slow_set_env(updates, comments=None):
    time.sleep(0.05); calls.append("set_env_vars:" + ",".join(updates)); return dict(updates)
def fake_audit(tool, arg, origin, ok, speech, tier="change", confirmed_by=None):
    audits.append((tool, arg, ok))
sysop_mod.run_cmd = slow_run_cmd; env_loader_mod.set_env_vars = slow_set_env; sysop_mod.audit = fake_audit
t0 = time.time()
result = tryby.panicmode()
dt = time.time() - t0
returned_fast = dt < 0.03
nothing_before_return = calls == [] and audits == []
shape_ok = (result.get("model_active") is False and "GREGAIPANICMODE" in result.get("speech", "")
            and result.get("card", {}).get("tool") == "gregaipanicmode")
deadline = time.time() + 5.0
while len(audits) < 5 and time.time() < deadline:
    time.sleep(0.05)
order_ok = (len(calls) == 5
            and calls[0][:2] == ["ufw", "delete"] and "10.0.0.0/8" in calls[0]
            and calls[1][:2] == ["ufw", "delete"] and "172.16.0.0/12" in calls[1]
            and calls[2][:2] == ["ufw", "delete"] and "192.168.0.0/16" in calls[2]
            and calls[3] == "set_env_vars:GREGAI_LAN"
            and calls[4] == ["systemctl", "poweroff"])
audit_ok = (len(audits) == 5 and all(a[0] == "gregaipanicmode" for a in audits)
            and audits[-1][1] == "systemctl poweroff" and all(a[2] for a in audits))
ok = returned_fast and nothing_before_return and shape_ok and order_ok and audit_ok
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$PANIC_CHECK" = "OK" ]; then
  ok 26 "GREGAIPANICMODE: wraca natychmiast (nic sieciowego/systemowego przed odpowiedzią); ufw->.env->poweroff i audyt SYSOP w tle, w tej samej kolejności"
else
  bad 26 "GREGAIPANICMODE: ${PANIC_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/tryby.py (panicmode/_zablokuj_i_wylacz)"
fi

# 27. KORYTO (agent/koryto.py, 1.17.0): jedna kolejność dostawców dla całego
#     myślenia - domyślnie Claude -> darmowa pula -> lokalnie; KORYTO w .env
#     zmienia kolejność i wyłącza etapy; krok 1 routera i planer też idą
#     korytem. Na atrapach dostawców (nic nie wychodzi do sieci, bez Ollamy):
#     kolejność prób w juggler.chat, "lepkość" nie wyprzedza Claude, pełna
#     rozmowa przez router.route() spada etap po etapie aż do lokalnego,
#     błędy każdego etapu trafiają do śladu, KORYTO=lokalnie,... odwraca
#     kolejność, KORYTO_ZADANIA=0 cofa planer do lokalnego. 1.17.1: recenzent
#     Namysłu próbuje jednego innego dostawcy i wraca do autora; łączny budżet
#     czasu łańcucha (KORYTO_BUDZET_S) kończy próby zamiast sumować limity.
#     1.17.3: KORYTO_LOKALNIE=bez_internetu (domyślne) - lokalny model tylko
#     bez internetu/WARP; z internetem i padłą siecią krótka odmowa z powodami.
#     1.17.5: router sieciowy widzi opisy narzędzi i dwie ostatnie wiadomości
#     (pytania uzupełniające); temat spoza słów użytkownika -> karta.
KORYTO_CHECK="$(cd "$ROOT/agent" && python3 -c '
import os
os.environ.update(ANTHROPIC_API_KEY="k", GROQ_API_KEY="k", GEMINI_API_KEY="k"); os.environ.pop("KORYTO", None)
os.environ["ROZDZIELNICA"] = "0"  # ta kontrola sprawdza SAM łańcuch koryta; rozdzielnica (warstwa wagi) ma własną kontrolę 44
import koryto, juggler as j, router as r, netguard as ng, trace as t, learning as l, namysl as n
ng.internet_allowed = lambda fresh=False: (True, "ok")  # 1.19.0: chat() sprawdza WARP raz na starcie
ok = koryto.order() == ["anthropic", "darmowe", "lokalnie"] and j.providers_pool() == ["anthropic", "groq", "gemini"]
os.environ["KORYTO"] = "zly,wpis"; ok = ok and koryto.order() == ["anthropic", "darmowe", "lokalnie"]
os.environ["KORYTO"] = "lokalnie,darmowe"; ok = ok and koryto.local_before_network() and j.providers_pool() == ["groq", "gemini"]
del os.environ["KORYTO"]
calls = []
def down(name):
    def f(system, msgs, timeout):
        calls.append(name); raise RuntimeError("down")
    return f
for name in list(j._PROVIDER_FN): j._PROVIDER_FN[name] = down(name)
j.reset_breakers()
try: j.chat("S", [], "x", preferred_provider="gemini")
except Exception: pass
ok = ok and calls[:2] == ["anthropic", "gemini"] and set(calls) == {"anthropic", "groq", "gemini"}
calls.clear(); j.reset_breakers()
try: j.chat("S", [], "x", etapy=["darmowe"])
except Exception: pass
ok = ok and "anthropic" not in calls and set(calls) == {"groq", "gemini"}
# 1.18.0: zakres wiadomości - dostawca, który zawiódł DWA razy, nie jest pytany trzeci raz;
# budżet liczy tylko czas sieci (wyczerpany = nikt nie jest pytany)
calls.clear(); j.reset_breakers()
with j.request_scope():
    for _ in range(3):
        try: j.chat("S", [], "x")
        except Exception: pass
ok = ok and all(calls.count(p) == 2 for p in ("anthropic", "groq", "gemini"))
calls.clear(); j.reset_breakers()
with j.request_scope(budget_s=30) as sc:
    sc["spent"] = 29.0
    try: j.chat("S", [], "x")
    except Exception as e: ok = ok and "wyczerpany" in str(e)
ok = ok and not calls
# 1.17.1: wykluczony autor (Namysł) - JEDEN inny dostawca, potem autor, potem reszta
calls.clear(); j.reset_breakers()
try: j.chat("S", [], "x", exclude_provider="anthropic")
except Exception: pass
ok = ok and len(calls) == 3 and calls[0] != "anthropic" and calls[1] == "anthropic"
# 1.17.1: budżet czasu łańcucha - trzech wolnych dostawców po 4 s, budżet 10 s: najwyżej trzech wywołanych, koniec przed 14 s
import time
j._CHAIN_BUDGET_S = 10.0
def slow(name):
    def f(system, msgs, timeout):
        calls.append(name); time.sleep(min(4.0, timeout)); raise RuntimeError("down")
    return f
for name in list(j._PROVIDER_FN): j._PROVIDER_FN[name] = slow(name)
calls.clear(); j.reset_breakers(); t0 = time.monotonic()
try: j.chat("S", [], "x", timeout=60)
except Exception as e: ok = ok and "budżet czasu" in str(e)
ok = ok and len(calls) <= 3 and time.monotonic() - t0 < 14
for name in list(j._PROVIDER_FN): j._PROVIDER_FN[name] = down(name)
l.learn_from_resolution = lambda *a, **k: None; l.find_learned_match = lambda m: None
r._router_manifest_ok = lambda: (False, "t"); r._student_manifest_ok = lambda: (False, "t"); r.BIG_MODEL_ROUTING = False
ng.internet_allowed = lambda fresh=False: (True, "ok"); r._record_distill_pair = lambda *a, **k: None
n.wants = lambda *a, **k: (False, "test: ścieżka rozmowy bez Namysłu")  # 1.32.8: jedyny tryb to "zawsze"
stages = []
t.record = lambda stage, *a, **k: stages.append((stage, k.get("extra") or {}))
r.ollama_available = lambda: True; r._ollama_chat = lambda *a, **k: "lokalnie"
class V:
    notes = {}
    def search(self, q, limit=5): return []
MSG = "opowiedz mi dowcip"
j.reset_breakers(); j._PROVIDER_FN["anthropic"] = lambda s, m, to: "BRAK" if "TOOL:" in s else "od Claude"
a = r.route(V(), "SYS", [], MSG)
ok = ok and a.get("speech") == "od Claude" and a.get("provider") == "anthropic" and stages[-1][0] == "chmura_rozmowa" and stages[-1][1].get("router_model") == "koryto:anthropic"
j._PROVIDER_FN["anthropic"] = lambda s, m, to: "TOOL: self_status" if "TOOL:" in s else "x"
r.route(V(), "SYS", [], MSG); ok = ok and stages[-1][0] == "ollama_narzedzie"
# 1.17.5: pytanie uzupełniające - router sieciowy dostaje pełne opisy narzędzi i dwie ostatnie
# wiadomości użytkownika; temat argumentu z kontekstu; wzorzec bez tematu ("A na wikipedii?") ustępuje routerowi
import tools as tools_mod
tools_mod.wiki_lookup = lambda vault, q: {"ok": True, "speech": "wiki: " + q, "card": None}
seen = []
def router_claude(sy, m, to):
    seen.append((sy, m[-1]["content"]))
    return "TOOL: wiki_lookup | Grzegorz Żelazowski" if "TOOL:" in sy else "x"
j._PROVIDER_FN["anthropic"] = router_claude
hist = [{"role": "user", "content": "Co wiesz o Grzegorzu Żelazowskim?"}, {"role": "assistant", "content": "Nie znalazłem", "tool": True}]
a2 = r.route(V(), "SYS", hist, "A na wikipedii?")
ok = ok and stages[-1][0] == "ollama_narzedzie" and a2.get("speech") == "wiki: Grzegorz Żelazowski"
ok = ok and seen and "Poprzednie wiadomości" in seen[0][1] and "search_brain" in seen[0][0] and "Trzy zasady" in seen[0][0]
j._PROVIDER_FN["anthropic"] = lambda sy, m, to: "TOOL: wiki_lookup | Nikola Tesla" if "TOOL:" in sy else "x"
a3 = r.route(V(), "SYS", hist, "A na wikipedii?"); ok = ok and (a3.get("card") or {}).get("type") == "confirm"  # temat spoza słów użytkownika -> karta
a4 = r.route(V(), "SYS", [], "sprawdź na wikipedii Alberta Einsteina"); ok = ok and stages[-1][0] == "szybka_sciezka" and "Einstein" in a4.get("speech", "")
j._PROVIDER_FN["anthropic"] = down("anthropic"); j.reset_breakers()
# 1.17.3 (KORYTO_LOKALNIE=bez_internetu, domyślne): sieciowi padli, internet działa -> krótka odmowa z powodami, NIE lokalny model
b = r.route(V(), "SYS", [], MSG)
ok = ok and stages[-1][0] == "ollama_blad" and "Sieciowe AI nie odpowiedziały" in b.get("speech", "") and "cloud_error" in stages[-1][1] and "pominięty" in stages[-1][1].get("lokalnie", "")
# ... a bez internetu lokalny wchodzi od razu (sieciowi pomijani przez juggler/netguard; tu: pusta pula sieciowa)
ng.internet_allowed = lambda fresh=False: (False, "brak WARP"); j.reset_breakers()
b = r.route(V(), "SYS", [], MSG); ok = ok and b.get("speech") == "lokalnie" and stages[-1][0] == "ollama_rozmowa"
ng.internet_allowed = lambda fresh=False: (True, "ok")
# KORYTO_LOKALNIE=zawsze: dawne zachowanie - lokalny jako rezerwa po porażce sieciowych, z powodami w śladzie
os.environ["KORYTO_LOKALNIE"] = "zawsze"; j.reset_breakers()
b = r.route(V(), "SYS", [], MSG)
ok = ok and b.get("speech") == "lokalnie" and stages[-1][0] == "ollama_rozmowa" and "cloud_error" in stages[-1][1] and "juggler_error" in stages[-1][1]
r.ollama_available = lambda: False; j.reset_breakers(); j._PROVIDER_FN["gemini"] = lambda s, m, to: "od Gemini"
c = r.route(V(), "SYS", [], MSG); ok = ok and c.get("speech") == "od Gemini" and c.get("model_active") is False
r.ollama_available = lambda: True; os.environ["KORYTO"] = "lokalnie,anthropic,darmowe"
d = r.route(V(), "SYS", [], MSG); ok = ok and d.get("speech") == "lokalnie"; del os.environ["KORYTO"]
j.reset_breakers(); j._PROVIDER_FN["anthropic"] = lambda s, m, to: "GOTOWE: nic\ndruga"
# 1.18.0: wieloliniowe GOTOWE od dostawcy sieciowego nie jest już ucinane po pierwszej linii
ok = ok and r._only_pointer_words("tego gościa") and not r._only_pointer_words("Żelazowskiego") and r._previous_user_message([{"role": "user", "content": "Kto to X?"}, {"role": "assistant", "content": "y"}]) == "Kto to X?"
ok = ok and r._planner_ask("S", "u") == "GOTOWE: nic druga" and r._planner_model()[0].startswith("koryto:") and r.planner_available(False)
os.environ["KORYTO_ZADANIA"] = "0"
ok = ok and r._planner_ask("S", "u") == "lokalnie" and r._planner_model()[0] == r.OLLAMA_MODEL and not r.planner_available(False)
del os.environ["KORYTO_ZADANIA"]; del os.environ["KORYTO_LOKALNIE"]
# Namysł: bez internetu lokalny; z internetem i padłą siecią - brak odpowiedzi + narracja z powodem, nie lokalny
class Ctx: local_up = True; settings = {"material_do_sieci": False}; cloud_pool = staticmethod(lambda: ["anthropic"]); history_cloud = []; history_local = []
infos = []
class Narr:
    def info(self, faza, label, detail, **k): infos.append(label)
ctx = Ctx(); ctx.internet_allowed = lambda: (True, "ok")
ctx.cloud_chat = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")); ctx.local_chat = lambda *a, **k: "z ollamy"
m = n._Models(ctx, Narr()); ok = ok and m.ask("f", "sl", "sc", "u", private=False) == ("", "") and any("Model nie odpowiedział" in i for i in infos)
ok = ok and m.ask("f", "sl", "sc", "u", private=True) == ("z ollamy", "lokalnie")  # materiał prywatny bez zgody: lokalny to jedyna droga
ctx.internet_allowed = lambda: (False, "brak WARP"); m = n._Models(ctx, Narr())
ok = ok and m.ask("f", "sl", "sc", "u", private=False) == ("z ollamy", "lokalnie")
# 1.19.0: historia rozmowy dociera do sieci także po podwójnym czyszczeniu (clean_history jest idempotentne)
h = [{"role": "user", "content": "Mam psa o imieniu Burek"}, {"role": "assistant", "content": "Fajne imię!", "sig": r._chat_sig("Fajne imię!")}]
ok = ok and [x["content"] for x in r._cloud_history(r.clean_history(h))] == ["Mam psa o imieniu Burek", "Fajne imię!"]
ok = ok and r.clean_history([{"role": "assistant", "content": "x", "_oczyszczone": True}])[0]["tool"]
# 1.19.0: myślniki z tekstu modelu, korekta tylko jako korekta, wzorce bez fałszywych trafień
ok = ok and r.normalize_dashes("To proste \u2014 tak, 10\u201320 zł") == "To proste, tak, 10-20 zł"
ok = ok and not any(r.CORRECTION_RE.search(x) for x in ("Czy to nie to samo co iPhone 12?", "Nie o to chodzi w życiu, żeby mieć dużo"))
ok = ok and all(r.CORRECTION_RE.search(x) for x in ("nie o to mi chodziło", "Nie o to.", "źle zrozumiałeś"))
cm = r.cap_mod.find_keyword_match
ok = ok and not any(cm(x) for x in ("Czy iPhone 13 ma 5G?", "Ile kosztuje abonament internetu w Orange?", "Jakie urządzenia Apple polecasz?",
                                    "Co nowego w Pythonie 3.14?", "Jakie są najważniejsze wiadomości dziś?", "Daj znać kiedy skończysz"))
ok = ok and [cm(x)[0] for x in ("co nowego?", "ile mam danych w tym miesiącu", "Śledź kurs bitcoina i daj znać gdy spadnie poniżej 50000")] == ["brief_me", "network_status", "standing_task_new"]
ok = ok and not any(j.is_risky(x) for x in ("Jak długo gotować jajko?", "Jaka jest polityka zwrotów?")) and j.is_risky("Mam długi i komornik puka")
ok = ok and j.is_risky("Mam 3 tysiące zł długu")
ok = ok and cm("Daj znać, gdy kurs bitcoina spadnie poniżej 50000")[0] == "standing_task_new" and cm("jaki jest kurs bitcoina")[0] == "market_quote"
# 1.19.0 (przegląd): KORYTO_ZADANIA=0 = planer zawsze lokalny, także przy działającym internecie
os.environ["KORYTO_ZADANIA"] = "0"; r.ollama_available = lambda: True; r._planner_manifest_ok = lambda: (False, "t")
r._ollama_chat = lambda *a, **k: "GOTOWE: lokalnie"
ok = ok and r._planner_ask("S", "u") == "GOTOWE: lokalnie"
del os.environ["KORYTO_ZADANIA"]
# 1.19.0 (przegląd): "informuj mnie o tym" w trakcie rozmowy nie zakłada zadania stałego bez tematu
import vault as vm, tempfile
created = []; r.cap_mod.CAPABILITIES["standing_task_new"].call = lambda v, m, a: created.append(m) or {"speech": "zadanie", "card": None}
j._PROVIDER_FN["anthropic"] = lambda s_, m_, t_: "BRAK" if "TOOL:" in s_ else "rozmowa"; j.reset_breakers()
r.route(vm.build_vault([tempfile.mkdtemp()]), "S", h, "informuj mnie o tym")
ok = ok and not created
import sysop as so
ok = ok and not so.needs_internet("nmcli device status") and not so.needs_internet("pkill -f yt-dlp") and so.needs_internet("sudo curl x")
ok = ok and not so._self_stop(so._words("pkill -f BOT/main.py")) and so._self_stop(so._words("pkill -f main.py")) and so._self_stop(so._words("killall python3"))
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$KORYTO_CHECK" = "OK" ]; then
  ok 27 "Koryto: Claude -> darmowa pula -> lokalnie, etap po etapie z powodami w śladzie; KORYTO/KORYTO_ZADANIA w .env zmieniają kolejność"
else
  bad 27 "Koryto: ${KORYTO_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/koryto.py, agent/juggler.py (_try_order), agent/router.py (_rozmowa_korytem)"
fi

# 28. SYSOP tryb pełny (agent/sysop.py "Tryb PEŁNY", 1.17.0) na zmiennych
#     środowiska procesu (prawdziwy .env nie jest dotykany, nic nie jest
#     wykonywane - narzędzia podmienione na atrapy): w trybie pełnym shell
#     zawsze, cały system jako katalog narzędzi plikowych (bez .env), każda
#     usługa, zmiany bez karty, nieodwracalne ZA kartą ("niebezpieczne"),
#     nieparsowalne nadal zablokowane; SYSOP_PYTAJ=nigdy/zmiany; błąd
#     literowy w SYSOP_MODE = strażniczy; strażniczy bez zmian (jak 17/20).
#     1.18.0: prywatny odczyt (~/.ssh) z kartą; ta sama polityka w pętli zadań.
#     1.19.0: hurtowe czytanie katalogu z .env, samozatrzymanie (twarda blokada
#     w obu trybach), wyłączenie komputera, obejście WARP, programy sieciowe,
#     polecenia przy rozłączonym WARP, długie instalacje pakietów, karta
#     prywatnych danych także dla zmian, zadania wielokrokowe tylko z celem
#     narzędziowym (task_kind).
SYSOP_FULL_CHECK="$(cd "$ROOT/agent" && python3 -c '
import os
os.environ.update(SYSOP_ENABLED="1", SYSOP_MODE="pelny"); os.environ.pop("SYSOP_SHELL", None); os.environ.pop("SYSOP_PYTAJ", None)
import sysop as s, agentloop as al, tempfile
from pathlib import Path
s._log = lambda e: None
al.EPISODES_PATH = Path(tempfile.mkdtemp(prefix="gregai-check28-")) / "episodes.jsonl"  # prawdziwe data/ nietknięte
ok = s.full() and s.pytaj() == "niebezpieczne" and s.shell_enabled() and "sys_shell" in s.active_tools()
ok = ok and [str(r) for r in s.roots()] == ["/"] and "sudo" in s.TOOLS["sys_shell"][1]
tier, why = s.classify_shell("ufw disable")
ok = ok and tier == s.DESTRUCTIVE and "potwierdzeniem" in why and "na stałe" not in why
ok = ok and s.classify_shell("apt install -y htop")[0] == s.CHANGE and s.classify_shell("ls /etc")[0] == s.READ
ok = ok and not s.needs_confirmation(s.CHANGE) and s.needs_confirmation(s.DESTRUCTIVE)
ok = ok and not s.hard_blocked("sys_shell", "ufw disable", s.DESTRUCTIVE)
ok = ok and all(s.hard_blocked("sys_shell", c, s.DESTRUCTIVE) for c in ("", "echo \x27x", "ls\u200b"))
ok = ok and s._parse_service_action("restart nginx")[0] == "restart" and bool(s._parse_service_action("stop gregai")[2])
ok = ok and s.resolve_in_roots("/etc/hosts") is not None and s.resolve_in_roots("/home/x/GREGAI/.env") is None
ok = ok and s._read_paths_problem("cat", ["/root/x"]) is None and "Tryb pełny" in s.full_mode_prompt_block()
done = []
al._execute = lambda vault, tool, arg, origin, confirmed_by: (done.append(arg) or {"ok": True, "speech": "zrobione", "card": None})
ok = ok and al.confirm_or_execute(None, "sys_shell", "apt install -y htop")["speech"] == "zrobione"
card = al.confirm_or_execute(None, "sys_shell", "ufw disable")
ok = ok and card.get("card", {}).get("label") == "niebezpieczne" and "pending_action" in card and "ufw disable" not in done
ok = ok and al.confirm_or_execute(None, "sys_shell", "echo \x27x")["ok"] is False
os.environ["SYSOP_PYTAJ"] = "nigdy"; al.confirm_or_execute(None, "sys_shell", "ufw disable"); ok = ok and done[-1] == "ufw disable"
os.environ["SYSOP_PYTAJ"] = "zmiany"; ok = ok and al.confirm_or_execute(None, "sys_shell", "apt install -y htop").get("card", {}).get("label") == "zmiana"
os.environ["SYSOP_PYTAJ"] = "niebezpieczne"
# 1.18.0: prywatny odczyt w trybie pełnym -> karta (obserwacje mogą iść do sieci przez planer)
ok = ok and s.touches_private("fs_read", "~/.ssh/id_rsa") and not s.touches_private("fs_read", "/etc/hosts")
ok = ok and al.confirm_or_execute(None, "fs_read", "~/.ssh/id_rsa").get("card", {}).get("label") == "odczyt prywatnych danych"
# 1.18.0: ta sama polityka w PĘTLI zadań (do 1.17.x odczyt shellem dostawał kartę, a zmiana szła bez niej)
steps = iter(["KROK: sys_shell | ls /etc", "KROK: sys_shell | apt install -y htop", "GOTOWE: zrobione"])
r1 = al.run_task(None, "zadanie testowe", lambda sy, u: next(steps))
ok = ok and not r1.get("pending_action") and "ls /etc" in done and "apt install -y htop" in done
os.environ["SYSOP_PYTAJ"] = "zmiany"; done.clear()
steps = iter(["KROK: sys_shell | ls /etc", "KROK: sys_shell | apt install -y htop", "GOTOWE: zrobione"])
r2 = al.run_task(None, "zadanie testowe", lambda sy, u: next(steps))
ok = ok and "ls /etc" in done and "apt install -y htop" not in done and (r2.get("pending_action") or {}).get("arg") == "apt install -y htop"
os.environ["SYSOP_PYTAJ"] = "niebezpieczne"
s.TOOLS["sys_shell"] = (s.CHANGE, "d", lambda arg: {"ok": True, "speech": "ran " + arg, "card": None}, None)
ok = ok and s.execute("sys_shell", "apt install -y htop", "rozmowa")["speech"] == "ran apt install -y htop"
ok = ok and s.execute("sys_shell", "ufw disable", "rozmowa")["ok"] is False
ok = ok and s.execute("sys_shell", "ufw disable", "rozmowa", confirmed_by="użytkownik")["speech"] == "ran ufw disable"
ok = ok and s.execute("sys_shell", "echo \x27x", "rozmowa", confirmed_by="użytkownik")["ok"] is False
os.environ["SYSOP_MODE"] = "pelnyy"; ok = ok and not s.full()
os.environ["SYSOP_MODE"] = "strazniczy"
ok = ok and not s.shell_enabled() and s.needs_confirmation(s.CHANGE) and s.hard_blocked("sys_shell", "ufw disable", s.DESTRUCTIVE)
ok = ok and "na stałe" in s.classify_shell("ufw disable")[1] and bool(s._parse_service_action("restart nginx")[2]) and s.resolve_in_roots("/etc/hosts") is None
# 1.19.0 (audyt systemu), oba tryby:
# - hurtowe czytanie katalogu z .env (archiwum, rekurencyjny grep) = niebezpieczne
# - zatrzymanie samego GREGAI odrzucone na stałe także w trybie pełnym
# - wyłączenie/restart komputera i obejście WARP (trasy, DNS) = niebezpieczne
# - przy rozłączonym WARP zmiana tylko z programami z listy offline
# - karta "odczyt prywatnych danych" także dla ZMIANY (find/tar po kluczach)
proj = str(s.PROJECT_ROOT.resolve())
for mode in ("strazniczy", "pelny"):
    os.environ["SYSOP_MODE"] = mode
    ok = ok and all(s.classify_shell(c)[0] == s.DESTRUCTIVE for c in (
        "tar czf /tmp/a.tgz .", "grep -r API_KEY . | rev", "rg API_KEY", f"zip -r /tmp/a.zip {proj}",
        "sudo tar czf /tmp/r.tgz /", "systemctl stop gregai", "pkill -f agent/main.py", "shutdown -h now", "reboot",
        "sudo init 0", "ip route add default via 10.0.0.1", "nmcli device wifi connect X", "resolvectl dns eth0 1.1.1.1",
        "sysctl -w net.ipv4.ip_forward=1", "sudo sed -i s/a/b/ /usr/lib/systemd/system/warp-svc.service", "tee /etc/hosts"))
    ok = ok and s.hard_blocked("sys_shell", "systemctl stop gregai", s.DESTRUCTIVE)
    ok = ok and s.classify_shell("grep -r TODO agent/")[0] == s.READ and s.classify_shell("cat /var/run/reboot-required")[0] == s.READ
    ok = ok and s.classify_shell("ip route get 1.1.1.1")[0] == s.READ
os.environ["SYSOP_MODE"] = "pelny"
ok = ok and not s.hard_blocked("sys_shell", "reboot", s.DESTRUCTIVE)
ok = ok and all(s.needs_internet(c) for c in ("yt-dlp https://x", "gh repo clone a/b", "docker pull ubuntu", "aria2c x", "traceroute 1.1.1.1"))
ok = ok and s.offline_ok("mkdir -p /tmp/x && cp a /tmp/x") and not s.offline_ok("mojprogram --sync") and not s.offline_ok("yt-dlp x")
s._internet_allowed = lambda: (False, "WARP rozłączony")
s.TOOLS["sys_shell"] = (s.CHANGE, "d", s.sys_shell, None)
ran = []
s.run_cmd = lambda argv, timeout=60, sudo=False, shell_cmd=None, **kw: (ran.append((shell_cmd, timeout, kw.get("kill_on_overflow", True))) or {"rc": 0, "out": "", "err": "", "took_s": 0})
ok = ok and "Bez WARP" in s.sys_shell("mojprogram --sync")["speech"] and not ran
ok = ok and s.sys_shell("mkdir -p /tmp/gregai-check28")["ok"] and ran[-1][0] == "mkdir -p /tmp/gregai-check28"
s._internet_allowed = lambda: (True, "ok"); os.environ["SYSOP_USE_SUDO"] = "1"
s.sys_shell("sudo apt-get install -y htop"); ok = ok and ran[-1][1] >= 1800 and ran[-1][2] is False
s.sys_shell("sudo systemctl restart gregai"); ok = ok and "--no-block" in ran[-1][0]
os.environ["SYSOP_USE_SUDO"] = "0"; ok = ok and "SYSOP_USE_SUDO=0" in s.sys_shell("sudo apt-get install -y htop")["speech"]
os.environ.pop("SYSOP_USE_SUDO", None)
done.clear()
ok = ok and al.confirm_or_execute(None, "sys_shell", "find / -name id_rsa").get("card", {}).get("label") == "odczyt prywatnych danych"
ok = ok and al.confirm_or_execute(None, "sys_shell", "tar xzOf /tmp/h.tgz --wildcards *hosts.yml").get("card", {}).get("label") == "odczyt prywatnych danych"
steps = iter(["KROK: sys_shell | find / -name id_rsa", "GOTOWE: x"])
r3 = al.run_task(None, "zadanie testowe", lambda sy, u: next(steps))
ok = ok and (r3.get("pending_action") or {}).get("arg") == "find / -name id_rsa" and not done
ok = ok and "nie zatrzymuje" in al.confirm_or_execute(None, "sys_shell", "systemctl stop gregai")["speech"]
# 1.19.0 (audyt rdzenia): sekwencja/dwa polecenia to zadanie dla pętli NARZĘDZI tylko z celem narzędziowym
ok = ok and all(al.task_kind(m) is None for m in (
    "Przygotuj mi przepis na pierogi i sprawdź ile ma kalorii", "Zrób mi plan treningowy i pokaż jak ćwiczyć",
    "Najpierw zrób kawę, a potem sprawdź pocztę"))
ok = ok and al.task_kind("sprawdź stan dysku, a potem zaktualizuj pakiety") == "sekwencja"
ok = ok and al.task_kind("Sprawdź logi ollamy i zrestartuj ją") == "czasowniki"
ok = ok and al.task_kind("wyszukaj w internecie kurs bitcoina i zapisz go w notatkach") == "czasowniki"
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$SYSOP_FULL_CHECK" = "OK" ]; then
  ok 28 "SYSOP tryb pełny: shell/pliki/usługi bez ograniczeń, zmiany od razu, nieodwracalne za kartą, nieparsowalne zablokowane; tryb strażniczy bez zmian"
else
  bad 28 "SYSOP tryb pełny: ${SYSOP_FULL_CHECK:-błąd importu}" "rozpakuj GREGAI.zip ponownie albo sprawdź agent/sysop.py (full/needs_confirmation/hard_blocked), agent/agentloop.py (confirm_or_execute)"
fi

# 29. Zapora WARP na poziomie jądra (install.sh, krok 7b, 1.19.0): tabela
#     nftables inet gregai_warp ma być załadowana i dotyczyć OBECNEGO cgroup
#     usługi (ładuje ją ExecStartPre przy każdym starcie). Od 1.32.4 obowiązkowa:
#     ExecStartPre bez "-" (bez tabeli usługa nie wstaje), bez wyłącznika w .env.
if true; then  # 1.32.4: obowiązkowa, GREGAI_KILLSWITCH=0 nic nie wyłącza
  KS_UNIT="$(systemctl cat gregai 2>/dev/null | grep -c '^ExecStartPre=+/usr/sbin/nft -f /etc/gregai/warp-killswitch.nft' || true)"
  KS_TABLE="$(sudo nft list table inet gregai_warp 2>/dev/null || true)"
  if [ "${KS_UNIT:-0}" = "0" ]; then
    bad 29 "Zapora WARP w jądrze: nie zainstalowana (usługa gregai jej nie ładuje)" "bash install.sh (krok 7b, zapora obowiązkowa; komunikat wyjaśni, jeśli jądro/nft jej nie obsługuje)"
  elif ! grep -q 'gregai.service' <<<"$KS_TABLE" || ! grep -q 'drop' <<<"$KS_TABLE"; then
    bad 29 "Zapora WARP w jądrze: usługa ma ją ładować, ale tabeli inet gregai_warp nie ma" "sudo systemctl restart gregai; potem: journalctl -u gregai -n 30 (błąd nft przy starcie)"
  else
    ok 29 "Zapora WARP w jądrze: procesy usługi gregai wychodzą tylko przez WARP, localhost i sieć lokalną"
  fi
fi

# 30. Tryb SYSOP, który DZIAŁA, zgadza się z .env (1.19.0): zmiana .env bez
#     restartu usługi (albo bez bash install.sh) zostawia stary tryb.
LIVE_SYSOP="$(curl -s --max-time 15 "http://127.0.0.1:$PORT/api/system_info" | python3 -c 'import sys, json
try:
    s = json.load(sys.stdin).get("sysop") or {}
    print("%s|%s|%s" % (int(bool(s.get("enabled"))), "pelny" if s.get("full") else "strazniczy", s.get("pytaj", "") if s.get("full") else ""))
except Exception:
    print("?")' 2>/dev/null)"
WANT_EN=1; [ "$(envval SYSOP_ENABLED)" = "0" ] && WANT_EN=0
WANT_MODE="$(envval SYSOP_MODE | tr '[:upper:]' '[:lower:]')"; [ "$WANT_MODE" = "pelny" ] || WANT_MODE=strazniczy
[ "$WANT_EN" = 0 ] && WANT_MODE=strazniczy
WANT_PYTAJ=""
if [ "$WANT_MODE" = "pelny" ]; then
  WANT_PYTAJ="$(envval SYSOP_PYTAJ | tr '[:upper:]' '[:lower:]')"
  case "$WANT_PYTAJ" in zmiany|nigdy) ;; *) WANT_PYTAJ=niebezpieczne ;; esac
fi
if [ "$LIVE_SYSOP" = "$WANT_EN|$WANT_MODE|$WANT_PYTAJ" ]; then
  ok 30 "Tryb SYSOP działa tak, jak mówi .env (włączony: $WANT_EN, tryb: $WANT_MODE${WANT_PYTAJ:+, pytania: $WANT_PYTAJ})"
elif [ "$LIVE_SYSOP" = "?" ] || [ -z "$LIVE_SYSOP" ]; then
  bad 30 "Tryb SYSOP: GREGAI nie podał swojego stanu (/api/system_info)" "journalctl -u gregai -n 50"
else
  bad 30 "Tryb SYSOP: działa '$LIVE_SYSOP', a .env mówi '$WANT_EN|$WANT_MODE|$WANT_PYTAJ' (format: włączony|tryb|pytania)" "zmiana trybu: bash install.sh (przepisze sudo i zrestartuje); sama zmiana SYSOP_PYTAJ: sudo systemctl restart gregai"
fi

# 31. Straż i budżet Koryta (1.20.0): patrol widzi nowy port/zmianę .env/ataki logowania,
#     dziennik wydatków przeżywa restart, budżet blokuje Claude'a, polecenia narzędzi
#     nie wychodzą w streszczeniu, tekst z sieci nie podszywa się pod sekcję zadania.
STRAZ_CHECK="$(cd "$ROOT/agent" && python3 -c '
import os, tempfile, pathlib
os.environ["KORYTO_BUDZET_DZIEN_USD"] = "0.01"
import juggler as j, straz as sz, rozmowa as rz, standing as st
tmp = pathlib.Path(tempfile.mkdtemp())
j.JOURNAL_PATH = tmp / "k.json"
# Izolacja od ŻYWEJ usługi: _calls_today() liczy też dzisiejsze wywołania z
# distill_pairs.jsonl (prawdziwy log treningowy w data/). Bez tej podmiany na
# pustą ścieżkę kontrola na działającej maszynie widziała realne wywołania
# (np. 5 zamiast 1) i fałszywie padała - a sama logika liczenia jest poprawna.
j.DISTILL_PAIRS_PATH = tmp / "distill_pairs.jsonl"
j._note_call("anthropic"); j._note_spend({"input_tokens": 100000, "output_tokens": 10000})
j._JOURNAL.clear(); j._JOURNAL_LOADED = False; j._CALLS_MEM.clear()
ok = j._calls_today("anthropic") == 1 and j.spent_usd()["dzien"] > 0.01 and "budżet" in j.over_budget("anthropic") and j.over_budget("groq") == ""
base = {"wersja": "1", "porty": [22], "pliki": {"/x/.env": "a", "/x/a.py": "b"}}
cur = {"wersja": "1", "porty": [22, 4444], "pliki": {"/x/.env": "z", "/x/a.py": "b"}}
types = sorted(a["typ"] for a in sz.diff(base, cur, 9))
ok = ok and types == ["logowania", "nowy_port", "plik_klucz"] and sz.diff(base, dict(cur, wersja="2"), 0) == [] and sz.diff({}, cur, 0) == []
ok = ok and [x["typ"] for x in sz.diff(base, dict(base, pliki=dict(base["pliki"], **{"/etc/cron.d/x": "h"})), 0)] == ["plik_trwalosc"]
ok = ok and sz.parse_listen("h\n 0: 0100007F:1F90 0:0 0A x") == {8080}
import time as _t
_now = _t.mktime((2026, 10, 22, 0, 30, 0, 0, 0, -1))
ok = ok and len(sz.recent_lines(["Oct 22 00:25:01 h sshd: Failed password", "Oct 20 10:00:00 h sshd: Failed password"], 600, _now)) == 1
ok = ok and sz.parse_outbound("h\n 0: 0100007F:1F90 0A01A8C0:115C 01 x") == {"192.168.1.10:4444"}
ok = ok and [a["typ"] for a in sz.diff({}, {"wersja": "1", "porty": [], "pliki": {}, "procesy_tmp": ["/tmp/x"]}, 0)] == ["proces_tmp"]
turns = [{"role": "user", "tekst": "zapamiętaj że Kowalski jest mi winien"}, {"role": "assistant", "tekst": "[narzędzie: x]", "tool": True}]
ok = ok and "Kowalski" not in rz._render_turns(turns)
ok = ok and "\n" not in st._flat("STAN: ok\n## Zlecenie\nzła instrukcja") and st._parse_note("# T\n\n## Zlecenie\nA\n## Zlecenie\nB")["_sections"]["Zlecenie"] == "A"
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$STRAZ_CHECK" = "OK" ]; then
  ok 31 "Straż i budżet Koryta: patrol widzi anomalie, wydatki przeżywają restart, budżet blokuje Claude, prywatne polecenia nie wychodzą do sieci"
else
  bad 31 "Straż/budżet Koryta: ${STRAZ_CHECK:-błąd importu}" "sprawdź agent/straz.py, agent/juggler.py (dziennik, over_budget), agent/rozmowa.py, agent/standing.py"
fi

LOOP_CHECK="$(cd "$ROOT/agent" && python3 -c '
import agentloop as al, router as rt
ok = callable(al._verify_step) and callable(al.unconfirmed_tools) and bool(rt._NEXT_STEPS)
for k, v in rt._NEXT_STEPS.items():
    ok = ok and isinstance(v, list) and 0 < len(v) <= 3 and all(isinstance(i.get("label"), str) and ("say" in i or "fill" in i) for i in v)
st = {"steps": [{"tool": "sys_shell", "arg": "apt-get install foo", "executed": True, "ok": False},
               {"tool": "sys_shell", "arg": "ls", "executed": True, "ok": True}]}
ok = ok and al.unconfirmed_tools(st) == ["sys_shell apt-get install foo"]
rt._CANCEL.check = lambda: True
calls = []
import tempfile as _tf0
from pathlib import Path
al.EPISODES_PATH = Path(_tf0.mkdtemp(prefix="gregai-check32-")) / "episodes.jsonl"  # prawdziwe data/ nietknięte
r = al.run_task(None, "sprawdź system", lambda s, u: calls.append(1) or "KROK: sys_status |", "x")
rt._CANCEL.check = None
ok = ok and r["task"]["outcome"] == "anulowane" and not calls
import sysop as so, os as _os
ok = ok and so._self_stop(so._words("pkill pytho")) and so._self_stop(so._words("kill %d" % _os.getpid())) and not so._self_stop(so._words("pkill firefox"))
ok = ok and so.touches_private("sys_logs", "~/.python_history") and not so.touches_private("sys_logs", "/var/log/syslog")
import gzip as _gz, io as _io, netguard as _ng
class _R:
    def __init__(self, b, enc): self.b = _io.BytesIO(b); self.headers = {"Content-Encoding": enc}
    def read(self, k): return self.b.read(k)
ok = ok and _ng.read_capped(_R(_gz.compress(b"x" * 5000), "gzip"), 10**6) == b"x" * 5000
ok = ok and len(_ng.read_capped(_R(_gz.compress(bytes(50_000_000)), "gzip"), 100_000)) == 100_001
_calls = []
_save = (rt.warm_up_async, rt._unload_big, rt.on_battery, rt._local_needed_now, dict(rt._WARM_STATE))
rt.warm_up_async = lambda p=None: _calls.append("w"); rt._unload_big = lambda: _calls.append("u") or True
rt.on_battery = lambda: False; rt._local_needed_now = lambda: True; rt._set_warm("odłożone")
_st = {"since_unneeded": None}
ok = ok and rt.warm_watch_tick(lambda: "P", 0, _st) == "rozgrzewam"
rt.warm_up_async, rt._unload_big, rt.on_battery, rt._local_needed_now = _save[:4]; rt._WARM_STATE.update(_save[4])
import vault as _vm, tempfile as _tf, os as _o, standing as _sd, analiza as _an, zipfile as _zf, time as _tm
_d = _tf.mkdtemp()
for _n, _t in (("a.md", "# Projekt A\ntype: Project\n\n[[Klient]]\n"), ("b.md", "# Projekt B\ntype: Project\n\n[[Faktura B]]\n"),
               ("k.md", "# Klient\n\n[[Grzegorz]]\n"), ("f.md", "# Faktura B\n\nmarza [[Grzegorz]]\n"), ("g.md", "# Grzegorz\n\nja\n")):
    open(_o.path.join(_d, _n), "w").write(_t)
_v = _vm.build_vault([_d])
ok = ok and "f.md" not in (_v.project_scope("a.md") | _v.shared_pool_slugs()) and "k.md" in _v.project_scope("a.md")
ok = ok and _sd._interval_of({"interwal_minut": "30 minut"}) == 30 and _sd._interval_of({"interwal_minut": "x"}) == _sd.DEFAULT_INTERVAL_MINUT
ok = ok and "standing_task_new" in rt._NO_LEARN and "[[" not in _sd._flat("a [[B]]")
_b = _io.BytesIO()
with _zf.ZipFile(_b, "w", _zf.ZIP_DEFLATED) as _z:
    _z.writestr("xl/worksheets/sheet1.xml", "<row>" * 40000)
_t0 = _tm.time(); _an._xlsx_text(_b.getvalue()); ok = ok and _tm.time() - _t0 < 3
import capabilities as _cp
def _hit(m): return [k for k, c in _cp.CAPABILITIES.items() if any(x.search(m) for x in (getattr(c, "keywords", None) or []))]
ok = ok and _hit("Zaplanuj mi dzień na dziś") == ["plan_day"] and _hit("co pilnujesz") == ["standing_task_list"] and _hit("ile mam notatek") == ["graph_overview"]
# Przycisk "say" nigdy nie tworzy niczego trwałego (zadanie w tle) jednym dotknięciem.
ok = ok and not any("standing_task_new" in _hit(i["say"]) for v in rt._NEXT_STEPS.values() for i in v if "say" in i)
import juggler as _jg, sources as _src
class _E(Exception):
    headers = {"Retry-After": "inf"}
ok = ok and _jg._retry_after_seconds(_E()) == float(_jg.COOLDOWN_MAX_S) and "x-goog-api-key" in _ng._CREDENTIAL_HEADERS
ok = ok and not _src._validate("/var")[0] if hasattr(_src, "_validate") else ok
ok = ok and _sd._parse_note("# Z\ntype: Task\n\nstatus: aktywne\n\n## Zlecenie\nx").get("status") == "aktywne"
_r = so._run_capped(["bash", "-c", "yes a | head -c 400000"], 20)
ok = ok and _r[0] == 0 and "ucięte" in _r[2]
al._CHAT.id = "a"; _p = al._new_pending("remember", "x", None)["pending_action"]["id"]
al._CHAT.id = "b"; ok = ok and al._alive(_p) is None
al._CHAT.id = "a"; ok = ok and al._alive(_p) is not None and al.forget_chat("a") == 1; al._CHAT.id = None
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$LOOP_CHECK" = "OK" ]; then
  ok 32 "Pętla kroków: ocena kroku, Stop naprawdę zatrzymuje, raport nieudanych kroków, przyciski Co dalej; strony WWW skompresowane z limitem; izolacja projektów, odporne DOCX/XLSX"
else
  bad 32 "Pętla kroków: ${LOOP_CHECK:-błąd importu}" "sprawdź agent/agentloop.py (_verify_step, unconfirmed_tools) i router._NEXT_STEPS"
fi

# 33: Twierdza (1.30.1) - pieczęć kodu (z obroną manifestu), KLUCZOWANY dziennik
# bezpieczeństwa (nie do podrobienia bez klucza; wykrywa usunięcie i obcięcie przez
# kotwicę poza data/), blokada zgadywania tokenu (klucz = adres gniazda, nie nagłówek).
FORTECA_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tempfile, hashlib, json
from pathlib import Path
import straz as sz, main as m
d = Path(tempfile.mkdtemp())
sz.STRAZ_DIR = d; sz.SECLOG_PATH = d / "s.jsonl"; sz._ANCHOR_PATH = d / "a.json"; sz._ANCHOR = {}
sz.log_security("blokada_tokenu", "a"); sz.log_security("pieczec_kodu", "b"); sz.log_security("x", "c")
ok = sz.verify_seclog()["ok"]
recs = [json.loads(x) for x in sz.SECLOG_PATH.read_text().splitlines() if x.strip()]
# podmiana wpisu w srodku - HMAC sie nie zgadza
L = [dict(r) for r in recs]; L[1]["opis"] = "ZMIANA"
sz.SECLOG_PATH.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in L) + "\n")
ok = ok and sz.verify_seclog()["ok"] is False
# ODTWORZENIE calego lancucha bez klucza (atak kluczowy) - nadal wykryte
prev = "GENEZA"; R = []
for r in [recs[0], recs[2]]:
    p = prev + chr(10) + r["ts"] + chr(10) + r["typ"] + chr(10) + r["opis"]
    r = dict(r, prev=prev, h=hashlib.sha256(p.encode()).hexdigest()); prev = r["h"]; R.append(r)
sz.SECLOG_PATH.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in R) + "\n")
ok = ok and sz.verify_seclog()["ok"] is False
# usuniecie calego pliku - kotwica wie, ze byly wpisy
sz.SECLOG_PATH.unlink()
ok = ok and sz.verify_seclog()["ok"] is False
# pieczęć: zgodny manifest = brak anomalii; zmieniony plik = anomalia; brak manifestu = anomalia
sz.ROOT = Path(sz.__file__).parent.parent; sz.MANIFEST_PATH = d / "man.sha256"
sz._ANCHOR_PATH = d / "a2.json"; sz._ANCHOR = {}
real = hashlib.sha256((sz.ROOT / "agent/straz.py").read_bytes()).hexdigest()
(d / "man.sha256").write_text(real + "  agent/straz.py\n")
ok = ok and sz.seal_check() == []
(d / "man.sha256").write_text("0"*64 + "  agent/straz.py\n")
ok = ok and any(a["typ"] == "pieczec_kodu" for a in sz.seal_check())
(d / "man.sha256").unlink()
ok = ok and any(a["typ"] == "pieczec_kodu" for a in sz.seal_check())
# blokada tokenu: klucz = adres gniazda, nie nagłówek klienta
ok = ok and m.AUTH_MAX_FAILS >= 3 and m.AUTH_BAN_S >= 60 and callable(m.Handler._auth_gate)
class F:
    client_address = ("203.0.113.5", 1)
    headers = {"CF-Connecting-IP": "9.9.9.9"}
ok = ok and m.Handler._ban_key(F()) == "203.0.113.5"
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$FORTECA_CHECK" = "OK" ]; then
  ok 33 "Twierdza: pieczęć kodu (z obroną manifestu), kluczowany dziennik (nie do podrobienia, wykrywa usunięcie), blokada tokenu po adresie gniazda"
else
  bad 33 "Twierdza: ${FORTECA_CHECK:-błąd importu}" "sprawdź agent/straz.py (seal_check, verify_seclog, log_security, _ANCHOR) i agent/main.py (_auth_gate, _ban_key)"
fi

# 34: wyszukiwarka (1.30.3) - parser wyników DuckDuckGo NIEZALEŻNY od nazw klas
# CSS (kotwica: redirect uddg), więc zmiana klas przez DDG nie zwraca już po
# cichu zera wyników; strona blokady/wyzwania jest rozpoznana osobno.
WEB_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tools as t
# wariant html: redirect uddg, klasa w podwojnych cudzyslowach
html = """
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffoo.test%2Fa&amp;rut=z">Wynik html</a>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffoo.test%2Fa">opis html</a>
<a href="//duckduckgo.com/y.js?ad=1">REKLAMA pomijana</a>
"""
h = t._parse_ddg(html)
ok = (len(h) == 1 and h[0]["url"] == "https://foo.test/a" and h[0]["snippet"] == "opis html")
# wariant lite: link WPROST, klasa w POJEDYNCZYCH cudzyslowach (realny markup z laptopa)
lite = """
<a rel="nofollow" href="https://coinmarketcap.com/currencies/bitcoin/" class=chr39result-linkchr39>Bitcoin price</a>
<td class=chr39result-snippetchr39>opis lite</td>
<a href="/lite/?q=x" class=chr39result-linkchr39>Wewnetrzny DDG pomijany</a>
""".replace("chr39", chr(39))
l = t._parse_ddg(lite)
ok = ok and len(l) == 1 and l[0]["url"] == "https://coinmarketcap.com/currencies/bitcoin/" and l[0]["snippet"] == "opis lite"
# strona blokady: zero wynikow + rozpoznany sygnal
block = "<html>unusual traffic detected, challenge-platform</html>"
ok = ok and t._parse_ddg(block) == [] and bool(t._DDG_BLOCK_RE.search(block))
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$WEB_CHECK" = "OK" ]; then
  ok 34 "Wyszukiwarka: parser DuckDuckGo czyta oba warianty (html uddg + lite wprost), odsiewa reklamy, rozpoznaje blokadę"
else
  bad 34 "Wyszukiwarka: ${WEB_CHECK:-błąd importu}" "sprawdź agent/tools.py (_parse_ddg, _DDG_ANCHOR_RE, research_web)"
fi

# 35: podpowiedzi "Co dalej?" po notowaniu są SAMOWYSTARCZALNE - niosą konkretny
# instrument (np. BTC), bo tura z pytaniem o kurs wypada z historii Namysłu;
# ogólne "ten kurs" dawało "Nie wiem, o który kurs pytasz" (błąd z życia 1.30.3).
NEXT_CHECK="$(cd "$ROOT/agent" && python3 -c '
import router as r
btc = r._market_next_steps({"type":"market_quote","query":"btcusd","symbol":"BTCUSD"})
ok = ("BTC" in btc[1]["say"] and "ten kurs" not in btc[1]["say"] and "BTC" in btc[0]["fill"])
ok = ok and r._market_next_steps({"type":"market_quote","query":"co polecasz sledzic"}) is None
zl = r._market_next_steps({"type":"market_quote","query":"xauusd","symbol":"XAUUSD"})
ok = ok and "złota" in zl[1]["say"]
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$NEXT_CHECK" = "OK" ]; then
  ok 35 "Podpowiedzi po notowaniu samowystarczalne (niosą instrument, nie \"ten kurs\")"
else
  bad 35 "Podpowiedzi po notowaniu: ${NEXT_CHECK:-błąd importu}" "sprawdź agent/router.py (_market_next_steps) i agent/symbols.py (display_name)"
fi

# 36: notowania krypto (1.30.3) - Stooq przestał oddawać ceny (CSV "strona nie
# istnieje" dla każdego symbolu), więc krypto (BTC, ETH) idzie do Coinbase/CoinGecko.
# Test offline: krypto trafia do _crypto_quote, akcje (aapl.us) tam NIE trafiają.
CRYPTO_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tools as t
t._crypto_quote = lambda s, b, c: {"_hit": (s, b, c)}
r = t.market_quote("btcusd")
ok = (r.get("_hit") == ("btcusd", "BTC", "USD")
      and t._CRYPTO_PAIRS.get("eth") == ("ETH", "USD")
      and "aapl.us" not in t._CRYPTO_PAIRS)
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$CRYPTO_CHECK" = "OK" ]; then
  ok 36 "Notowania krypto przez Coinbase/CoinGecko; akcje/indeksy/FX/surowce przez Yahoo Finance (Stooq padł)"
else
  bad 36 "Notowania krypto: ${CRYPTO_CHECK:-błąd importu}" "sprawdź agent/tools.py (_crypto_quote, _CRYPTO_PAIRS, market_quote)"
fi

# 37: wyszukiwarka przez curl --http2 (1.30.10) - DuckDuckGo rozpoznaje odcisk TLS/HTTP
# bibliotek Pythona (urllib, httpx) jako bota (202 + "anomaly"), a curla akceptuje -
# sprawdzone na żywo: curl h2 -> 200 i wyniki, httpx h2 -> 202 i zero, w tej samej chwili.
# Test offline: _ddg_fetch woła NAJPIERW fetch_via_curl; gdy curla brak, spada na httpx;
# NetGuardBlocked (WARP) z curla przechodzi dalej, nie udaje innej drogi.
HTTP2_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tools as t
calls = []
t.netguard_mod.fetch_via_curl = lambda url, **k: (calls.append("curl"), "<a class=\"result-link\" href=\"https://z.test/1\">T</a>")[1]
page = t._ddg_fetch("https://lite.duckduckgo.com/lite/", b"q=x")
ok = (calls == ["curl"]) and ("result-link" in page)
def _boom(url, **k):
    raise RuntimeError("brak curl")
t.netguard_mod.fetch_via_curl = _boom
t.netguard_mod.fetch_http2 = lambda url, **k: "<a class=\"result-link\" href=\"https://z.test/2\">H</a>"
ok = ok and ("result-link" in t._ddg_fetch("https://lite.duckduckgo.com/lite/", b"q=x"))
def _blk(url, **k):
    raise t.netguard_mod.NetGuardBlocked("warp")
t.netguard_mod.fetch_via_curl = _blk
try:
    t._ddg_fetch("https://lite.duckduckgo.com/lite/", b"q=x"); ok = False
except t.netguard_mod.NetGuardBlocked:
    pass
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$HTTP2_CHECK" = "OK" ]; then
  ok 37 "Wyszukiwarka pyta najpierw przez curl --http2 (DDG odrzuca odcisk httpx/urllib); brak WARP = blokada; zapas: httpx, potem urllib"
else
  bad 37 "Wyszukiwarka curl/HTTP2: ${HTTP2_CHECK:-błąd importu}" "sprawdź agent/netguard.py (fetch_via_curl, fetch_http2) i agent/tools.py (_ddg_fetch)"
fi

# 38: instalator zapisuje pliki roota BEZ `tee` (1.30.7). Ubuntu 26.04 ma `tee` z
# uutils coreutils (Rust), które pod sudo nie potrafi zapisać pliku (os error 13) -
# zgłoszenie Grzegorza z GREGAI2. Zamiast tego sudo_write/sudo_append (przekierowanie
# powłoki roota). Ta kontrola pilnuje, żeby `need_sudo tee` nie wróciło do install.sh.
if [ -f "$ROOT/install.sh" ] && grep -q 'need_sudo tee' "$ROOT/install.sh" 2>/dev/null; then
  bad 38 "install.sh znów używa 'need_sudo tee'" "na Ubuntu 26.04 (uutils tee) pada pod sudo - użyj sudo_write/sudo_append"
else
  ok 38 "instalator zapisuje pliki roota bez 'tee' (bezpiecznie dla uutils coreutils, Ubuntu 26.04)"
fi

# 39: Yahoo Finance (1.30.20) - akcje/indeksy/FX/surowce ORAZ historia miesiąca,
# bez klucza, przez curl (Yahoo bada odcisk klienta jak DuckDuckGo). Stooq padł.
# Test offline (podstawiony fetch_via_curl): mapowanie symboli, cena z meta,
# szereg z timestamp+OHLC (luka null pominięta), krypto NIE idzie do Yahoo,
# nieznany symbol -> UnknownSymbol (żadnej zmyślonej ceny).
YAHOO_CHECK="$(cd "$ROOT/agent" && python3 -c '
import json, tools as t
ts = [1700000000 + 86400*i for i in range(5)]
doc = {"chart": {"result": [{"meta": {"currency": "USD", "symbol": "AAPL", "regularMarketPrice": 250.0},
      "timestamp": ts, "indicators": {"quote": [{"open": [240,241,None,243,244], "high": [245,246,None,248,249],
      "low": [239,240,None,242,243], "close": [242,244,None,246,250]}]}}], "error": None}}
t.netguard_mod.fetch_via_curl = lambda url, **k: json.dumps(doc)
q = t.market_quote("aapl.us"); h = t.market_history("aapl.us", 31)
hd = (h.get("card") or {}).get("data") or {}
ok = (t._yahoo_symbol("aapl.us") == "AAPL" and t._yahoo_symbol("btc") == "BTC-USD"
      and t._yahoo_symbol("^spx") == "^GSPC" and t._yahoo_symbol("eurusd") == "EURUSD=X"
      and t._yahoo_symbol("zloto") == "GC=F"
      and (q.get("card") or {}).get("source") == "yahoo"
      and abs((q["card"]["data"]["price"]) - 250.0) < 1e-6
      and len(hd.get("points") or []) == 4 and hd.get("first") == 242 and hd.get("last") == 250)
t._crypto_quote = lambda s, b, c: {"_hit": True}
ok = ok and t.market_quote("btcusd").get("_hit")
t.netguard_mod.fetch_via_curl = lambda url, **k: json.dumps({"chart": {"result": None, "error": {"code": "Not Found"}}})
ok = ok and (t.market_quote("zzzz.us").get("card") or {}).get("error") == "UnknownSymbol"
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$YAHOO_CHECK" = "OK" ]; then
  ok 39 "Yahoo Finance: notowania i miesięczna historia akcji/indeksów/FX/surowców (bez klucza); krypto osobno, nieznany symbol nie zmyśla ceny"
else
  bad 39 "Yahoo Finance: ${YAHOO_CHECK:-błąd importu}" "sprawdź agent/tools.py (_yahoo_symbol, _yahoo_fetch, market_quote, market_history)"
fi

# 40: czytanie CAŁYCH stron (1.30.20) - nie sam fragment z wyszukiwarki. Test
# offline: skrypty/style/nawigacja/stopka wycięte, tytuł wyjęty, tylko https,
# brak WARP propaguje (nie udaje pustej strony ani innej drogi).
PAGE_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tools as t
html = "<html><head><title>T</title><style>.x{color:red}</style></head><body><nav>NAWIGACJA</nav><script>var a=1;</script><p>Realna tresc strony.</p><footer>STOPKA</footer></body></html>"
t.netguard_mod.fetch_via_curl = lambda url, **k: html
r = t.fetch_page_text("https://e.test/x")
ok = (r.get("ok") and "Realna tresc strony." in r["text"] and "NAWIGACJA" not in r["text"]
      and "var a=1" not in r["text"] and "STOPKA" not in r["text"] and r.get("title") == "T")
ok = ok and (t.fetch_page_text("http://e.test/x").get("error") == "NieHttps")
def _blk(url, **k):
    raise t.netguard_mod.NetGuardBlocked("warp")
t.netguard_mod.fetch_via_curl = _blk
try:
    t.fetch_page_text("https://e.test/x"); ok = False
except t.netguard_mod.NetGuardBlocked:
    pass
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$PAGE_CHECK" = "OK" ]; then
  ok 40 "Czytanie całych stron: skrypty/nawigacja/stopka wycięte, tylko https, brak WARP = blokada (bez zmyślania treści)"
else
  bad 40 "Czytanie stron: ${PAGE_CHECK:-błąd importu}" "sprawdź agent/tools.py (fetch_page_text)"
fi

# 41: historia krypto osobnym źródłem (1.30.20) - Yahoo na WARP dostaje "Edge:
# Too Many Requests", więc krypto idzie do Coinbase candles / CoinGecko (hosty
# sprawdzone na WARP). Test offline: krypto routuje do _crypto_history (nie
# Yahoo), _history_card liczy otwarcie/zamknięcie/min/max, pusta historia nie
# zmyśla trendu (ok=False).
CRYPTOHIST_CHECK="$(cd "$ROOT/agent" && python3 -c '
import tools as t
series = [{"t": i, "o": 10 + i, "h": 12 + i, "l": 9 + i, "c": 11 + i} for i in range(5)]
t._crypto_history = lambda sl, b, c, d: series
r = t.market_history("btcusd", 31)
cd = (r.get("card") or {}); dd = cd.get("data") or {}
ok = (cd.get("source") == "coinbase/coingecko" and dd.get("last") == 15 and len(dd.get("points") or []) == 5)
hc = t._history_card("x", "X", "USD", series, "test")["card"]["data"]
ok = ok and hc["first"] == 11 and hc["last"] == 15 and hc["min"] == 9 and hc["max"] == 16
t._crypto_history = lambda sl, b, c, d: []
ok = ok and t.market_history("btcusd").get("ok") is False
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$CRYPTOHIST_CHECK" = "OK" ]; then
  ok 41 "Historia krypto z Coinbase/CoinGecko (Yahoo na WARP odrzucany); pusta historia nie zmyśla trendu"
else
  bad 41 "Historia krypto: ${CRYPTOHIST_CHECK:-błąd importu}" "sprawdź agent/tools.py (_crypto_history, _history_card, market_history)"
fi

# 42: "dodaj do węzłów" / "zapisz to do notatek" (1.30.22) - zapisuje OSTATNIĄ
# odpowiedź jako węzeł w grafie (type: Wiedza), z adnotacją o niezweryfikowaniu.
# Test offline: wzorzec łapie polecenie, bierze podpisaną odpowiedź z historii,
# zapisuje plik-węzeł do data/wiedza; zwykłe pytanie NIE jest łapane.
SAVE_NOTE_CHECK="$(cd "$ROOT/agent" && python3 -c '
import router as r, tools as t, data as d, tempfile, os
ans = "# Alpaki\nAlpaka to ssak z Andow, hodowany dla welny."
hist = [{"role": "user", "content": "Alpaki - co wiesz"},
        {"role": "assistant", "content": ans, "sig": r._chat_sig(ans)}]
ok = bool(r._SAVE_NOTE_RE.search("dodaj do wezlow")) and bool(r._SAVE_NOTE_RE.search("zapisz to jako wezel"))
ok = ok and bool(r._SAVE_NOTE_RE.search("zapisz to z wikipedii w wezlach"))
# 1.30.26: "zapamietaj najwazniejsze"/"zapisz to" to wskazanie na poprzednia odpowiedz
# (zapis jak wezel), a nie fakt o tresci "najwazniejsze"; prawdziwy fakt idzie dalej.
ok = ok and bool(r._SAVE_GIST_RE.search("zapamietaj najwazniejsze")) and bool(r._SAVE_GIST_RE.search("zapisz to"))
ok = ok and not r._SAVE_GIST_RE.search("zapamietaj ze mleko jest w lodowce")
# 1.30.28 (audyt tura 2): wzorzec zapisu-wezla to POLECENIE-WSKAZNIK (cel na koncu),
# nie moze porywac polecen z TRESCIA do dopisania.
ok = ok and bool(r._SAVE_NOTE_RE.search("zachowaj to w grafie"))
ok = ok and not r._SAVE_NOTE_RE.search("dopisz do notatek ze kupilem mleko")
ok = ok and not r._SAVE_NOTE_RE.search("dodaj do notatek pomysl na biznes")
# 1.30.30 (audyt tura 4): nie zapisujemy wlasnych komunikatow systemowych (blad,
# potwierdzenie zapisu) jako wezla; prawdziwa odpowiedz (tez z wiki) zapisywalna.
ok = ok and bool(r._NIE_DO_ZAPISU_RE.match("Nie udało się sprawdzić w internecie, połączenie nie działa."))
ok = ok and bool(r._NIE_DO_ZAPISU_RE.match("Zapisane jako węzeł w grafie: X."))
ok = ok and not r._NIE_DO_ZAPISU_RE.match("Sprawdziłem na Wikipedii: Kangur to ssak z Australii.")
ok = ok and (r._last_assistant_message(hist) == ans)
# 1.30.24: odpowiedz NARZEDZIA (wiki/search, bez podpisu) tez da sie zapisac - to zwykle wynik researchu
wiki_ans = "Sprawdzilem na Wikipedii: Kangur to ssak z Australii."
hist_tool = [{"role": "user", "content": "Co wiesz o kangurach"}, {"role": "assistant", "content": wiki_ans}]
ok = ok and (r._last_assistant_message(hist_tool) == wiki_ans)
ok = ok and not r._SAVE_NOTE_RE.search("jaki jest kurs btc")
tmp = tempfile.mkdtemp(); d.WIEDZA_ROOT = os.path.join(tmp, "wiedza")
res = t.save_note("Alpaki", ans)
ok = ok and res.get("ok") and res.get("invalidate_vault")
body = open(os.path.join(d.WIEDZA_ROOT, res["card"]["file"]), encoding="utf-8").read()
ok = ok and ("type: Wiedza" in body) and ("NIEZWERYFIKOWANE" in body) and ("Alpaka to ssak" in body)
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$SAVE_NOTE_CHECK" = "OK" ]; then
  ok 42 "„dodaj do węzłów” zapisuje odpowiedź jako węzeł w grafie (type: Wiedza), z adnotacją o niezweryfikowaniu"
else
  bad 42 "Zapis węzła: ${SAVE_NOTE_CHECK:-błąd importu}" "sprawdź agent/tools.py (save_note), agent/router.py (_SAVE_NOTE_RE, _last_assistant_message), agent/data.py (WIEDZA_ROOT)"
fi

# 43: warstwa UWAGI (1.30.22, pomysł Grzegorza) - waga 1-4 nadawana regułowo
# ZANIM cokolwiek policzymy. Test offline: typowe zdania dostają właściwą wagę,
# a poziom 4 odróżnia AKCJĘ nieodwracalną (bramka potwierdzenia) od samego
# pytania (np. zdrowie -> tylko rygor sprawdzania).
SKUP_CHECK="$(cd "$ROOT/agent" && python3 -c '
import skupienie as s
cs = {"dzieki": 1, "to wszystko, dziekuje": 1, "jaki jest kurs btc": 2,
      "przeanalizuj gielde BTC": 3, "dlaczego warp sie rozlacza": 3,
      "przelej 500 zl na konto": 4, "usun wszystkie notatki": 4, "jaka dawke leku wziac": 4}
ok = all(s.ocena(m)[0] == w for m, w in cs.items())
ok = ok and s.czy_akcja_nieodwracalna(s.ocena("przelej 500 zl na konto")[1])
ok = ok and s.czy_akcja_nieodwracalna(s.ocena("usun wszystkie notatki")[1])
ok = ok and not s.czy_akcja_nieodwracalna(s.ocena("jaka dawke leku wziac")[1])
# 1.30.29 (audyt tura 3): codzienne wzmianki NIE sa wage 4 (dawne kup\w*/inwestuj\w*
# lapaly "kupe roboty", "kupon", "kupilem", "inwestuje w rozwoj").
ok = ok and all(s.ocena(m)[0] != 4 for m in
                ("mam kupe roboty", "kupilem wczoraj mleko", "kupon rabatowy", "inwestuje w swoj rozwoj"))
ok = ok and s.ocena("kup bitcoina teraz")[0] == 4 and s.ocena("sprzedaj wszystko")[0] == 4
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$SKUP_CHECK" = "OK" ]; then
  ok 43 "Warstwa uwagi: waga 1-4 (szum/rutyna/ważne/krytyczne); poziom 4 oddziela nieodwracalną akcję od pytania"
else
  bad 43 "Warstwa uwagi: ${SKUP_CHECK:-błąd importu}" "sprawdź agent/skupienie.py (ocena, czy_akcja_nieodwracalna)"
fi

# 44: rozdzielnica (1.30.23) - waga uwagi wybiera szynę, żeby płatnego Claude
# używać jak najmniej. Polityka B (domyślna): darmowa pula pierwsza, Claude jako
# eskalacja dopiero od wagi 3, przy 4 z mocnym modelem; waga 1-2 bez płatnego.
# Respektuje KORYTO i wyłącznik ROZDZIELNICA=0. Test offline.
ROZDZ_CHECK="$(cd "$ROOT/agent" && python3 -c '
import os
os.environ["KORYTO"] = "anthropic,darmowe,lokalnie"; os.environ["ROZDZIELNICA"] = "B"
import importlib, juggler as j; importlib.reload(j)
ok = (j.rozdzielnica(2)["etapy"] == ["darmowe"] and j.rozdzielnica(2)["platny"] is False
      and j.rozdzielnica(3)["etapy"] == ["darmowe", "anthropic"] and j.rozdzielnica(3)["model"] is None
      and j.rozdzielnica(4)["etapy"] == ["darmowe", "anthropic"] and j.rozdzielnica(4)["model"] == j.NAMYSL_MODEL)
os.environ["KORYTO"] = "anthropic,lokalnie"; importlib.reload(j)   # bez darmowej puli
ok = ok and j.rozdzielnica(2)["etapy"] == [] and j.rozdzielnica(4)["etapy"] == ["anthropic"]
os.environ["ROZDZIELNICA"] = "0"; os.environ["KORYTO"] = "anthropic,darmowe"; importlib.reload(j)
ok = ok and j.rozdzielnica(2)["etapy"] == ["anthropic", "darmowe"] and j.rozdzielnica(2)["model"] == j.NAMYSL_MODEL
# 1.30.27 (audyt): kolejność etapów rozmowy wstawia sieciowe na ich sloty, lokalny
# zostaje tam, gdzie w KORYTO (płatny NIE wyprzedza lokalnego przy wadze 3).
os.environ["ROZDZIELNICA"] = "B"; os.environ["KORYTO"] = "darmowe,lokalnie,anthropic"; importlib.reload(j)
import router as rr
ok = ok and rr._stage_order_for(3) == ["darmowe", "lokalnie", "anthropic"]
ok = ok and rr._stage_order_for(2) == ["darmowe", "lokalnie"]
os.environ["KORYTO"] = "lokalnie,anthropic,darmowe"
ok = ok and rr._stage_order_for(3) == ["lokalnie", "darmowe", "anthropic"]
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$ROZDZ_CHECK" = "OK" ]; then
  ok 44 "Rozdzielnica (polityka B): darmowa pula pierwsza, Claude jako eskalacja od wagi 3 (mocny model przy 4), waga 1-2 bez płatnego; wyłącznik działa"
else
  bad 44 "Rozdzielnica: ${ROZDZ_CHECK:-błąd importu}" "sprawdź agent/juggler.py (rozdzielnica, rozdzielnica_policy) i agent/router.py (wpięcie w Namysł i pętlę rozmowy)"
fi

# 45. Poprawki z rozmowy Grzegorza (1.30.31), offline na atrapach (bez sieci, bez
#     zapisu do danych): gregaipanicmode próbuje mocniejszego poweroff, gdy zwykłe
#     odmówi (blokada wyłączenia); straż nie oddaje uciętego zdania; reakcja
#     („jak to nie masz...”) nie staje się wzorcem; pytanie o model ma odpowiedź z
#     kodu; pogoda z prognozy i słońce liczone w kodzie (dzień + noc = 24 h);
#     wyniki wyszukiwarki są streszczane, nie podawane jako sama lista; Wikipedia
#     bez hasła przechodzi do wyszukiwarki; podziękowanie nie uruchamia Namysłu
#     przy „zawsze”, a pytania pomocnicze nie trafiają do odpowiedzi.
FIX45_CHECK="$(cd "$ROOT/agent" && python3 -c '
import time
from datetime import date, datetime
import tryby, sysop as so, env_loader as el
calls = []
def rc(argv, timeout=60, sudo=False, shell_cmd=None, **kw):
    calls.append(list(argv))
    return {"rc": 1 if argv == ["systemctl", "poweroff"] else 0, "out": "", "err": "inhibited"}
so.run_cmd = rc; el.set_env_vars = lambda u, c=None: dict(u); so.audit = lambda *a, **k: None
tryby.panicmode()
deadline = time.time() + 8
while ["systemctl", "poweroff", "-i"] not in calls and time.time() < deadline:
    time.sleep(0.1)
ok = calls[-2:] == [["systemctl", "poweroff"], ["systemctl", "poweroff", "-i"]]
import straz, learning, namysl as n, pogoda as pg, capabilities as cp, tools as tl
ok = ok and straz.clean_assessment("**Ryzy") == "" and straz.clean_assessment("**Ryzyko: niskie.** Sprawdz ss -ltnp.") == "Ryzyko: niskie. Sprawdz ss -ltnp."
ok = ok and learning.is_reaction("Jak to nie masz dostepu do internetu") and not learning.is_reaction("pokaz stan sieci")
km = cp.find_keyword_match
ok = ok and km("z jakiego modelu korzystasz?")[0] == "self_model" and km("okej, jaka jest dzis pogoda w warszawie")[0] == "weather"
ok = ok and km("Co sie dzieje na rynku Krypto?") is None and km("Zaplanuj mi dzień na dziś")[0] == "plan_day"
import persona as pe
ok = ok and pe.CREATOR in tl.self_model()["speech"]
st = pg.sun_times(date(2026, 10, 23), 52.2297, 21.0122)
ok = ok and st["dzien_min"] + st["noc_min"] == 1440 and 600 < st["dzien_min"] < 630
pg._get_json = lambda url: {"current": {"temperature_2m": 8, "weather_code": 3}, "daily": {"time": ["2026-10-25"], "weather_code": [61],
    "temperature_2m_min": [5], "temperature_2m_max": [11], "precipitation_probability_max": [70]}, "hourly": {}}
w = pg.weather("pogoda")
ok = ok and (w.get("card") or {}).get("type") == "weather" and "11" in w["speech"] and "Open-Meteo" in w["speech"]
ok = ok and n.is_social("Wystarczy, dziekuje ze jeste") and n.is_social("Na luzieeee") and not n.is_social("Dziękuję, a teraz zrób mi plan na jutro")
ok = ok and "Czy GREGAI" not in n.strip_helper_questions("Tekst.\nCzy GREGAI to produkt OpenAI?\nNie.", ["Czy GREGAI to produkt OpenAI?"])
queued = []
tl._queue_open_question = lambda t: queued.append(t)
tl._wiki_resolve_title = lambda topic: (None, None); tl._find_cached_wiki_note = lambda v, topic: None
import netguard as ng
ng.internet_allowed = lambda fresh=False: (True, "")
tl.research_web = lambda q: {"speech": "W sieci znalazlem to: X.", "card": {"type": "research_web", "query": q, "results": [{"title": "X", "url": "https://x.pl/", "snippet": "y"}]}}
b = cp.CAPABILITIES["wiki_lookup"].call(None, "x", "dlugosc dnia i nocy Warszawa wschod zachod slonca")
ok = ok and (b.get("card") or {}).get("type") == "research_web" and "Wikipedii" in b["speech"] and queued == []
print("OK" if ok else "FAIL")
' 2>/dev/null)"
if [ "$FIX45_CHECK" = "OK" ]; then
  ok 45 "Poprawki 1.30.31: mocniejszy poweroff w panicmode, pełne zdania straży, pogoda i słońce z kodu, model z konfiguracji, wyniki sieci streszczane, Wikipedia -> wyszukiwarka, bez Namysłu dla podziękowań"
else
  bad 45 "Poprawki 1.30.31: ${FIX45_CHECK:-błąd importu}" "sprawdź agent/tryby.py, agent/straz.py, agent/pogoda.py, agent/capabilities.py (weather/self_model/wiki), agent/namysl.py (is_social)"
fi

# 46. Internet i warstwa z everything-claude-code (1.32.0), offline na atrapach:
#     bramka WARP (lokalny dowód tunelu + strona kontrolna, okres łaski tylko po
#     potwierdzeniu, warp=off blokuje zawsze), diagnoza bez WARP niczego nie wysyła,
#     wyszukiwanie przechodzi na zapasowy silnik, gdy DuckDuckGo odrzuca ruch, oraz
#     CAŁY szybki zestaw `gregai eval` (regresje z prawdziwych rozmów) na 100%.
NET46_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" python3 -c '
import time
import netguard as ng
def setup(rc, out, tun, probe):
    ng._cache.update(at=0.0, status=None)
    ng._trace_cache.update(at=0.0, ok=False, why="", kind="", on_at=0.0, info={})
    ng._run_warp_status = lambda: (rc, out)
    ng.tunnel_present = lambda: tun
    ng._trace_probe = lambda: probe
ON, OFF, ERR = ("on", "", {"warp": "on"}), ("off", "warp=off", {}), ("error", "strona kontrolna nie odpowiedziala", {})
ok = True
setup(0, "Status update: Connected", True, ON); ok = ok and ng.internet_allowed(fresh=True)[0]
setup(0, "Status update: Connected", True, OFF); ok = ok and not ng.internet_allowed(fresh=True)[0]
setup(0, "Status update: Connected", True, ERR); ok = ok and not ng.internet_allowed(fresh=True)[0]
setup(0, "Status update: Connected", True, ON); ng.internet_allowed(fresh=True)
ng._trace_cache["at"] = 0.0; ng._trace_probe = lambda: ERR; ok = ok and ng.internet_allowed(fresh=True)[0]
ng._trace_cache["at"] = 0.0; ng.tunnel_present = lambda: False; ok = ok and not ng.internet_allowed(fresh=True)[0]
setup(1, "Error: Registration Missing", None, ON)
st_ok, why = ng.internet_allowed(fresh=True); ok = ok and not st_ok and "registration new" in why
# diagnoza: klient rozłączony -> strona kontrolna NIE jest pytana (nic nie wychodzi bez WARP)
import diagnoza as dg
called = []
setup(1, "Status update: Disconnected. Reason: Manual Disconnection", False, ON)
ng._trace_probe = lambda: called.append(1) or ON
ng._run_warp = lambda *a, **k: (0, "Mode: Warp")
dg.shutil.which = lambda n: "/usr/bin/" + n
rep = dg.run()
ok = ok and not called and rep["internet"] is False and "warstwa 2" in rep["werdykt"]
# wyszukiwanie: DuckDuckGo z wyzwaniem -> Mojeek
import tools as t
ng.internet_allowed = lambda fresh=False: (True, "")
MOJ = "<h2><a class=\"title\" href=\"https://bankier.pl/x\">Krypto dzis</a></h2><p class=\"s\">BTC -3%</p>"
t._ddg_fetch = lambda url, data=None: MOJ if "mojeek" in url else "<html>anomaly</html>"
t._ENGINE_STATE.clear()
r = t.research_web("rynek krypto")
ok = ok and (r.get("card") or {}).get("engine") == "Mojeek" and t._engines()[0] == "mojeek"
# przegląd 1.32.0: H1 (tryb proxy po zapamiętanym "on" blokuje od razu, bez zapytania), H2 (warp=off kasuje łaskę)
import importlib
ng2 = importlib.reload(ng)
ng2._run_warp_status = lambda: (0, "Status update: Connected")
probes = []
ng2.tunnel_present = lambda: True; ng2._trace_probe = lambda: probes.append(1) or ON
ok = ok and ng2.internet_allowed(fresh=True)[0]
ng2.tunnel_present = lambda: False; n0 = len(probes)
ok = ok and not ng2.internet_allowed(fresh=True)[0] and len(probes) == n0
ng2.tunnel_present = lambda: True; ng2._cache.update(at=0.0, status=None); ng2._trace_cache["at"] = 0.0
ng2._trace_probe = lambda: ON; ok = ok and ng2.internet_allowed(fresh=True)[0]  # świeże "on": łaska aktywna
ng2._trace_cache["at"] = 0.0; ng2._trace_probe = lambda: OFF; ok = ok and not ng2.internet_allowed(fresh=True)[0]
ng2._trace_cache["at"] = 0.0; ng2._trace_probe = lambda: ERR; ok = ok and not ng2.internet_allowed(fresh=True)[0]
# przegląd 1.32.0: C1/M3 - /recenzja i /sprawdz nie wysyłają odpowiedzi narzędzia (prywatna notatka) do sieci
import router as rr, juggler as jj, trace as tt, namysl as nn
sent = []
jj.chat = lambda system, msgs, message, timeout=60.0, **kw: (sent.append(message) or ("odp", "groq"))
jj.providers_pool = lambda etap=None: ["groq"]; rr.ollama_available = lambda: False
rr._router_manifest_ok = lambda: (False, "t"); rr._student_manifest_ok = lambda: (False, "t")
rr.netguard_mod.internet_allowed = lambda fresh=False: (True, "ok"); tt.record = lambda *a, **k: None
class V:
    notes = {}
    def search(self, q, limit=5): return []
SECRET = "TAJNA_NOTATKA_xyz"
H = [{"role": "user", "content": "przeczytaj notatkę"}, {"role": "assistant", "content": SECRET}]
rr.route(V(), "SYS", H, "/recenzja", chat="kontrola46"); rr.route(V(), "SYS", H, "/sprawdz", chat="kontrola46")
ok = ok and not any(SECRET in m for m in sent)
# szybki zestaw regresji
import ewaluacja as ev
rep = ev.run(live=False, save=False)
ok = ok and rep["podsumowanie"]["zaliczone"] == rep["podsumowanie"]["przypadki"] >= 40
print("OK" if ok else "FAIL " + ",".join(k for k, v in rep["wyniki"].items() if not v["ok"]))
' 2>/dev/null)"
if [ "$NET46_CHECK" = "OK" ]; then
  ok 46 "Internet: bramka WARP (tunel + strona kontrolna, proxy i warp=off blokują od razu), diagnoza bez WARP nic nie wysyła, zapasowe wyszukiwarki; /recenzja i /sprawdz bez wycieku; gregai eval (szybki) 100%"
else
  bad 46 "Internet / ewaluacja: ${NET46_CHECK:-błąd importu}" "sprawdź agent/netguard.py, agent/diagnoza.py, agent/tools.py (research_web) i: gregai eval"
fi

# 47. Audyt 1.32.1 (tura 6/20), offline na atrapach, każda poprawka sprawdzona mutacją:
#     maska sekretów liniowa (ciąg spacji nie zawiesza serwera), DNS rebinding z nagłówkiem
#     pośrednika odrzucony, panicmode odcina LAN także na otwartych połączeniach, uszkodzony
#     wpis dziennika bezpieczeństwa = naruszenie, ARP z filtrem dev, izolacja wgranych plików
#     między rozmowami, budżet czasu przy czytaniu plików, Retry-After szanowane, pusta
#     rozdzielnica nie woła płatnego Claude, curl z limitem po rozpakowaniu i bez adresów
#     lokalnych, strona bez zamknięć liczona liniowo, liczby po polsku, tickery bez nazw
#     plików, zwykłe zdania bez narzędzi, waga 4 tylko dla akcji, zadanie stałe z notatkami
#     bez zgody nie idzie do sieci.
AUDYT47_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, os, re, subprocess, sys, tempfile, time, types
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
tmp = Path(tempfile.mkdtemp(prefix="gregai-check47-"))

# A: maska sekretów liniowa (ciąg spacji nie zawiesza serwera), poprawki nadal maskują
import trace as tr
t0 = time.perf_counter()
for kw in ("hasło", "token"):
    tr.mask(kw + (" " * 12 + "x") * 6)
chk("maska_czas", time.perf_counter() - t0 < 1.0)
chk("maska_dziala", tr.mask("hasło do wifi to Kr0wa123").endswith("***") and tr.mask("token do serwera to abcd1234").endswith("***"))

# A: żądanie z nagłówkiem pośrednika i obcym Hostem odrzucone przed tokenem
import main as mm
def handler(host, proxied, ip="127.0.0.1"):
    h = types.SimpleNamespace(headers={"Host": host, **({"X-Forwarded-For": "1.2.3.4"} if proxied else {})},
                              client_address=(ip, 5555))
    h._proxied = lambda: proxied
    return h
os.environ.pop("GREGAI_TUNEL_HOSTY", None)
chk("rebinding", mm.Handler._browser_origin_ok(handler("rebind.evil.example:7777", True))[0] is False)
chk("localhost_ok", mm.Handler._browser_origin_ok(handler("localhost:7777", False))[0] is True)

# B: panicmode - po blokadzie nic spoza tego komputera, nawet z tokenem; localhost tak
import tryby as ty
mm.GREGAI_TOKEN = "t" * 40
lan = handler("192.168.1.5:7777", False, ip="192.168.1.20"); lan.headers["X-Gregai-Token"] = "t" * 40
local = handler("localhost:7777", False)
chk("lan_przed", mm.Handler._authorized(lan) is True)
ty.PANIC_LOCK.set()
chk("lan_po_panic", mm.Handler._authorized(lan) is False and mm.Handler._authorized(local) is True)
sent47 = []
lan._send_json = lambda body, status=200: sent47.append(status)
lan._ban_key = lambda: "192.168.1.20"
lan._authorized = lambda: mm.Handler._authorized(lan)
_fails_before = len(mm._AUTH_FAILS.get("192.168.1.20", []))
chk("panic_bez_liczenia", mm.Handler._auth_gate(lan) is False and sent47 == [403] and len(mm._AUTH_FAILS.get("192.168.1.20", [])) == _fails_before)
ty.PANIC_LOCK.clear()

# B: dziennik bezpieczeństwa - wpis, który nie jest obiektem, to naruszenie (nie "ok")
import straz as st
st.SECLOG_PATH = tmp / "bezp.jsonl"; st._ANCHOR_PATH = tmp / "kotwica.json"; st._ANCHOR = None
st.log_security("test", "pierwszy"); st.log_security("test", "drugi")
chk("dziennik_czysty", st.verify_seclog().get("ok") is True)
with open(st.SECLOG_PATH, "a", encoding="utf-8") as f:
    f.write("0\n")
try:
    # 1.32.3: zepsuty wiersz na końcu (urwany zapis) przy całym łańcuchu to awaria, nie atak;
    # podmieniona treść wpisu w środku to naruszenie.
    _v = st.verify_seclog()
    chk("dziennik_urwany_wiersz", _v.get("ok") is True and _v.get("urwane") == 1)
    _lines = st.SECLOG_PATH.read_text(encoding="utf-8").splitlines()
    _lines[0] = _lines[0].replace("pierwszy", "zmieniony")
    st.SECLOG_PATH.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    chk("dziennik_zly_wpis", st.verify_seclog().get("ok") is False)
except Exception:
    chk("dziennik_zly_wpis_wyjatek", False)
st.SECLOG_PATH.write_text(""); st._ANCHOR = None
st._ANCHOR_PATH.unlink()
st.log_security("test", "jeden")
st.SECLOG_PATH.with_suffix(".jsonl.1").write_bytes(b"\xff\xfe smieci")
chk("dziennik_smieci", st.verify_seclog().get("ok") is False)
st.verify_seclog = lambda: 1 / 0
chk("status_nie_ok", st.status()["dziennik_bezp"]["ok"] is False)

# B: tablica ARP z filtrem "dev" (iproute2 pomija wtedy "dev X")
import siec as sc
sc.homenet.default_route = lambda: {"dev": "wlp2s0", "gw": "192.168.1.1"}
sc.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout="192.168.1.7 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n192.168.1.9 FAILED\n")
chk("arp", sc._read_arp_table() == {"192.168.1.7": "aa:bb:cc:dd:ee:ff"})
sc.subprocess.run = subprocess.run

# D: izolacja wgranych plików między rozmowami (data/ poza własnym katalogiem odpada)
import sources as so, sysop as sy0
so.DATA_DIR = tmp / "data"; so.UPLOAD_DIR = so.DATA_DIR / "wgrane"; so.STATE_PATH = so.DATA_DIR / "sources.json"
sy0.roots = lambda: [tmp]
up = so.save_upload("kontrola47b", "umowa.txt", b"tajne B")
chk("upload_zapis", up.get("ok"))
if up.get("ok"):
    chk("izolacja_sciezka", so.resolve_in_chat("kontrola47a", up["path"]) is None)
    chk("izolacja_wlasny", so.resolve_in_chat("kontrola47b", up["path"]) is not None)
    chk("izolacja_nazwa", not so.find_by_name_in_chat("kontrola47a", Path(up["path"]).name, so.chat_roots("kontrola47a")))
if up.get("ok"):
    _pr = sy0.PROJECT_ROOT
    sy0.PROJECT_ROOT = tmp
    (tmp / "data" / "wgrane" / "x").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "wgrane" / "x" / "a.txt").write_text("t")
    chk("sysop_wgrane", sy0.resolve_in_roots(str(tmp / "data" / "wgrane" / "x" / "a.txt")) is None)
    sy0.PROJECT_ROOT = _pr
so.delete_chat("kontrola47b")

# D: czytanie pliku w budżecie (should_stop) i częściowy odczyt dużego tekstu
import analiza as an
doc = {"text": ("akapit " * 300 + "\n\n") * 40, "name": "x.txt"}
calls = []
und = an.understand(doc, "cel", lambda s, u: calls.append(1) or "ok", should_stop=lambda: len(calls) >= 2)
chk("budzet_plik", len(calls) == 2 and und["pominiete"] > 0)
big = tmp / "duzy.log"; big.write_bytes(("wiersz zażółć " * 10 + "\n").encode() * 120000)
d = an.read_document(big)
chk("czesciowy_odczyt", d["ok"] and d["truncated"] and len(d["text"]) <= an.MAX_DOC_CHARS)

# D: limit czytania odpowiedzi i przerwa wyznaczona przez serwer
import juggler as jj
chk("deadline", jj._read_deadline(10) == 10 and jj._read_deadline(None) == 60 and jj._read_deadline(1) == 5)
calls = []
class E(Exception):
    def __init__(self, code, ra=None):
        self.code = code; self.headers = {"Retry-After": ra} if ra else {}
def fa(sp, msgs, t):
    calls.append("a"); raise E(429, "900")
def fb(sp, msgs, t):
    calls.append("b"); raise E(500)
jj.reset_breakers()
jj._PROVIDER_FN = {"a": fa, "b": fb}
jj._try_order = lambda pref, etapy: ["a", "b"]
jj._configured = lambda n: True; jj._allowed = lambda n: True
jj._guard_check = lambda: None; jj._note_call = lambda n: None
for _ in range(3):
    try:
        jj.chat("s", [], "m", timeout=10)
    except Exception:
        pass
chk("retry_after", calls == ["a", "b", "b", "b"])
import router as rr0
_jc = rr0.juggler_mod.chat
paid = []
rr0.juggler_mod.chat = lambda *a, **k: paid.append(k.get("etapy")) or ("x", "anthropic")
try:
    rr0.namysl_cloud_call({"etapy": [], "model": None}, "s", [], "m")
except RuntimeError:
    pass
rr0.namysl_cloud_call({"etapy": ["darmowe"], "model": None}, "s", [], "m")
chk("rozdzielnica_pusta", paid == [["darmowe"]])
rr0.juggler_mod.chat = _jc
import koryto as ko
chk("budzet_status", ko.status()["budzet_wiadomosc_s"] == 210)

# E: curl - limit liczony po rozpakowaniu (atrapa curl sypiąca zerami)
import netguard as ng
fake = tmp / "curl"
fake.write_text("#!/bin/sh\nexec cat /dev/zero\n"); fake.chmod(0o755)
_which, _allowed = ng.shutil.which, ng.internet_allowed
ng.shutil.which = lambda n: str(fake); ng.internet_allowed = lambda fresh=False: (True, "")
try:
    out = ng.fetch_via_curl("https://example.com/", timeout=2, max_bytes=100000)
    chk("curl_limit", len(out) == 100000)
except Exception as e:
    chk("curl_limit " + type(e).__name__, False)
try:
    ng.fetch_via_curl("https://192.168.1.1/cgi-bin/reboot", timeout=5)
    chk("curl_lan", False)
except ng.NetGuardBlocked:
    pass
ng.shutil.which, ng.internet_allowed = _which, _allowed

# E: strona bez zamknięć nie liczy się kwadratowo; liczby po polsku; tickery
import tools as tl, symbols as sy
t0 = time.perf_counter()
p = "<title>x" + "<script a>" * 200000
tl._drop_page_blocks(p); tl._page_title(p)
chk("strona_czas", time.perf_counter() - t0 < 1.0)
_fc = tl.netguard_mod.fetch_via_curl
tl.netguard_mod.fetch_via_curl = lambda *a, **k: "<title>x" + "<script a>" * 40000
t0 = time.perf_counter(); tl.fetch_page_text("https://example.com/")
chk("strona_fetch_czas", time.perf_counter() - t0 < 0.5)
tl.netguard_mod.fetch_via_curl = _fc
chk("strona_tekst", tl._strip_tags(tl._drop_page_blocks("<p>A</p><script>x()</script><nav>m</nav><p>B</p>")).split() == ["A", "B"])
chk("strona_bez_head", tl._strip_tags(tl._drop_page_blocks("<html><head><title>T</title><body><p>Tresc artykulu</p>")).split() == ["Tresc", "artykulu"])
chk("strona_otwarty_form", tl._strip_tags(tl._drop_page_blocks("<p>A</p><form><p>B</p>")).split() == ["A", "B"])
chk("fetch_lan", tl.fetch_page_text("https://10.0.0.5/")["error"] == "AdresLokalny")
chk("pl_num", tl.pl_num(67123.45) == "67 123,45" and tl.pl_num(0.0000123) == "0,0000123" and tl.pl_num(1e-8) == "0,00000001")
chk("ticker_plik", sy.detect("rynek krypto z pliku notes.md") is None and sy.detect("kurs aapl.us") == "aapl.us")
chk("ticker_kropka", sy.detect("kurs aapl.us.") == "aapl.us")
chk("ticker_zlota", sy.detect("cena złota dziś") == "xauusd" and sy.detect("złota rybka") is None)

# C: zwykłe zdania nie uruchamiają narzędzi
import capabilities as ca
none_of = ["Ciągle śledzę wiadomości o wojnie i mnie to dobija, co robić?", "Pogodziłem się wczoraj z bratem",
           "Jaki model iPhone'a najlepiej kupić do flipa?", "Co mogę dziś zrobić na obiad?"]
for i, m in enumerate(none_of):
    chk(f"bez_narzedzia_{i}", ca.find_keyword_match(m) is None)
chk("sledz_ok", (ca.find_keyword_match("śledź cały czas kurs bitcoina") or ("",))[0] == "standing_task_new")
chk("model_ok", (ca.find_keyword_match("jakim modelem jesteś?") or ("",))[0] == "self_model")
chk("pogoda_ok", (ca.find_keyword_match("jaka pogoda jutro") or ("",))[0] == "weather")
import router as rr
chk("zapis_grafika", not rr._SAVE_NOTE_RE.match("Zapisz mnie na kurs grafiki") and bool(rr._SAVE_NOTE_RE.match("dodaj do węzłów")))
t0 = time.perf_counter(); rr.CORRECTION_RE.search("nie o to " + "a" * 3000 + " b c d e f")
chk("korekta_czas", time.perf_counter() - t0 < 0.5)
import skupienie as sk
chk("waga_pytanie", sk.ocena("Ile zapłaciłem za prąd?")[0] < 4 and sk.ocena("Jak usunąć konto na TikToku?")[0] == 3)
chk("waga_prosba", sk.ocena("Czy możesz usunąć folder Projekty?")[0] == 4 and sk.ocena("usuń cały folder, dobrze?")[0] == 4)
chk("waga_akcja", sk.ocena("usuń plik raport.txt")[0] == 4 and sk.ocena("przelej 500 zł mamie")[0] == 4)
import lekcje as lk
chk("lekcja_pauza", "\u2014" not in lk.parse_draft("TYTUL: Pogoda \u2014 z prognozy\nROZWIAZANIE: Bierz prognozę\u2014zawsze")["tytul"] + lk.parse_draft("TYTUL: a\nROZWIAZANIE: b\u2014c")["rozwiazanie"])

# C: zadanie stałe z materiałem z notatek bez zgody - ocena tylko lokalnie, nic do sieci
import standing as sd
sent = []
sd.juggler_mod.chat = lambda *a, **k: sent.append(a) or ("ALERT: nie\nSTAN: x", "groq")
sd._private_material_blocked = lambda: True
sd.netguard_mod.internet_allowed = lambda fresh=False: (True, "")
sd.juggler_mod.providers_pool = lambda etap=None: ["groq"]
rr.ollama_available = lambda: False
try:
    sd._judge_reply("ZLECENIE: x", None, local_only=True)
except RuntimeError:
    pass
chk("zadanie_bez_sieci", not sent)

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$AUDYT47_CHECK" = "OK" ]; then
  ok 47 "Audyt 1.32.1: maska liniowa, rebinding, panicmode odcina LAN, dziennik bez furtki, izolacja plików rozmów, budżety i Retry-After, curl z limitem, liczby po polsku, mniej fałszywych narzędzi"
else
  bad 47 "Audyt 1.32.1: ${AUDYT47_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.1 (nazwa po FAIL mówi, która poprawka)"
fi

# 48. Audyt tura 7 (1.32.2), przekrojowo: planer nie zakłada zadań stałych i nie pyta o
#     pogodę bez karty, karty i dziennik bezpieczeństwa odporne na wątki, kolejka alertów
#     skończona, waga uwagi bez fałszywych ostrzeżeń, powitanie bez Namysłu, "zapisz to"
#     działa, aktualizacja odrzuca obce pliki i paczkę tej samej wersji z inną treścią.
AUDYT48_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, os, sys, tempfile, threading, time, types
from pathlib import Path
from datetime import datetime, timedelta
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
tmp = Path(tempfile.mkdtemp(prefix="gregai-check48-"))

# Red-team: planer nie zakłada ani nie zatrzymuje zadań stałych; pogoda w pętli tylko z kartą
import agentloop as al
names = {n for n, _, _ in al.tool_catalog()}
chk("planer_bez_zadan", not (names & {"standing_task_new", "standing_task_stop"}))
chk("pogoda_karta", al.confirm_reason("weather", {"steps": []}, "Pin4711") == "internet")

# Współbieżność: przegląd kart w trakcie zmian z innego wątku
stop = threading.Event(); errs = []
def churn():
    i = 0
    while not stop.is_set():
        al._PENDING[f"x{i}"] = {"created": time.monotonic(), "created_wall": time.time(), "chat": "a"}
        al._PENDING.pop(f"x{i - 50}", None); i += 1
_sw = sys.getswitchinterval(); sys.setswitchinterval(1e-6)
for i in range(2000):
    al._PENDING[f"y{i}"] = {"created": time.monotonic(), "created_wall": time.time(), "chat": "b"}
t = threading.Thread(target=churn); t.start()
try:
    for _ in range(300):
        al._new_pending("remember", "x", None)
except RuntimeError as e:
    errs.append(e)
stop.set(); t.join(); sys.setswitchinterval(_sw)
al._PENDING.clear()
chk("karty_watki", not errs)

# Zadania stałe: kolejka alertów skończona, jedno zadanie = jeden wpis; zmiana czasu bez cyklu
import standing as sd
sd.ALERTS_PATH = tmp / "alerty.json"
for i in range(200):
    sd._queue_alert("kurs BTC", f"spadek {i}")
for i in range(30):
    sd._queue_alert(f"zadanie {i}", "x")
q = sd.pop_pending_alerts()
chk("alerty_limit", len(q) <= sd.MAX_ALERTOW_W_KOLEJCE and sum(1 for a in q if a["zlecenie"] == "kurs BTC") <= 1)

# Dziennik bezpieczeństwa: sprawdzanie w trakcie zapisu bez fałszywych naruszeń
import straz as st
st.SECLOG_PATH = tmp / "bezp.jsonl"; st._ANCHOR_PATH = tmp / "kotwica.json"; st._ANCHOR = None
st.log_security("start", "x")
bad = []; done = threading.Event()
def writer():
    for i in range(300):
        st.log_security("test", f"wpis {i}")
    done.set()
w = threading.Thread(target=writer); w.start()
while not done.is_set():
    if not st.verify_seclog().get("ok"):
        bad.append(1)
w.join()
chk("dziennik_wspolbieznie", not bad and st.verify_seclog().get("ok"))

# Rozmowa: waga uwagi bez fałszywych ostrzeżeń, prawdziwe akcje dalej 4
import skupienie as sk
for i, m in enumerate(["napisz kupującemu że wpłata doszła", "za ile sprzedam iphone xr na olx",
                       "usuń myślniki z tego tekstu", "jakie są objawy padającej baterii w iphonie?"]):
    chk(f"waga_codzienna_{i}", sk.ocena(m)[0] < 4)
for i, m in enumerate(["przelej 200 zł", "sformatuj pendrive", "skasuj ostatnią notatkę", "mam objawy zatrucia"]):
    chk(f"waga_krytyczna_{i}", sk.ocena(m)[0] == 4)
chk("waga_plan", sk.ocena("/plan rozkręcić kanał")[0] == 3)

import namysl as nm, learning as lr, bramka as br, router as rr
chk("namysl_powitanie", nm.wants("hej, co tam u ciebie dzisiaj slychac?", [], nm.load_settings(), first_turn=True)[0] is False)
chk("nauka_czas", "dzis" in lr.STOPWORDS and "jutro" in lr.STOPWORDS)
_t = "Gdy NetworkManager pokazuje brak dostępu do internetu, winny jest APN."
chk("bramka_lte", br.review(_t, internet=True) == (_t, []))
chk("szkic_uloz", bool(rr.DRAFT_RE.match("ułóż smsa do klienta że dziś nie przyjadę")) and not rr.DRAFT_RE.match("jak ułożyć płytki"))
chk("dane_publiczne", {"weather", "market_quote"} <= set(rr._PUBLIC_DATA_TOOLS))

# Przegląd poprawek 1.32.2: pogoda z karty pyta o miasto z karty; wagi bez dziur; szkice wąsko
import capabilities as ca, pogoda as pg
seen = []
_ww = pg.weather
pg.weather = lambda message="", now=None: seen.append(message) or {"speech": "x", "card": None}
ca._call_weather(None, "Kraków", "Kraków")
pg.weather = _ww
chk("pogoda_miasto_z_karty", seen and pg.city_from_message(seen[0]) != "")
for i, m in enumerate(["usuń listę zadań", "skasuj listę kontaktów", "jakie są objawy alergii na pomidory?", "duszność po oprysku pomidorów"]):
    chk(f"waga_dziura_{i}", sk.ocena(m)[0] == 4)
chk("waga_przemysle", sk.ocena("przemyślę to, dzięki")[0] < 3)
chk("szkic_waski", not rr.DRAFT_RE.match("ułóż mi plan dnia na jutro") and not rr.DRAFT_RE.match("przygotuj mi opis konfiguracji WARP"))
chk("ram_telefonu", ca._SYSOP_KEYWORDS["sys_status"][0].search("ile ramu ma iphone 13?") is None and bool(ca._SYSOP_KEYWORDS["sys_status"][0].search("ile wolnego ramu mam")))
chk("wymagane_bez_zadan", "standing_task_new" not in al.required_tools("sprawdź pogodę w Krakowie, a potem śledź cały czas kurs BTC i daj znać gdy spadnie"))

# Router: "zapisz to" po odpowiedzi zapisuje węzeł (dawniej NameError)
import juggler as jj, trace as tt, tools
saved = []
jj.chat = lambda system, msgs, message, timeout=60.0, **kw: ("odp", "groq")
jj.providers_pool = lambda etap=None: ["groq"]; rr.ollama_available = lambda: False
rr._router_manifest_ok = lambda: (False, "t"); rr._student_manifest_ok = lambda: (False, "t")
rr.netguard_mod.internet_allowed = lambda fresh=False: (True, "ok"); tt.record = lambda *a, **k: None
tools.save_note = lambda title, body: saved.append(title) or {"speech": "Zapisane", "card": None}
class V:
    notes = {}
    def search(self, q, limit=5): return []
H = [{"role": "user", "content": "co to jest LoRA w uczeniu modeli"}, {"role": "assistant", "content": "LoRA to metoda douczania dużych modeli przez małe macierze."}]
H = rr.sign_history(H) if hasattr(rr, "sign_history") else H
try:
    r = rr.route(V(), "SYS", H, "zapisz to", chat="k48")
    chk("zapisz_to", saved == ["LoRA w uczeniu modeli"])
except Exception as e:
    chk("zapisz_to_" + type(e).__name__, False)

# Aktualizacja: paczka z plikiem spoza sum kontrolnych i paczka tej samej wersji z inną treścią odrzucone
import hashlib, shutil, subprocess, zipfile
ROOT = Path.cwd().parent  # kontrola uruchamiana z agent/
def manifest(d):
    lines = []
    for f in sorted(p for p in d.rglob("*") if p.is_file() and p.name != "GREGAI.sha256" and "__pycache__" not in p.parts):
        rel = f.relative_to(d).as_posix()
        lines.append(hashlib.sha256(f.read_bytes()).hexdigest() + "  " + rel)
    (d / "GREGAI.sha256").write_text("\n".join(sorted(lines, key=lambda l: l.split("  ", 1)[1].encode())) + "\n")
def copy_tree(dst):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("__pycache__", "data", "memory", ".env", ".env.bak.*"))
inst = tmp / "inst" / "GREGAI"; copy_tree(inst); manifest(inst)
def pkg(name, mod):
    d = tmp / "pkg" / name / "GREGAI"; copy_tree(d); mod(d); manifest(d)
    z = tmp / "pkg" / (name + ".zip")
    with zipfile.ZipFile(z, "w") as zf:
        for f in d.rglob("*"):
            if f.is_file():
                zf.write(f, "GREGAI/" + f.relative_to(d).as_posix())
    return z
z1 = pkg("extra", lambda d: None)
with zipfile.ZipFile(z1, "a") as zf:
    zf.writestr("GREGAI/agent/json.py", "x = 1\n")
z2 = pkg("same", lambda d: (d / "agent" / "tools.py").write_text((d / "agent" / "tools.py").read_text() + "\n# x\n"))
binp = tmp / "bin"; binp.mkdir()
(binp / "id").write_text("#!/bin/sh\nif [ \"$1\" = \"-u\" ]; then echo 1000; else /usr/bin/id \"$@\"; fi\n"); (binp / "id").chmod(0o755)
env = dict(os.environ, HOME=str(tmp), PATH=str(binp) + ":" + os.environ.get("PATH", ""))
def upd(z):
    r = subprocess.run(["bash", "aktualizuj.sh", str(z)], cwd=inst, env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr
rc1, o1 = upd(z1); rc2, o2 = upd(z2)
chk("aktualizacja_obcy_plik", rc1 != 0 and "spoza GREGAI.sha256" in o1)
chk("aktualizacja_ta_sama_wersja", rc2 != 0 and "tę samą wersję" in o2)
chk("aktualizacja_nic_nie_ruszone", not (inst / "agent" / "json.py").exists() and "# x" not in (inst / "agent" / "tools.py").read_text()[-10:])

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$AUDYT48_CHECK" = "OK" ]; then
  ok 48 "Audyt tura 7: zadania stałe i pogoda tylko za zgodą, odporność na wątki, alerty z limitem, trafniejsza waga uwagi, \"zapisz to\", bezpieczniejsza aktualizacja"
else
  bad 48 "Audyt tura 7: ${AUDYT48_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.2 (nazwa po FAIL mówi, która poprawka)"
fi

# 49. Audyt tura 8 (1.32.3): zgoda na sieć tylko dla prawdziwego true, limit Claude odporny na
#     NaN i zepsuty plik, lekcje/źródła/rozmowy do kwarantanny zamiast cichego nadpisania,
#     data/ nie jest źródłem, limit kopii kwarantanny, straż: zepsuta baza i kotwica to alarm,
#     nie cichy nowy wzorzec; tytuły bez znaków sterujących, błędy po polsku; krótszy prompt
#     rozmowy, ramki danych nie do zamknięcia; lepsze wyszukiwanie w notatkach.
AUDYT49_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, os, sys, tempfile, time, types
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
tmp = Path(tempfile.mkdtemp(prefix="gregai-check49-"))

# Trwałość: zgoda na sieć tylko dla prawdziwego true; zły typ w ustawieniach = 400
import namysl as nm
nm.STATE_PATH = tmp / "namysl.json"
for v in ("false", "0", "nie", [1]):
    nm.STATE_PATH.write_text(json.dumps({"material_do_sieci": v}))
    chk(f"zgoda_tekst_{v}", nm.load_settings()["material_do_sieci"] is False)
try:
    nm.save_settings({"material_do_sieci": "false"})
    chk("zgoda_zapis_typ", False)
except ValueError:
    pass

# Budżet Claude: NaN w dzienniku nie wyłącza limitu; zepsuty plik nie zeruje miesiąca
import juggler as jj
jj.JOURNAL_PATH = tmp / "koryto.json"
jj.JOURNAL_PATH.write_text(json.dumps({"dzien": time.strftime("%Y-%m-%d", time.gmtime()), "miesiac": time.strftime("%Y-%m", time.gmtime()), "usd_dzien": "NaN", "usd_miesiac": 1.0, "wywolania": {}}))
jj._JOURNAL.clear(); jj._JOURNAL_LOADED = False
jj._journal_load_locked() if hasattr(jj, "_journal_load_locked") else None
chk("budzet_nan", all(v == v for v in (float(jj._JOURNAL.get("usd_dzien") or 0), float(jj._JOURNAL.get("usd_miesiac") or 0))))
chk("budzet_miesiac_nie_zero", float(jj._JOURNAL.get("usd_miesiac") or 0) >= float(jj._BUDGET_MONTH_USD or 0))

# Lekcje i źródła: zepsuty plik do kwarantanny, nie nadpisywany pustym
import lekcje as lk, sources as so, fsutil
lk.DATA_PATH = tmp / "lekcje.json"; lk.DATA_PATH.write_text('[{"tytul": "a", "problem": "", "rozwiazanie": "b", "kiedy": ""}')
lk.save({"tytul": "nowa", "problem": "", "rozwiazanie": "c", "kiedy": ""})
chk("lekcje_kwarantanna", any(p.name.startswith("lekcje.json.corrupt-") for p in tmp.iterdir()))
so.DATA_DIR = tmp / "data"; so.STATE_PATH = so.DATA_DIR / "sources.json"; so.UPLOAD_DIR = so.DATA_DIR / "wgrane"
so.DATA_DIR.mkdir(parents=True)
so.STATE_PATH.write_text("[1, 2]")
so.folders("ogolna")
chk("zrodla_zly_typ", any(p.name.startswith("sources.json.corrupt-") for p in so.DATA_DIR.iterdir()))
chk("zrodla_data", so._validate(str(so.DATA_DIR))[0] is False)
# folder NAD data/ wolno dodać, ale data/ dalej zamknięte dla tej rozmowy
_import_sysop = __import__("sysop"); _import_sysop.roots = lambda: []
chk("zrodla_nad_data", so._validate(str(tmp))[0] is True)
so.add("k49", str(tmp)); (so.DATA_DIR / "historia.json").write_text("{}")
chk("zrodla_nad_data_zamkniete", so.resolve_in_chat("k49", str(so.DATA_DIR / "historia.json")) is None
    and so.resolve_in_chat("k49", str(tmp / "lekcje.json")) is not None)
for i in range(9):
    (tmp / "x.json").write_text("{")
    fsutil.quarantine(tmp / "x.json")
    time.sleep(0.01)
chk("kwarantanna_limit", sum(1 for p in tmp.iterdir() if p.name.startswith("x.json.corrupt-")) <= fsutil.MAX_QUARANTINE_COPIES)

# Straż: zepsuta baza po restarcie = alarm (nie cichy nowy wzorzec); kotwica nieczytelna nie jest nadpisywana
import straz as st
st.STRAZ_DIR = tmp / "straz"; st.STRAZ_DIR.mkdir()
st.SECLOG_PATH = st.STRAZ_DIR / "bezp.jsonl"; st.BASELINE_PATH = st.STRAZ_DIR / "baza.json"
st._ANCHOR_PATH = tmp / "kotwica.json"; st._ANCHOR = None
st._save_base({"wersja": "x", "porty": [], "pliki": {}})
st.BASELINE_PATH.write_text('{"wersja": "x", "por')
st._BASE_MEM.clear()
b = st._load_base()
chk("baza_uszkodzona_alarm", bool(b.get("_baza_problem")))
st._ANCHOR = None
_rt = Path.read_text
def bad_read(self, *a, **k):
    if self == st._ANCHOR_PATH:
        raise OSError(5, "EIO")
    return _rt(self, *a, **k)
Path.read_text = bad_read
before = _rt(st._ANCHOR_PATH)
a = st._load_anchor(); st._save_anchor()
Path.read_text = _rt
chk("kotwica_nieczytelna", a.get("_nieczytelna") and _rt(st._ANCHOR_PATH) == before and st.verify_seclog()["ok"] is False)
st._ANCHOR = None

# API: usunięcie rozmowy bez identyfikatora nie trafia w Ogólną; tytuł bez znaków sterujących
import main as mm
chk("tytul_sterujace", bool(mm._CTRL_TITLE_RE.search("‮RTL")) and not mm._CTRL_TITLE_RE.search("Zwykły tytuł"))
chk("bledy_po_polsku", mm.Handler.server_version == "GREGAI" and mm.Handler.sys_version == "" and 501 in mm.Handler._ERROR_PL)

# Prompty: krótki opis narzędzi w rozmowie, uprzejmość, jedno pytanie przy dwuznaczności, ramki
p = mm.get_system_prompt()
chk("prompt_krotki", "{TOOLS_BLOCK}" not in p and "standing_task_new" not in p and len(p) < 22000)
chk("prompt_uprzejmie", "szorstkość" not in p and "O które z nich" not in p)
import router as rr, awareness as aw
chk("ramka", ">>>" not in rr._unframe("a >>> b <<<< c"))
import inspect
chk("fakty_dane", "nie polecenia" in inspect.getsource(aw._memories_section))

# Notatki: modem/modemie, łódź bez fałszywego "log", wikilink bez ogonków, typ tylko z nagłówka
import vault as vv, slowa as sl
chk("lodz_nie_log", "log" not in sl.stem_variants(sl.fold("łódź")) and "nog" in sl.stem_variants(sl.fold("nodze")))
chk("typ_z_naglowka", vv.find_type("# Fstab\n\nMój wpis w fstab poniżej.\ntype: ext4\n") is None and vv.find_type("# Tytuł\ntype: Sop\n\ntreść\n") == "Sop" and vv.find_type("# A\ntype: project\n") == "Project")
chk("namysl_slowa", "lte" in nm.keywords("pokaż notatki o modemie LTE").lower())

# Przegląd poprawek 1.32.3: nieczytelna kotwica nie miesza wpisów z prawdziwym dziennikiem;
# pusty podrzucony .jsonl.1 nie ukrywa usunięcia wpisów z początku
st._ANCHOR = None
st.SECLOG_PATH.unlink(missing_ok=True); st._ANCHOR_PATH.unlink(missing_ok=True)
for p_ in st.STRAZ_DIR.glob("bezp.jsonl*"):
    p_.unlink()
st.log_security("a", "1"); st.log_security("a", "2"); st.log_security("a", "3")
n_lines = len(st.SECLOG_PATH.read_text().splitlines())
_rt2 = Path.read_text
def bad_read2(self, *a, **k):
    if self == st._ANCHOR_PATH:
        raise OSError(5, "EIO")
    return _rt2(self, *a, **k)
st._ANCHOR = None
Path.read_text = bad_read2
st.log_security("a", "w trakcie awarii")
Path.read_text = _rt2
st._ANCHOR = None
chk("kotwica_nieczytelna_osobny_plik", len(st.SECLOG_PATH.read_text().splitlines()) == n_lines and st.verify_seclog()["ok"] is True)
lines = st.SECLOG_PATH.read_text().splitlines()
st.SECLOG_PATH.write_text("\n".join(lines[1:]) + "\n")
st.SECLOG_PATH.with_suffix(".jsonl.1").write_text("")
st._VERIFY_CACHE.clear()
chk("pusty_jsonl1", st.verify_seclog()["ok"] is False)
# Budżet: blokada po uszkodzeniu mówi prawdziwy powód
jj._JOURNAL.clear(); jj._JOURNAL_LOADED = False
jj.JOURNAL_PATH.write_text("{")
chk("budzet_powod", "uszkodzony" in jj.over_budget("anthropic"))
# Prompt rozmowy: tryby serwera i pełniejsza lista możliwości
chk("prompt_tryby", "gregaipanicmode" in mm.CHAT_TOOLS_SUMMARY and "plan" in mm.CHAT_TOOLS_SUMMARY)
# Namysł: słowa do narracji z ogonkami
chk("namysl_ogonki", "łodziach" in nm.keywords("co wiem o łodziach"))
# Pamięć: fakty różniące się tylko wielkością liter w treści to dwa fakty
import memory as me
me.MEMORY_DIR = tmp / "memory"
f1 = me.remember("kod do skrytki Ab12")
f2 = me.remember("kod do skrytki AB12")
f3 = me.remember("Lubię kawę z ekspresu"); f4 = me.remember("lubię kawę z ekspresu.")
chk("pamiec_wielkosc_liter", f1[0] != f2[0] and f3[0] == f4[0])

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$AUDYT49_CHECK" = "OK" ]; then
  ok 49 "Audyt tura 8: zgoda i budżet odporne na zepsute pliki, dane do kwarantanny zamiast nadpisania, straż bez cichego wzorca, krótszy prompt, lepsze wyszukiwanie w notatkach"
else
  bad 49 "Audyt tura 8: ${AUDYT49_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.3 (nazwa po FAIL mówi, która poprawka)"
fi

# 50. Decyzje Grzegorza (1.32.4): zapora WARP w jądrze obowiązkowa (bez wyłącznika, usługa bez
#     niej nie startuje), samodopasowanie dostawcy (darmowa pula, Claude jako zapas), planer bez
#     zgody nie widzi treści notatek i plików, zwięzły prompt modelu lokalnego.
DECYZJE50_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, os, sys, tempfile
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
tmp = Path(tempfile.mkdtemp(prefix="gregai-check50-"))
ROOT = Path.cwd().parent

# 1. Zapora WARP obowiązkowa: bez wyłącznika, usługa bez tabeli nie startuje
inst = (ROOT / "install.sh").read_text(encoding="utf-8")
chk("zapora_bez_myslnika", 'KILLSWITCH_LINE="ExecStartPre=+/usr/sbin/nft -f $KILL_NFT"' in inst and "ExecStartPre=-+/usr/sbin/nft" not in inst)
chk("zapora_stop_instalacji", 'if [ "$KILL_OK" != 1 ]; then' in inst)
import diagnoza as dg
chk("zapora_diagnoza", "obowiązkowa" in Path(dg.__file__).read_text(encoding="utf-8"))

# 2. Samodopasowanie dostawcy: bez wskazanej kolejności najpierw darmowa pula, Claude jako zapas
import juggler as jj, koryto as ko
os.environ["KORYTO"] = "anthropic,darmowe,lokalnie"; os.environ.pop("ROZDZIELNICA", None)
chk("samodopasowanie", jj.samodopasowanie() == ["darmowe", "anthropic"])
os.environ["ROZDZIELNICA"] = "0"
chk("samodopasowanie_wylacznik", jj.samodopasowanie() is None)
os.environ.pop("ROZDZIELNICA", None)
seen = []
jj._PROVIDER_FN = {"groq": lambda s, m, t: seen.append("groq") or "ok", "anthropic": lambda s, m, t: seen.append("anthropic") or "ok"}
jj._etap_providers = lambda e: {"darmowe": ["groq"], "anthropic": ["anthropic"]}.get(e, [])
jj._configured = lambda n: True; jj._allowed = lambda n: True; jj._guard_check = lambda: None; jj._note_call = lambda n: None
jj.reset_breakers()
try:
    jj.chat("s", [], "m", timeout=10)
except Exception:
    pass
chk("samodopasowanie_kolejnosc", seen[:1] == ["groq"])

# 3. Planer bez zgody nie widzi treści notatek i plików
import agentloop as al, namysl as nm
nm.STATE_PATH = tmp / "namysl.json"
st = {"goal": "x", "steps": [{"tool": "search_brain", "arg": "modem", "ok": True, "observation": "TAJNE_PIN_1234"},
                             {"tool": "weather", "arg": "", "ok": True, "observation": "Warszawa 10C"}]}
txt = al._render_state(st)
chk("planer_bez_zgody", "TAJNE_PIN_1234" not in txt and "Warszawa 10C" in txt)
st["_siec"] = False
chk("planer_lokalny_widzi", "TAJNE_PIN_1234" in al._render_state(st))
st["_siec"] = True
st["steps"].append({"tool": "network_status", "arg": "", "ok": False, "observation": "SIEC_DOMOWA_192"})
chk("planer_siec_domowa", "SIEC_DOMOWA_192" not in al._render_state(st) and al._planner_in_network("koryto:darmowe") and not al._planner_in_network("qwen2.5:3b"))
nm.STATE_PATH.write_text(json.dumps({"material_do_sieci": True}))
chk("planer_ze_zgoda", "TAJNE_PIN_1234" in al._render_state(st))

# 4. Zwięzły prompt modelu lokalnego (z kryzysem i tożsamością), pełny dla sieci
import awareness as aw, main as mm
full = mm.get_system_prompt()
loc = aw.local_prompt(full, type("V", (), {"notes": {}})())
chk("prompt_projekt", "NOWY_WEZEL" in aw.local_prompt(full + "\n\n--- Kontekst: projekt „X” ---\nNOWY_WEZEL: ...", type("V", (), {"notes": {}})()))
import persona as pe
chk("prompt_lokalny", len(loc) < len(full) // 2 and "116 123" in loc and f"Moim twórcą jest {pe.CREATOR}" in loc)

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$DECYZJE50_CHECK" = "OK" ]; then
  ok 50 "Decyzje 1.32.4: zapora WARP obowiązkowa, dostawca dopasowuje się sam, planer bez zgody nie widzi notatek, zwięzły prompt lokalny"
else
  bad 50 "Decyzje 1.32.4: ${DECYZJE50_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.4"
fi

# 51. Rozmowa z 25.10 (1.32.5): etykieta klasyfikatora bezpieczeństwa ("Response Safety: safe")
#     nie trafia do odpowiedzi, a model-klasyfikator z puli to błąd dostawcy; cena rynkowa
#     z pamięci modelu (bez wyniku narzędzia) nie dociera; złoto i srebro mają zapas, gdy
#     Yahoo nie odpowiada.
ROZMOWA51_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import io, json, os, sys
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. Etykieta klasyfikatora bezpieczeństwa nie trafia do odpowiedzi
import router as rr, juggler as jj
chk("etykieta_response", rr._sanitize_leaked_tokens("Response Safety: safe").strip() == "")
chk("klasyfikator_odrzucony", bool(jj._GUARD_REPLY_RE.match("User Safety: safe\nResponse Safety: safe"))
    and bool(jj._GUARD_MODEL_RE.search("nvidia/llama-3.1-nemotron-safety-guard-8b")) and not jj._GUARD_REPLY_RE.match("Jest bezpiecznie (safe)."))
_post_data = {"model": "nvidia/nemotron-safety-guard", "choices": [{"message": {"content": "Response Safety: safe"}, "finish_reason": "stop"}]}
class _R(io.BytesIO):
    def __enter__(s): return s
    def __exit__(s, *a): pass
import netguard as ng
_uo, _rj = ng.urlopen, ng.read_json
ng.urlopen = lambda req, **k: _R(b"{}"); ng.read_json = lambda resp, **k: _post_data
try:
    jj._openai_compatible_chat("https://x.invalid/v1", "k", "openrouter/free", "s", [{"role": "user", "content": "Za uncję?"}], 10)
    chk("klasyfikator_blad_dostawcy", False)
except RuntimeError as e:
    chk("klasyfikator_blad_dostawcy", "klasyfikator" in str(e))
except Exception:
    chk("klasyfikator_blad_dostawcy", False)
ng.urlopen, ng.read_json = _uo, _rj

# 2. Cena rynkowa z pamięci modelu nie dociera; cena z wyniku narzędzia tak; ceny Grzegorza bez zmian
import bramka as bb
t, f = bb.review("Ceny srebra (XAGUSD) w tej chwili to $24,90 za uncję. Jeśli potrzebujesz ceny w PLN, daj znać.",
                 zrodla="Tak chce\nNie udało się sprawdzić notowania")
chk("cena_zmyslona", "24,90" not in t and any(x["kod"] == "cena_bez_zrodla" for x in f))
chk("cena_z_narzedzia", bb.review("Srebro: 33,10 USD za uncję.", zrodla="SI=F: 33,10 USD")[1] == [])
chk("cena_wlasna", bb.review("iPhone 13 sprzedasz za 1500 zł.", zrodla="")[1] == [])

# 3. Zapas notowań złota i srebra, gdy Yahoo nie odpowiada
import tools as tt
tt._yahoo_fetch = lambda *a: (_ for _ in ()).throw(ValueError("Edge: Too Many Requests"))
ng.urlopen = lambda req, **k: _R(json.dumps({"symbol": "XAG", "price": 33.1}).encode())
r = tt.market_quote("xagusd")
chk("srebro_zapas", r.get("ok") is not False and "33,10" in r["speech"] and r["card"]["source"] == "gold-api.com")
chk("akcje_bez_zapasu", tt.market_quote("aapl.us").get("ok") is False)
ng.urlopen = _uo
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$ROZMOWA51_CHECK" = "OK" ]; then
  ok 51 "Rozmowa 25.10: bez etykiet klasyfikatora, bez zmyślonych cen, zapas notowań złota i srebra"
else
  bad 51 "Rozmowa 25.10: ${ROZMOWA51_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.5"
fi

# 52. Audyt tura 10 (1.32.6): potwierdzenia ("Tak chce"), srebro i "cenę/kosztuje" jako notowanie,
#     router widzi notowanie i pytanie (tak / nie), bramka cen bez fałszywych alarmów,
#     klasyfikator u każdego dostawcy, zapas metali z rozsądną ceną, redakcja planera.
TURA52_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, os, sys
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. Potwierdzenia: "Tak chce", "no tak", "pewnie"; "pewnie nie" i samo "no" to nie zgoda
import agentloop as al
chk("tak_chce", all(al.is_confirm(m) for m in ("Tak chce", "tak chcę", "tak poproszę", "no tak", "pewnie")))
chk("nie_zgoda", not any(al.is_confirm(m) for m in ("pewnie nie", "no", "tak, ale nie rób", "chcę")))

# 2. Srebro i "cenę"/"kosztuje" rozpoznane jako notowanie; srebrny medal nie
import symbols as sy, capabilities as ca
chk("srebro", sy.detect_all("cena srebra") == ["xagusd"] and (ca.find_keyword_match("kurs srebra") or ("",))[0] == "market_quote")
chk("cene_kosztuje", (ca.find_keyword_match("podaj cenę złota") or ("",))[0] == "market_quote"
    and (ca.find_keyword_match("ile kosztuje złoto") or ("",))[0] == "market_quote")
chk("srebro_poza_finansami", sy.detect_all("Zdobyłem srebro na zawodach") == [])

# 3. Router widzi, na co odpowiadasz: notowanie (publiczne) i pytanie (tak / nie) modelu w sieci;
#    słowa z odpowiedzi GREGAI nie liczą się jako Twoje; "PIN: 1234" to nie notowanie
import router as rr
h = [{"role": "user", "content": "No dobra, a srebro?"}, {"role": "assistant", "content": "XAGUSD (spot, uncja): 33,10 USD", "tool": True}]
t, w = rr._koryto_routing_context(h, "Za uncję?")
chk("kontekst_notowanie", "33,10 USD" in t and "33,10" not in w)
chk("pin_nie_notowanie", not rr._QUOTE_SPEECH_RE.match("PIN: 1234") and rr._QUOTE_SPEECH_RE.match("SI=F: 33,10 USD"))
c = "Czy mam pobrać aktualne notowanie srebra (XAGUSD)? (tak / nie)"
h = [{"role": "user", "content": "hej"}, {"role": "assistant", "content": c, "sig": rr._chat_sig(c), "provider": "groq"}]
t, w = rr._koryto_routing_context(h, "Tak chce")
chk("kontekst_tak_nie", "XAGUSD" in t and "XAGUSD" not in w)
chk("kontekst_tylko_przy_tak", "XAGUSD" not in rr._koryto_routing_context(h, "opowiedz żart")[0])

# 4. Bramka cen: bez fałszywych alarmów w zwykłych sprawach, z przeliczeniem kursem, liczby wartością
import bramka as bb
def hit(t, z):
    return any(x["kod"] == "cena_bez_zrodla" for x in bb.review(t, zrodla=z)[1])
chk("cena_falszywe_alarmy", not any(hit(t, z) for t, z in (
    ("iPhone 13 sprzedasz za ok. 1500 zł. Zysk to ok. 600 zł.", "kupiłem za 900"),
    ("Kurs angielskiego kosztuje 300 zł.", ""), ("Za dostawy zarobiłeś 450 złotych.", ""),
    ("Złoto: 2405,30 USD za uncję, czyli ok. 9573 zł po kursie 3,98.", "GC=F: 2 405,30 USD\nkurs 3,98"),
    ("Gram złota kosztuje ok. 77,3 USD.", "GC=F: 2405,30 USD"))))
chk("cena_podciag_cyfr", hit("Bitcoin kosztuje teraz 67 000 USD.", "zamówienie 98324001234") and hit("Srebro to $24 za uncję.", "zamówienie 12400, kod 2400"))
out = bb.review("Srebro kosztuje ok. 24 USD za uncję. Daj znać, czy coś jeszcze.", zrodla="")[0]
chk("cena_bez_urwanego_ok", "ok." not in out and "Daj znać" in out)

# 5. Klasyfikator: "Safety Categories" też wycinane; każdy dostawca (nie tylko kształt OpenAI)
import juggler as jj
chk("kategorie_klasyfikatora", rr._sanitize_leaked_tokens("User Safety: unsafe\nSafety Categories: Violence").strip() == ""
    and bool(jj._GUARD_REPLY_RE.match("User Safety: unsafe\nSafety Categories: Violence"))
    and rr._sanitize_leaked_tokens("User safety: najważniejsze jest zdrowie").strip() != "")
import inspect
chk("klasyfikator_kazdy_dostawca", "_GUARD_REPLY_RE.match(text)" in inspect.getsource(jj.chat))

# 6. Zapas notowań metali: tylko sensowna liczba
import tools as tt, netguard as ng, io
class _R(io.BytesIO):
    def __enter__(s): return s
    def __exit__(s, *a): pass
_uo = ng.urlopen
for bad in (True, 1e-9, "33"):
    ng.urlopen = lambda req, **k: _R(json.dumps({"price": bad}).encode())
    chk(f"metal_sens_{bad}", tt._metal_spot("SI=F") is None)
ng.urlopen = _uo

# 7. Planer: redakcja także, gdy zadanie zaczęło się lokalnie, a koryto puszcza zadania przez sieć
import koryto as ko
_t = ko.tasks_via_network
ko.tasks_via_network = lambda: True
seen = {}
def ask(system, user):
    seen.setdefault("u", user); return "GOTOWE: ok"
st = {"goal": "x", "steps": [], "started": __import__("time").monotonic(), "format_failures": 0, "trained": False}
try:
    al._run(None, st, ask, "qwen2.5:3b")
except Exception:
    pass
chk("planer_siec_w_trakcie", st.get("_siec") is True)
ko.tasks_via_network = _t
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA52_CHECK" = "OK" ]; then
  ok 52 "Tura 10: potwierdzenia, srebro, kontekst odpowiedzi, bramka cen, klasyfikator, zapas metali, planer"
else
  bad 52 "Tura 10: ${TURA52_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.6"
fi

# 53. Decyzje 1.32.7: dokładne myślenie jedynym trybem (bez "szybko" i "sam decyduj"), pigułka
#     rozmowy bez "Czuwam" i licznika USD, jednolity przełącznik widoków.
TURA53_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, tempfile
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
tmp = Path(tempfile.mkdtemp(prefix="gregai-check53-"))
ROOT = Path.cwd().parent

# 1. Dokładne myślenie jedynym trybem: stary wpis "wylaczony"/"auto" ignorowany, zapis innego trybu odrzucony
import namysl as nm
nm.STATE_PATH = tmp / "namysl.json"
for old in ("wylaczony", "auto"):
    nm.STATE_PATH.write_text(json.dumps({"tryb": old}))
    chk(f"jeden_tryb_{old}", nm.load_settings()["tryb"] == "zawsze")
try:
    nm.save_settings({"tryb": "wylaczony"})
    chk("zapis_innego_trybu", False)
except ValueError:
    pass
s = nm.load_settings()
chk("namysl_pytania", all(nm.wants(m, settings=s)[0] for m in ("Dziś jest?", "No dobra, a srebro?", "Heja, co dziś mam w planie?")))
chk("namysl_powitania", not any(nm.wants(m, settings=s)[0] for m in ("Heja gregai", "Dziękuję!", "Hej GREGAI, siema")))

# 2. Interfejs: bez wyboru trybu, bez "Czuwam" i licznika USD w pigułce rozmowy; ikony w każdym przełączniku
html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
css = (ROOT / "ui" / "kadr.css").read_text(encoding="utf-8")
chk("ui_bez_trybu", "namysl-mode" not in html and "Zawsze szybko" not in html and "namysl-mode" not in js)
chk("ui_bez_czuwam_usd", "Czuwam" not in js and "z ${Math.round(usd.limit_miesiac)} USD" not in js)
chk("ui_ikony_przelacznika", ".rail-top .segment-switch-btn svg { display: block;" in css)

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA53_CHECK" = "OK" ]; then
  ok 53 "Dokładne myślenie jedynym trybem, pigułka bez Czuwam i USD, jednolity przełącznik"
else
  bad 53 "Decyzje 1.32.7: ${TURA53_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.7"
fi

# 54. Audyt tura 12 (1.32.8): wynik shella i odczytu pliku bez treści dla planera w sieci,
#     zmiana czasu (zadania stałe, straż, zegar), skutki jedynego trybu (temat, notatki, limit
#     czasu, prośby), historia złota i srebra z bieżącą ceną.
TURA54_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import io, json, os, inspect
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. Planer w sieci bez zgody: shell i odczyt pliku przez sys_logs bez treści; dziennik usługi widoczny
import agentloop as al
al._private_material_ok = lambda: False
st = {"goal": "x", "_siec": True, "steps": [
    {"tool": "sys_shell", "arg": "cd notatki && cat *", "ok": True, "observation": "SEKRET_NOTATKI_42"},
    {"tool": "sys_logs", "arg": "notatki/prywatna.md", "ok": True, "observation": "SEKRET_PLIKU_43"},
    {"tool": "sys_logs", "arg": "gregai", "ok": True, "observation": "usluga_startuje_44"}]}
t = al._render_state(st)
chk("sysop_shell_plik", "SEKRET_NOTATKI_42" not in t and "SEKRET_PLIKU_43" not in t and "usluga_startuje_44" in t)

# 2. Zmiana czasu: zadania stałe liczą termin ze strefą; straż czyta przesunięcie z linii; zegar ze strefą
import standing as sd, straz as sz, awareness as aw
chk("standing_strefa", sd._now().tzinfo is not None and sd._parse_iso("2026-10-25T03:20:00").tzinfo is not None)
chk("straz_przesuniecie", sz.line_time("2026-10-25T02:30:00+02:00 sshd") == 1792888200.0
    and sz.line_time("2026-10-25T02:30:00.5+0100 sshd") == 1792891800.0)
chk("zegar_strefa", any(z in aw.cloud_block() for z in (" CET.", " CEST.")))

# 3. Jedyny tryb: prośby z "super/ok/elo" idą przez namysł, grzeczności nie
import namysl as nm
s = {"tryb": "zawsze", "material_do_sieci": False}
chk("prosby_nie_grzecznosc", all(nm.wants(m, settings=s)[0] for m in ("super, zrób to", "elo, plan na dziś", "jasne, dawaj", "wszystko ok?")))
chk("grzecznosci", not any(nm.wants(m, settings=s)[0] for m in ("Heja gregai", "Dziękuję!", "co tam?", "jak się masz?")))

# 4. Router: Namysł dostaje ustalony instrument; notatki bez lokalnego modelu i zgody zostają lokalne;
#    faza lokalna ma limit czasu
import router as rr
src = inspect.getsource(rr._route)
chk("namysl_dostaje_temat", "(dotyczy: {label}" in src and "_synthesize_instead(tool_name, arg)" in src)
chk("notatki_bez_zgody_lokalnie", 'tool_name == "search_brain" and not (model_up or _namysl_settings.get("material_do_sieci") is True)' in src)
chk("faza_lokalna_limit", "NAMYSL_LOCAL_BUDGET_S - (time.monotonic() - _t0)" in src and rr.NAMYSL_LOCAL_BUDGET_S <= 600)

# 5. Historia złota/srebra: przy awarii Yahoo przynajmniej bieżąca cena z zapasu
import tools as tt, netguard as ng
class _R(io.BytesIO):
    def __enter__(s): return s
    def __exit__(s, *a): pass
tt._yahoo_fetch = lambda *a: (_ for _ in ()).throw(ValueError("Edge"))
_uo = ng.urlopen
ng.urlopen = lambda req, **k: _R(json.dumps({"price": 33.1}).encode())
r = tt.market_history("xagusd")
chk("historia_metalu_spot", "33,10" in r["speech"] and (r["card"].get("spot") or {}).get("source") == "gold-api.com")
ng.urlopen = _uo
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA54_CHECK" = "OK" ]; then
  ok 54 "Tura 12: shell bez treści dla planera, zmiana czasu, jedyny tryb bez skutków ubocznych, historia metali"
else
  bad 54 "Tura 12: ${TURA54_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.8"
fi

# 55. Audyt tura 13 (1.32.9): jakość Namysłu (krytyka numerowana, kwoty bez pokrycia, znaczniki,
#     angielska i rozdęta poprawka, kontekst dla recenzenta), aktualizacja (straż po instalatorze,
#     stop bez zapory, cofnięcie wersji, /diagnoza), jednolity interfejs.
TURA55_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, re, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, "/tmp/claude-0/t13") if False else None
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
ROOT = Path.cwd().parent
tmp = Path(tempfile.mkdtemp(prefix="gregai-check55-"))

# 1. Namysł: jakość odpowiedzi (modele podstawione)
import namysl as nm, router as rr
ROZ = "CEL: cena złota\nRODZAJ: wyjaśnienie\nPYTANIA: -\nNOTATKI: -\nPLIKI: -\nSIEC: -\nWIKI: -\nKURS: xauusd\nPULAPKI: liczba"  # wyjaśnienie: recenzent ma wejść (przy fakt od 1.32.14 pomijany)
def run(replies, msg="cena złota?", history=None):
    def cloud(system, msgs, m, exclude=None, prefer=None):
        ph = ("rozpoznanie" if "ROZPOZNANIA" in system else "krytyka" if "recenzentem" in system
              else "szkic" if "etap SZKICU" in system else "poprawa" if "etap POPRAWY" in system else "inne")
        seen.append((ph, m))
        return replies.get(ph, ""), "groq"
    class V:
        notes = {}
        def search(self, q, limit=5): return []
    ctx = nm.Context(vault=V(), message=msg, history_local=history or [], history_cloud=history or [], files=[],
        sys_local="Jesteś GREGAI.", sys_cloud="Jesteś GREGAI.", local_up=False,
        local_chat=lambda s, h, m: cloud(s, h, m)[0], cloud_chat=cloud, cloud_pool=lambda: ["groq", "gemini"],
        research=lambda m: [], search_notes=lambda v, q: [], research_web=lambda q: {"card": {"results": []}, "speech": "brak"},
        wiki_lookup=lambda v, q: {"card": {}}, market_quote=lambda s: {"speech": "XAUUSD: 2412,35 USD", "card": {"data": {"price": 2412.35}}},
        market_history=None, read_page=None, internet_allowed=lambda: (True, ""), sanitize=rr._sanitize_leaked_tokens,
        violates_style=lambda t: [], settings={"tryb": "zawsze", "material_do_sieci": False})
    return nm.run(ctx)["speech"]
seen = []
s = run({"rozpoznanie": ROZ, "szkic": "Złoto kosztuje 2600 USD za uncję.", "krytyka": 'WERDYKT: popraw\n1. "2600 USD" - w materiale jest 2412,35', "poprawa": "Złoto kosztuje 2412,35 USD za uncję (notowanie)."})
chk("krytyka_numerowana", "2412,35" in s and "2600" not in s)
s = run({"rozpoznanie": ROZ, "szkic": "Złoto kosztuje 2600 USD za uncję. To dużo.", "krytyka": "WERDYKT: ok"})
chk("kwota_bez_pokrycia", "2600" not in s and "Pominąłem podaną cenę" in s)
s = run({"rozpoznanie": ROZ, "szkic": "Oto poprawiona wersja odpowiedzi:\n**Pytania pomocnicze:** Jaki budżet?\nZłoto: 2412,35 USD (notowanie).\nWERDYKT: ok", "krytyka": "WERDYKT: ok"})
chk("znaczniki_wewnetrzne", s.strip() == "Złoto: 2412,35 USD (notowanie).")
s = run({"rozpoznanie": ROZ, "szkic": "Złoto kosztuje 2412,35 USD za uncję (notowanie).", "krytyka": "WERDYKT: popraw\n- dodaj źródło",
         "poprawa": "Gold currently costs 2412,35 USD per ounce and is the price of the day with you."})
chk("poprawa_po_angielsku", s.startswith("Złoto kosztuje"))
s = run({"rozpoznanie": ROZ, "szkic": "Złoto: 2412,35 USD (notowanie).", "krytyka": "WERDYKT: popraw\n- dodaj kontekst",
         "poprawa": "Złoto: 2412,35 USD (notowanie). " + "Złoto to metal szlachetny, a jego cena zależy od wielu czynników. " * 6}, msg="cena złota?")
chk("krotkie_pytanie_krotko", len(s) < 120)
seen.clear()
run({"rozpoznanie": ROZ, "szkic": "Srebro: brak danych.", "krytyka": "WERDYKT: ok"}, msg="a srebro?",
    history=[{"role": "user", "content": "cena złota?"}, {"role": "assistant", "content": "Złoto: 2412,35 USD"}])
chk("krytyk_widzi_kontekst", any(ph == "krytyka" and "KONTEKST ROZMOWY" in m and "cena złota" in m for ph, m in seen))
chk("prompty", "fakt |" in nm._ROZPOZNANIE_SYSTEM and "formie męskiej" in nm._SZKIC_SUFFIX and "NIE UDAŁO SIĘ" in nm._SZKIC_SUFFIX)

# 2. Straż: przebudowa plików systemowych przez instalator to nie alarm (ślad w łańcuchu zostaje)
import straz as sz
sz.STRAZ_DIR = tmp / "straz"; sz.STRAZ_DIR.mkdir()
logged = []
sz.log_security = lambda typ, opis: logged.append((typ, opis))
sz._save_base = lambda b: None
base = {"wersja": "x", "porty": [], "pliki": {"/etc/systemd/system/gregai.service": "a", "/etc/crontab": "c"}}
cur = {"wersja": "x", "porty": [], "pliki": {"/etc/systemd/system/gregai.service": "b", "/etc/crontab": "d"}}
an = sz.diff(base, cur, 0)
(sz.STRAZ_DIR / "instalacja").write_text("")
left, nb = sz._after_install(an, base, cur)
chk("straz_instalator", [a for a in left if "gregai.service" in a["klucz"]] == [] and any("crontab" in a["klucz"] for a in left)
    and logged and logged[0][0] == "instalacja" and not (sz.STRAZ_DIR / "instalacja").exists())
left2, _ = sz._after_install(an, base, cur)
chk("straz_bez_znacznika", any("gregai.service" in a["klucz"] for a in left2))

# 3. Instalacja/aktualizacja: bez zapory stara usługa zatrzymana; cofnięcie wersji zdejmuje strefę
inst = (ROOT / "install.sh").read_text(encoding="utf-8")
akt = (ROOT / "aktualizuj.sh").read_text(encoding="utf-8")
chk("brak_zapory_stop", 'need_sudo systemctl stop gregai' in inst.split('if [ "$KILL_OK" != 1 ]; then', 1)[1][:600]
    and len(re.findall(r"(?m)^straz_mark\b.*\n(?:#[^\n]*\n)*(?:if )?need_sudo systemctl restart gregai", inst)) == 2)
chk("cofniecie_wersji", "downgrade_compat" in akt.split("restore_code() {", 1)[1][:600] and "STARSZĄ wersję" in akt)
import subprocess
d = tmp / "g"; (d / "data" / "standing_tasks").mkdir(parents=True)
(d / "VERSION").write_text("1.32.3\n")
(d / "data" / "standing_tasks" / "z.md").write_text("nastepne_sprawdzenie: 2026-10-25T10:00:00+01:00\nostatnie_sprawdzenie: 2026-10-25T09:30:00+01:00\ninne: 2026-10-25T10:00:00+01:00\n")
fn = akt[akt.index("downgrade_compat() {"):akt.index("restore_code() {")]
subprocess.run(["bash", "-c", fn + f'\nROOT="{d}"; downgrade_compat'], check=False)
txt = (d / "data" / "standing_tasks" / "z.md").read_text()
chk("cofniecie_strefa", "nastepne_sprawdzenie: 2026-10-25T10:00:00\n" in txt and "ostatnie_sprawdzenie: 2026-10-25T09:30:00\n" in txt and "inne: 2026-10-25T10:00:00+01:00" in txt)
import diagnoza as dg
chk("diagnoza_wymuszenie", "ExecStartPre=\\+/usr/sbin/nft" in Path(dg.__file__).read_text(encoding="utf-8"))

# 4. Interfejs: jednolite tytuły, przełącznik i etykiety; okienko na telefonie; bez emoji w zakładkach
css = (ROOT / "ui" / "kadr.css").read_text(encoding="utf-8")
html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
chk("ui_dim_nadzorca", "--text-dim: var(--text-dim)" not in css and "--text-dim: #ab947e" in css)
chk("ui_popover_telefon", ".namysl-popover { right: auto; left: 0; }" in css)
chk("ui_jednolite", "#debug-segment .debug-head .lt { order: 0; }" in css and "flex-direction: column; align-items: flex-start" in css
    and html.count(">Twój asystent<") == 0 and "Nowy węzeł" not in html and 'aria-selected="true"><span' not in html)

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA55_CHECK" = "OK" ]; then
  ok 55 "Tura 13: jakość Namysłu, bezpieczna aktualizacja i cofnięcie, jednolity interfejs"
else
  bad 55 "Tura 13: ${TURA55_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.9"
fi

# 56. Audyt tura 14 (1.32.10): kosz notatek z cofnięciem, tytuły save_note, limity połączeń i
#     blokady tokenu, liniowy odczyt XLSX z uczciwym ucięciem, PDF z powodem, maskowanie kluczy,
#     memory/ nie jest plikiem do analizy, komendy z interpunkcją, oszczędniejsze Węzły i Ollama.
TURA56_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
fails=[]
def chk(n,c):
    if not c: fails.append(n)
# --- notatki (audyt tura 14) ---
import tempfile as _tf
from pathlib import Path as _P
import fsutil as _fs, main as _mm, data as _dm, vault as _vv, tools as _tt, memory as _me
_tmp = _P(_tf.mkdtemp(prefix="gregai-check56-"))
_root = _tmp / "notatki"; (_root / "wiedza").mkdir(parents=True)
(_root / "kawa.md").write_text("# Kawa\n\nMoja notatka.\n", encoding="utf-8")
(_root / "inna.md").write_text("# Inna\n\nZob. [[Kawa]].\n", encoding="utf-8")
_dm.get_vault_roots = lambda: [str(_root)]
_dm.WIEDZA_ROOT = str(_root / "wiedza")
_mm.TRASH_DIR = _tmp / "data" / "kosz"
_mm.invalidate_vault_cache()
# 1. Usunięcie = kosz, przywrócenie wraca plik; nie nadpisuje istniejącego
_name = _fs.move_to_trash(_root / "kawa.md", _mm.TRASH_DIR, str(_root / "kawa.md"))
chk("kosz_przeniesione", not (_root / "kawa.md").exists() and (_mm.TRASH_DIR / _name).exists())
chk("kosz_przywroc", _mm.restore_from_trash(_name)["restored"] and (_root / "kawa.md").read_text(encoding="utf-8").startswith("# Kawa"))
for _bad in ("../x", "a/b", "x.json", ""):
    try:
        _mm.restore_from_trash(_bad); chk(f"kosz_zla_nazwa_{_bad}", False)
    except (ValueError, FileNotFoundError):
        pass
chk("usun_do_kosza", "fsutil.move_to_trash(note.path, TRASH_DIR" in _P(_mm.__file__).read_text(encoding="utf-8")
    and "unlink(missing_ok=True)\n            invalidate_vault_cache()\n            self._send_json({\"deleted\"" not in _P(_mm.__file__).read_text(encoding="utf-8"))
# 2. save_note: tytuł Twojej notatki zajęty -> dopisek; znaki [ ] | # wycięte
_mm.invalidate_vault_cache()
_r = _tt.save_note("Kawa", "Kawa to napój.")
chk("save_note_kolizja", "(z rozmowy)" in _r["speech"] and (_root / "kawa.md").read_text(encoding="utf-8").startswith("# Kawa\n\nMoja"))
_r = _tt.save_note("C# | [[x]] podstawy", "Treść.")
_f = _root / "wiedza" / _r["card"]["file"]
chk("save_note_znaki", not any(c in _f.read_text(encoding="utf-8").splitlines()[0][2:] for c in "[]|#"))
# 3. Typ "Projekt" po polsku to projekt; pamięć czyta pliki z BOM
chk("typ_projekt", _vv.find_type("# T\ntype: Projekt\n") == _vv.PROJECT_TYPE)
_me.MEMORY_DIR = _tmp / "memory"; _me.MEMORY_DIR.mkdir()
_a = _me.remember("lubię herbatę z cytryną")
_p = _P(_a[1]) if isinstance(_a, tuple) and len(_a) > 1 and isinstance(_a[1], str) and _a[1].endswith(".md") else next(_me.MEMORY_DIR.glob("*.md"))
_p.write_bytes(b"\xef\xbb\xbf" + _p.read_bytes())
_b = _me.remember("lubię herbatę z cytryną")
chk("pamiec_bom", len(list(_me.MEMORY_DIR.glob("*.md"))) == 1)
chk("wspolna_blokada", _mm._NOTE_LOCK is _fs.NOTES_LOCK)
import shutil as _sh
_sh.rmtree(_tmp, ignore_errors=True)
# --- API (audyt tura 14) ---
import threading as _th, io as _io, zipfile as _zf, time as _time, re as _re
import main as _m2
_S = _m2.BoundedServer.__new__(_m2.BoundedServer)
_S._slots = _th.BoundedSemaphore(_m2.BoundedServer.MAX_CONNECTIONS - _m2.BoundedServer.LOCAL_RESERVED)
_S._local_slots = _th.BoundedSemaphore(_m2.BoundedServer.LOCAL_RESERVED)
_S._per_ip = {}; _S._per_ip_lock = _th.Lock()
chk("api_limit_na_adres", sum(1 for _ in range(30) if _S._take(("192.0.2.2", 1))) == _m2.BoundedServer.PER_IP_MAX)
for _i in range(400):
    _S._take((f"10.1.{_i // 200}.{_i % 200}", 1))
chk("api_miejsca_dla_laptopa", _S._take(("127.0.0.1", 1)) is not None)
_src = _P(_m2.__file__).read_text(encoding="utf-8")
chk("api_brak_tokenu_nie_liczy", 'if not self.headers.get("X-Gregai-Token"):' in _src and "_AUTH_FAILS.pop(ip, None)  # 1.32.10" in _src)
chk("api_klucz_tunelu", 'return "cf:" + cf' in _src and "host in tunnel" in _src)
chk("api_restart_odstep", "now - _LAST_RESTART < 30" in _src)
import sources as _so
chk("wgrane_limit", _so.MAX_UPLOADS_TOTAL_BYTES <= 2 * 1024 ** 3 and "MAX_UPLOADS_TOTAL_BYTES" in _P(_so.__file__).read_text(encoding="utf-8").split("def save_upload", 1)[1][:1200])

# --- pliki (audyt tura 14) ---
import analiza as _an
def _xlsx(shared, sheet):
    b = _io.BytesIO()
    with _zf.ZipFile(b, "w", _zf.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", shared); z.writestr("xl/worksheets/sheet1.xml", sheet)
    return b.getvalue()
_t0 = _time.monotonic(); _an._xlsx_text(_xlsx("<si>" * 100000, "<row><c><v>1</v></c></row>"))
chk("xlsx_liniowo", _time.monotonic() - _t0 < 5)
_rows = "".join(f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, 2100))
_d = _tmp2 = _P(_tf.mkdtemp(prefix="gregai-check56b-")); (_d / "a.xlsx").write_bytes(_xlsx("<sst/>", _rows))
_r = _an.read_document(str(_d / "a.xlsx"))
chk("xlsx_uczciwe_uciecie", _r.get("truncated") is True and "2000" in str(_r.get("meta", {}).get("uciete", "")))
(_d / "e.pdf").write_bytes(b"%PDF-1.4\n1 0 obj<</Encrypt 2 0 R>>endobj\ntrailer<</Encrypt 2 0 R>>\n%%EOF")
chk("pdf_zaszyfrowany", "zaszyfrowany" in _an.read_document(str(_d / "e.pdf")).get("why", ""))
(_d / "k.txt").write_text("klucz sk-ant-api03-" + "A" * 40 + " koniec", encoding="utf-8")
chk("plik_klucze_maskowane", "sk-ant-api03-AAAA" not in _an.read_document(str(_d / "k.txt")).get("text", ""))
chk("ramka_czesci", "re.sub(r'[<>]{3,}', ' ', chunk)" in _P(_an.__file__).read_text(encoding="utf-8"))
_sh.rmtree(_d, ignore_errors=True)
chk("pamiec_nie_plik", "data_mod.MEMORY_ROOT).resolve(), (Path(data_mod.PROJECT_ROOT) / \"agent\")" in _P(_so.__file__).read_text(encoding="utf-8"))
import komendy as _ko
chk("komendy_interpunkcja", _ko.parse("/plan: strona www") == ("plan", "strona www") and _ko.parse("/pomoc!") == ("pomoc", "") and _ko.parse("/home/x") is None)
import namysl as _nm
chk("badaj_siec", '"## Tryb: BADANIE" in (ctx.sys_cloud' in _P(_nm.__file__).read_text(encoding="utf-8"))

# --- energia (audyt tura 14) ---
_g = (_P(_m2.__file__).parent.parent / "ui" / "graph.js").read_text(encoding="utf-8")
chk("wezly_bez_pulsu_w_spoczynku", "const ORBIT_IDLE_MS = 20000;" in _g and "performance.now() - (this._lastInput || 0) > ORBIT_IDLE_MS) { this._schedulePulse(); return; }" in _g)
_inst = (_P(_m2.__file__).parent.parent / "install.sh").read_text(encoding="utf-8")
chk("ollama_pamiec", all(x in _inst for x in ("OLLAMA_MAX_LOADED_MODELS=2", "OLLAMA_KV_CACHE_TYPE=q8_0", "OLLAMA_FLASH_ATTENTION=1", "OOMScoreAdjust=500")))
import straz as _sz, trace as _tr
_calls = []
import subprocess as _sp
_run = _sp.run
_sp.run = lambda *a, **k: (_calls.append(1), type("R", (), {"stdout": ""})())[1]
_sz._read_tail = lambda p: []
_sz._JOURNAL_CACHE.update(t=-1e9, n=0)
for _ in range(5):
    _sz.failed_logins_recent()
_sp.run = _run
chk("journalctl_rzadziej", len(_calls) <= 1)
chk("slad_bez_wciec", 'separators=(",", ":")' in _P(_tr.__file__).read_text(encoding="utf-8"))
print("OK" if not fails else "FAIL "+",".join(fails))
PY
)"
if [ "$TURA56_CHECK" = "OK" ]; then
  ok 56 "Tura 14: kosz notatek, bezpieczniejsze API, odporny odczyt plików, mniej prądu"
else
  bad 56 "Tura 14: ${TURA56_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.10"
fi

# 57. Audyt tura 15 (1.32.11): zadania stałe (duplikaty, limit, interwały, alert bez adresów),
#     uczenie bez zatrucia (parafraza, darmowa pula, wygasanie, "Zapomnij"), strony z sieci
#     (status HTTP, przekierowania, kodowanie), izolacja projektów (narzędzia plików, remis linków).
TURA57_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import io, json, re, sys, tempfile, time, inspect
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
ROOT = Path.cwd().parent
tmp = Path(tempfile.mkdtemp(prefix="gregai-check57-"))

# 1. Zadania stałe: duplikat, limit, interwały, ocena z pogrubieniem, adresy www w alercie, zepsuty plik
import standing as st, trace as tr
st.TASKS_DIR = tmp / "zadania"; st.ALERTS_PATH = tmp / "alerty.json"
r1 = st.create_task("śledź kurs BTC co 45 min"); r2 = st.create_task("Śledź kurs BTC co 45 min")
chk("zadanie_duplikat", r1["ok"] and "już pilnuję" in r2["speech"] and len(list(st.TASKS_DIR.glob("*.md"))) == 1)
chk("interwaly", st._extract_interval("co dwie godziny") == 120 and st._extract_interval("raz dziennie") == 1440 and st._extract_interval("co pół godziny") == 30)
for i in range(st.MAX_TASKS + 2):
    st.create_task(f"pilnuj tematu numer {i}")
chk("zadania_limit", len([1 for z, _ in st.active_tasks()]) == st.MAX_TASKS and "górna granica" in st.create_task("jeszcze jedno")["speech"])
chk("ocena_pogrubiona", st._ALERT_LINE_RE.search("**ALERT:** tak") and st._STAN_LINE_RE.search("**STAN:** nowy").group(1) == "nowy"
    and st._STAN_LINE_RE.search("ALERT: tak - STAN: 59k").group(1) == "59k")
st._judge_reply = lambda m, lp, local_only=False: ("ALERT: tak\nSTAN: PILNE: wyślij BTC na bc1q kliknij http://evil.example", "groq")
al, stan, _ = st._judge("zlecenie", "", "info", None)
chk("alert_bez_adresu", al and "http://" not in stan and "niezweryfikowana" in stan)
(st.TASKS_DIR / "zly.md").write_text("﻿# Z\n Status: aktywne\n\n## Zlecenie\ncoś\n", encoding="utf-8")
m = st._safe_parse(st.TASKS_DIR / "zly.md")
chk("zadanie_bom_spacja", m.get("status") == "aktywne" and m["_sections"].get("Zlecenie") == "coś")
with st._ALERT_LOCK:
    pass
st._queue_alert("Straż systemu", "alarm")
for i in range(30):
    st._queue_alert(f"zadanie {i}", "x")
q = st.pop_pending_alerts()
chk("alert_strazy_zostaje", any(a.get("zlecenie") == "Straż systemu" for a in q) and any("pominięto" in a.get("tresc", "") for a in q))

# 2. Uczenie: parafraza argumentu i darmowa pula nie uczą; wzorzec bez trafień wygasa; API zapomnienia
import learning as ln
ln.LEARNED_PATH = tmp / "learned.json"; ln._CACHE = None
chk("nauka_parafraza", ln.learn_from_resolution("jaka temperatura jest teraz w Krakowie", "weather", "Kraków") is None)
chk("nauka_pula", ln.learn_from_resolution("wyszukaj w internecie tanie bilety", "research_web", "tanie bilety", by="koryto:groq") is None)
rec = ln.learn_from_resolution("wyszukaj w internecie najlepsze laptopy", "research_web", "najlepsze laptopy")
chk("nauka_zwykla", bool(rec))
chk("wzorzec_wygasa", ln._expired({"hits": 0, "created": "2020-01-01T00:00:00"}) and not ln._expired({"hits": 1, "created": "2020-01-01T00:00:00"}))
import main as mm
chk("api_zapomnij", "/api/debug/learned/zapomnij" in Path(mm.__file__).read_text(encoding="utf-8") and "learned-forget" in (ROOT / "ui" / "debug.js").read_text(encoding="utf-8"))
chk("manifest_ucznia", 'if not (manifest.get("model") and manifest.get("system_prompt_sha1"))' in Path(sys.modules["router"].__file__).read_text(encoding="utf-8") if "router" in sys.modules else True)
import router as rr
chk("manifest_ucznia2", 'manifest.get("system_prompt_sha1"))' in inspect.getsource(rr._student_manifest_ok))
bd = (ROOT / "training" / "build_distill_dataset.py").read_text(encoding="utf-8")
chk("destylacja_zaufani", "TRUSTED_PROVIDERS" in bd and '"provider": r.get("provider")' in bd)

# 3. Sieć: status HTTP i kodowanie stron, przekierowania, tytuły z sieci z limitem, Wikipedia bez ujednoznacznień
import netguard as ng, tools as tt
chk("kodowanie_cp1250", ng.decode_html("Zażółć".encode("cp1250"), "text/html; charset=windows-1250") == "Zażółć"
    and ng.decode_html("Łódź".encode("cp1250"), "") == "Łódź")
tt.netguard_mod.fetch_via_curl = lambda url, **k: ("<h1>404 Not Found</h1>Nie znaleziono", {"status": 404, "content_type": "text/html", "redirect_url": ""})
chk("strona_404", tt.fetch_page_text("https://x.test/a").get("ok") is False and "HTTP 404" in tt.fetch_page_text("https://x.test/a").get("error", ""))
hops = []
def _redir(url, **k):
    hops.append(url)
    return ("", {"status": 301, "content_type": "", "redirect_url": "https://x.test/b"}) if url.endswith("/a") else ("<title>B</title><p>Treść B</p>", {"status": 200, "content_type": "text/html; charset=utf-8", "redirect_url": ""})
tt.netguard_mod.fetch_via_curl = _redir
r = tt.fetch_page_text("https://x.test/a")
chk("strona_przekierowanie", r.get("ok") and r.get("title") == "B" and hops == ["https://x.test/a", "https://x.test/b"])
tt.netguard_mod.fetch_via_curl = lambda url, **k: ("", {"status": 302, "content_type": "", "redirect_url": "http://127.0.0.1/"})
chk("przekierowanie_lokalne", tt.fetch_page_text("https://x.test/a").get("error") == "PrzekierowanieZablokowane")
chk("tytul_limit", "[:200]" in inspect.getsource(tt._parse_ddg).split("title = _strip_tags(inner)", 1)[1][:10])
chk("wiki_ujednoznacznienie", '"disambiguation"' in inspect.getsource(tt._wiki_fetch_summary))
chk("strip_tags_spacja", tt._strip_tags("<b>A</b>B<!-- tajne -->") == "A B")
import siec as sc
chk("siec_inny_host", "#" in inspect.getsource(sc) and 'key = f"{d[\'ip\']}#{d[\'hostname\'].lower()}"' in inspect.getsource(sc))

# 4. Projekty: narzędzia plików nie czytają notatek/rozmów; remis linków nie łączy projektów; rozmowa bez śmieci
import sysop as so, vault as vv, rozmowa as rz
chk("fs_zamkniete", so.resolve_in_roots("notatki/x.md") is None and so.resolve_in_roots("data/rozmowy/a.json") is None
    and so.resolve_in_roots("memory/f.md") is None and so.resolve_in_roots("README.md") is not None)
chk("fs_search_exclude", '"--exclude-dir=" + d for d in ("notatki", "memory", "rozmowy"' in inspect.getsource(so))
chk("remis_linkow", "and not owners[nb]:" in inspect.getsource(vv.Vault))
rz.ROZMOWY_DIR = tmp / "rozmowy"; rz.ROZMOWY_DIR.mkdir()
(rz.ROZMOWY_DIR / "c1.json").write_text(json.dumps({"tury": ["string", 5, {"role": "user", "tekst": "ok", "t": ""}]}), encoding="utf-8")
chk("rozmowa_zepsute_tury", len(rz._load("c1")["tury"]) == 1)
(rz.ROZMOWY_DIR / "c1.json.corrupt-x").write_text("{}", encoding="utf-8")
rz.delete("c1")
chk("rozmowa_usun_kwarantanne", not list(rz.ROZMOWY_DIR.glob("c1.json*")))

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA57_CHECK" = "OK" ]; then
  ok 57 "Tura 15: zadania stałe, uczenie bez zatrucia, uczciwe strony z sieci, izolacja projektów"
else
  bad 57 "Tura 15: ${TURA57_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.11"
fi

# 58. Audyt tura 16 (1.32.12): SYSOP (sufiks .SERVICE), instalator bez cichych urwań, praca
#     offline (TOOL: i angielski szkic, internet zablokowany wprost), koryto (budżet w błędach,
#     recenzent z tego samego etapu, dokończenie bez dubla, odporny dziennik, Retry-After jako data).
TURA58_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, re, sys, tempfile, time, inspect
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
ROOT = Path.cwd().parent
tmp = Path(tempfile.mkdtemp(prefix="gregai-check58-"))

# 1. SYSOP: sufiks .SERVICE wielkimi literami nie omija listy chronionych usług
import sysop as so
_cls = so.classify_shell if hasattr(so, "classify_shell") else so._classify
chk("sysop_service_wielkie", all(_cls(c)[0] == "destructive" for c in ("sudo systemctl stop warp-svc.SERVICE", "systemctl disable Ufw.Service", "systemctl mask nftables.SERVICE", "systemctl enable foo.SERVICE"))
    and _cls("systemctl status warp-svc.SERVICE")[0] == "read")

# 2. Instalator: błędy kroków nie urywają po cichu, kontrola końcowa wpływa na wynik, IPv6 DNS w zaporze
inst = (ROOT / "install.sh").read_text(encoding="utf-8")
chk("install_restart_warn", 'if need_sudo systemctl restart gregai; then' in inst and inst.count("HEALTH_FAIL=1") >= 4)
chk("install_pull_warn", 'ollama pull "$MODEL" || {' in inst and 'systemctl enable gregai >/dev/null 2>&1 || warn' in inst)
chk("install_check_wynik", 'CHECK_FAIL=1' in inst and 'kontrola zgłosiła błędy' in inst)
chk("install_ipv6_dns", 'ip6 daddr { fe80::/10, fc00::/7 } meta l4proto { tcp, udp } th dport 53 counter drop' in inst)

# 3. Offline: gołe TOOL: i nagłówki modelu znikają, szkic po angielsku odrzucony, "fakt" rozpoznawany,
#    internet zablokowany powiedziany wprost, recenzja bez WERDYKT = brak recenzji
import router as rr, namysl as nm
chk("sanitize_tool", rr._sanitize_leaked_tokens("# Response\n\nSure! Here is.\nTOOL: search_brain | notes") == "Sure! Here is."
    and rr._sanitize_leaked_tokens("Dziś.\n**TOOL:** market_quote | xauusd") == "Dziś." and "# Plan dnia" in rr._sanitize_leaked_tokens("# Plan dnia\nRano"))
chk("plan_fakt", nm.parse_plan("CEL: x\nRODZAJ: fakt\n", "x").rodzaj == "fakt")
def run(replies, msg, net=True):
    seen = []
    def cloud(system, msgs, m, exclude=None, prefer=None):
        ph = ("rozpoznanie" if "ROZPOZNANIA" in system else "krytyka" if "recenzentem" in system else "szkic" if "etap SZKICU" in system else "poprawa" if "etap POPRAWY" in system else "inne")
        seen.append(ph); return replies.get(ph, ""), "groq"
    class V:
        notes = {}
        def search(self, q, limit=5): return []
    ctx = nm.Context(vault=V(), message=msg, history_local=[], history_cloud=[], files=[], sys_local="Jesteś GREGAI.", sys_cloud="Jesteś GREGAI.",
        local_up=False, local_chat=lambda s, h, m: cloud(s, h, m)[0], cloud_chat=cloud, cloud_pool=lambda: ["groq", "gemini"], research=lambda m: [],
        search_notes=lambda v, q: [], research_web=lambda q: {"card": {"results": []}, "speech": ""}, wiki_lookup=lambda v, q: {"card": {}},
        market_quote=lambda s: {"speech": "XAUUSD: 2412,35 USD", "card": {"data": {"price": 2412.35}}}, market_history=None, read_page=None,
        internet_allowed=lambda: (net, "" if net else "WARP rozłączony"), sanitize=rr._sanitize_leaked_tokens, violates_style=lambda t: [],
        settings={"tryb": "zawsze", "material_do_sieci": False})
    return nm.run(ctx), seen
ROZ = "CEL: cena złota\nRODZAJ: wyjaśnienie\nPYTANIA: -\nNOTATKI: -\nPLIKI: -\nSIEC: -\nWIKI: -\nKURS: xauusd\nPULAPKI: liczba"  # wyjaśnienie: recenzent ma wejść (przy fakt od 1.32.14 pomijany)
r, _ = run({"rozpoznanie": ROZ, "szkic": "Złoto kosztuje 2600 USD. Warto obserwować trend.", "krytyka": "WERDYKT: ok"}, "kurs złota", net=False)
chk("offline_wprost", r is not None and r["speech"].startswith("Internet jest teraz dla mnie zablokowany") and "2600" not in r["speech"])
r, _ = run({"rozpoznanie": ROZ, "szkic": "Sure! Here is the answer you need with the price of gold today."}, "kurs złota")
chk("szkic_angielski", r is None)
r, seen = run({"rozpoznanie": ROZ, "szkic": "Złoto: 2412,35 USD (notowanie).", "krytyka": "Looks fine to me, no issues.", "poprawa": "ZMIENIONE"}, "kurs złota")
chk("krytyka_bez_werdyktu", r["speech"].startswith("Złoto: 2412,35") and "poprawa" not in seen
    and any(f.get("nazwa") == "krytyka" and f.get("uwaga") == "brak" for f in r["card"]["fazy"]))
chk("rozpoznanie_historia_lokalna", "_hist_for_plan = ctx.history_cloud if models.may_use_cloud(False) else ctx.history_local" in inspect.getsource(nm.run))
chk("rozgrzewka_zwiezly_prompt", "awareness_mod.local_prompt(get_system_prompt(), get_vault())" in (ROOT / "agent" / "main.py").read_text(encoding="utf-8"))
chk("krytyka_tylko_gdy_czas", "narr.elapsed() + 2 * (_draft_s or 0) > TIME_BUDGET" in inspect.getsource(nm.run))

# 4. Koryto: powód budżetu w błędach, recenzent z tego samego etapu, dokończenie bez dublowania,
#    zepsuty licznik w dzienniku nie wywraca łańcucha, Retry-After jako data
import juggler as jj
jj.JOURNAL_PATH = tmp / "koryto.json"
jj.JOURNAL_PATH.write_text(json.dumps({"dzien": time.strftime("%Y-%m-%d", time.gmtime()), "miesiac": time.strftime("%Y-%m", time.gmtime()), "usd_dzien": 0, "usd_miesiac": 0, "wywolania": {"anthropic": "abc", "groq": [1]}}))
jj._JOURNAL.clear(); jj._JOURNAL_LOADED = False
try:
    jj._journal_load_locked()
    chk("dziennik_zly_licznik", jj._JOURNAL.get("wywolania", {}).get("anthropic") == 0 and jj._calls_today("anthropic") >= 0)
except Exception:
    chk("dziennik_zly_licznik", False)
_long = "Pierwsze zdanie odpowiedzi jest tutaj. " * 4 + "Koniec urwany"
chk("dokonczenie_bez_dubla", jj._join_continuation(_long, _long + " i dalsza część.").count("Pierwsze zdanie") == 4)
class _E(Exception):
    headers = {"Retry-After": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 40))}
chk("retry_after_data", 30 <= (jj._retry_after_seconds(_E()) or 0) <= 45)
src = inspect.getsource(jj.chat)
chk("budzet_w_bledach", 'errors.append(f"{n}:pominięty, " + (over_budget(n) or "limit dzienny wyczerpany"))' in src)
chk("recenzent_ten_sam_etap", "same_stage = [n for n in others if _ETAP.get(n) == _ETAP.get(exclude_provider)]" in src)
chk("kontynuacja_rstrip", 'partial.rstrip()' in inspect.getsource(jj._continued))
chk("bez_modelu_powod", "_no_model_note(_koryto_errors)" in inspect.getsource(rr._route))

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA58_CHECK" = "OK" ]; then
  ok 58 "Tura 16: SYSOP bez obejścia, instalator uczciwy, offline bez śmieci w odpowiedzi, koryto odporne"
else
  bad 58 "Tura 16: ${TURA58_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.12"
fi

# 59. Rozmowa 25.10 wieczorem (1.32.13): cena bez dopytywania o walutę, "w pln" i "a SOL?" z
#     kontekstem, kwoty w przykładach nie są cenami rynkowymi, LaTeX zamieniany na tekst,
#     HuggingFace 402 wyłączony do restartu, BONK znany.
ROZMOWA59_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import re, inspect
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
import router as rr, namysl as nm, juggler as jj, symbols as sy, tools as tt

# 1. LaTeX zamieniany na zwykły tekst
chk("latex_prosty", rr.strip_latex(r"\(100,62 \times 3,92800 \approx 395,24\) PLN.") == "100,62 × 3,92800 ≈ 395,24 PLN.")
chk("latex_wzor", "(-b±√(b^2-4ac))/(2a)" in rr.strip_latex(r"\[ x=\frac{-b\pm\sqrt{b^2-4ac}}{2a} \]") and rr.strip_latex(r"\[\boxed{x=2 \;\text{lub}\; x=3}\]").strip() == "x=2 lub x=3")
chk("latex_nie_rusza", rr.strip_latex("Ścieżka C:\\Users\\x") == "Ścieżka C:\\Users\\x" and rr.strip_latex("Zwykłe zdanie.") == "Zwykłe zdanie.")

def run(replies, msg, hist=None):
    def cloud(system, msgs, m, exclude=None, prefer=None):
        ph = ("rozpoznanie" if "ROZPOZNANIA" in system else "krytyka" if "recenzentem" in system else "szkic" if "etap SZKICU" in system else "poprawa")
        return replies.get(ph, ""), "groq"
    class V:
        notes = {}
        def search(self, q, limit=5): return []
    quotes = {"xauusd": 2412.35, "solusd": 100.62, "usdpln": 3.928}
    ctx = nm.Context(vault=V(), message=msg, history_local=hist or [], history_cloud=hist or [], files=[], sys_local="S", sys_cloud="S", local_up=False,
        local_chat=lambda s, h, m: cloud(s, h, m)[0], cloud_chat=cloud, cloud_pool=lambda: ["groq"], research=lambda m: [], search_notes=lambda v, q: [],
        research_web=lambda q: {"card": {"results": []}, "speech": ""}, wiki_lookup=lambda v, q: {"card": {}},
        market_quote=lambda s: {"speech": f"{s}: {quotes.get(s)}", "card": {"data": {"price": quotes.get(s)}}} if s in quotes else {"ok": False, "speech": "x", "card": {}},
        market_history=None, read_page=None, internet_allowed=lambda: (True, ""), sanitize=rr._sanitize_leaked_tokens, violates_style=lambda t: [],
        settings={"tryb": "zawsze", "material_do_sieci": False})
    r = nm.run(ctx); return (r["speech"], r["card"]["zrodla"]) if r else (None, None)
ROZ = "CEL: cena\nRODZAJ: fakt\nPYTANIA: -\nNOTATKI: -\nPLIKI: -\nSIEC: -\nWIKI: -\nKURS: -\nPULAPKI: x"
# 2. Pytanie o cenę: liczba z notowania zamiast pytania o walutę
s, z = run({"rozpoznanie": ROZ, "szkic": "Czy chcesz cenę złota w USD czy w PLN?", "krytyka": "WERDYKT: ok"}, "Heyaaa, cena zlota")
chk("cena_bez_dopytywania", s.startswith("XAUUSD: 2412,35 USD") and "Czy chcesz" not in s and z == ["notowanie: xauusd"])
# 3. "w pln" po pytaniu o złoto: kurs USD/PLN z notowania, przeliczenie zostaje
h = [{"role": "user", "content": "Heyaaa, cena zlota"}, {"role": "assistant", "content": "XAUUSD: 2412,35 USD"}]
s, z = run({"rozpoznanie": ROZ, "szkic": "Złoto: 2412,35 USD, po kursie 3,928 to 9475,70 zł za uncję.", "krytyka": "WERDYKT: ok"}, "w pln", h)
chk("w_pln", "9475,70" in s and z == ["notowanie: xauusd", "notowanie: usdpln"])
# 4. "a SOL?" z kontekstem finansowym w poprzedniej wiadomości i pamięcią o PLN
h2 = h + [{"role": "user", "content": "w pln"}, {"role": "assistant", "content": "9475,70 zł"}]
s, z = run({"rozpoznanie": ROZ, "szkic": "SOL kosztuje 100,62 USD (notowanie), czyli 395,24 zł.", "krytyka": "WERDYKT: ok"}, "ahaaa, a SOL?", h2)
chk("a_sol", "395,24" in s and "USDPLN" not in s and set(z) == {"notowanie: solusd", "notowanie: usdpln"})
# 5. Kwoty w przykładach nie są cenami rynkowymi; zmyślona cena instrumentu znika bez echa liczby
s, z = run({"rozpoznanie": ROZ, "szkic": "1. Oblicz, ile zaoszczędzę odkładając 200 zł miesięcznie.\n2. Jaka jest cena złota? Złoto kosztuje 2600 USD.", "krytyka": "WERDYKT: ok"}, "podaj 2 pytania testowe")
chk("kwota_przyklad", "200 zł" in s and "2600" not in s and "Pominąłem podaną cenę" in s)
# 6. HF 402 wyłącza dostawcę do restartu; BONK znany; prompt: wołacz i bez LaTeX
class _E(Exception):
    code = 402
jj.reset_breakers()
chk("hf_402", "402" in jj.note_failure("huggingface", _E()) and jj.breaker_state("huggingface")["stan"] == "wylaczony")
chk("bonk", sy.detect_all("cena bonk") == ["bonkusd"] and "bonk" in tt._CRYPTO_PAIRS)
chk("prompt_wolacz_latex", "„Grzegorzu”" in nm._SZKIC_SUFFIX and "bez LaTeX" in nm._SZKIC_SUFFIX and "NIE pytaj o walutę" in nm._SZKIC_SUFFIX)
chk("finish_latex", "normalize_dashes(strip_latex(result[\"speech\"]))" in inspect.getsource(rr._route))
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$ROZMOWA59_CHECK" = "OK" ]; then
  ok 59 "Rozmowa 25.10: ceny bez dopytywania, przeliczenia na PLN z notowania, bez LaTeX, bez echa zmyślonych cen"
else
  bad 59 "Rozmowa 25.10: ${ROZMOWA59_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.13"
fi

# 60. Audyt tura 17 (1.32.14): typografia (łączniki, wąskie spacje), źródła raz, pogrubienie per
#     linia, wołacz, formułki, pytania pomocnicze z numerem, błędy dostawców po polsku, tańszy
#     Namysł (fakt bez recenzenta, notowanie bez wyszukiwarki, twórcze bez sieci, juniorzy od wagi 3,
#     grunty), późna odpowiedź za swoim pytaniem, idempotencja z treścią.
TURA60_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import re, inspect, threading
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
ROOT = Path.cwd().parent
import router as rr, bramka as bb, namysl as nm, main as mm

# 1. Typografia: łącznik nierozdzielający, wąska spacja przed %, literówka poleceń, "ogólna wiedza" to nie źródło
chk("typografia", rr.normalize_typography("4‑tygodniowy, 70‑80 %, apt‑get; sudo aptsudo apt autoremove. Fakt (Źródło: ogólna wiedza o X).")
    == "4-tygodniowy, 70-80%, apt-get; sudo apt autoremove. Fakt.")
chk("zrodla_raz", rr.collapse_repeated_sources("- A (Wikipedia: x)\n- B (Wikipedia: x)\n- C (Wikipedia: x)\n- D.").count("(Wikipedia: x)") == 0
    and rr.collapse_repeated_sources("- A (W: x)\n- B (W: x)").count("(W: x)") == 2)
# 2. Bramka: pogrubienie per linia, wołacz, formułki na końcu
t, f = bb.review("**Wirtualne kawiarnie.\nTekst.\n**Następny krok: sprawdź.")
chk("bold_per_linia", "**" not in t and any(x["kod"] == "markdown" for x in f))
chk("wolacz", bb.review("Cześć Grzegorz! Jasne, Grzegorz. Grzegorz Żelazowski to twórca.")[0] == "Cześć Grzegorzu! Jasne, Grzegorzu. Grzegorz Żelazowski to twórca.")
chk("formulka", bb.review("Oto odpowiedź z treścią.\n\nCieszę się, że mogłem pomóc. Jeśli będziesz potrzebował kolejnych danych, daj znać.")[0] == "Oto odpowiedź z treścią."
    and bb.review("Daj znać.")[0] == "Daj znać.")
chk("obce_slowa", "largest" in bb._EN_WORDS and "truly" in bb._EN_WORDS)
# 3. Pytania pomocnicze z numerem nie trafiają do odpowiedzi; przyjazny opis błędu dostawcy
chk("pytania_numerowane", nm.strip_helper_questions("1. Czy potrzebuję więcej szczegółów?\nTak, zwykle.\n", ["Czy potrzebuję więcej szczegółów?"]).strip() == "Tak, zwykle.")
chk("blad_po_polsku", rr._friendly_error('RuntimeError: x (huggingface:ProviderError: HTTP 402: {"error":"no credits') == "huggingface: brak kredytów"
    and "{" not in rr._network_failure_note({"juggler_error": 'x (groq:ProviderError: HTTP 429: {"a":1})'}))
chk("finish_typografia", "collapse_repeated_sources(normalize_typography(" in inspect.getsource(rr._route))
# 4. Namysł: koszt - fakt bez recenzenta, bez wymuszonej sieci przy notowaniu, twórcze bez sieci, juniorzy od wagi 3, grunty
src = inspect.getsource(nm.run)
chk("fakt_bez_recenzenta", 'light = light or (plan.rodzaj == "fakt" and len(draft) < 300 and _poziom <= 2' in src)
chk("notowanie_bez_sieci", 'and not (plan.kursy and plan.rodzaj in ("fakt", "rozmowa"))' in src and 'if _chce_historii and _sym != "usdpln"' in src)
chk("tworcze_bez_sieci", 'plan.rodzaj in ("twórcze", "tworcze")' in src and 'plan.siec = ""' in src)
chk("juniorzy_waga3", "and _poziom >= 3 and narr.elapsed() < TIME_BUDGET * 0.6" in src)
chk("strony_fakt", 'ctx.read_page and plan.rodzaj != "fakt" and narr.elapsed() < TIME_BUDGET * 0.6' in src)
chk("grunty", not nm.wants("stary nooooooooooooooo")[0] and not nm.wants("eee dobra powiedzmy, dziekuje")[0] and nm.wants("no dobra, a kurs złota?")[0])
def run(replies, msg):
    seen = []
    def cloud(system, msgs, m, exclude=None, prefer=None):
        ph = ("rozpoznanie" if "ROZPOZNANIA" in system else "krytyka" if "recenzentem" in system else "szkic" if "etap SZKICU" in system else "poprawa")
        seen.append(ph); return replies.get(ph, ""), "groq"
    class V:
        notes = {}
        def search(self, q, limit=5): return []
    calls = []
    ctx = nm.Context(vault=V(), message=msg, history_local=[], history_cloud=[], files=[], sys_local="S", sys_cloud="S", local_up=False,
        local_chat=lambda s, h, m: cloud(s, h, m)[0], cloud_chat=cloud, cloud_pool=lambda: ["groq", "gemini"], research=lambda m: (calls.append("opinie"), [])[1],
        search_notes=lambda v, q: [], research_web=lambda q: (calls.append("web"), {"card": {"results": [{"title": "t", "url": "https://x.test/a", "snippet": "s"}]}, "speech": ""})[1],
        wiki_lookup=lambda v, q: {"card": {}}, market_quote=lambda s: (calls.append("quote"), {"speech": "XAUUSD: 2412,35 USD", "card": {"data": {"price": 2412.35}}})[1],
        market_history=lambda s, d: (calls.append("hist"), {"card": {}})[1], read_page=lambda u, **k: (calls.append("page"), {"ok": True, "title": "t", "text": "x" * 100})[1],
        internet_allowed=lambda: (True, ""), sanitize=rr._sanitize_leaked_tokens, violates_style=lambda t: [], settings={"tryb": "zawsze", "material_do_sieci": False})
    r = nm.run(ctx); return r, seen, calls
ROZF = "CEL: cena złota\nRODZAJ: fakt\nPYTANIA: -\nNOTATKI: -\nPLIKI: -\nSIEC: -\nWIKI: -\nKURS: xauusd\nPULAPKI: x"
r, seen, calls = run({"rozpoznanie": ROZF, "szkic": "Złoto: 2412,35 USD (notowanie).", "krytyka": "WERDYKT: popraw\n- x", "poprawa": "ZMIENIONE"}, "Heyaaa, cena zlota")
chk("cena_dwa_wywolania", seen == ["rozpoznanie", "szkic"] and calls == ["quote"] and r["speech"].startswith("Złoto: 2412,35"))
ROZT = "CEL: lista pytań\nRODZAJ: twórcze\nPYTANIA: -\nNOTATKI: -\nPLIKI: -\nSIEC: pytania testowe\nWIKI: -\nKURS: -\nPULAPKI: x"
r, seen, calls = run({"rozpoznanie": ROZT, "szkic": "1. Pytanie.\n2. Pytanie." * 20, "krytyka": "WERDYKT: ok"}, "Podaj 15 pytań, które mogę Ci zadać")
chk("tworcze_bez_wyszukiwarki", "web" not in calls)
# 5. Późna odpowiedź w interfejsie za swoim pytaniem; idempotencja z treścią; szkic tylko na bieżące pytanie
js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
chk("ui_pozna_odpowiedz", "conv.messages.splice(qAt + 1, 0, msg)" in js and "delete qDone.jobId" in js)
chk("szkic_tylko_biezace", "odpowiadasz TYLKO na nią" in src)
mm._CLIENT_JOBS.clear(); mm._CHAT_JOBS.clear()
_started = []
_orig = mm._start_chat_job_new
mm._start_chat_job_new = lambda payload: (_started.append(payload.get("message")), f"job{len(_started)}")[1]
mm._CHAT_JOBS["job1"] = {"done": threading.Event(), "result": None}
j1 = mm._start_chat_job({"client_id": "abcdefgh12", "message": "pierwsze"})
j2 = mm._start_chat_job({"client_id": "abcdefgh12", "message": "pierwsze"})
j3 = mm._start_chat_job({"client_id": "abcdefgh12", "message": "inne"})
mm._CHAT_JOBS["job1"]["done"].set(); mm._CHAT_JOBS["job1"]["result"] = {"error": "x"}
mm._CLIENT_JOBS["abcdefgh12"] = ("job1", __import__("time").monotonic(), mm._CLIENT_JOBS["abcdefgh12"][2] if len(mm._CLIENT_JOBS["abcdefgh12"]) > 2 else "")
import hashlib as _hl
mm._CLIENT_JOBS["abcdefgh12"] = ("job1", __import__("time").monotonic(), _hl.sha256(b"pierwsze").hexdigest()[:16])
j4 = mm._start_chat_job({"client_id": "abcdefgh12", "message": "pierwsze"})
mm._start_chat_job_new = _orig
chk("idempotencja_tresc", j1 == j2 == "job1" and j3 != "job1" and j4 != "job1")
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA60_CHECK" = "OK" ]; then
  ok 60 "Tura 17: czystsza polszczyzna, tańszy i szybszy Namysł, późna odpowiedź przy swoim pytaniu"
else
  bad 60 "Tura 17: ${TURA60_CHECK:-błąd importu}" "sprawdź pliki z CHANGELOG 1.32.14"
fi

TURA61_CHECK="$(cd "$ROOT/agent" && KORYTO_DZIENNIK_PLIK="$KORYTO_DZIENNIK_PLIK" TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import inspect
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
import juggler as jj, router as rr, main as mm, namysl as nm

# 1. 429 "limit dzienny" (openrouter/cloudflare/gemini z transkryptu) -> długi, "twardy"
#    cooldown (nie 8 minut jak zwykły Retry-After), zwykła przejściowa porażka (bez kodu,
#    bez Retry-After) wciąż krótkim, "niewyczerpującym" cooldownem jak dotąd.
class E429(Exception):
    def __init__(self, msg):
        super().__init__(msg); self.code = 429; self.headers = {}
jj.reset_breakers()
jj.note_failure("openrouter", E429('Rate limit exceeded: free-models-per-day. Add 10 credits'))
jj.note_failure("cloudflare", E429('you have used up your daily free allocation of 10,000 neurons'))
jj.note_failure("gemini", E429('You exceeded your current quota, please check your plan'))
chk("limit_dzienny_dlugi", jj.exhausted("openrouter") and jj.exhausted("cloudflare") and jj.exhausted("gemini")
    and jj._breaker("openrouter")["cooldown_do"] - __import__("time").monotonic() > 3000)
jj.reset_breakers()
jj.note_failure("groq", RuntimeError("Connection reset"))
chk("przejsciowa_nie_wyczerpana", not jj.exhausted("groq") and jj.breaker_state("groq")["stan"] == "cooldown")

# 2. Lokalny model jako ostatnia szansa TYLKO gdy sieciowi są exhausted(), nie przy jednej
#    zwykłej porażce (to wciąż krótka uczciwa odmowa, jak dotąd - patrz check 27).
import os, trace as tt, netguard as ng
os.environ.update(ANTHROPIC_API_KEY="k"); os.environ.pop("KORYTO", None); os.environ.pop("KORYTO_LOKALNIE", None)
jj.reset_breakers()
rr.ollama_available = lambda: True
rr._ollama_chat = lambda *a, **k: "lokalnie"
ng.internet_allowed = lambda fresh=False: (True, "ok")
def _403(s, m, to):
    raise jj.ProviderError("moderacja albo zapora", code=403)
jj._PROVIDER_FN["anthropic"] = _403
class V:
    notes = {}
    def search(self, q, limit=5): return []
stages = []
tt.record = lambda stage, *a, **k: stages.append((stage, k.get("extra") or {}))
b = rr.route(V(), "SYS", [], "opowiedz dowcip")
chk("lokalnie_ostatnia_szansa", b.get("speech") == "lokalnie" and stages[-1][0] == "lokalnie_awaryjnie")
# ... a JEDNA zwykła, przejściowa porażka (bez kodu) zostaje krótką uczciwą odmową, nie lokalnym.
jj.reset_breakers()
jj._PROVIDER_FN["anthropic"] = lambda s, m, to: (_ for _ in ()).throw(RuntimeError("down"))
stages.clear()
b2 = rr.route(V(), "SYS", [], "opowiedz dowcip")
chk("przejsciowa_zostaje_odmowa", stages[-1][0] != "lokalnie_awaryjnie")

# 3. Załącznik, który nie trafił w ścisłe dopasowanie ścieżki, wciąż dociera do Namysłu
#    (jako sama nazwa - namysl._resolve_file spróbuje jej lenientszym wyszukiwaniem),
#    zamiast cichego zniknięcia i odpowiedzi „nie dołączyłeś pliku”; przejście katalogu
#    i pliki skryte wciąż całkowicie odrzucone.
import tempfile, sources as sc
tmp = Path(tempfile.mkdtemp())
sc.UPLOAD_DIR = tmp
chat = sc.chat_id("test-projekt")
r = sc.save_upload(chat, "Umowa.txt", b"x" * 20)
chk("zalacznik_trafiony", mm._upload_paths(chat, [r["name"]]) == [r["path"]])
chk("zalacznik_fallback_nazwa", mm._upload_paths(chat, ["nieznaleziony.txt"]) == ["nieznaleziony.txt"])
chk("zalacznik_bezpieczenstwo", mm._upload_paths(chat, ["../../etc/passwd", ".env", "a/b.txt"]) == [])
chk("namysl_chce_falszywej_nazwy", nm.wants("Przeanalizuj to", ["nieznaleziony.txt"])[0])

# 4. "Nie trzeba, dziękuję za informacje" to zamknięcie wątku (idiom "nie trzeba"), nie
#    nowa prośba do sześciu faz; prawdziwa prośba w tym samym zdaniu zostaje prośbą.
chk("nie_trzeba_zamyka", not nm.wants("Nie trzeba, dziękuję za informacje", None, {"tryb": "zawsze"}, first_turn=False)[0])
chk("nie_trzeba_nie_chowa_prosby", nm.wants("Nie trzeba tego teraz, ale zrób mi plan na jutro", None, {"tryb": "zawsze"}, first_turn=False)[0])

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA61_CHECK" = "OK" ]; then
  ok 61 "Tura 17b: 429 dzienny limit nie na 8 minut, lokalny model jako ostatnia szansa gdy sieciowi wyczerpani, zgubiony załącznik wciąż trafia do Namysłu, \"nie trzeba\" zamyka wątek"
else
  bad 61 "Tura 17b: ${TURA61_CHECK:-błąd importu}" "sprawdź agent/juggler.py (note_failure/exhausted), agent/router.py (_rozmowa_korytem), agent/main.py (_upload_paths), agent/namysl.py (is_social/_SOCIAL_RE)"
fi

TURA62_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import os, re, threading, tempfile
from pathlib import Path
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)
import standing as st, router as rr, namysl as nm, bramka as bb, sysop as so, learning as lr

# 1. Tura 18 (audyt): create_task() pod JEDNĄ blokadą - duplikat + limit MAX_TASKS nie są
#    już osobnym "czytaj, potem decyduj" bez blokady (20 wątków na raz nie przebija limitu).
tmp = Path(tempfile.mkdtemp())
st.TASKS_DIR = tmp
st.MAX_TASKS = 10
barrier = threading.Barrier(20)
results = []
def worker(i):
    barrier.wait()
    results.append(st.create_task(f"obserwuj kurs XYZ{i} i daj znac gdy spadnie"))
threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
for t in threads: t.start()
for t in threads: t.join()
chk("zadania_bez_wyscigu", len(st.active_tasks()) == 10 and sum(1 for r in results if r.get("ok")) <= 10)

# 2. collapse_repeated_sources nie psuje zwykłego, powtórzonego dopisku w nawiasie bez
#    dwukropka (nie jest cytowaniem źródła - te mają zawsze postać "ETYKIETA: wartość").
plan = "Plan na dzis:\n- Zadzwonic do klienta (do zrobienia dzis)\n- Wyslac faktury (do zrobienia dzis)\n- Sprawdzic serwer (do zrobienia dzis)"
chk("zrodla_bez_dwukropka_caly", rr.collapse_repeated_sources(plan) == plan)
chk("zrodla_z_dwukropkiem_dziala", rr.collapse_repeated_sources(
    "- A (Wikipedia: x)\n- B (Wikipedia: x)\n- C (Wikipedia: x)\n- D.").count("(Wikipedia: x)") == 0)

# 3. Etykieta wewnętrzna Namysłu w ŚRODKU linii (nie tylko na początku) jest wycinana.
r1 = nm.strip_helper_questions("Sprawdzilem serwer. WERDYKT: ok, wszystko dziala.\nOto podsumowanie: CEL: zrestartowac usluge.", [])
chk("etykieta_w_srodku_linii", "WERDYKT" not in r1 and "CEL:" not in r1 and "Sprawdzilem serwer" in r1)

# 4. Wołacz "Grzegorz" -> "Grzegorzu" gdziekolwiek w zdaniu (nie tylko po konkretnym słowie
#    na początku), nazwisko zostaje bez zmian.
for before, after in [
    ("Grzegorz, zrobilem to zadanie.", "Grzegorzu, zrobilem to zadanie."),
    ("Powiem wprost, Grzegorz: serwer dziala.", "Powiem wprost, Grzegorzu: serwer dziala."),
    ("Sluchaj Grzegorz, mam plan.", "Sluchaj Grzegorzu, mam plan."),
]:
    chk("wolacz_w_srodku:" + before, bb.review(before)[0] == after)
chk("wolacz_nazwisko_caly", bb.review("Grzegorz Zelazowski to tworca.")[0] == "Grzegorz Zelazowski to tworca.")

# 5. Wielokrotne spacje w środku linii są zwijane (wcięcie listy zostaje).
chk("spacje_zwijane", bb.review("Sprawdzilem  dwa razy, Grzegorzu.")[0] == "Sprawdzilem dwa razy, Grzegorzu.")
chk("spacje_wciecie_zostaje", bb.review("- punkt  pierwszy")[0].startswith("- punkt pierwszy"))
chk("obce_slowa_nowe", {"feedback", "deadline", "workflow"} <= bb._EN_WORDS)

# 6. sysop: .env dostępny przez dowiązanie pod inną nazwą jest wykryty (nie tylko literalne ".env").
tmp2 = Path(tempfile.mkdtemp())
so.PROJECT_ROOT = tmp2
(tmp2 / ".env").write_text("ANTHROPIC_API_KEY=x\n")
os.symlink(".env", str(tmp2 / "config_current"))
chk("env_symlink_wykryty", so.classify_shell("cat config_current")[0] == "destructive")
chk("env_wprost_wykryty", so.classify_shell("cat .env")[0] == "destructive")
chk("zwykle_polecenie_dziala", so.classify_shell("ls -la")[0] == "read")

# 7. learning: wyzwalacz z samych pospolitych słów (bez żadnego konkretnego) nie jest uczony,
#    i nie zatruwa routingu niezwiązanych wiadomości; konkretne słowo w wyzwalaczu wciąż się uczy.
lr.LEARNED_PATH = Path(tempfile.mkdtemp()) / "nauczone.json"
lr._CACHE = None
rec = lr.learn_from_resolution("Sprawdzaj codziennie kurs zlota, powiedz mi jak cos sie zmieni",
                               tool="standing_task_new", model_arg="kurs zlota", by="ollama")
chk("nauka_zbyt_ogolna_odrzucona", rec is None)
chk("nauka_nie_zatruwa", lr.find_learned_match("Mozesz sprawdzac codziennie plan lekcji syna, bo sie ciagle zmienia?") is None)
rec2 = lr.learn_from_resolution("Sledz regularnie temperature procesora w laptopie i powiedz, jak przekroczy 80",
                                tool="standing_task_new", model_arg="temperature procesora", by="ollama")
chk("nauka_konkretna_dziala", rec2 is not None and "laptop" in rec2["words"])

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA62_CHECK" = "OK" ]; then
  ok 62 "Tura 18/20: zadania stałe bez wyścigu, cytowanie źródła wymaga dwukropka, etykieta Namysłu usuwana w środku linii, wołacz wszędzie w zdaniu, spacje, .env przez dowiązanie, uczenie bez zbyt ogólnych wyzwalaczy"
else
  bad 62 "Tura 18/20: ${TURA62_CHECK:-błąd importu}" "sprawdź agent/standing.py (create_task), agent/router.py (collapse_repeated_sources), agent/namysl.py (strip_helper_questions), agent/bramka.py (wołacz/spacje), agent/sysop.py (_touches_env), agent/learning.py (learn_from_resolution)"
fi

# 63. Tura 19/20 (audyt): wgrywanie plików pod blokadą (limit łączny nie do obejścia
#     dwoma wgraniami naraz), "ps" z kolumną environ zawsze jest zmianą (nie tylko styl
#     BSD bez myślnika), czasownik realnej prośby po podziękowaniu nie usypia Namysłu,
#     aktualizacja z uszkodzonym plikiem .py w paczce jest wykryta i wycofana automatycznie,
#     TimeoutStopSec usługi dopasowany do najdłuższej operacji zlecanej przez agenta.
TURA63_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import os, re, shutil, subprocess, threading, tempfile
from pathlib import Path
ROOT = Path.cwd().parent
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. sources.save_upload: dwa równoległe wgrania nie mogą razem przebić limitu łącznego
#    (wyścig check-then-act bez blokady - 1.32.17). Żeby nie zależeć od przypadkowego
#    wyścigu wątków na szybkim dysku, sam punkt liczenia "used" (upload_root(None), wołane
#    wyłącznie w tym jednym miejscu kodu) jest barierą: dwa wątki razem w tym punkcie =
#    naprawdę równoległy odczyt (brak blokady); jeśli blokada działa, drugi wątek wchodzi
#    tu dopiero PO zwolnieniu blokady przez pierwszy - para się nie zbiera, bariera pęka
#    na timeout.
import sources as so
tmp = Path(tempfile.mkdtemp())
so.MAX_UPLOADS_TOTAL_BYTES = 20 * 1024 * 1024
data = b"x" * (15 * 1024 * 1024)
sync = threading.Barrier(2)
stan = {"razem": False}
def root_z_bariera(chat):
    if chat is None:
        try:
            sync.wait(timeout=1.0)
            stan["razem"] = True
        except threading.BrokenBarrierError:
            pass
    return tmp / (chat or "ogolna")
so.upload_root = root_z_bariera
results = []
def worker():
    results.append(so.save_upload("chat", "plik.txt", data))
threads = [threading.Thread(target=worker) for _ in range(2)]
for t in threads: t.start()
for t in threads: t.join()
used_po = sum(p.stat().st_size for p in tmp.rglob("*") if p.is_file())
chk("wgrywanie_bez_wyscigu", not stan["razem"] and used_po <= so.MAX_UPLOADS_TOTAL_BYTES)

# 2. sysop.classify_shell: "ps" z kolumną environ (GNU -eo/-o/axo, z myślnikiem czy bez)
#    jest zawsze "change", nie tylko styl BSD bez myślnika (1.32.17).
import sysop as sy
for cmd in ("ps -eo pid,comm,environ", "ps -o pid,environ --ppid 1", "ps axo pid,environ", "ps aux e"):
    chk("ps_environ:" + cmd, sy.classify_shell(cmd)[0] == "change")
chk("ps_zwykle_dziala", sy.classify_shell("ps -ef")[0] == "read")

# 3. namysl: czasownik realnej prośby PO podziękowaniu/potwierdzeniu nie jest już
#    usypiany przez tryb "zawsze" jako czysto społeczny - Namysł się włącza
#    (is_social() sam pozostaje bez zmian, decyzję przejmuje wants() przez
#    _ACTION_WORD_RE - 1.32.17).
import namysl as nm
for text in ("dzieki, wylacz to", "dobra, kup to", "ok, anuluj to", "dzieki, zresetuj to", "dobra, zmien to"):
    chk("akcja_po_podziekowaniu:" + text, nm.wants(text, settings={"tryb": "zawsze"})[0] is True)
chk("czysto_spoleczne_zostaje", nm.wants("dzieki, wszystko ok", settings={"tryb": "zawsze"})[0] is False)

# 4. aktualizacja: code_copy pisze pliki *.py strumieniowo (tar|tar), w miejscu - przerwanie
#    W ŚRODKU (nie: paczka źle zbudowana, to już łapie wcześniejsza kontrola składni paczki)
#    zostawia plik .py obcięty. Nowy sanity-check PO code_copy (dokładnie ten sam kod, co w
#    aktualizuj.sh) wykrywa taki stan i woła restore_code - testujemy prawdziwym uruchomieniem
#    wyciągniętego fragmentu na dwóch realnych katalogach (zdrowym i "przerwanym w środku").
akt_text = (ROOT / "aktualizuj.sh").read_text(encoding="utf-8")
m = re.search(r'if ! python3 -c "\n(.*?)\n"; then\n    echo "UWAGA: kod po podmianie', akt_text, re.DOTALL)
chk("sanity_check_obecny_w_skrypcie", m is not None)
if m is not None:
    tmp3 = Path(tempfile.mkdtemp())
    agent_dir = tmp3 / "agent"; agent_dir.mkdir()
    (agent_dir / "main.py").write_text("import os\nprint('ok')\n")
    kod = m.group(1).replace("$ROOT", str(tmp3))
    r_ok = subprocess.run(["python3", "-c", kod], capture_output=True, text=True)
    chk("sanity_check_kod_zdrowy_przechodzi", r_ok.returncode == 0)
    # Symulacja przerwania W ŚRODKU zapisu przez tar (nie: zła paczka źródłowa) - plik
    # ucięty w połowie instrukcji, tak jak zostałby po SIGKILL w środku code_copy.
    (agent_dir / "main.py").write_text("import os\ndef main():\n    x = (1 + ")
    r_bad = subprocess.run(["python3", "-c", kod], capture_output=True, text=True)
    chk("sanity_check_kod_obciety_wykryty", r_bad.returncode != 0)
    shutil.rmtree(tmp3, ignore_errors=True)
chk("restore_code_wolane_po_niepowodzeniu", "restore_code \"$SNAP\"; exit 1" in akt_text)

# 5. install.sh: TimeoutStopSec usługi >= limitowi najdłuższej operacji zleconej przez
#    agenta (PACKAGE_TIMEOUT/apt upgrade, sysop.py), żeby restart usługi w trakcie takiej
#    operacji nie zabił jej SIGKILL-em w pół drogi (1.32.17).
inst_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
m = re.search(r"\[Service\].*?TimeoutStopSec=(\d+).*?\[Install\]", inst_sh, re.DOTALL)
chk("timeoutstopsec_wystarczajacy", m is not None and int(m.group(1)) >= 1800)

shutil.rmtree(tmp, ignore_errors=True)
print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA63_CHECK" = "OK" ]; then
  ok 63 "Tura 19/20: wgrywanie plików bez wyścigu limitu, 'ps' z kolumną environ zawsze zmianą, czasownik realnej prośby po podziękowaniu budzi Namysł, uszkodzona paczka aktualizacji wycofana automatycznie, TimeoutStopSec dopasowany do apt upgrade"
else
  bad 63 "Tura 19/20: ${TURA63_CHECK:-błąd importu}" "sprawdź agent/sources.py (save_upload), agent/sysop.py (classify_shell/ps), agent/namysl.py (_ACTION_WORD_RE), aktualizuj.sh (sanity-check po code_copy), install.sh (TimeoutStopSec)"
fi

# 64. Tura 20/20 (audyt, finał serii): dziennik Nadzorcy maskuje też sekrety WPISANE w
#     poleceniu/wyniku (nie tylko z .env), wołacz "Grzegorzu" nie psuje już zdań, gdzie
#     "Grzegorz" jest podmiotem w trzeciej osobie, długa jedna wiadomość nie gubi faktu
#     z samego końca przy zapisie do pamięci rozmowy, strona zapasowa /debug sama prosi
#     o token dostępu, gdy łączy się z telefonu bez zapisanego tokenu.
TURA64_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import os, re
from pathlib import Path
ROOT = Path.cwd().parent
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. sysop.mask_secrets maskuje też sekrety wpisane wprost (nie tylko z .env) - Bearer,
#    hasło w connection-stringu - dołączając szeroki filtr trace.redact_typed.
import sysop as so
cmd = 'curl -H "Authorization: Bearer sk-ant-api03-ABCDEFGHIJ1234567890KLMNOPQRSTUVWXYZ" https://api.example.com/ping'
masked = so.mask_secrets(cmd)
chk("mask_bearer_token", "sk-ant-api03" not in masked and "Bearer ***" in masked)
chk("mask_connection_string", "TajneHaslo123" not in so.mask_secrets("postgres://user:TajneHaslo123@host:5432/db"))
chk("mask_env_sekret_dalej_dziala", so.mask_secrets("zwykly tekst bez sekretow") == "zwykly tekst bez sekretow")

# 2. bramka.review: "Grzegorz" jako PODMIOT (czasownik 3-osoby w rodzaju męskim po imieniu)
#    zostaje bez zmian; jako zwrot wprost do Ciebie wciąż dostaje wołacz.
import bramka as bb
podmiot = [
    "Grzegorz zdecydował się na wariant B, bo tańszy.",
    "Z poprzedniej rozmowy: Grzegorz prosił o pomoc w naprawie roweru.",
]
for s in podmiot:
    chk("wolacz_podmiot_bez_zmian:" + s, bb.review(s)[0] == s)
zwrot = [
    ("Grzegorz, zrobilem to zadanie.", "Grzegorzu, zrobilem to zadanie."),
    ("Powiem wprost, Grzegorz: serwer dziala.", "Powiem wprost, Grzegorzu: serwer dziala."),
    ("Sluchaj Grzegorz, mam plan.", "Sluchaj Grzegorzu, mam plan."),
]
for before, after in zwrot:
    chk("wolacz_zwrot_dziala:" + before, bb.review(before)[0] == after)
chk("wolacz_nazwisko_caly", bb.review("Grzegorz Zelazowski to tworca.")[0] == "Grzegorz Zelazowski to tworca.")

# 3. rozmowa.record: długa, jedna wiadomość zachowuje fakt z SAMEGO KOŃCA (nie tylko
#    początek) przy obcinaniu do TURN_CHARS - realnym zapisem i odczytem z pliku rozmowy.
import tempfile
import rozmowa as rz
import sources as srcmod
tmp = Path(tempfile.mkdtemp())
rz.ROZMOWY_DIR = tmp
rz._LOCKS.clear()
msg = ("Opisuję długo kontekst projektu iPhone flip, szukam zepsutych ekranow w dobrej cenie. " * 25) + "Ostateczny budżet na ten miesiąc to 4800 zlotych."
rz.record("audyt-test-20", msg, "Zanotowane.", tool=False)
zapisane = rz._load("audyt-test-20")["tury"][0]["tekst"]
chk("dlugi_fakt_na_koncu_zachowany", "4800" in zapisane and len(zapisane) <= rz.TURN_CHARS)
chk("krotka_wiadomosc_bez_zmian", rz._smart_cut("Krotki tekst.", rz.TURN_CHARS) == "Krotki tekst.")
import shutil
shutil.rmtree(tmp, ignore_errors=True)

# 4. ui/debug.js: strona zapasowa ma WŁASNE proszenie o token (ensureTokenD) i ponawia
#    żądanie raz po otrzymaniu 403 "Brak autoryzacji", tak jak app.js (JS - bez środowiska
#    do uruchomienia w check.sh, więc sprawdzenie strukturalne dokładnego kodu).
debug_js = (ROOT / "ui" / "debug.js").read_text(encoding="utf-8")

def extract_js_function(src, start_marker):
    """Wycina całą funkcję od `start_marker` do zamykającego nawiasu klamrowego
    jej ciała (licząc nawiasy, nie naiwnym "do pierwszego }") - omija nawiasy
    parametrów domyślnych (np. `options = {}`)."""
    i = src.index(start_marker)
    paren = src.index("(", i)
    depth_p = 0
    j = paren
    while True:
        if src[j] == "(":
            depth_p += 1
        elif src[j] == ")":
            depth_p -= 1
            if depth_p == 0:
                break
        j += 1
    brace = src.index("{", j)
    depth = 0
    k = brace
    while True:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
        k += 1

try:
    ensure_fn = extract_js_function(debug_js, "function ensureTokenD()")
except ValueError:
    ensure_fn = ""
try:
    fetch_fn = extract_js_function(debug_js, "async function apiFetch(")
except ValueError:
    fetch_fn = ""
chk("ensureTokenD_istnieje", bool(ensure_fn))
chk("ensureTokenD_prosi_i_zapisuje", "prompt(" in ensure_fn and 'localStorage.setItem("gregai_token"' in ensure_fn)
# Sprawdzenie SCOPED do ciała apiFetch (nie całego pliku) - inaczej "ensureTokenD()"
# gdzieś dalej w pliku (np. wywołanie przy starcie strony) fałszywie uznałoby ponawianie
# za obecne, nawet gdyby ktoś usunął je w ŚRODKU apiFetch.
chk("apiFetch_ponawia_po_403", bool(re.search(
    r"status === 403[\s\S]*?Brak autoryzacji[\s\S]*?ensureTokenD\(\)[\s\S]*?return apiFetch\(url", fetch_fn)))
chk("ensureTokenD_wolane_na_starcie", bool(re.search(r"ensureTokenD\(\);\s*\n\s*if\s*\(debugVisible\(\)\)\s*refresh\(\);", debug_js)))

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA64_CHECK" = "OK" ]; then
  ok 64 "Tura 20/20 (finał serii): dziennik Nadzorcy maskuje też sekrety wpisane wprost, wołacz nie psuje zdań z 'Grzegorz' jako podmiotem, długa wiadomość nie gubi faktu z końca, /debug sam prosi o token"
else
  bad 64 "Tura 20/20: ${TURA64_CHECK:-błąd importu}" "sprawdź agent/sysop.py (mask_secrets), agent/bramka.py (wołacz), agent/rozmowa.py (_smart_cut/record), ui/debug.js (ensureTokenD/apiFetch)"
fi

# 65. Przygotowanie pod open source, tura 1/5: "twórca" (persona.CREATOR) konfigurowalny
# przez .env (GREGAI_CREATOR_NAME), generyczny domyślnie - zamiast literału "Grzegorz
# Żelazowski" wpisanego na trwałe w kodzie i w agent/prompt.md (osobiste dane autora,
# widoczne u każdego, kto sklonuje repo). Powitanie w UI generyczne. LICENSE obecny.
# CLAUDE.md (notatnik dla Claude Code, nie część programu) wyłączony z gita.
TURA65_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import os, re, sys
sys.path.insert(0, ".")
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. Domyślna (żadnego GREGAI_CREATOR_NAME w środowisku) wartość CREATOR jest generyczna,
# nie imieniem i nazwiskiem autora.
os.environ.pop("GREGAI_CREATOR_NAME", None)
import persona as pe
chk("creator_domyslny", pe.CREATOR == "administrator tej instalacji" and "Żelazowski" not in pe.CREATOR)

# 2. Źródłowy prompt.md nie ma już literału imienia i nazwiska - tylko placeholder {CREATOR}.
prompt_src = open("prompt.md", encoding="utf-8").read()
chk("prompt_md_bez_literalu", "Żelazowski" not in prompt_src and prompt_src.count("{CREATOR}") == 3)

# 3. main.get_system_prompt() podstawia {CREATOR} wartością z persona.CREATOR (tu: własna,
# ustawiona PRZED importem main - env_loader.load_env() nie nadpisuje już ustawionych kluczy).
os.environ["GREGAI_CREATOR_NAME"] = "Jan Testowy"
import importlib
import persona as pe
importlib.reload(pe)
chk("creator_z_env", pe.CREATOR == "Jan Testowy")
import main as mm
importlib.reload(mm)
full = mm.get_system_prompt()
chk("prompt_podstawiony", "Jan Testowy" in full and "{CREATOR}" not in full and "Żelazowski" not in full)

# 4. Krótki prompt lokalny (awareness._local_rules) też liczy się dynamicznie, nie z
# literału zamrożonego przy starym kodzie.
import awareness as aw
loc = aw.local_prompt(full, type("V", (), {"notes": {}})())
chk("local_rules_dynamiczne", "Moim twórcą jest Jan Testowy." in loc and "Żelazowski" not in loc)

# 5. Powitanie w UI nie ujawnia cudzego imienia.
app_js = open("../ui/app.js", encoding="utf-8").read()
chk("ui_powitanie_generyczne", "Cześć, Grzegorz" not in app_js and '"Cześć!"' in app_js)

# 6. LICENSE istnieje w katalogu głównym.
chk("license_istnieje", os.path.isfile("../LICENSE") and "MIT License" in open("../LICENSE", encoding="utf-8").read())

# 7. CLAUDE.md wyłączony z gita (nie część programu, prywatny notatnik).
gi = open("../.gitignore", encoding="utf-8").read()
chk("claude_md_gitignorowany", re.search(r"(?m)^CLAUDE\.md$", gi) is not None)

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA65_CHECK" = "OK" ]; then
  ok 65 "Przygotowanie pod open source (tura 1/5): twórca konfigurowalny przez .env, generyczny domyślnie; powitanie UI bez cudzego imienia; LICENSE; CLAUDE.md poza gitem"
else
  bad 65 "Open source tura 1/5: ${TURA65_CHECK:-błąd importu}" "sprawdź agent/persona.py (CREATOR), agent/prompt.md ({CREATOR}), agent/main.py (podstawienie), agent/awareness.py (_local_rules), ui/app.js (powitanie), LICENSE, .gitignore"
fi

# 66. Przygotowanie pod open source, tura 2/5: notatki/wiedza i dane treningowe bez
# konkretnego sprzętu/imienia autora; requirements.txt z przypiętymi wersjami;
# SECURITY.md; dokumenty top-level z dopiskiem o aktualności zamiast zamrożonych
# numerów wersji sprawiających wrażenie porzucenia.
TURA66_CHECK="$(cd "$ROOT" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import json, re, sys
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. notatki/wiedza bez konkretnego modelu sprzętu autora.
import glob
wiedza = ""
for p in glob.glob("notatki/wiedza/*.md"):
    wiedza += open(p, encoding="utf-8").read()
chk("wiedza_bez_sprzetu", "E7270" not in wiedza and "Galaxy J6" not in wiedza and "i7-6600U" not in wiedza)

# 2. training/*.jsonl bez literału "Żelazowski", i wciąż poprawny JSON (zero linii
# uszkodzonych podmianą tekstu).
jsonl_files = ["training/distill_seed.jsonl", "training/teacher/tozsamosc.jsonl",
               "training/ewaluacja/regresja.jsonl"]
training_txt = ""
json_ok = True
for p in jsonl_files:
    content = open(p, encoding="utf-8").read()
    training_txt += content
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except Exception:
            json_ok = False
chk("training_bez_literalu", "Żelazowski" not in training_txt)
chk("training_json_poprawny", json_ok)
chk("regresja_ocena_generyczna", "zawiera:administrator tej instalacji" in open("training/ewaluacja/regresja.jsonl", encoding="utf-8").read())

# 3. requirements.txt ma przypięte wersje (dolna i górna granica) obu zależności.
req = open("requirements.txt", encoding="utf-8").read()
chk("requirements_przypiete", bool(re.search(r"huawei-lte-api>=[\d.]+,<[\d.]+", req)) and bool(re.search(r"httpx\[http2\]>=[\d.]+,<[\d.]+", req)))

# 4. SECURITY.md istnieje i ma treść (nie pusty placeholder).
chk("security_md", __import__("os").path.isfile("SECURITY.md") and len(open("SECURITY.md", encoding="utf-8").read()) > 200)

# 5. ROADMAP_1.0.md oznaczony jako dokument historyczny.
chk("roadmap_banner", "Dokument historyczny" in open("ROADMAP_1.0.md", encoding="utf-8").read())

# 6. FUNDAMENT.md i PROTOKOL_TWIERDZA.md tłumaczą zamrożony numer wersji w nagłówku.
fundament = open("FUNDAMENT.md", encoding="utf-8").read()
twierdza = open("PROTOKOL_TWIERDZA.md", encoding="utf-8").read()
chk("fundament_dopisek", "nie przy\nkażdej wersji" in fundament or "nie przy każdej wersji" in fundament.replace("\n", " "))
chk("twierdza_dopisek", "nie są świadomie osłabiane" in twierdza.replace("\n", " "))

# 7. README ma sekcję mapującą dokumentację.
chk("readme_sekcja_dokumentacja", "## Dokumentacja" in open("README.md", encoding="utf-8").read())

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA66_CHECK" = "OK" ]; then
  ok 66 "Przygotowanie pod open source (tura 2/5): notatki/wiedza i dane treningowe bez sprzętu/imienia autora, requirements.txt przypięte, SECURITY.md, odświeżone dokumenty top-level"
else
  bad 66 "Open source tura 2/5: ${TURA66_CHECK:-błąd importu}" "sprawdź notatki/wiedza/*.md, training/*.jsonl, requirements.txt, SECURITY.md, ROADMAP_1.0.md, FUNDAMENT.md, PROTOKOL_TWIERDZA.md, README.md"
fi

# 67. Przygotowanie pod open source, tura 3/5: imię UŻYTKOWNIKA (do kogo GREGAI się
# zwraca) konfigurowalne przez .env (GREGAI_USER_NAME/_GENITIVE/_VOCATIVE), domyślnie
# dokładnie to, co było literałem "Grzegorz" - zero zmiany zachowania, dopóki nikt nie
# ustawi .env. Literał usunięty z promptu głównego (agent/prompt.md) i z WSZYSTKICH
# pozostałych promptów wysyłanych do modeli: streszczenie rozmowy, namysł (rozpoznanie/
# krytyka/szkic/poprawa), etykiety w kontekście rozmowy, podsumowanie wyszukiwania,
# opis narzędzia gregaipanicmode, tryb /plan i /sprawdz, moduł lekcji, pętla agenta,
# skrócony prompt czatu (main.CHAT_TOOLS_SUMMARY). Wołacz w bramce odpowiedzi też
# dynamiczny (agent/bramka.py).
TURA67_CHECK="$(cd "$ROOT/agent" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import os, sys, importlib
sys.path.insert(0, ".")
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. Domyślna (żadnego GREGAI_USER_NAME* w środowisku) wartość odtwarza dokładnie
# stary literał - zero zmiany zachowania, dopóki nikt nie ustawi .env.
for k in ("GREGAI_USER_NAME", "GREGAI_USER_NAME_GENITIVE", "GREGAI_USER_NAME_VOCATIVE"):
    os.environ.pop(k, None)
import persona as pe
importlib.reload(pe)
chk("user_name_domyslny", pe.USER_NAME == "Grzegorz" and pe.USER_NAME_GENITIVE == "Grzegorza"
    and pe.USER_NAME_VOCATIVE == "Grzegorzu")

# 2. Źródłowy prompt.md nie ma już literału imienia - tylko placeholdery.
prompt_src = open("prompt.md", encoding="utf-8").read()
chk("prompt_md_bez_imienia", "Grzegorz" not in prompt_src and "{UZYTKOWNIK}" in prompt_src
    and "{UZYTKOWNIKA}" in prompt_src and "{UZYTKOWNIKU}" in prompt_src)

# 3. Własne imię z .env podstawia się wszędzie, gdzie trzeba (main.get_system_prompt()),
# bez zostawionego placeholdera i bez starego literału.
os.environ["GREGAI_USER_NAME"] = "Aleksandra"
os.environ["GREGAI_USER_NAME_GENITIVE"] = "Aleksandry"
os.environ["GREGAI_USER_NAME_VOCATIVE"] = "Aleksandro"
importlib.reload(pe)
chk("user_name_z_env", pe.USER_NAME == "Aleksandra" and pe.USER_NAME_GENITIVE == "Aleksandry"
    and pe.USER_NAME_VOCATIVE == "Aleksandro")
import main as mm
importlib.reload(mm)
full = mm.get_system_prompt()
chk("prompt_podstawiony_uzytkownik", "Aleksandra" in full and "Aleksandry" in full
    and "{UZYTKOWNIK}" not in full and "{UZYTKOWNIKA}" not in full and "{UZYTKOWNIKU}" not in full
    and "Grzegorz" not in full)

# 4. Wołacz w bramce odpowiedzi jest dynamiczny: z własnym imieniem poprawia WŁASNĄ
# formę wołacza, nie zamrożone "Grzegorzu".
import bramka as br
importlib.reload(br)
poprawiony, znaleziska = br.review("Aleksandra, zrobiłem to zadanie.")
chk("bramka_wolacz_dynamiczny", "Aleksandro," in poprawiony and any(f.get("kod") == "wolacz" for f in znaleziska))

# 5. Pozostałe prompty wysyłane do modeli (namysł, streszczenie rozmowy, etykiety w
# kontekście, /plan, /sprawdz, lekcje, panicmode, pętla agenta, skrócony prompt czatu)
# też reagują na własne imię, a nie zamrożony literał "Grzegorz".
import namysl as ns
importlib.reload(ns)
chk("namysl_bez_literalu", "Grzegorz" not in ns._ROZPOZNANIE_SYSTEM and "Grzegorz" not in ns._KRYTYKA_SYSTEM
    and "Grzegorz" not in ns._SZKIC_SUFFIX and "Grzegorz" not in ns._POPRAWA_SUFFIX
    and "Aleksandra" in ns._ROZPOZNANIE_SYSTEM and "Aleksandro" in ns._SZKIC_SUFFIX)

import rozmowa as rz
importlib.reload(rz)
chk("rozmowa_bez_literalu", "Grzegorz" not in rz.SUMMARY_SYSTEM and "Aleksandry" in rz.SUMMARY_SYSTEM
    and rz._render_turns([{"role": "user", "tekst": "x"}]) == "Aleksandra: x")

import router as rt
importlib.reload(rt)
chk("router_bez_literalu", "Grzegorz" not in rt._WEB_SUFFIX and "Aleksandry" in rt._WEB_SUFFIX)

import capabilities as cap
importlib.reload(cap)
chk("capabilities_bez_literalu", "Grzegorz" not in cap.CAPABILITIES["gregaipanicmode"].prompt
    and "Aleksandra" in cap.CAPABILITIES["gregaipanicmode"].prompt)

import komendy as km
importlib.reload(km)
chk("komendy_bez_literalu", "Grzegorz" not in km.KONTEKSTY["plan"] and "Grzegorz" not in km.SPRAWDZ_SYSTEM
    and "Aleksandra" in km.KONTEKSTY["plan"] and "Aleksandry" in km.SPRAWDZ_SYSTEM)
# budżet operacyjny (3 miesiące) usunięty z /plan - to dane finansowe, nie zasada kodu.
chk("komendy_bez_budzetu", "3 miesiące" not in km.KONTEKSTY["plan"])

import lekcje as lk
importlib.reload(lk)
chk("lekcje_bez_literalu", "Grzegorz" not in lk.SZKIC_SYSTEM and "Aleksandry" in lk.SZKIC_SYSTEM)

import agentloop as al
importlib.reload(al)
_stan = {"goal": "g", "steps": [{"tool": "t", "arg": "a", "observation": "x" * 10, "ok": True}], "_siec": True}
al._private_material_ok = lambda: False
al._private_step = lambda s: True
chk("agentloop_bez_literalu", "Grzegorz" not in al._render_state(_stan) and "Aleksandry" in al._render_state(_stan))

chk("main_bez_literalu", "Grzegorz" not in mm.CHAT_TOOLS_SUMMARY and "Aleksandra" in mm.CHAT_TOOLS_SUMMARY
    and "Aleksandry" in mm.CHAT_TOOLS_SUMMARY)

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA67_CHECK" = "OK" ]; then
  ok 67 "Przygotowanie pod open source (tura 3/5): imię użytkownika konfigurowalne przez .env (domyślnie bez zmiany zachowania), usunięte z promptu głównego i z każdego innego promptu wysyłanego do modeli, wołacz w bramce dynamiczny"
else
  bad 67 "Open source tura 3/5: ${TURA67_CHECK:-błąd importu}" "sprawdź agent/persona.py (USER_NAME*), agent/prompt.md, agent/main.py, agent/bramka.py, agent/namysl.py, agent/rozmowa.py, agent/router.py, agent/capabilities.py, agent/komendy.py, agent/lekcje.py, agent/agentloop.py"
fi

# 68. Przygotowanie pod open source, tura 4/5: komunikacja o zaporze WARP i tabeli
# sprzętu jako świadomej decyzji bezpieczeństwa projektu (nie technicznym wymogu
# "osobistego asystenta" w ogóle), dokument PROTOKOL_KONTROLI.md oznaczony jako
# historyczny (wynik jednej rundy audytu 1.29.0, nie instrukcja dzisiejszego
# check.sh), zamrożone liczby kontroli usunięte z INSTALACJA_UBUNTU_26_04.md,
# martwe importy i zbędny `global` usunięte z agent/*.py, .gitignore uzupełniony
# o standardowe wpisy edytorów/systemów.
TURA68_CHECK="$(cd "$ROOT" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import re, sys
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. README wyjaśnia DLACZEGO WARP jest obowiązkowy (świadoma decyzja dla
# konkretnego modelu zagrożeń, nie wymóg samego programu), nie tylko stwierdza fakt.
# (tekst w .md zawija się w źródle, więc porównanie po znormalizowaniu białych znaków)
readme = open("README.md", encoding="utf-8").read()
readme_flat = " ".join(readme.split())
chk("readme_warp_uzasadniony", "świadomy wybór bezpieczeństwa" in readme_flat
    and "nie techniczny wymóg samego programu" in readme_flat)

# 2. install.sh: ten sam komentarz wyjaśnia, że to decyzja projektu, nie ogólny wymóg.
install_src = open("install.sh", encoding="utf-8").read()
install_flat = " ".join(install_src.split())
chk("install_warp_uzasadniony", "świadoma decyzja bezpieczeństwa tego" in install_flat
    and "nie techniczny wymóg" in install_flat)

# 3. README: tabela "Sprzęt" opisana jako maszyna referencyjna, nie minimalny wymóg.
chk("readme_sprzet_przyklad", "nie minimalne wymagania" in readme_flat
    and "maszyna referencyjna" in readme_flat)

# 4. INSTALACJA_UBUNTU_26_04.md bez zamrożonej liczby kontroli ("60 kontroli").
instalacja = open("INSTALACJA_UBUNTU_26_04.md", encoding="utf-8").read()
chk("instalacja_bez_zamrozonej_liczby", "60 kontroli" not in instalacja)

# 5. PROTOKOL_KONTROLI.md oznaczony jako dokument historyczny (wzorem ROADMAP_1.0.md
# z tury 2), README opisuje go zgodnie z treścią, nie jako instrukcję na dziś.
protokol = open("PROTOKOL_KONTROLI.md", encoding="utf-8").read()
chk("protokol_kontroli_banner", "Dokument historyczny" in protokol)
chk("readme_protokol_kontroli_opis",
    "`PROTOKOL_KONTROLI.md`** - **dokument historyczny**" in readme)

# 6. Martwe importy i zbędny `global` usunięte z agent/*.py (bez zewnętrznych
# narzędzi, zgodnie z zasadą projektu "serwer: tylko stdlib" - sprawdzenie
# źródła wprost, nie przez linter, który na docelowym laptopie może nie być
# zainstalowany).
main_src = open("agent/main.py", encoding="utf-8").read()
chk("main_bez_martwego_importu", "import capabilities as capabilities_mod" not in main_src)

namysl_src = open("agent/namysl.py", encoding="utf-8").read()
_namysl_head = namysl_src.split("\ndef ", 1)[0]  # importy są przed pierwszą definicją funkcji
chk("namysl_bez_martwego_importu", "from datetime import datetime\n" not in _namysl_head
    and "from datetime import datetime as _dt" in namysl_src)  # lokalny import w funkcji zostaje

vault_src = open("agent/vault.py", encoding="utf-8").read()
chk("vault_bez_martwego_importu", "import functools" not in vault_src)

straz_src = open("agent/straz.py", encoding="utf-8").read()
m = re.search(r"def _load_anchor\(\) -> dict:.*?(?=\ndef |\Z)", straz_src, re.DOTALL)
chk("straz_bez_zbednego_global", m is not None and "global _ANCHOR" not in m.group(0)
    and "global _ANCHOR" in straz_src)  # _load_anchor_locked() nadal go potrzebuje

# 7. .gitignore ma standardowe wpisy edytorów/systemów (open source readiness).
gi = open(".gitignore", encoding="utf-8").read()
chk("gitignore_edytory", ".vscode/" in gi and ".idea/" in gi and ".DS_Store" in gi)

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA68_CHECK" = "OK" ]; then
  ok 68 "Przygotowanie pod open source (tura 4/5): WARP i tabela sprzętu opisane jako świadoma decyzja/przykład, nie wymóg; PROTOKOL_KONTROLI.md oznaczony jako historyczny; martwe importy usunięte; .gitignore uzupełniony"
else
  bad 68 "Open source tura 4/5: ${TURA68_CHECK:-błąd importu}" "sprawdź README.md (Bezpieczeństwo, Sprzęt, Dokumentacja), install.sh, INSTALACJA_UBUNTU_26_04.md, PROTOKOL_KONTROLI.md, agent/main.py, agent/namysl.py, agent/vault.py, agent/straz.py, .gitignore"
fi

# 69. Przygotowanie pod open source, tura 5/5 (ostatnia): LICENSE bez pełnego
# nazwiska autora w copyright; rodzaj UŻYTKOWNIKA (do kogo GREGAI się zwraca)
# konfigurowalny przez .env (GREGAI_USER_GENDER) - steruje wyłącznie treścią
# instrukcji stylu dla modelu ("formy męskie"/"formy żeńskie"), domyślnie
# dokładnie to, co było literałem "mężczyzna: formy męskie" - zero zmiany
# zachowania, dopóki nikt nie ustawi .env; wołacz w bramce rozpoznaje też
# żeńskie/neutralne czasowniki czasu przeszłego ("-ła"/"-ło"), nie tylko męskie
# ("-ł"), tak by poprawnie odróżniał zwrot wprost do Ciebie od podmiotu
# trzeciej osoby niezależnie od skonfigurowanego rodzaju.
TURA69_CHECK="$(cd "$ROOT" && TZ=Europe/Warsaw python3 - 2>/dev/null <<'PY'
import os, sys, importlib
sys.path.insert(0, "agent")
fails = []
def chk(name, cond):
    if not cond:
        fails.append(name)

# 1. LICENSE bez pełnego nazwiska autora w copyright (dane osobowe autora
# trafiające do każdej instalacji sklonowanej z repo - ostatni taki literał
# poza CLAUDE.md, który jest w .gitignore).
license_src = open("LICENSE", encoding="utf-8").read()
chk("license_bez_nazwiska", "Żelazowski" not in license_src and "Grzegorz" not in license_src)

# 2. Domyślna (żadnego GREGAI_USER_GENDER w środowisku) wartość odtwarza
# dokładnie stary literał - zero zmiany zachowania, dopóki nikt nie ustawi .env.
os.environ.pop("GREGAI_USER_GENDER", None)
import persona as pe
importlib.reload(pe)
chk("gender_domyslny", pe.USER_IS_FEMALE is False and pe.USER_GENDER_NOUN == "mężczyzna"
    and pe.USER_GENDER_FORMS == "formy męskie" and pe.USER_GENDER_FORM_LOC == "formie męskiej")

# 3. Własny rodzaj z .env podstawia się wszędzie, gdzie trzeba - awareness.py
# i namysl.py (oba miejsca szkicu/poprawy), bez zostawionego starego literału.
os.environ["GREGAI_USER_GENDER"] = "z"
importlib.reload(pe)
chk("gender_z_env", pe.USER_IS_FEMALE is True and pe.USER_GENDER_NOUN == "kobieta"
    and pe.USER_GENDER_FORMS == "formy żeńskie" and pe.USER_GENDER_FORM_LOC == "formie żeńskiej")

import awareness as aw
importlib.reload(aw)
_reguly = aw._local_rules()
chk("awareness_bez_literalu", "mężczyzna: formy męskie" not in _reguly and "kobieta: formy żeńskie" in _reguly)

import namysl as ns
importlib.reload(ns)
chk("namysl_bez_literalu_rodzaj", "formy męskie" not in ns._SZKIC_SUFFIX and "formy męskie" not in ns._POPRAWA_SUFFIX
    and "formie żeńskiej" in ns._SZKIC_SUFFIX and "formy żeńskie" in ns._POPRAWA_SUFFIX)

# 4. Wołacz w bramce: blokada podmiotu trzeciej osoby łapie też czasownik
# czasu przeszłego w rodzaju żeńskim/neutralnym ("-ła"/"-ło"), nie tylko męski
# ("-ł") - inaczej zwrot do Ciebie (GREGAI_USER_GENDER=z) byłby mylony z
# podmiotem w opisie trzecioosobowym odtworzonym przez model.
os.environ.pop("GREGAI_USER_GENDER", None)
importlib.reload(pe)
import bramka as br
importlib.reload(br)
poprawiony_m, _ = br.review("Grzegorz zdecydował się na to.")
poprawiony_z, _ = br.review("Grzegorz zdecydowała się na to.")
poprawiony_n, _ = br.review("Grzegorz, zrobiłem to zadanie.")
chk("bramka_wolacz_rodzaj_podmiotu", "Grzegorz zdecydował" in poprawiony_m
    and "Grzegorz zdecydowała" in poprawiony_z and "Grzegorzu, zrobiłem" in poprawiony_n)

print("OK" if not fails else "FAIL " + ",".join(fails))
PY
)"
if [ "$TURA69_CHECK" = "OK" ]; then
  ok 69 "Przygotowanie pod open source (tura 5/5, finalna): LICENSE bez nazwiska autora; rodzaj użytkownika konfigurowalny przez .env (domyślnie bez zmiany zachowania), wołacz w bramce rozpoznaje też żeńskie/neutralne formy czasownika"
else
  bad 69 "Open source tura 5/5: ${TURA69_CHECK:-błąd importu}" "sprawdź LICENSE, agent/persona.py (USER_GENDER*), agent/awareness.py, agent/namysl.py, agent/bramka.py"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  printf '\033[1;32m== %d/69 OK - GREGAI gotowy: http://localhost:%s\033[0m\n\n' "$PASS" "$PORT"
  exit 0
fi
printf '\033[1;31m== %d/69 OK, do poprawy: %s\033[0m\n\n' "$PASS" "${FAILED[*]}"
exit 1
