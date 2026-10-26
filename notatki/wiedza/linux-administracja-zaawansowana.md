# Linux: administracja zaawansowana
type: Wiedza

Część [[Nauka i technika]]. Rozszerza [[Komendy Linuksa: system i procesy]]. Ubuntu na starszym laptopie. Polecenia z `sudo` zmieniają system, więc czytaj je uważnie, a dyski ruszaj tylko po sprawdzeniu nazwy urządzenia (`lsblk`).

## systemd: unity i timery

- Unit usługi trafia do `/etc/systemd/system/nazwa.service`. Minimalny przykład:

```
[Unit]
Description=Moja usluga
After=network-online.target

[Service]
User=grzegorz
WorkingDirectory=/home/grzegorz/projekt
ExecStart=/usr/bin/python3 serwer.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

- Po zmianie pliku: `sudo systemctl daemon-reload`, potem `sudo systemctl enable --now nazwa`. Logi: `journalctl -u nazwa -f`. Diagnostyka: `systemctl status nazwa`, `systemctl --failed`.
- Nadpisania bez edycji oryginału: `sudo systemctl edit nazwa` (tworzy drop-in).
- Timer zastępuje cron: plik `nazwa.timer` z sekcją `[Timer]` (`OnCalendar=daily` lub `OnCalendar=*-*-* 03:00:00`, `Persistent=true`) i `[Install] WantedBy=timers.target` uruchamia `nazwa.service`. Włączenie: `sudo systemctl enable --now nazwa.timer`. Lista: `systemctl list-timers`. Składnię czasu testuj: `systemd-analyze calendar "Mon *-*-* 03:00"`.
- Czas startu: `systemd-analyze`, `systemd-analyze blame` (co spowalnia start).

## Dyski, ext4, LVM

- Przegląd: `lsblk -f`, `blkid`, `df -h`, `sudo fdisk -l`. Zdrowie: `sudo smartctl -H /dev/sda` (pakiet `smartmontools`).
- Nowy system plików (kasuje dane na partycji): `sudo mkfs.ext4 /dev/sdX1`. Przed tym trzy razy sprawdź nazwę.
- Montowanie na stałe: wpis w `/etc/fstab` z UUID, np. `UUID=... /mnt/dane ext4 defaults,nofail 0 2`. `nofail` chroni przed zawieszeniem startu, gdy dysku nie ma. Test bez restartu: `sudo mount -a`. Błąd w fstab potrafi uniemożliwić start, więc zrób kopię pliku.
- Sprawdzenie systemu plików: `sudo fsck -f /dev/sdX1` tylko na odmontowanej partycji.
- LVM: warstwy PV (dysk) -> VG (grupa) -> LV (wolumen). Podgląd: `sudo pvs`, `sudo vgs`, `sudo lvs`. Powiększenie wolumenu wraz z systemem plików: `sudo lvextend -r -L +10G /dev/vg/lv` (opcja `-r` zmienia też rozmiar ext4). Dodanie dysku: `pvcreate`, `vgextend`. Zmniejszanie jest ryzykowne, zrób kopię.
- Miejsce zajęte: `du -h --max-depth=1 / 2>/dev/null | sort -h`, narzędzie `ncdu` pokazuje je interaktywnie.

## Backup: rsync i tar

- Kopia katalogu: `rsync -aAXH --delete --info=progress2 /zrodlo/ /cel/`. Ukośnik na końcu źródła znaczy "zawartość katalogu". Najpierw próba: dodaj `-n` (dry run). `--delete` usuwa w celu pliki, których nie ma w źródle, więc pomyłka w kolejności argumentów kasuje dane.
- Po sieci: `rsync -az -e ssh /zrodlo/ user@host:/cel/`.
- Archiwum: `tar czf kopia.tar.gz katalog/`, rozpakowanie `tar xzf kopia.tar.gz`, lista `tar tzf kopia.tar.gz`.
- Reguła 3-2-1: trzy kopie, dwa rodzaje nośników, jedna poza domem. Kopia, której nie sprawdzono odtworzeniem, jest tylko nadzieją.

## Uprawnienia

- `ls -l` pokazuje `rwxr-xr--`: właściciel, grupa, inni. Liczbowo r=4, w=2, x=1: `chmod 640 plik`, `chmod 755 skrypt.sh`, `chmod +x skrypt.sh`.
- Właściciel: `sudo chown user:grupa plik`, rekurencyjnie `-R`. Na katalogu x oznacza prawo wejścia.
- `umask` (np. 022) odejmuje bity od nowych plików. Sekrety i klucze: `chmod 600`. Klucz prywatny SSH z luźnymi uprawnieniami zostanie odrzucony.
- Unikaj `chmod 777`. ACL: `getfacl`, `setfacl -m u:user:rw plik`.

## Logi

- Wszystko w journald: `journalctl -b` (od startu), `journalctl -p err -b` (błędy), `journalctl --since "1 hour ago"`, `journalctl -k` (jądro).
- Rozmiar: `journalctl --disk-usage`, czyszczenie: `sudo journalctl --vacuum-time=2weeks` lub `--vacuum-size=500M`.
- Klasyczne pliki w `/var/log` (np. `auth.log`, `syslog`), rotacja przez `logrotate`. Komunikaty sprzętu: `dmesg -T` (czasem wymaga sudo).

## Cron

- Edycja: `crontab -e`, lista `crontab -l`. Pięć pól: minuta godzina dzień-miesiąca miesiąc dzień-tygodnia, np. `30 3 * * *` to codziennie 03:30. Jeden zapis: `*/15 * * * *` co 15 minut.
- Cron ma ubogie środowisko: używaj pełnych ścieżek i przekierowuj wyjście (`>> /home/user/log.txt 2>&1`). Dla nowych zadań wygodniejszy jest timer systemd.

## Diagnoza wolnego systemu

1. `uptime` i `top`: obciążenie (load) względem liczby wątków (`nproc`, tu 4). Kto zjada CPU: `top` potem `P`, pamięć `M`.
2. Pamięć: `free -h`. Gdy swap jest mocno używany, a RAM pełny, system się dławi. `vmstat 1` pokazuje swap (kolumny si, so).
3. Dysk: `iostat -x 1` (pakiet `sysstat`) i `iotop`. Wysokie `%iowait` w `top` to wąskie gardło dysku. Pełny dysk: `df -h`. Zdrowie: `smartctl`.
4. Temperatura: `sensors`. Laptop przegrzany obniża taktowanie (thermal throttling), więc wszystko zwalnia. Pomaga czyszczenie wentylatora i praca z `nice -n 19`.
5. Start: `systemd-analyze blame`. Zbędne usługi wyłącz (`systemctl disable`).
6. Zbędne procesy w tle (przeglądarka z wieloma kartami, modele Ollamy trzymane w RAM): `ollama ps`.
7. Aktualizacje: `sudo apt update && sudo apt upgrade`, czyszczenie `sudo apt autoremove`. Patrz też [[Sieci komputerowe - podstawy]].
