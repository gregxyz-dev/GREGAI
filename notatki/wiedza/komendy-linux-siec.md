# Komendy Linuksa: sieć i bezpieczeństwo
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Diagnostyka sieci i narzędzia obronne na
**własnym** systemie. Poprzednie: [[Komendy Linuksa: pliki i tekst]],
[[Komendy Linuksa: system i procesy]].

## Adresy i trasy

- `ip addr` - adresy interfejsów. `ip -4 addr show dev wlp1s0` - konkretny
  interfejs. `ip route` - tablica tras (brama domyślna). `ip neigh` -
  tablica ARP (sąsiedzi w sieci lokalnej; tak GREGAI rozpoznaje bramę).
- `hostname -I` - adresy IP maszyny. `nmcli` - zarządzanie siecią (Wi-Fi,
  połączenia).

## Co nasłuchuje i co jest połączone

- `ss -tulpn` - otwarte porty i procesy za nimi (TCP/UDP, nasłuch).
  Kluczowe do sprawdzenia powierzchni ataku: każdy nasłuch to drzwi.
  (`netstat -tulpn` - starszy odpowiednik.)
- `ss -tnp` - aktywne połączenia TCP. Szukaj nietypowych połączeń
  wychodzących. Patrz [[Wykrywanie i reakcja na incydent]].
- `lsof -i :7777` - kto trzyma dany port.

## Diagnostyka łączności

- `ping host` - czy odpowiada. `traceroute host` / `mtr host` - trasa
  pakietów. `dig domena` / `nslookup domena` - zapytania DNS.
  `dig +short domena` - sam wynik.
- `curl -I https://host` - nagłówki odpowiedzi (bez treści). `curl -s URL`
  - cicho pobierz. `wget URL` - pobierz plik. Zawsze preferuj `https`.
- W GREGAI cały ruch wychodzi przez WARP (`https` tylko); sprawdzenie:
  `curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp` ->
  `warp=on`. Patrz [[Bezpieczeństwo sieci]].

## Zapora (ufw)

- `sudo ufw status verbose` - stan i reguły. `sudo ufw enable` - włącz.
- `sudo ufw default deny incoming` + `default allow outgoing` - rozsądna
  baza. `sudo ufw allow 22/tcp` - otwórz port (tylko gdy trzeba).
  `sudo ufw delete ...` - usuń regułę.
- W GREGAI zapora blokuje przychodzące; nic nie trzeba otwierać, bo nic nie
  jest wystawione.

## WARP (Cloudflare)

- `warp-cli status` - połączony czy nie. `warp-cli connect` /
  `warp-cli disconnect`. `warp-cli registration show` - rejestracja.
  `warp-cli dns families malware` - DNS z blokadą złośliwych domen.
- W GREGAI WARP jest obowiązkowy i fail-closed (bez niego nic nie wychodzi),
  a model nie może go rozłączyć.

## Narzędzia obronne (na swoim systemie, za zgodą)

- `fail2ban` - blokuje adresy po serii nieudanych logowań (np. SSH).
- `auditd` + `ausearch`/`aureport` - audyt dostępu do wrażliwych plików i
  wywołań systemowych.
- `clamav` (`clamscan`) - skan plików pod kątem znanego malware.
- `tcpdump -i wlp1s0` - podgląd ruchu na **swoim** interfejsie (diagnostyka).
  `wireshark` - to samo z interfejsem graficznym.
- `nmap localhost` - jakie porty ma **Twoja** maszyna (audyt własnej
  powierzchni ataku).

## Zasada etyczna

Skanowanie, podsłuch i testy prowadź wyłącznie na **własnym** sprzęcie i
sieci albo tam, gdzie masz wyraźną **zgodę** (programy bug bounty, własne
konta testowe). Bez zgody to łamanie prawa. GREGAI pomaga bronić i
diagnozować własny system, nie atakować cudze. Patrz [[OPSEC i prywatność]].

## Szybki audyt własnej maszyny (checklist komend)

1. `ss -tulpn` - co nasłuchuje? (powinno być minimum)
2. `sudo ufw status` - zapora aktywna?
3. `systemctl list-unit-files --state=enabled` - co startuje?
4. `sudo journalctl --since '7 days ago' --grep 'Failed password|Invalid user|authentication failure' | tail` - próby włamań przez logowanie?
5. `ss -tnp` - podejrzane połączenia wychodzące?
6. `sudo smartctl -H /dev/sda` - dysk zdrowy?
7. `apt list --upgradable` - są łatki do zainstalowania?
