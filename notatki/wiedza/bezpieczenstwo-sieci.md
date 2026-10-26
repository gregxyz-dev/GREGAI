# Bezpieczeństwo sieci
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Jak chronić drogę komputer - sieć -
internet. Komendy: [[Komendy Linuksa: sieć i bezpieczeństwo]].

## Model warstwowy (uproszczony)

Dane idą przez warstwy: aplikacja (HTTP, DNS) - transport (TCP/UDP, porty)
- sieć (IP, routing) - łącze (Ethernet, Wi-Fi, MAC). Atak i obrona mogą
dziać się na każdej. Zrozumienie warstw pomaga wiedzieć, co dana ochrona
faktycznie chroni.

## Zapora (firewall)

- Filtruje ruch po adresach, portach, kierunku. Reguła domyślna: **blokuj
  przychodzące, pozwól wychodzące** (dom/serwer osobisty).
- W Ubuntu: `ufw`. Zaawansowane: `nftables`/`iptables` pod spodem.
- Otwieraj port tylko wtedy, gdy usługa naprawdę ma być dostępna z sieci.
  W GREGAI nic nie jest wystawione, więc nie trzeba otwierać nic.

## DNS

- Zamienia nazwy na adresy IP. Zwykły DNS jest jawny: dostawca widzi, co
  odwiedzasz, i może podmienić odpowiedź.
- **DNS over HTTPS/TLS** (DoH/DoT) szyfruje zapytania. **1.1.1.1** (Cloudflare)
  i warianty z blokadą złośliwych domen (families malware) podnoszą
  bezpieczeństwo. W GREGAI DNS idzie przez WARP z blokadą malware.
- Zagrożenia: DNS spoofing/cache poisoning (podmiana odpowiedzi),
  DNS tunneling (ukryty kanał eksfiltracji). Obrona: szyfrowany DNS,
  monitoring nietypowych zapytań.

## TLS/HTTPS

- Szyfruje i uwierzytelnia połączenie (poufność + autentyczność +
  integralność). Kłódka to TLS, nie "strona jest bezpieczna".
- Certyfikaty: urząd (CA) poświadcza tożsamość serwera. **HSTS** (najlepiej
  z listą preload) wymusza HTTPS, a **Certificate Transparency** pozwala
  wykryć błędnie wystawione certyfikaty. Przypinanie certyfikatu (pinning) w
  przeglądarkach wycofano (HPKP); dziś tylko we własnych aplikacjach i z
  planem rotacji kluczy.
- W GREGAI: wszystko do internetu tylko przez `https`, także po
  przekierowaniach (netguard).

## VPN i WARP

- **VPN/tunel** szyfruje ruch między Tobą a punktem wyjścia, chowając go
  przed lokalnym dostawcą sieci (kawiarnia, hotel). **Cloudflare WARP** to
  taki tunel (nie klasyczny VPN z logowaniem do firmowej sieci).
- Czego VPN **nie** robi: nie daje anonimowości (dostawca VPN widzi ruch),
  nie chroni przed atakiem przychodzącym - to robi zapora i nasłuch tylko
  na localhost. Patrz [[OPSEC i prywatność]].
- W GREGAI WARP jest obowiązkowy i fail-closed: bez niego nic nie wychodzi.

## Wi-Fi

- Używaj WPA3 (lub WPA2) z długim hasłem; unikaj WEP i sieci otwartych.
- W obcej sieci zakładaj, że ktoś podsłuchuje: tunel (WARP) + HTTPS.
- Adres MAC bywa losowany dla prywatności; w GREGAI rozpoznanie sieci
  domowej opiera się na bramie i jej MAC, zapamiętanym świadomie.

## Ataki sieciowe (świadomość obronna)

- **MITM**: podsłuch/podmiana w drodze. Obrona: TLS, VPN, HSTS.
- **ARP spoofing**: podszycie w sieci lokalnej. Obrona: segmentacja,
  monitoring.
- **DDoS**: zalanie ruchem. Obrona: filtrowanie, limity, usługi ochrony.
- **Skanowanie portów**: mapowanie, co nasłuchuje. Obrona: mała powierzchnia,
  nic niewystawione. Patrz [[Techniki atakujących (obrona)]].

## Segmentacja

Oddziel strefy o różnym zaufaniu (np. IoT na osobnej sieci/VLAN). Przejęcie
jednej strefy nie daje dostępu do reszty. To zero trust w sieci.
