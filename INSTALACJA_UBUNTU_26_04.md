# GREGAI: instalacja na Ubuntu 26.04.1 LTS (Dell E7270)

Plik do wykonania, krok po kroku: od czystego dysku SSD do działającego
GREGAI. Ustalone 2026-10-09: laptop jest
jednocześnie serwerem GREGAI i zwykłym komputerem do codziennej pracy, a
GREGAI obsługujesz WYŁĄCZNIE z tego samego laptopa.

Polecenia wklejasz do terminala (Ctrl+Alt+T; wklejanie w terminalu:
Ctrl+Shift+V). Bloki oznaczone "na starym laptopie" robisz na starym, resztę
na nowym.

## Najkrótsza droga: jedna komenda, z dowolnego folderu

Masz już zainstalowane Ubuntu 26.04.1 Desktop (Kroki 0-5 poniżej) i folder
`GREGAI` (z paczki `GREGAI.zip` albo przeniesiony z dysku/pendrive'a)?
Połóż go **gdziekolwiek** i wpisz jedną komendę:

```bash
bash /sciezka/do/GREGAI/install.sh
```

Skrypt robi sam Kroki 6, 8, 9 i 12 (laptop jako serwer, `.env`, pakiety,
WARP, Ollama z modelem 3B, usługi, sudo, zapora, swap 8 GB, router domowy) i
na końcu odpala `check.sh` (liczbę kontroli pokazuje sam skrypt). Pyta tylko o: hasło sudo, warunki
Cloudflare WARP (akceptujesz je sam) i klucz Anthropic (Enter = pomiń).
Dodatkowo `--train` uruchamia w tle trening router + planer + uczeń (Krok 10).

Przenosisz folder w inne miejsce (inny katalog, inna nazwa)? **Ta sama
komenda w nowym miejscu**: skrypt wykryje przeniesienie, wypisze starą i
**nową ścieżkę**, przepnie usługi systemd i `SYSOP_ROOTS` w `.env`, nic nie
skasuje w starym miejscu. Folder na dysku USB (np. Twoim 500 GB) albo w
katalogu tymczasowym nie nadaje się na stałe miejsce usługi (po restarcie
dysku nie ma, a FAT/exFAT/NTFS nie trzyma praw `600` dla `.env`): wtedy
skrypt sam skopiuje projekt z `.env` i danymi do `~/Dokumenty/GREGAI` i zainstaluje
stamtąd. Reszta tego pliku to wyjaśnienie, co dokładnie się dzieje, i
instrukcja ręczna na wypadek, gdyby coś trzeba było zrobić samemu.

## Jeden system, nie dwa obok siebie (ważne)

Dual boot (Ubuntu Server i Ubuntu dla zwykłego użytkownika jako dwa
osobne systemy na jednym dysku) tu NIE zadziała: komputer uruchamia
naraz tylko jeden system. Pracując w "zwykłym" Ubuntu miałbyś wyłączony
serwer, a żeby porozmawiać z GREGAI, musiałbyś restartować laptop.

Dlatego: **jedno Ubuntu 26.04.1 LTS w wersji Desktop** (pulpit dla
zwykłego użytkownika) i GREGAI w nim jako usługa systemowa w tle:
- startuje sam przy włączeniu laptopa, jeszcze przed zalogowaniem,
- działa cały czas, niezależnie od tego, co robisz na pulpicie,
- rozmawiasz z nim w przeglądarce na tym samym laptopie:
  **`http://localhost:7777`** (adres stały, działa w każdej sieci i bez
  internetu, bez tokenu),
- do sieci nic nie jest wystawione (`GREGAI_LAN=0`), więc nie potrzeba
  stałego IP w routerze, SSH ani otwierania portów.

## Ustalenia

| | |
|---|---|
| Laptop | **Dell Latitude E7270** |
| Procesor | **Intel Core i7-6600U** (2 rdzenie / 4 wątki, 2.6 GHz, AVX2, bez AVX-512) |
| Grafika | Intel HD Graphics 520 (zintegrowana; Ollama jej nie używa, modele liczą się na CPU) |
| RAM | **16 GB DDR4 (2 x 8 GB)**, wspólne dla pulpitu, przeglądarki i modeli (patrz "Budżet RAM"). Kości 2400 MHz pracują tu z prędkością **2133 MHz**: to maksimum kontrolera pamięci i7-6600U - wszystko działa, tylko bez zysku z 2400. Ważne, że są dwie (dwa kanały = dwa razy większa przepustowość, a od niej zależy szybkość modeli) |
| Dysk | **Lite-On CV1-8B256-HP, 256 GB, M.2 2280 SATA**, cały dla Ubuntu (w systemie: `/dev/sda`) |
| Sieć | Wi-Fi Intel 8260, Ethernet Intel I219-LM - obie działają w Ubuntu bez dodatkowych sterowników |
| Obraz | **`ubuntu-26.04.1-desktop-amd64.iso`** (wersja Desktop, nie live-server) |
| Katalog projektu | **`~/Dokumenty/GREGAI`** (na starym laptopie `~/Dokumenty/SIECAI`) |
| Adres GREGAI | `http://localhost:7777` |
| Modele | router: **Qwen2.5-1.5B** (dotrenowany), uczeń: **Qwen2.5-1.5B** dystylowany **z chmury (Claude) + ręcznego seedu, NIE z lokalnego dużego modelu**, planer: **Qwen2.5-0.5B**, duży/SYSOP: **`qwen2.5:3b`** (decyzja 2026-10-12: zejście z 7B dla szybkości; 14B odpowiadał 4-6 min, 7B ok. 1-2 min), trudne pytania: chmura (Claude). Rozmiary zablokowane 2026-10-08 (na 8 GB RAM bazy schodzą do 0.5B zmienną `BASE_MODEL`) |
| Cloudflare | **WARP, obowiązkowy i wbudowany w projekt** (Krok 12): cały ruch laptopa do internetu szyfrowany przez Cloudflare; bez WARP GREGAI nie wychodzi do internetu; bez domeny, bez strony, nic nie jest wystawione |
| Priorytet | **cyberbezpieczeństwo** (decyzja 2026-10-09): wszystko niżej jest ustawione pod to - wyjaśnienie dlaczego w README.md, sekcja "Bezpieczeństwo" |

### Dysk: Lite-On CV1-8B256-HP (M.2 2280 SATA)

Gniazdo laptopa obsługuje ten dysk (sprawdzone). Co warto wiedzieć:
1. **To dysk OEM z laptopów HP, często używany.** Po instalacji sprawdź
   jego stan (Krok 5): zużycie i błędy.
2. **Prędkość:** SATA ok. 500 MB/s - model 3B (ok. 2 GB) wczytuje się z
   dysku w kilka sekund. GREGAI robi to sam zaraz po starcie (rozgrzewanie,
   Krok 10), a potem Ollama trzyma model w pamięci.
3. **Miejsce:** 256 GB wystarczy z zapasem: system ok. 25 GB, modele
   (`qwen2.5:3b` i wytrenowane) kilka GB, środowisko treningowe (venv, modele bazowe, GGUF, punkty kontrolne) ok. 20-25 GB (szacunek), swap 8 GB.

### Hasła (trzy różne, wszystkie na papierze)

1. **szyfrowanie dysku** (Krok 4) - wpisywane przy każdym włączeniu,
2. **konto** (Krok 4) - logowanie i `sudo`,
3. **archiwum z danymi** (Krok 0) - jednorazowe, do Kroku 7.

Hasło 1 wpisujesz przy włączaniu laptopa, zanim wczyta się polska
klawiatura, więc **tylko małe litery a-z, cyfry i myślniki, bez polskich
znaków** (np. cztery losowe słowa połączone myślnikami). Hasło 3 ułóż tak
samo: przepiszesz je z papieru na innym komputerze niż ten, na którym
powstało, i nic nie może zależeć od układu klawiatury.

---

## Krok 0: NAJPIERW zabezpiecz dane ze starego laptopa

Zanim cokolwiek wymienisz, sformatujesz albo zaczniesz instalację: na
**starym** laptopie spakuj dane (notatki, pamięć, wszystko, czego GREGAI
się nauczył, `.env`) do jednego zaszyfrowanego archiwum na pendrivie. W
`.env` są sekrety, więc na pendrivie nie mogą leżeć jawnie. Pendrive inny
niż ten, z którego będziesz instalować system (tamten zostanie wymazany).

**Na starym laptopie.** Najpierw zatrzymaj stary WEBAI (tak nazywał się wcześniej), żeby nic nie
zapisywał w trakcie pakowania (komunikat "not loaded" przy którejś nazwie
jest w porządku: tej usługi po prostu tam nie ma):

```bash
sudo systemctl stop webai.service
sudo systemctl stop siecai.timer siecai.service
```

Włóż pendrive i sprawdź jego nazwę (wstaw ją niżej w miejsce `PENDRIVE`):

```bash
ls "/media/$USER"
cd ~/Dokumenty/SIECAI
du -sh notatki memory data          # ile tego jest
```

Pendrive sformatowany jako FAT32 przyjmie plik najwyżej 4 GB. Jeśli
`notatki`, `memory` i `data` mają razem więcej niż ok. 3,5 GB, sformatuj
pendrive jako exFAT (aplikacja Dyski) albo daj znać.

```bash
tar -czf - notatki memory data .env \
  | gpg --symmetric --cipher-algo AES256 -o "/media/$USER/PENDRIVE/gregai-dane.tgz.gpg"
sync
```

`gpg` zapyta dwa razy o hasło do archiwum: wymyśl nowe, jednorazowe (zasady
w "Hasła" wyżej) i **zapisz na papierze** do Kroku 7. Jedno zaszyfrowane
archiwum zamiast wielu plików: zachowuje nazwy plików z dowolnymi znakami i
prawa dostępu, czego pendrive FAT32 sam by nie zrobił.

**Test, że archiwum naprawdę się otwiera** (bez tego nie idź dalej):
wysuń pendrive w menedżerze plików, wyjmij, włóż ponownie, potem:

```bash
gpgconf --kill gpg-agent             # gpg zapomina hasło, test sprawdzi to z papieru
gpg --decrypt "/media/$USER/PENDRIVE/gregai-dane.tgz.gpg" | tar -tzf - > /dev/null && echo ARCHIWUM_OK
```

Musi zapytać o hasło i wypisać `ARCHIWUM_OK`. Jeśli masz już
`GREGAI.zip` z tej rozmowy na starym laptopie, skopiuj go też na ten
pendrive (przyda się w Kroku 7, gdyby nowy laptop nie miał jeszcze sieci):

```bash
cp ~/Pobrane/GREGAI.zip "/media/$USER/PENDRIVE/"
```

Stary WEBAI zostaje zatrzymany. Gdybyś chciał go jeszcze używać:
`sudo systemctl start webai.service`.

## Krok 1: Pobranie i weryfikacja ISO

**Na starym laptopie:** z `https://releases.ubuntu.com/26.04/` pobierz w
przeglądarce `ubuntu-26.04.1-desktop-amd64.iso` (trafi do `~/Pobrane`),
potem:

```bash
cd ~/Pobrane
wget -O SHA256SUMS https://releases.ubuntu.com/26.04/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS
```

Musi wypisać `ubuntu-26.04.1-desktop-amd64.iso: OK`. Jeśli wypisze
`FAILED` albo nic: pobierz ISO jeszcze raz (plik z dopiskiem `(1)` w nazwie
to drugie pobranie: usuń stary i zmień nazwę nowego).

## Krok 2: Bootowalny pendrive (min. 8 GB, zostanie wymazany)

**Najpierw wyjmij pendrive z danymi z Kroku 0**, żeby go przez pomyłkę nie
wymazać. Potem włóż pendrive na system.

**Na starym laptopie:** aplikacja **Kreator dysków startowych** (Startup
Disk Creator): wybierz ISO i pendrive. Jeśli jej nie ma, w terminalu:

```bash
lsblk -d -o NAME,SIZE,TRAN,MODEL    # pendrive: TRAN = usb i jego rozmiar, np. sdb
cd ~/Pobrane
sudo dd if=ubuntu-26.04.1-desktop-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

W miejsce `sdX` wstaw nazwę pendrive'a z `lsblk` (np. `sdb`), **nigdy**
dysku z systemem (ten ma `TRAN` = `sata` albo `nvme`).

## Krok 3: BIOS Della (E7270)

1. Przy starcie: **F2** = ustawienia BIOS, **F12** = jednorazowe menu
   startowe (stąd wybierzesz pendrive).
2. **System Configuration -> SATA Operation -> AHCI.** Ważne: E7270 ma
   fabrycznie "RAID On" (Intel RST) - na obecnym laptopie też tak jest
   (`82801 Mobile SATA Controller [RAID mode]`). Instalator Ubuntu przy
   RST często nie widzi dysku albo odmawia instalacji. Dysk zostanie i tak
   w całości wymazany, więc zmiana na AHCI jest bezpieczna.
3. **Power Management -> Primary Battery Charge Configuration ->
   "Primarily AC Use"**: laptop stale na zasilaczu nie trzyma baterii
   ciągle na 100% (wolniej się zużywa).
4. Secure Boot może zostać włączony (Ubuntu ma podpisany bootloader).
5. Apply / Exit, potem przy starcie **F12** -> pendrive (UEFI).

## Krok 4: Instalator Ubuntu Desktop

1. **Język:** Polski (to Twój komputer do codziennej pracy).
2. **Klawiatura:** Polska (programisty).
3. **Sieć:** Wi-Fi albo kabel (instalator pobierze aktualizacje i
   sterowniki).
4. **Typ instalacji:** interaktywna, **domyślny wybór aplikacji** (nie
   rozszerzony: mniej zbędnych programów).
5. **Oprogramowanie firm trzecich:** możesz zaznaczyć (kodeki
   multimediów); Wi-Fi Intel 8260 i grafika Intel działają i bez tego.
6. **Dysk:** "Wymaż dysk i zainstaluj Ubuntu" (cały SSD dla Ubuntu).
   **Funkcje zaawansowane -> LVM i szyfrowanie (hasło): OBOWIĄZKOWO.**
   Na dysku będą Twoje notatki, pamięć GREGAI i klucz API Anthropic;
   skradziony laptop bez hasła szyfrowania = nic do odczytania. Hasło
   długie (min. 4-5 słów), inne niż hasło konta, **tylko a-z, cyfry i
   myślniki** (patrz "Hasła": przy starcie, zanim wczyta się polska
   klawiatura, polskie znaki mogą się nie dać wpisać). Podajesz je przy
   każdym włączeniu (GREGAI startuje zaraz potem).
   **Zapisz je na papierze w bezpiecznym miejscu** - bez niego dane są
   nie do odzyskania, także dla Ciebie.
7. **Konto:** imię Grzegorz, nazwa komputera `gregai`, nazwa użytkownika i
   hasło. Ten użytkownik będzie właścicielem usługi GREGAI.
8. **Strefa czasowa:** Warszawa.
9. Instalacja -> "Uruchom ponownie" -> wyjmij pendrive.

## Krok 5: Po pierwszym uruchomieniu

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Po restarcie:

```bash
python3 --version             # 3.10+ wymagane, 26.04 ma 3.14
lsblk -d -o NAME,SIZE,MODEL   # sda, ok. 238 GiB = 256 GB, LITEON CV1-8B256
```

Stan dysku (używany dysk OEM, warto wiedzieć, na czym stoisz):

```bash
sudo apt install -y smartmontools
sudo smartctl -H -A /dev/sda
```

Ma być `PASSED`. W atrybutach zwróć uwagę na `Reallocated_Sector_Ct`
(powinno być 0) i wskaźnik zużycia / `Total_LBAs_Written`. Jeśli wynik
nie jest `PASSED` albo realokowanych sektorów jest dużo, nie trzymaj na
nim jedynej kopii danych (Krok 11: stary laptop zostaje zapasem).

## Krok 6: Laptop jako serwer (żeby GREGAI nie zasypiał)

(`install.sh` robi punkty 1, 2 i 4 sam, chyba że dasz `--no-host`; poniżej
wersja ręczna.)

1. **Bez usypiania na zasilaczu** (Twoja sesja):
   ```bash
   gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
   ```
   Na baterii laptop dalej usypia normalnie (bezpieczne np. w plecaku).
   Ekran logowania (po włączeniu, zanim się zalogujesz) ma własne
   ustawienie i może uśpić laptop po ok. 15 min: po włączeniu po prostu
   się zaloguj. GREGAI obsługujesz i tak z zalogowanej sesji.
2. **Zamknięcie klapy na zasilaczu nie usypia** (na baterii usypia jak
   zwykle):
   ```bash
   sudo mkdir -p /etc/systemd/logind.conf.d
   printf '[Login]\nHandleLidSwitchExternalPower=ignore\n' | sudo tee /etc/systemd/logind.conf.d/gregai.conf
   ```
   Zadziała po restarcie (`sudo reboot`). NIE restartuj
   `systemd-logind` przy otwartej sesji: wylogowuje z pulpitu.
3. **Zapora:** nic nie musi wchodzić z sieci, więc "blokuj przychodzące".
   `install.sh` (Krok 9) włącza ją sam; możesz też od razu:
   ```bash
   sudo ufw enable
   ```
4. **Swap 8 GB** (zapas, gdy duży model, przeglądarka i pulpit zbiegną się
   w czasie). Polecenie samo znajduje plik wymiany (a jeśli go nie ma,
   zakłada `/swap.img`):
   ```bash
   SW="$(swapon --show=NAME,TYPE --noheadings | awk '$2=="file"{print $1; exit}')"; SW="${SW:-/swap.img}"; echo "plik wymiany: $SW"
   sudo swapoff "$SW" 2>/dev/null; sudo fallocate -l 8G "$SW" && sudo chmod 600 "$SW" && sudo mkswap "$SW" && sudo swapon "$SW"
   grep -qE "^${SW}[[:space:]]" /etc/fstab || echo "$SW none swap sw 0 0" | sudo tee -a /etc/fstab
   swapon --show      # ma być plik 8G
   ```
   Wpis w `/etc/fstab` sprawia, że swap wraca po restarcie.

## Krok 7: Kod GREGAI + Twoje dane ze starego laptopa

Dwie osobne rzeczy, celowo rozdzielone, żeby stary kod ze starego laptopa
nie nadpisał nowego:
- **kod** (GREGAI, ta wersja): paczka `GREGAI.zip` z tej rozmowy,
- **dane** (notatki, pamięć, wszystko, czego GREGAI się nauczył, `.env` z
  kluczami): zaszyfrowane archiwum z pendrive'a, zrobione w Kroku 0.

**a) Kod.** Otwórz tę rozmowę w przeglądarce na nowym laptopie i pobierz
`GREGAI.zip` (trafi do `~/Pobrane`). Bez sieci: skopiuj go z pendrive'a z
Kroku 0 do `~/Pobrane`. Jeśli pobierasz drugi raz, Firefox nazwie plik
`GREGAI(1).zip`: usuń stary, nowy nazwij `GREGAI.zip`.

```bash
sudo apt install -y unzip
mkdir -p ~/Dokumenty && cd ~/Dokumenty && unzip ~/Pobrane/GREGAI.zip
cd ~/Dokumenty/GREGAI && sha256sum --quiet -c GREGAI.sha256 && echo PACZKA_OK
```

Musi wypisać `PACZKA_OK`. Każde `FAILED` = uszkodzone pobranie: usuń
`~/Dokumenty/GREGAI` (`rm -r ~/Dokumenty/GREGAI`), pobierz paczkę jeszcze raz i powtórz.

**b) Dane** z pendrive'a do środka `~/Dokumenty/GREGAI` (włóż pendrive z danymi):

```bash
ls "/media/$USER"
gpg --decrypt "/media/$USER/PENDRIVE/gregai-dane.tgz.gpg" | tar -xzf - -C ~/Dokumenty/GREGAI
chmod 600 ~/Dokumenty/GREGAI/.env
ls ~/Dokumenty/GREGAI/notatki | head    # Twoje notatki są na miejscu
```

**c)** Usuń archiwum z pendrive'a (jest zaszyfrowane, ale nie ma po co go
trzymać; kopią zapasową zostaje stary laptop, Krok 11):

```bash
rm "/media/$USER/PENDRIVE/gregai-dane.tgz.gpg"
```

**Co przenosimy ze starego laptopa, a czego nie.** Kod zawsze z paczki
`GREGAI.zip` (stary jest starszy, bez WARP i poprawek bezpieczeństwa).
Dane: `notatki/` (graf), `memory/` (to, co kazałeś zapamiętać), `data/`
(wszystko, czego GREGAI się nauczył: materiał treningowy, bank wiedzy z
Wikipedii, dziennik, pary z chmury) i `.env` (sekrety; `install.sh` zmienia
nazwy kluczy `SIECAI_*` na `GREGAI_*`, usuwa martwe klucze głosu i wpisy starych
modeli `webai-*`). NIE
przenosimy: `training/.work/` (środowisko treningowe, GB, odtwarzane),
wytrenowanych modeli (zestaw narzędzi SYSOP jest inny, więc stare same by
się wyłączyły; trenujesz od nowa), modeli Ollamy (`install.sh` pobiera
sam) ani starych plików usług (`siecai.service`, `webai.service`:
miały ścieżki starego laptopa). Nic na starym laptopie nie kasuj przez co
najmniej tydzień: to Twoja kopia zapasowa (potem `ollama rm` modeli i
usunięcie `~/Dokumenty/SIECAI/training/.work/` zwolni ok. 5 GB).

Starego routera (GGUF) nie przenosimy: na nowym laptopie i tak trenujesz go
od nowa (Krok 10), bo zmienił się zestaw narzędzi (SYSOP). Klucze `.env`
ze starą nazwą (`SIECAI_...`) `install.sh` sam przemianuje na `GREGAI_...`.

## Krok 8: `.env` pod ustaloną architekturę

`install.sh` tworzy `.env` sam z szablonu `.env.example` (ustalone wartości
poniżej) i pyta o klucz Anthropic, więc ten krok jest **opcjonalny**. Robisz
go ręcznie tylko wtedy, gdy chcesz zmienić coś przed instalacją albo masz
`.env` ze starego laptopa (Krok 7), który chcesz dopasować. PRZED
`install.sh` otwórz plik w edytorze:

```bash
nano ~/Dokumenty/GREGAI/.env
```

Ustaw te wiersze (jeśli wiersz już jest, zmień jego wartość zamiast
dopisywać drugi; stary `OLLAMA_MODEL=gemma2:2b` podmień):

```
GREGAI_LAN=0
OLLAMA_MODEL=qwen2.5:3b
ANTHROPIC_API_KEY=sk-ant-...twój klucz...
KORYTO=anthropic,darmowe,lokalnie
CLOUD_DAILY_LIMIT=300
SYSOP_SHELL=0
```

Wyizolowane Ubuntu tylko dla GREGAI (pełen dostęp do systemu, 1.17.0) -
dodatkowo, ŚWIADOMIE:

```
SYSOP_MODE=pelny
```

Zapis w `nano`: **Ctrl+O**, **Enter**; wyjście: **Ctrl+X**.

- `GREGAI_LAN=0`: GREGAI tylko na tym laptopie (`http://localhost:7777`),
  nic w sieci.
- `OLLAMA_MODEL=qwen2.5:3b`: duży model lokalny (SYSOP, rozmowa do czasu
  treningu ucznia, zapas bez internetu). Gdybyś zapomniał, `install.sh`
  sam podmieni stary mały model i podniesie `OLLAMA_NUM_CTX` z 4096 do
  16384 (w 4096 pełny prompt GREGAI się nie mieści, a 16384 zostawia duży
  zapas na historię rozmowy, żeby GREGAI nie gubił wątku).
- `ANTHROPIC_API_KEY`: klucz z `console.anthropic.com` (sekcja kluczy
  API: utwórz klucz, skopiuj, wklej tu; w terminalu wklejasz
  Ctrl+Shift+V). Klucz widać tylko raz, przy tworzeniu.
- `KORYTO=anthropic,darmowe,lokalnie` (1.17.0, `agent/koryto.py`): kolejność
  dostawców dla całego myślenia - Claude pierwszy (główny dostawca, domyślnie
  Haiku), darmowa pula druga, lokalny model ostatni. Każdy błąd etapu (sieć,
  limit, klucz) = cicho następny etap, bez przerwy w rozmowie. Każda
  odpowiedź z sieci uczy ucznia. Stare `CLOUD_FALLBACK`/`JUGGLER_MODE` można
  zostawić - są ignorowane.
- `CLOUD_DAILY_LIMIT=300`: najwyżej 300 **zapytań** do Claude dziennie (to
  liczba zapytań, nie kwota; `install.sh` sam podnosi stare 50 do 300, bo
  jako główny dostawca 50 kończyłoby się w godzinę). Limit pieniędzy
  ustawiasz dodatkowo w konsoli Anthropic (limity wydatków).
- `SYSOP_MODE=pelny` (tylko wyizolowane Ubuntu dla GREGAI): dowolny shell z
  sudo do wszystkiego, pliki w całym systemie, każda usługa; zwykłe zmiany
  bez pytania, nieodwracalne za jednym potwierdzeniem (`SYSOP_PYTAJ=nigdy`
  wyłącza i to). `install.sh` wpisuje wtedy do sudoers jedną regułę
  `ALL=(ALL) NOPASSWD: ALL`. Na laptopie z Twoimi prywatnymi danymi tego nie
  wpisuj - bez wpisu zostaje tryb strażniczy (jak dotąd).
- `SYSOP_SHELL=0`: SYSOP używa **stałych, nazwanych narzędzi** (stan
  serwera, usługi, logi, aktualizacje, sieć, procesy, timery, pliki, kopia
  zapasowa). Dowolny shell jest wyłączony: model go nie widzi, a próba
  użycia jest odrzucana. `SYSOP_SHELL=1` + restart włącza go świadomie.
- `ROUTER_MODEL`/`STUDENT_MODEL`/`PLANNER_MODEL` ustawią same skrypty
  treningowe (Krok 10).

(Cloudflare WARP nie ma przełącznika w `.env`: jest twardo wbudowany,
Krok 12.)

## Krok 9: `bash install.sh`

```bash
bash /sciezka/do/GREGAI/install.sh      # z dowolnego katalogu; folder może leżeć gdziekolwiek
```

Jako zwykły użytkownik, **bez `sudo` przed poleceniem** (o hasło skrypt
zapyta sam; uruchomiony jako root odmówi). Rób to **w domu** (Krok 12,
punkt 10). Opcje: `--train` (trening w tle po instalacji), `--no-host` (bez
ustawień laptopa), `--here` (instaluj dokładnie w tym folderze, nawet na
USB), `--yes` (bez pytań), `--help`. Folder na USB/wymiennym dysku skrypt
kopiuje sam do `~/Dokumenty/GREGAI`, oryginał zostaje (patrz "Najkrótsza droga").

9 kroków, każdy pomija to, co już zrobione:

1. pakiety systemowe,
2. **Cloudflare WARP** - warunki Cloudflare pokaże klient, akceptujesz
   sam; **bez działającego WARP skrypt się zatrzymuje** i nie instaluje
   niczego dalej (jeśli Cloudflare nie ma jeszcze repozytorium dla nazwy
   kodowej świeżego Ubuntu, skrypt próbuje repozytoriów `noble` i `jammy`:
   ten sam podpisany pakiet),
3. Ollama (już przez WARP), ustawiona tylko na `127.0.0.1`, na jedną
   rozmowę naraz (mniej RAM) i na okno 16384 tokenów,
4. foldery i ustawienia laptopa (brak usypiania na zasilaczu, klapa, swap 8 GB),
5. `.env` (z `.env.example`, jeśli go nie ma; pyta o klucz Anthropic): klucze `SIECAI_*` -> `GREGAI_*`, tryb lokalny (`GREGAI_LAN=0`),
   model `qwen2.5:3b` i okno 16384 (jeśli zostały stare wartości), token;
   jeśli w `.env` są dane routera HiLink, doinstalowuje bibliotekę do
   mostu routera (tylko dla Twojego użytkownika),
6. modele (`qwen2.5:3b`, ok. 2 GB, przez WARP; kilka minut),
7. usługa `gregai.service` (start przy włączeniu laptopa, po WARP) i skan
   sieci domowej co 15 min (`gregai-siec.timer`); przed nią (1.19.0) **zapora
   WARP w jądrze** - patrz Krok 12, punkt "Zapora WARP w jądrze",
8. kontrola: tu pojawia się `GREGAI odpowiada. Na tym komputerze, w
   przeglądarce: http://localhost:7777`,
9. SYSOP (sudo tylko dla usług `gregai` i `ollama` oraz dla `apt-get update -q`
   i `apt-get upgrade -y -q` (z opcjami dpkg zachowującymi Twoje pliki konfiguracyjne); narzędzia plikowe
   tylko w `~/Dokumenty/GREGAI`), osobno i zawsze reguły `gregaipanicmode`
   (`/etc/sudoers.d/gregai-panic`: zapora + wyłączenie komputera), **zapora
   ufw włączona** (domyślna polityka wychodzących ustawiana tylko przy
   pierwszym włączeniu - Twoje świadome "deny outgoing" zostaje), router
   domowy zapamiętany.

Na końcu odpala `check.sh` (liczbę kontroli pokazuje sam skrypt) i wypisuje **ścieżkę projektu**
oraz listę "Opcjonalnie" (trening, pomiar czasów). Dodaj `http://localhost:7777` do zakładek
(albo ustaw jako stronę startową Firefoksa).

**Gdy skrypt się zatrzyma:** przeczytaj ostatnie żółte wiersze `UWAGA`:
mówią, co jest nie tak i co wpisać. Popraw to i uruchom ponownie
`bash install.sh` (zrobione kroki pominie). Te `UWAGA` są niegroźne i
instalacja idzie dalej:
- `wygenerowano token dostępu` - tylko informacja (token przydałby się
  wyłącznie z innego urządzenia),
- `router domowy nie zapamiętany` - nie jesteś w domu albo `ROUTER_HOST` w
  `.env` to nie adres Twojej bramy (sprawdź `ip route | grep default`; domyślne
  `192.168.8.1` to fabryczny Huawei). Popraw `.env` i w domu:
  `cd ~/Dokumenty/GREGAI && python3 agent/homenet.py --pin`,
- `nie udało się zainstalować huawei-lte-api` - nie zadziała tylko odczyt
  routera HiLink, reszta tak.

## Krok 10: Dzień 1 - kontrola i trening

Wszystkie polecenia z tego kroku wpisujesz w katalogu projektu (`cd ~/Dokumenty/GREGAI`).

1. **Wszystkie kontrole jednym poleceniem** (liczbę pokazuje sam skrypt):
   ```bash
   cd ~/Dokumenty/GREGAI && bash check.sh
   ```
   Sprawdza na prawdziwym laptopie to, czego nie da się sprawdzić
   wcześniej: system, szyfrowanie dysku, stan dysku, RAM i swap, WARP
   (status i realny ruch), zaporę i AppArmor, Ollamę (tylko lokalnie,
   ustawienia, okno 16384), model, usługę GREGAI wskazującą ten folder i
   timer skanu sieci, port 7777 (tylko lokalnie), odpowiedź
   serwera, blokadę żądań z zewnątrz bez tokenu, strażnika internetu
   (netguard), prawa `.env`, reguły sudo, blokadę "rozłącz WARP", realny
   budżet pamięci rozmowy (ile tur historii mieści się razem z promptem),
   szybką ścieżkę narzędzi (rozpoznaje prawdziwe komendy - notowania,
   śledzenie na bieżąco, zasięg sieci, typy notatek, logi/timery/procesy/
   backup SYSOP - ale ignoruje zwykłą rozmowę o tych samych słowach: "kurs
   programowania", "mocny sygnał", "Wall Street Journal"...) i blokady SYSOP
   na stałe (WARP/zapora/sudo/systemd) niezależnie od wielkości liter w
   poleceniu, blok „Teraz” (zegar i pamięć podręczna GREGAI: dzisiejsza
   data w prompcie, a treść zapamiętanych faktów tylko dla modelu lokalnego,
   nigdy do chmury), Namysł (sześć faz myślenia przechodzi przez prawdziwy
   router z podstawionymi modelami, a notatki nie idą do sieci bez zgody) i
   Źródła (folder dodany z interfejsu nigdy nie obejdzie reguł plików:
   ani /, ani katalog domowy, ani foldery prywatne), jedno wyjście do sieci
   (żaden plik w agent/ nie woła internetu z pominięciem netguard.py) oraz
   pamięć rozmowy i bezpiecznik dostawców (streszczenie co 8 tur bez treści
   narzędzi, „gdzie skończyliśmy” po przerwie, dostawca po awarii odpoczywa
   zamiast psuć każdą odpowiedź).
   Na końcu `28/28 OK` albo lista, co poprawić (z podpowiedzią jak). Zapyta raz o
   hasło (sudo), bo część kontroli tego wymaga. Uruchamiaj go też potem,
   kiedy chcesz, np. po aktualizacjach.
2. **Jak szybki jest duży model (rozgrzewanie).** Po każdym starcie GREGAI
   sam, w tle, wczytuje `qwen2.5:3b` i przetwarza jego prompt systemowy
   (osobowość i zasady, ok. 6300 tokenów). Na tym procesorze to **kilka
   minut** (szacunek, nie pomiar); stan widać w `http://localhost:7777/debug`, wiersz
   "Rozgrzewanie modeli". Potem model zostaje w pamięci z tym promptem i
   odpowiada zwykle w **kilkadziesiąt sekund** (tyle trwa napisanie odpowiedzi).
   Wiadomość wysłana w trakcie rozgrzewania poczeka na jego koniec; czat
   pokazuje wtedy "Model jeszcze liczy…" i nie przerywa czekania. To samo
   po zadaniu SYSOP przed treningiem planera (punkt 4): pierwsza zwykła
   odpowiedź po nim jest wolniejsza. Liczby to szacunek; prawdziwe da
   (opcjonalnie, ok. 10-15 min):
   ```bash
   cd ~/Dokumenty/GREGAI && python3 training/bench_chat.py --models qwen2.5:3b --limit 3
   sudo systemctl restart gregai     # benchmark wyładował model; to go rozgrzeje od nowa
   ```
   Wynik w `data/training/bench_chat.md`: "pierwsza (zimna)" = jak po
   starcie, "kolejne (ciepłe)" = zwykła rozmowa. Zwykłą rozmowę po
   treningu przejmie uczeń (szybko), trudne pytania idą do chmury
   (sekundy), więc duży model pracuje rzadko. Zmiana modelu, gdyby kiedyś
   była potrzebna, to `ollama pull <model>`, jedna linia `OLLAMA_MODEL=...`
   w `.env`, `sudo systemctl restart gregai` i `bash check.sh` (kontrola 10);
   bez pobrania GREGAI powie w czacie, że modelu nie ma.
   Wszystkie trzy treningi razem to według szacunku ok. 2-3 doby na tym
   CPU (każdy model jest opcjonalny: GREGAI działa też bez nich). Po każdej
   epoce zapisywany jest punkt kontrolny: po przerwie (prąd, uśpienie)
   to samo polecenie wznawia od ostatniej epoki, a `install.sh --train`
   pomija modele, które już są wytrenowane i aktualne.
   Wszystkie trzy treningi (punkty 3-5) uruchomi w tle jedna komenda:
   `bash /sciezka/do/GREGAI/install.sh --train` (nice 19, log w
   `data/training/train_all.log`, po wszystkim sam restartuje `gregai`).
   Poniżej wersja ręczna, etap po etapie. Każdy z tych skryptów pobiera pakiety
   i modele z internetu, więc na starcie sprawdza WARP: bez połączenia kończy
   się od razu, z podpowiedzią `warp-cli connect`.
3. **Router (Qwen2.5-1.5B)** - na tym CPU rząd 12-26 h (obliczenie z
   liczby tokenów i mocy procesora, nie pomiar: `finetune.py` wypisze
   prawdziwy przewidywany czas po pierwszych krokach), z zamkniętą
   przeglądarką (trening zjada większość RAM):
   ```bash
   cd ~/Dokumenty/GREGAI && BASE_MODEL=Qwen/Qwen2.5-1.5B-Instruct BATCH=1 GRAD_ACCUM=8 nice -n 19 bash training/run.sh
   ```
   Do czasu tego treningu narzędzia (notatki, plan dnia, sieć, SYSOP...)
   rozpoznawane są po słowach kluczowych, a wszystko inne to rozmowa z
   dużym modelem. Po treningu router decyduje w sekundy także o
   sformułowaniach, których słowa kluczowe nie znają. (`nice -n 19`:
   trening ustępuje miejsca wszystkiemu innemu, więc laptop zostaje
   używalny.)
4. **Planer zadań wielokrokowych (SYSOP)** - rząd 5-9 h (szacunek jak wyżej):
   ```bash
   cd ~/Dokumenty/GREGAI && BATCH=1 GRAD_ACCUM=8 nice -n 19 bash training/run_planner.sh
   ```
   Bez niego zadania typu "sprawdź logi i jeśli są błędy, zrestartuj"
   planuje duży model: działa, ale każdy krok to kilkadziesiąt sekund. Wytrenowany
   planer: powinien być wyraźnie szybszy (szacunek, bez pomiaru).
5. **Uczeń (osobowość GREGAI)** - na tym CPU rząd 20-40 h (szacunek jak
   wyżej), **odpal na noc albo na weekend**, bez przeglądarki:
   ```bash
   cd ~/Dokumenty/GREGAI && BATCH=1 GRAD_ACCUM=8 nice -n 19 bash training/run_student.sh
   ```
   Rano przeczytaj `data/training/student_eval_report.md`.
   (`BATCH=1 GRAD_ACCUM=8` to teraz ustawienie domyślne skryptów: ten sam
   efekt treningu co 4x2, ale dużo mniej pamięci; na starym laptopie 4x2
   zużywało ok. 14 GB, a tu część RAM zajmuje pulpit.) Po treningu ucznia duży
   model nie musi już stale siedzieć w pamięci (zwalnia ją po 30 min
   bezczynności).
6. **Koryto (Claude jako główny dostawca):** `http://localhost:7777/debug` ->
   wiersz „Claude (Anthropic, płatny)”: `Claude aktywny (1. etap koryta):
   claude-haiku-5-5, dziś N/300, limit odpowiedzi 1600 tok.`; wiersz „Koryto
   (kolejność)” pokazuje Claude -> darmowa pula -> lokalny model.
7. **SYSOP (stałe narzędzia):** "ile mam miejsca na dysku?", "pokaż logi
   gregai", "zrestartuj usługę gregai" (to ostatnie poprosi o potwierdzenie).
   `/debug` -> wiersz SYSOP pokazuje liczbę narzędzi i "shell wyłączony".
8. **Start po restarcie:** `sudo reboot`, po starcie (z hasłem szyfrowania)
   od razu `http://localhost:7777`: GREGAI ma działać bez żadnej komendy.
   Potem jeszcze raz `cd ~/Dokumenty/GREGAI && bash check.sh` -> wszystkie OK.
9. **Blokada bez WARP (test bezpieczeństwa):** `warp-cli disconnect`, w
   GREGAI "sprawdź w internecie pogodę w Warszawie" -> ma odpowiedzieć, że
   internet jest zablokowany. Potem `warp-cli connect`, **odczekaj ok.
   30 s** i to samo pytanie -> wyniki. Na koniec w rozmowie: "rozłącz
   warp" -> GREGAI ma odmówić.

## Budżet RAM (16 GB, wszystko na jednym laptopie)

| co | ile, w przybliżeniu |
|---|---|
| Pulpit GNOME + system | 2-3 GB |
| Przeglądarka z kilkoma kartami | 1-2 GB |
| `qwen2.5:3b` z oknem 16384 (w pamięci stale, dopóki rozmawia; po treningu ucznia tylko gdy potrzebny) | ok. 2,5-3 GB |
| router + uczeń (gdy załadowane, zwalniane po 30 min bezczynności) | ok. 1-3 GB |

Zwykła praca + rozmowa z GREGAI mieści się z zapasem; swap 8 GB z Kroku 6
to dodatkowy bufor. Trening (Krok 10, punkty 3-5) zawsze przy zamkniętej
przeglądarce - on zajmuje najwięcej RAM (skrypty same zwalniają na ten
czas pamięć Ollamy).

## Krok 11: Bezpiecznik

Stary laptop (albo, jeśli wymieniasz dysk w tym samym laptopie, stary dysk
128 GB odłożony na bok) zostaje nietknięty co najmniej tydzień: to Twoja
kopia danych. Dopiero gdy nowy GREGAI pracuje stabilnie (`bash check.sh`
-> 28/28, brak "Out of memory" w `journalctl -u gregai`, brak
nieoczekiwanych restartów, SYSOP działa), możesz go wyczyścić.

## Krok 12: Cloudflare WARP - obowiązkowy, wbudowany w projekt

Darmowy klient Cloudflare (ten sam co aplikacja "1.1.1.1 z WARP" na
telefon). **Nie używa Twojej domeny ani strony**, nie wymaga konta, nie
wystawia niczego do internetu. Instaluje go `install.sh` (krok 2/9).

Co daje:
- cały ruch laptopa do internetu (przeglądarka, GREGAI -> Claude API,
  wyszukiwanie, Wikipedia, pobieranie modeli, aktualizacje) idzie
  **szyfrowanym tunelem do Cloudflare**; operator sieci (dom, kawiarnia,
  hotel) nie widzi, z czym się łączysz,
- DNS przez 1.1.1.1, z blokadą znanych złośliwych domen.

Jak jest "twardo zakodowany" (nie da się go wyłączyć ustawieniem):
1. **`agent/netguard.py`** - każde połączenie GREGAI z internetem przechodzi
   przez jeden moduł, który najpierw sprawdza, czy WARP jest połączony
   (co najwyżej co 3 s) i co 30 s, czy ruch naprawdę idzie przez tunel
   (strona Cloudflare: `warp=on`; sam napis "Connected" w trybie proxy
   albo samego DNS nie wystarczy). Jeśli nie, połączenie **nie wychodzi**
   (fail-closed): chmura stoi i rozmowa idzie lokalnie, wyszukiwanie
   odpowiada "internet zablokowany, WARP rozłączony", pytania do
   Wikipedii czekają w kolejce, aż WARP wróci. Tylko `https://`, także po
   przekierowaniach. Polecenia SYSOP, które łączą się z internetem
   (aktualizacje, curl, git...), też nie ruszą bez WARP. Rozmowa lokalna
   (Ollama) działa zawsze.
2. **`install.sh`** - WARP to krok 2; bez niego instalacja się zatrzymuje.
   **Zapora WARP w jądrze** (1.19.0, krok 7b): plik
   `/etc/gregai/warp-killswitch.nft`, ładowany przy KAŻDYM starcie usługi
   (`ExecStartPre=+/usr/sbin/nft -f ...`; bez reguł usługa nie wystartuje), tworzy tabelę nftables
   `inet gregai_warp` z jednym łańcuchem na wyjściu. Dotyczy wyłącznie
   procesów z cgroup `system.slice/gregai.service` - czyli GREGAI i wszystkiego,
   co uruchomi (także polecenia shella przez sudo); reszty systemu nie rusza.
   Reguły, po kolei: wyjście przez interfejs `lo` albo `CloudflareWARP` -
   wolno; adres w `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`,
   `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fe80::/10`, `fc00::/7`
   (localhost, sieć domowa, router) - wolno; wszystko inne - odrzucone przez
   jądro (licznik `counter drop`, widać go w `sudo nft list table inet
   gregai_warp`). Czyli: rozłączony WARP = żaden proces GREGAI nie wyjdzie do
   internetu, nawet program, którego `agent/sysop.py` nie zna. Reguła wskazuje
   cgroup po ścieżce, a ten powstaje na nowo przy każdym starcie usługi - stąd
   ładowanie przy każdym starcie. Instalator najpierw sprawdza reguły na sucho
   (`nft -c`); gdy jądro/nft ich nie obsługuje, instalacja się zatrzymuje z
   wyjaśnieniem. Zapora jest obowiązkowa (od 1.32.4): nie ma wyłącznika, a
   usługa bez załadowanej tabeli nie wystartuje. `check.sh` (kontrola 29) to sprawdza.
3. **`gregai.service`** startuje po usłudze WARP (`warp-svc`).
4. **GREGAI nie może osłabić własnych zabezpieczeń** (`agent/sysop.py`,
   zablokowane na stałe, nawet z Twoim "tak" w rozmowie - chroni też
   przed poleceniem wstrzykniętym w notatkę czy stronę): rozłączenie lub
   przestawienie WARP, wyłączenie zapory, zatrzymanie `warp-svc`/`ufw`/
   `apparmor`/`unattended-upgrades`, odinstalowanie ich, zmiany w
   sudoers, SSH, źródłach pakietów. Te rzeczy robisz tylko Ty, we własnym
   terminalu.
5. **sudo dla GREGAI tylko na listę usług** (`gregai`, `ollama`; do tego
   dokładnie dwa polecenia `apt-get update -q` i `apt-get upgrade -y -q` z opcjami dpkg
   `--force-confdef --force-confold`, czyli zmienione przez Ciebie pliki konfiguracyjne zostają), nie na
   "dowolną usługę" - system sam nie pozwoli procesowi GREGAI zatrzymać
   WARP. Kolejną usługę dopisujesz świadomie w `install.sh`
   (`SYSOP_UNITS`) i uruchamiasz go ponownie.
6. **Ollama tylko lokalnie** - adres Ollamy spoza tego komputera w `.env`
   jest ignorowany (rozmowy szłyby siecią bez szyfrowania).
7. **Dowolny shell wyłączony domyślnie** (`SYSOP_SHELL=0`): SYSOP ma tylko
   stałe, nazwane narzędzia, każde z własną wąską walidacją. Jeśli
   świadomie włączysz `SYSOP_SHELL=1`: **odczyt bez pytania jest naprawdę
   tylko odczytem** - polecenia wykonywane bez Twojego "tak" to wąska lista
   programów, które nie umieją niczego zapisać, wysłać ani uruchomić, i są
   wykonywane bez shella. Wszystko inne czeka na "tak" przy pokazanym
   dokładnie poleceniu.
   Polecenia, których treści nie da się przeczytać przed wykonaniem
   (zmienne, `$(...)`, base64, `| bash`), są zablokowane.
8. **Sekrety i prywatne pliki** - `.env`, klucze SSH, profil przeglądarki
   i hasła są niedostępne dla GREGAI; sekrety z `.env` (także ich
   fragmenty) i klucze prywatne są wycinane z każdego wyniku polecenia i
   maskowane w śladach oraz danych treningowych. Do chmury nigdy nie idą
   odpowiedzi narzędzi (notatki, pliki, logi, sieć domowa), tylko Twoje
   zwykłe wiadomości z rozmowy i prompt systemowy GREGAI (osobowość i zasady
   z `agent/prompt.md`, w tym Twoje imię i opis zajęć, oraz opisy narzędzi). W zadaniu wielokrokowym zapytanie w
   internet i zapis faktu przeczytanego z pliku lub strony czekają na
   Twoje „tak” (także poza zadaniem, gdy przy `BIG_MODEL_ROUTING=1` duży
   model ułoży zapytanie ze słów spoza Twojej wiadomości).
9. **Strony z internetu nie wyślą nic do GREGAI** - inna strona otwarta w
   Firefoksie nie może wysłać żądania do `http://localhost:7777` w Twoim
   imieniu (sprawdzanie Host, Origin i Sec-Fetch-Site; tylko JSON).
10. **Sieć domowa** - skan sieci i odczyt routera HiLink działają tylko w
   domu: brama `ROUTER_HOST` z `.env` i jej adres MAC, zapamiętany
   świadomie przez `install.sh` w domu (`data/home_router.json`). Nic w
   tle niczego samo nie zapamiętuje, a każdy błąd = sieć obca. W
   kawiarni czy hotelu nic nie jest skanowane, a hasło panelu routera
   nigdy nie idzie do obcej bramy. Dlatego `install.sh` uruchamiasz w
   domu, z `ROUTER_HOST` w `.env` równym adresowi Twojej bramy. Gdyby wtedy nie był w domu: później, w domu,
   `cd ~/Dokumenty/GREGAI && python3 agent/homenet.py --pin`. Po wymianie routera,
   w domu: `cd ~/Dokumenty/GREGAI && python3 agent/homenet.py --pin --replace`.

Stan WARP widać w `http://localhost:7777/debug` (wiersz "Cloudflare
WARP") i w terminalu:

```bash
warp-cli status
curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp   # warp=on
```

Po restarcie laptopa WARP łączy się sam. Gdyby się rozłączył:
`warp-cli connect`.

Czego WARP NIE robi (żeby nie było złudzeń):
- nie jest anonimowością (Cloudflare widzi, dokąd idzie ruch),
- nie chroni GREGAI przed atakiem z zewnątrz - to robią: nasłuch tylko na
  `localhost`, zapora `ufw` i szyfrowanie dysku. WARP zabezpiecza drogę
  laptop -> internet.

Możliwy efekt uboczny: niektóre serwisy traktują adresy WARP jak VPN.
Jeśli wyszukiwanie GREGAI ("sprawdź w internecie ...") zacznie zwracać
puste wyniki, NIE wyłączaj WARP dla wyszukiwarki - GREGAI dalej ma
Wikipedię i chmurę (Claude) do trudnych pytań. Daj znać, dobierzemy inne
źródło wyszukiwania, które działa przez WARP.

(Dostęp z telefonu jest poza zakresem 1.0: GREGAI jest obsługiwany wyłącznie
z tego laptopa. Tryb `GREGAI_LAN=1` (sieć domowa, token, reguły ufw tylko z sieci
prywatnych) jest przeznaczony dla komputera bez pulpitu; szczegóły w `README.md`.
Na laptopie zostaw `GREGAI_LAN=0`.)

---

## Aktualizacja do nowej wersji (od 1.19.0)

```bash
gregai update ~/Pobrane/GREGAI-1.20.0.zip     # = bash aktualizuj.sh PLIK.zip
```

Paczkę zostawiasz tam, gdzie się pobrała - nic nie rozpakowujesz sam.
Skrypt: rozpakowuje ją obok, sprawdza (`GREGAI.sha256`, składnia Pythona i
skryptów; uszkodzona albo zmieniona paczka = odmowa), robi kopię obecnego
kodu w `~/.local/share/gregai/kopie/` (trzy ostatnie), podmienia kod i
restartuje GREGAI, a potem czeka do 60 s, aż naprawdę odpowie. Nie wstał -
**sam wraca do poprzedniej wersji** i pokazuje ostatnie linie dziennika.
Nietknięte zawsze: `notatki/` (z paczki dochodzą tylko pliki, których
jeszcze nie masz), `memory/`, `data/`, `backups/`, `.env`, modele z treningu.
Powrót ręczny: `gregai rollback`.

Pierwszy raz z wersji 1.18.x (jej `aktualizuj.sh` nie zna jeszcze paczek):
rozpakuj paczkę na folder GREGAI jak dotąd i `gregai update`; od tej
wersji już zawsze wystarczy `gregai update PLIK.zip`. Gdy aktualizacja
powie, że pliki systemowe są z poprzedniej wersji instalatora, uruchom raz
`bash install.sh` (zrobione kroki pominie).

## Checklista

- [ ] Hasła: dysk, konto, archiwum - na papierze; dysk i archiwum tylko a-z, cyfry, myślniki
- [ ] Krok 0: stary GREGAI zatrzymany, dane w zaszyfrowanym archiwum na pendrivie, test -> `ARCHIWUM_OK`
- [ ] ISO Desktop zweryfikowane (`sha256sum -c` -> OK), pendrive z danymi wyjęty, pendrive systemowy gotowy
- [ ] BIOS: AHCI (nie RST/RAID), boot z USB, ewentualnie limit ładowania
- [ ] Instalacja: cały dysk, LVM + szyfrowanie (obowiązkowo)
- [ ] `apt full-upgrade` + restart
- [ ] `smartctl -H` -> PASSED
- [ ] Brak usypiania na zasilaczu, klapa na zasilaczu ignorowana
- [ ] Swap 8 GB (zaporę włącza `install.sh`)
- [ ] Kod: `GREGAI.zip` rozpakowany (gdziekolwiek; skrypt sam pilnuje ścieżki), `PACZKA_OK`
- [ ] Dane: zaszyfrowane archiwum rozpakowane do folderu projektu, `.env` chmod 600, archiwum usunięte z pendrive'a
- [ ] `.env` (z `.env.example`): `GREGAI_LAN=0`, `OLLAMA_MODEL=qwen2.5:3b`, klucz Anthropic, `KORYTO=anthropic,darmowe,lokalnie`, `CLOUD_DAILY_LIMIT=300`, `SYSOP_SHELL=0` (wyizolowane Ubuntu: `SYSOP_MODE=pelny`)
- [ ] `bash <folder>/install.sh` -> 9/9 bez błędów, warunki WARP zaakceptowane, krok 2: `warp=on`; na końcu wypisana ścieżka projektu
- [ ] `curl -s https://www.cloudflare.com/cdn-cgi/trace | grep warp` -> `warp=on` (też po restarcie)
- [ ] `bash check.sh` -> wszystkie kontrole OK
- [ ] `http://localhost:7777` działa, zakładka dodana; `/debug` -> "Rozgrzewanie modeli": gotowe
- [ ] (opcjonalnie) `bench_chat.py --limit 3` -> czasy 3B, potem `sudo systemctl restart gregai`
- [ ] Router, planer i uczeń wytrenowani (`install.sh --train` albo ręcznie `BATCH=1 GRAD_ACCUM=8 nice -n 19`; przeglądarka zamknięta; uczeń na noc)
- [ ] `/debug`: WARP połączony, Claude aktywny (1. etap koryta), SYSOP włączony (albo TRYB PEŁNY na wyizolowanym Ubuntu)
- [ ] Test blokady: bez WARP brak internetu dla GREGAI; "rozłącz warp" w rozmowie -> odmowa
- [ ] Po restarcie GREGAI startuje sam
- [ ] Stary laptop jako zapas przez tydzień
