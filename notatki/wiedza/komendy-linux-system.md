# Komendy Linuksa: system i procesy
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Procesy, usługi, zasoby, użytkownicy, dyski,
logi. Poprzednia: [[Komendy Linuksa: pliki i tekst]]. Dalej: [[Komendy
Linuksa: sieć i bezpieczeństwo]].

## Procesy

- `ps aux` - wszystkie procesy. `ps aux | grep nazwa` - znajdź konkretny.
- `top` / `htop` - na żywo, CPU/RAM, sortowanie. W `top`: `q` wychodzi,
  `M` sortuj po pamięci, `P` po CPU.
- `kill PID` - poproś o zakończenie. `kill -9 PID` - wymuś (ostateczność).
  `pkill nazwa`, `pgrep nazwa` (ostrożnie z wzorcem, by nie trafić siebie).
- `nice -n 19 polecenie` - uruchom z niskim priorytetem (ustępuje reszcie;
  tak odpalamy trening w GREGAI). `nohup polecenie &` - w tle, przeżyje
  zamknięcie terminala.
- `jobs`, `fg`, `bg` - zadania powłoki. Ctrl+Z wstrzymaj, Ctrl+C przerwij.

## Usługi (systemd)

- `systemctl status usluga` - stan. `systemctl start/stop/restart usluga`.
- `systemctl enable --now usluga` - włącz na stałe i teraz. `disable` -
  wyłącz autostart.
- `systemctl list-units --type=service` - działające usługi.
  `list-unit-files --state=enabled` - co startuje z systemem (przejrzyj pod
  kątem bezpieczeństwa). Patrz [[Utwardzanie Linuksa]].
- `journalctl -u usluga` - logi usługi. `journalctl -u usluga -f` - na
  żywo. `journalctl -b` - od ostatniego startu. `journalctl -p err` -
  tylko błędy. (Tak oglądamy logi usługi `gregai`.)

## Zasoby

- `free -h` - pamięć RAM i swap. `uptime` - obciążenie i czas pracy.
- `df -h` - miejsce na dyskach. `du -sh *` - co zajmuje miejsce tutaj.
- `lsblk` - dyski i partycje. `lscpu` - procesor. `nproc` - liczba rdzeni.
- `sensors` - temperatury (pakiet `lm-sensors`). `smartctl -H /dev/sda` -
  zdrowie dysku (SMART).

## Użytkownicy i uprawnienia

- `whoami`, `id` (kto i w jakich grupach). `who`, `w` - kto zalogowany.
- `sudo polecenie` - jako root. `sudo -l` - co mi wolno przez sudo.
- `useradd`/`adduser`, `passwd user` - konta i hasła (ostrożnie).
- `last` - historia logowań (od Ubuntu 25.04 dostarcza go pakiet `wtmpdb` z
  universe, nie jest domyślnie zainstalowany: `sudo apt install wtmpdb
  libpam-wtmpdb`). `lastb` w nowych wydaniach już nie ma. Nieudane logowania
  (sygnał ataku siłowego): `sudo journalctl --since '7 days ago' --grep 'Failed
  password|Invalid user|authentication failure'`. Patrz [[Wykrywanie i reakcja na incydent]].
- Pliki: `/etc/passwd` (konta), `/etc/group`, `/etc/sudoers.d/` (reguły
  sudo). Nie edytuj sudoers ręcznie - `visudo` (waliduje składnię).

## Dyski i pamięć masowa

- `mount` / `umount` - podłączanie. `lsblk -f` - systemy plików i etykiety.
- Szyfrowanie: LUKS (`cryptsetup`). `swapon --show` - plik/partycja
  wymiany.

## Zadania cykliczne

- `crontab -e` - edytuj swoje zadania cron. `crontab -l` - pokaż.
  `systemctl list-timers` - timery systemd (tak działa skan sieci w GREGAI,
  `gregai-siec.timer`).
- Uwaga bezpieczeństwa: nowe, nieznane wpisy cron/timer to typowy sposób
  utrwalenia się napastnika. Przeglądaj je. Patrz [[Techniki atakujących
  (obrona)]].

## Pakiety

- `apt update` (odśwież listy), `apt upgrade`/`full-upgrade` (zainstaluj
  łatki), `apt install pakiet`, `apt remove pakiet`, `apt search`.
- `dpkg -l` - zainstalowane. `apt list --upgradable` - co do aktualizacji.
- Instaluj z oficjalnych repozytoriów; cudze źródła to zaufanie i ryzyko.

## Środowisko

- `env` - zmienne środowiskowe. `export ZMIENNA=wartosc`. `echo $ZMIENNA`.
- Uwaga: sekrety w zmiennych środowiskowych bywają widoczne innym procesom
  i w logach - w GREGAI są dlatego wycinane z wyników poleceń.
