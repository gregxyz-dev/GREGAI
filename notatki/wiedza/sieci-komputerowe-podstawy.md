# Sieci komputerowe - podstawy
type: Wiedza

Część [[Nauka i technika]]. Podstawy działania sieci i diagnostyka z terminala Linuksa. Bezpieczeństwo sieci osobno: [[Bezpieczeństwo sieci]].

## Adres IP i maska

- IPv4 to 32 bity zapisane jako cztery liczby 0-255, np. `192.168.1.20`. IPv6 ma 128 bitów (zapis szesnastkowy).
- Maska dzieli adres na część sieci i część hosta. Zapis `/24` oznacza 24 bity sieci, czyli `255.255.255.0`. W sieci /24 jest 256 adresów, z czego 254 dla urządzeń (pierwszy to adres sieci, ostatni to broadcast). Ogólnie hostów w /n: 2^(32-n) - 2.
- Adresy prywatne (nie trasowane w internecie): `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`. Link-local `169.254.0.0/16` (brak DHCP). Pętla zwrotna `127.0.0.1` (localhost).
- Zakres `100.64.0.0/10` to CGNAT, często używany przez operatorów komórkowych. Jeśli przez modem LTE masz taki adres, nie jesteś osiągalny z zewnątrz bez tunelu.
- Brama domyślna (gateway) to router, do którego trafia ruch spoza sieci lokalnej.

## DNS

- Zamienia nazwy na adresy. Rekordy: A (IPv4), AAAA (IPv6), CNAME (alias), MX (poczta), TXT (tekst, weryfikacje), NS (serwery nazw).
- Gdy "działa ping po IP, a po nazwie nie", problem leży w DNS, nie w łączu.
- Na Ubuntu zwykle działa `systemd-resolved`: `resolvectl status` pokazuje używane serwery.

## NAT

- Router domowy lub operator tłumaczy wiele adresów prywatnych na jeden publiczny, pamiętając mapowanie portów. Dlatego z zewnątrz nie widać urządzeń w domu.
- Dostęp z zewnątrz wymaga przekierowania portu (port forwarding), tunelu (VPN, Tailscale, Cloudflare Tunnel) lub publicznego adresu. Każde otwarcie portu zwiększa powierzchnię ataku.

## Porty, TCP i UDP

- Port (0-65535) wskazuje usługę na hoście. Znane: 22 SSH, 53 DNS, 80 HTTP, 443 HTTPS, 25/587 SMTP, 123 NTP, 67/68 DHCP. Ollama domyślnie 11434.
- TCP: połączeniowy, gwarantuje kolejność i dostarczenie (WWW, SSH, poczta). UDP: bez gwarancji, szybki i lekki (DNS, strumienie, gry, VoIP).
- Gniazdo nasłuchujące na `127.0.0.1` jest dostępne tylko lokalnie, na `0.0.0.0` z całej sieci. Usługi pomocnicze wiąż z localhost.

## DHCP

- Serwer (zwykle router) przydziela adres, maskę, bramę i DNS na określony czas (dzierżawa). Rezerwacja po adresie MAC daje stały adres serwerowi domowemu.
- Brak odpowiedzi DHCP kończy się adresem `169.254.x.x`.

## Warstwy i trasa pakietu

- Uproszczenie: łącze (Ethernet, Wi-Fi, LTE) -> IP -> TCP/UDP -> aplikacja (HTTP, DNS). TLS szyfruje na wierzchu TCP (HTTPS).
- MTU to maksymalny rozmiar pakietu, typowo 1500. Na niektórych łączach (LTE, tunele VPN) bywa mniejszy, a objawem są strony, które się "wieszają" po nawiązaniu połączenia.

## Diagnostyka krok po kroku

1. Interfejs i adres: `ip a` (lub `ip -br a`). Trasy i brama: `ip r`.
2. Brama: `ping -c 4 192.168.1.1` (podstaw swoją bramę z `ip r`).
3. Internet po IP: `ping -c 4 1.1.1.1`. Jeśli działa, a nazwy nie, to DNS.
4. DNS: `dig example.com` (pełna odpowiedź), `dig +short example.com`, `dig @1.1.1.1 example.com` (zapytanie do konkretnego serwera, porównaj z domyślnym). Alternatywa: `resolvectl query example.com`. Pakiet z `dig`: `dnsutils` (Ubuntu) lub `bind9-dnsutils` w nowszych wydaniach.
5. Trasa: `traceroute example.com` albo `tracepath example.com` (nie wymaga roota), `mtr example.com` pokazuje straty na każdym skoku. Gwiazdki `* * *` nie zawsze oznaczają awarię, część routerów nie odpowiada.
6. Co nasłuchuje: `ss -tulpn` (TCP i UDP, nasłuch, procesy; `sudo` pokaże nazwy cudzych procesów). Aktywne połączenia: `ss -tn`. Filtr: `ss -tulpn | grep 11434`.
7. Test portu zdalnego: `nc -zv host 443` (jeśli jest `netcat`) lub `curl -I https://example.com`.
8. Prędkość i opóźnienia: `ping` pokazuje ms i utratę pakietów. Wysoka utrata na Wi-Fi lub LTE zwykle oznacza słaby sygnał.

## Modem LTE w laptopie (WWAN)

- Karta WWAN w Linuksie jest zwykle obsługiwana przez ModemManager i NetworkManager: `mmcli -L` (lista modemów), `nmcli device` (stan urządzeń), `nmcli connection show`.
- Potrzebny jest APN operatora (ustawienia profilu GSM). Sprawdź go w danych operatora, bo różni się między planami.
- Przy LTE zwróć uwagę na CGNAT, limity transferu i mniejsze MTU. Na łączu z limitem unikaj dużych aktualizacji i uploadów wideo.

## Higiena

- Nie wystawiaj do internetu portów bez potrzeby, a usługi administracyjne (SSH) zabezpiecz kluczami. Patrz [[Cyberbezpieczeństwo]] i [[Linux: administracja zaawansowana]].
- Zapora na Ubuntu: `sudo ufw status`, `sudo ufw allow 22/tcp`, `sudo ufw enable`. Przed włączeniem zapory zdalnie upewnij się, że nie odetniesz sobie SSH.
