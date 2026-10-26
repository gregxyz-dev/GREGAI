# Utwardzanie Linuksa
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Konkretne utwardzenie (hardening) systemu
Ubuntu, pod kątem laptopa-serwera jak w GREGAI. Zasada: [[Podstawy
bezpieczeństwa]] w praktyce. Komendy: [[Komendy Linuksa: system i
procesy]], [[Komendy Linuksa: sieć i bezpieczeństwo]].

## Aktualizacje

- `sudo apt update && sudo apt full-upgrade` regularnie. Większość włamań
  idzie przez znane, załatane dziury.
- `unattended-upgrades` dla łatek bezpieczeństwa automatycznie. W GREGAI
  jest chroniony: model nie może go wyłączyć.

## Konta i uprawnienia

- Osobne konto użytkownika, root wyłączony do logowania bezpośredniego.
- `sudo` zamiast pracy jako root; dokładnie dobrana lista w
  `/etc/sudoers.d/` (reguły wąskie, bez `ALL`, bez gwiazdek). Walidacja
  `visudo -c`.
- Silne, unikatowe hasło konta (patrz [[Uwierzytelnianie i sekrety]]).
- Zasada najmniejszych uprawnień wszędzie.

## Dysk i dane

- **Szyfrowanie całego dysku** (LUKS) - skradziony laptop bez hasła = nic
  do odczytania. W GREGAI obowiązkowe.
- Prawa plików: sekrety `chmod 600`, katalogi prywatne `700`. `.env` nigdy
  światu do odczytu.
- Kopie zapasowe szyfrowane i offline (ransomware nie zaszyfruje tego, co
  odłączone).

## Sieć

- Zapora `ufw`: domyślnie blokuj przychodzące, pozwól wychodzące. Otwieraj
  port tylko, gdy naprawdę trzeba. Patrz [[Bezpieczeństwo sieci]].
- Usługi nasłuchują tylko tam, gdzie muszą: `127.0.0.1` zamiast `0.0.0.0`,
  jeśli dostęp ma być lokalny (w GREGAI serwer i Ollama tylko na localhost).
- SSH (jeśli w ogóle): klucze zamiast haseł, bez logowania roota,
  `fail2ban` na próby.

## Usługi i powierzchnia ataku

- `systemctl list-unit-files --state=enabled` - wyłącz, czego nie
  używasz.
- `ss -tulpn` - zobacz, co nasłuchuje. Każdy otwarty port to drzwi.
- Mniej zainstalowanego = mniej do łatania.

## Jądro i izolacja

- `AppArmor` (w Ubuntu domyślnie) ogranicza, co proces może zrobić, nawet
  jeśli zostanie przejęty. W GREGAI chroniony przed wyłączeniem.
- Parametry jądra (`sysctl`): utwardzenia sieciowe, ASLR (losowanie adresów
  pamięci), ograniczenie `ptrace`.
- Kontenery/sandboksy dla ryzykownych rzeczy.

## Logi i audyt

- `journalctl` do przeglądu; `auditd` do śledzenia wrażliwych zdarzeń
  (dostęp do plików, wywołania systemowe).
- Logi najlepiej wysyłać poza maszynę, żeby napastnik nie wyczyścił śladów.
- Patrz [[Wykrywanie i reakcja na incydent]].

## Szybka lista kontrolna

1. Zaktualizowany system, auto-łatki bezpieczeństwa.
2. Dysk zaszyfrowany, kopie zapasowe offline.
3. Zapora: blokuj przychodzące.
4. Usługi tylko na localhost, jeśli to możliwe.
5. Silne, unikatowe hasła + MFA, gdzie się da.
6. Minimum zainstalowanych usług i otwartych portów.
7. AppArmor włączony, sudo wąsko dobrane.
8. Logi zbierane i przeglądane.
