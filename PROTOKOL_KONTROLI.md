# Protokół kontroli GREGAI 1.29.0

> **Dokument historyczny.** Wynik jednej konkretnej rundy kontroli (stan
> 2026-10-22, wersja 1.28.0 -> 1.29.0): metoda i znalezione wtedy usterki,
> już naprawione. Zachowany jako przykład metody ("jak sanepid") i dowód,
> że GREGAI przeszedł przez takie rundy - nie opis bieżącego stanu ani
> instrukcja czytania dzisiejszego `check.sh` (ten sam skrypt, ale 1.29.0
> miało dużo mniej kontroli niż obecna wersja - patrz `VERSION`).

Data: 2026-10-22. Kontrolowana wersja: 1.28.0. Wersja po poprawkach: 1.29.0.

Kontrola "jak sanepid": pięciu niezależnych inspektorów (osobne sesje AI, bez
wglądu w swoje wyniki), każdy z listą kontrolną swojego obszaru i obowiązkiem
udowodnienia każdego zarzutu skryptem albo zrzutem ekranu. Zarzuty
niepotwierdzone oznaczono jako "prawdopodobne". Po poprawkach scenariusze
inspektorów uruchomiono ponownie.

Skala: **K** - krytyczne (prywatność, pieniądze, bezpieczeństwo), **P** -
poważne (utrata danych, awaria), **D** - drobne.

## 1. Przepływ danych na zewnątrz

Spis wszystkich wyjść do sieci (dostawcy AI, wyszukiwarka, Wikipedia, notowania,
WARP, router domowy) z bramką dla każdego. Wynik po poprawkach: żaden z
odtworzonych wycieków nie przechodzi.

| Ocena | Zarzut | Stan |
|---|---|---|
| K | Odpowiedź lokalnego AI (widziało wyniki narzędzi i fakty z "Zapamiętaj") wracała potem do chmury w historii i streszczeniu - np. diagnoza z notatki | naprawione: każda odpowiedź napisana lokalnie zostaje lokalna |
| K | Blok "Teraz" w prompcie systemowym (ze streszczeniem rozmowy) nie był maskowany - hasło wpisane w rozmowie szło jawnie | naprawione: maska na bloku i na zapisie streszczenia |
| K | Kontekst routera: "nie zapomnij, że..." szło do chmury przy następnym pytaniu | naprawione: pytanie obsłużone narzędziem idzie tylko, gdy wygląda na publiczne |
| P | Nazwy wgranych plików w rozpoznaniu Namysłu bez zgody | naprawione: tylko liczba i rodzaje plików |
| prawd. | Zadania stałe przeszukują notatki wszystkich projektów | do decyzji razem z długiem z FUNDAMENT §9 |

Sekrety z `.env`, token LAN i hasło routera: maskowane we wszystkich
sprawdzonych drogach (wiadomości, ślad, błędy dostawców, pary destylacji).

## 2. Trwałość danych i odporność na awarie

Tabela wszystkich zapisywanych plików (blokada, atomowość, limit wzrostu);
prawdziwy pełny dysk (tmpfs), ucięte i uszkodzone pliki, wyścigi wątków,
skoki zegara.

| Ocena | Zarzut | Stan |
|---|---|---|
| K | Uszkodzony dziennik wydatków zerował budżet Claude (bezpiecznik otwierał się zamiast zamykać) | naprawione: kopia .corrupt, dzień uznany za wyczerpany, chwilowy błąd = Claude czeka; zegar cofnięty nie zeruje wydatków |
| P | Chwilowy błąd odczytu (np. za dużo otwartych plików) odsuwał zdrowe pliki: ślad, rozmowa, dziennik audytu, wyuczone skróty | naprawione: odsuwamy tylko plik naprawdę uszkodzony |
| P | Uszkodzona albo usunięta baza straży powstawała po cichu od nowa i wchłaniała zmiany (np. podmieniony .env) | naprawione: ostatnia dobra baza w pamięci i alarm |
| P | Nieudane wgranie pliku zostawiało ucięty plik, który dało się dołączyć | naprawione: zapis przez plik tymczasowy z fsync |
| P | Zadanie stałe zamierało po skoku zegara do przodu | naprawione |
| P | Korekta "nie o to" przepisywała cały plik par (po roku ok. 700 MB RAM) | naprawione: krótki znacznik dopisywany na końcu |
| D | Sprzątanie po awarii pomijało podfoldery data/ | naprawione |
| D | Tura z alertem zapisywana w pamięci rozmowy jako "narzędzie" | naprawione |
| D | Dwie karty naraz gubiły zmianę ustawień Namysłu (także zgodę) | naprawione |
| prawd. | Pliki rosnące bez końca: wgrane, dziennik GREGAI, wiki, kopie | do przeglądu (kilka MB rocznie, bez wpływu na działanie) |

## 3. Złośliwe dane na wejściu (żywy serwer)

Każdy punkt API ostrzelany: złe typy JSON, 50 000 poziomów zagnieżdżenia,
niepoprawny UTF-8, NUL, 50 MB, kłamliwy Content-Length, przemierzanie ścieżek,
równoległe duplikaty. Serwer przeżył wszystko bez jednego błędu wewnętrznego.

| Ocena | Zarzut | Stan |
|---|---|---|
| P | 64 milczące połączenia odcinały interfejs na ~20 s (bez tokenu) | naprawione: 256 miejsc, 8 s na nagłówki, czas na treść wg rozmiaru, limit także dla kolejnych żądań na tym samym połączeniu, fałszywy "50 MB" zwalnia wątek po 2 s |

Fuzzer do ponownego użycia jest w materiałach kontroli (insp3/fuzz.py).

## 4. Interfejs

Każde kliknięcie na laptopie (1366x768) i telefonie (360x740, dotyk), także
z procesorem spowolnionym 4x; 13 rodzajów kart, błędy serwera, dwie karty,
odświeżenie w trakcie, brak sieci. Zero błędów strony, brak wycieków pamięci
(100 przełączeń rozmów, 100 wiadomości).

| Ocena | Zarzut | Stan |
|---|---|---|
| P | Schowana mapa 3D liczyła fizykę w tle (telefon: ok. 2 s blokady przy starcie i przy każdym odświeżeniu) | naprawione: mapa buduje się i liczy dopiero, gdy ją widać |
| P | Stop nie działał, gdy serwer nie zdążył nadać numeru zadania (przycisk wisiał) | naprawione: przerwanie żądania i limit 25 s |
| P | Odświeżenie strony w trakcie odpowiedzi gubiło odpowiedź | naprawione: "Odpowiedź mogła już przyjść. Sprawdź" |
| P | Długi tytuł powiązania wypychał "Edytuj" i "Usuń" poza ekran | naprawione |
| P | Telefon nie pokazywał, że serwer nie odpowiada | naprawione: pigułka "Brak połączenia z GREGAI" |
| D | "Sprawdź" przy zadaniu, którego już nie ma, kazało czekać w nieskończoność | naprawione: "Zapytaj jeszcze raz" |
| D | Brak "Spróbuj ponownie" po przeciążeniu (429) i błędzie serwera (5xx) | naprawione |
| D | Za duży załącznik kodowany w całości przed odmową; powód błędu niewidoczny na telefonie | naprawione |
| D | Tekst mniejszy niż 12 px, przyciski mniejsze niż 44 px, słaby kontrast podpowiedzi | naprawione |
| D | Okienko "Dokładne myślenie" gubiło fokus po Esc | naprawione |
| prawd. | Przy 2000 notatek mapa może mieć mało klatek na starym telefonie (rysowanie) | do przebudowy rysowania, gdy notatek będzie tyle |

## 5. Instalacja, aktualizacja, dokumentacja

Symulacja w odizolowanej przestrzeni (atrapy sudo, systemctl, apt, nft, ufw,
warp-cli, ollama): aktualizacja z paczki, uszkodzona paczka, automatyczny
powrót, ręczny powrót, przeniesienie folderu, migracje `.env`.

| Ocena | Zarzut | Stan |
|---|---|---|
| P | Kontrola 32 w `check.sh` zawsze kończyła się błędem (cudzysłów w bashu) | naprawione; wszystkie bloki sprawdzane teraz prawdziwym bashem |
| P | `gregai update` wykonywał kroki "po wgraniu" STAREGO skryptu (nowe migracje .env dopiero za drugim razem) | naprawione od 1.29.0 (pierwsza aktualizacja z 1.28.0 jeszcze po staremu) |
| P | Poprawki wiedzy z paczki nigdy nie docierały (każda istniejąca notatka była pomijana) | naprawione: notatka, której nie zmieniałeś, dostaje nową wersję |
| P | Straż nie mogła widzieć `authorized_keys` ani plików `/etc/sudoers.d`, a dokumentacja twierdziła inaczej | naprawione: pilnowany katalog sudoers.d, dokumentacja uczciwa |
| P | Bez `auth.log` (system bez rsyslog) straż zawsze liczyła 0 nieudanych logowań | naprawione: zapasowo dziennik systemd |
| D | Kontrola 32 pisała do prawdziwego `data/training` | naprawione |
| D | Sprzeczne komunikaty przy przeniesieniu do folderu bez `.env`; "25 s" zamiast 60 s; po automatycznym powrocie `gregai rollback` nie cofał dalej | naprawione |
| D | Liczba kontroli w dokumentach (30/31 zamiast 32), README z wersją 1.19.0, martwa zmienna `GREGAI_PORT` | naprawione |
| D | `rsync -au` przy przenoszeniu mógł zostawić mieszankę wersji | naprawione |

## Co zostaje świadomie (FUNDAMENT §9)

Zadania stałe i planer wysyłają do sieci materiał bez osobnej zgody, tryb pełny
na koncie użytkownika, klucze API w `.env` czytelnym dla usługi, DNS przez
systemowy resolver przy rozłączonym WARP, ograniczenie Ollamy do WARP tylko
na systemd 251+. Każde z nich wymaga Twojej decyzji, nie poprawki.
