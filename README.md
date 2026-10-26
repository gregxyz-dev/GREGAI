# GREGAI 1.32.24

Osobista inteligencja strategiczna jednej osoby. Rozmówca nazywa się **GREGAI**
i mieszka na laptopie: zna Twoje notatki, pamięta to, co mu powiesz
(`zapamiętaj: ...`), czyta ze zrozumieniem pliki, które mu dasz (Źródła,
spinacz), zawsze myśli w sześciu fazach, poza powitaniem i podziękowaniem (Namysł, z
przebiegiem na żywo), i zarządza komputerem, na którym działa (SYSOP).
Serwer: Python stdlib (jedyny wyjątek: opcjonalna biblioteka `huawei-lte-api`
do odczytu routera, patrz `requirements.txt`). Przeglądarka: wyłącznie vanilla JS.
Bez frameworków, bez procesu budowania.

- Adres: **http://localhost:7777** (tylko na tym laptopie)
- Instalacja: **jedna komenda, z dowolnego folderu**: `bash <folder>/install.sh`
  (niżej); system od zera: `INSTALACJA_UBUNTU_26_04.md`
- Kontrola po instalacji: **`bash check.sh`** (69 kontroli; `install.sh` odpala ją sam)
- Decyzje, zakres i bramki 1.0.0 (historia stabilizacji): **`ROADMAP_1.0.md`**
- Licencja: **MIT** (`LICENSE`)

## Dokumentacja

Kilka plików `.md` w katalogu głównym, każdy z inną rolą:

- **`README.md`** (ten plik) - jak zainstalować i używać, stan obecny.
- **`CHANGELOG.md`** - pełna historia wydań, co i dlaczego się zmieniało.
- **`FUNDAMENT.md`** - architektura: jak projekt jest złożony, czego NIE wolno
  złamać, znany dług. Aktualizowany przy zmianie fundamentów, nie co wersję.
- **`PROTOKOL_TWIERDZA.md`** - obrona przed atakiem na SYSOP, wynik testu
  red-team; mechanizmy opisane tu są częścią fundamentu i nie są osłabiane.
- **`PROTOKOL_KONTROLI.md`** - **dokument historyczny** (stan 1.29.0):
  wynik jednej rundy audytu "jak sanepid", przykład metody.
- **`SECURITY.md`** - jak zgłosić podatność bezpieczeństwa.
- **`INSTALACJA_UBUNTU_26_04.md`** - instalacja krok po kroku na jednej,
  konkretnej maszynie jako przykład end-to-end; realne minimum sprzętowe
  jest niewielkie (patrz sekcja "Sprzęt" niżej).
- **`ROADMAP_1.0.md`** - **dokument historyczny** (stan z 2026-10-14, wersja
  1.0.0): decyzje architektoniczne, których się nie odkręca, plus bramki
  stabilizacji sprzed wielu wersji. Zachowany dla tabeli decyzji, nie jako
  opis bieżącego stanu.

## Co nowego

Historia wydań, od 1.1.0 do dziś, z opisem każdej zmiany i jej weryfikacji:
**`CHANGELOG.md`**. Najnowsze: 1.32.24 - nowa sekcja "Wsparcie" (adresy
kryptowalutowe BTC/ETH/SOL, czysto dobrowolne, bez zobowiązań) - to zmiana
poza zaplanowaną serią pięciu tur open source, na wyraźną prośbę po jej
zamknięciu. Wcześniej 1.32.23 - przygotowanie pod open source, tura
5/5 (ostatnia tury zaplanowanej serii pięciu): `LICENSE` miał wciąż pełne
nazwisko autora w copyright (`Copyright (c) 2026 Grzegorz Żelazowski`) -
ostatni taki literał w publicznie wysyłanej części repo, wykryty
niezależnym przeglądem na koniec tej tury; zmieniony na `GREGAI project`.
Założenie rodzaju męskiego w instrukcji stylu dla modelu ("formy męskie")
rozwiązane kluczem `.env` `GREGAI_USER_GENDER` (domyślnie męski - zero
zmiany zachowania), a regex wołacza w `agent/bramka.py` rozszerzony, by
poprawnie rozpoznawać też żeńskie/neutralne czasowniki czasu przeszłego
(kontrola 69). Świadomie POZA zakresem: własna, pierwszoosobowa mowa
GREGAI o sobie zostaje gramatycznie męska w setkach miejsc (patrz
`FUNDAMENT.md`, sekcja 9) - to odrębny temat, nie "pozostałość" tej serii.
Wcześniej 1.32.22 - przygotowanie pod open source, tura 4/5:
sekcja "Bezpieczeństwo" i `install.sh` tłumaczą teraz, że zapora WARP jest
świadomym wyborem bezpieczeństwa tego projektu dla jednoosobowej, izolowanej
maszyny z realną władzą SYSOP-a nad komputerem, nie technicznym wymogiem
samego programu; tabela "Sprzęt" opisana jako maszyna referencyjna, nie
minimalne wymagania; `PROTOKOL_KONTROLI.md` oznaczony jako dokument
historyczny (wynik jednej rundy audytu 1.29.0); usunięte zamrożone liczby
kontroli w `INSTALACJA_UBUNTU_26_04.md`; usunięte cztery martwe importy i
zbędny `global` w `agent/*.py`; `.gitignore` uzupełniony o standardowe wpisy
edytorów (kontrola 68). Wcześniej 1.32.21 - przygotowanie pod open source,
tura 3/5:
imię UŻYTKOWNIKA (do kogo GREGAI się zwraca) było wpisane na trwałe jako "Grzegorz"
w prompcie głównym i w kilkunastu innych promptach wysyłanych do modeli (namysł,
streszczenie rozmowy, tryby /plan i /sprawdz, moduł lekcji, pętla agenta i inne);
teraz konfigurowalne przez trzy klucze `.env` (`GREGAI_USER_NAME` i odmiana), z
domyślną wartością dokładnie odtwarzającą dawne zachowanie (kontrola 67). Wcześniej
1.32.20 - przygotowanie pod open source, tura 2/5:
baza wiedzy (`notatki/wiedza/`) i dane treningowe (`training/*.jsonl`) nie podają już
konkretnego modelu sprzętu ani imienia i nazwiska autora jako uniwersalnego faktu;
`requirements.txt` ma przypięte wersje zależności; dodano `SECURITY.md`; przestarzałe
dokumenty top-level (`ROADMAP_1.0.md`, `FUNDAMENT.md`, `PROTOKOL_TWIERDZA.md`) mają
jasny dopisek o swojej aktualności zamiast zamrożonych numerów wersji w nagłówku, a
README ma sekcję "Dokumentacja" mapującą rolę każdego pliku (kontrola 66). Wcześniej
1.32.19 - przygotowanie pod open source, tura 1/5
(trzej niezależni recenzenci): "twórca" GREGAI (odpowiedź na "kto cię stworzył?")
jest teraz konfigurowalny przez `.env` (`GREGAI_CREATOR_NAME`), generyczny domyślnie,
zamiast imienia i nazwiska autora wpisanego na trwałe w kodzie i w `agent/prompt.md`;
ekran powitalny w UI nie pokazuje już cudzego imienia; dodano `LICENSE` (MIT); notatnik
`CLAUDE.md` (dla Claude Code, nie część programu) wyłączony z gita (kontrola 65).
Wcześniej 1.32.18 - audyt tura 20/20, ostatnia z serii (trzej
niezależni recenzenci): dziennik audytu Nadzorcy maskuje teraz też sekrety WPISANE w
poleceniu albo jego wyniku (Bearer, hasło w adresie bazy danych), nie tylko te z .env;
wołacz "Grzegorzu" już nie psuje zdań, gdzie "Grzegorz" jest podmiotem w trzeciej osobie;
długa, jedna wiadomość nie gubi faktu z samego końca przy zapisie do pamięci rozmowy;
strona zapasowa /debug sama prosi o token dostępu, gdy łączysz się z telefonu bez
zapisanego tokenu (kontrola 64). Wcześniej 1.32.17 - audyt tura 19/20 (trzej niezależni
recenzenci): dwa równoległe wgrania plików nie mogą już razem przebić limitu łącznego,
polecenie "ps" z kolumną środowiska procesów (sekrety) jest zawsze traktowane jako zmiana
wymagająca zgody, czasownik realnej prośby po podziękowaniu budzi dokładne myślenie,
uszkodzony plik po przerwanej aktualizacji jest wykrywany i kod wraca do poprzedniej
wersji automatycznie, czas na zamknięcie usługi dopasowany do najdłuższej operacji, którą
sam GREGAI zleca (kontrola 63). Wcześniej 1.32.16 - audyt tura 18/20 (trzej niezależni recenzenci):
zadania stałe bez wyścigu przy dwóch wiadomościach naraz, cytowanie źródła wymaga
dwukropka (zwykły powtórzony dopisek w nawiasie już nie jest kasowany), wewnętrzna
etykieta Namysłu wycinana też w środku linii, wołacz "Grzegorzu" wszędzie w zdaniu,
podwójne spacje zwijane, dowiązanie do .env pod inną nazwą wykryte w poleceniach shella,
uczenie się wzorców bez zbyt ogólnych wyzwalaczy (kontrola 62). Wcześniej 1.32.15 - z
kolejnego transkryptu: limit dzienny u darmowych
dostawców dostaje godziny przerwy, nie minuty, a gdy wszyscy sieciowi są naprawdę wyczerpani,
lokalny model odpowiada jako ostatnia szansa; zgubiony załącznik wciąż trafia do Namysłu
(zamiast "nie dołączyłeś pliku"); "nie trzeba, dziękuję" zamyka wątek bez pełnego namysłu
(kontrola 61). Wcześniej 1.32.14 - audyt tura 17: czystsza polszczyzna w odpowiedziach, o połowę tańszy Namysł przy pytaniach o fakt, odpowiedź odebrana później trafia przy swoim pytaniu (kontrola 60). Wcześniej 1.32.13 - poprawki po rozmowie z 25.10 wieczorem: cena bez pytania o walutę, „w pln” i „a SOL?” rozumiane z kontekstu, kwoty w przykładach nie znikają, wzory bez LaTeX (kontrola 59). Wcześniej 1.32.12 - audyt tura 16: zamknięta luka w poleceniach systemowych (warp-svc.SERVICE), instalator nie urywa się po cichu, praca offline bez śmieci w odpowiedzi, koryto mówi o budżecie (kontrola 58). Wcześniej 1.32.11 - audyt tura 15: notatki projektu B niedostępne z projektu A przez narzędzia plików, strony błędów nie udają treści, zadania stałe bez duplikatów i z limitem, uczenie odporne na zatrucie (kontrola 57). Wcześniej 1.32.10 - audyt tura 14: usunięta notatka trafia do kosza z „Cofnij”, bezpieczniejsze API przy telefonie, odporny odczyt plików, mniej prądu w Węzłach (kontrola 56). Wcześniej 1.32.9 - audyt tura 13: lepsze odpowiedzi w dokładnym myśleniu, bezpieczniejsza aktualizacja, jednolity interfejs (kontrola 55). Wcześniej 1.32.8 - audyt tura 12: wynik poleceń systemowych nie trafia bez zgody do AI w sieci, poprawki zmiany czasu, jedyny tryb bez skutków ubocznych (kontrola 54). Wcześniej 1.32.7 - dokładne myślenie to jedyny tryb GREGAI, rozmowa bez „Czuwam” i licznika USD, jednolity przełącznik widoków (kontrola 53). Wcześniej 1.32.6 - audyt tura 10: „Tak chce” działa, srebro i „ile kosztuje złoto” idą prosto do notowań, bramka cen bez fałszywych alarmów (kontrola 52). Wcześniej 1.32.5 - poprawki po Twojej rozmowie z 25.10: bez etykiety „Response Safety: safe”, bez zmyślonej ceny srebra, zapasowe źródło notowań złota i srebra (kontrola 51). Wcześniej 1.32.4 - Twoje cztery decyzje: zapora WARP w jądrze obowiązkowa (bez niej GREGAI nie wystartuje), dostawca AI dopasowuje się sam (darmowa pula, płatny Claude jako zapas), planer bez Twojej zgody nie widzi treści notatek i plików, zwięzły prompt modelu lokalnego (kontrola 50). Wcześniej 1.32.3 - audyt tura 8/20: każde wejście API sprawdzone złośliwymi danymi, prompt rozmowy krótszy o jedną czwartą i bez sprzeczności, mniej budzenia procesora i radia w tle, odporność na zepsute i niezapisywalne pliki (nic nie jest już po cichu nadpisywane), lepsze wyszukiwanie w notatkach po polsku (kontrola 49). Wcześniej 1.32.2 - audyt tura 7/20, przekrojowo: próba przemycenia poleceń (planer nie zakłada zadań w tle ani nie pyta o pogodę bez Twojej zgody), wiele rozmów i wątków naraz, cały interfejs w przeglądarce i na telefonie (koniec zamarzania przy wpisywaniu komend), ponad 120 realistycznych rozmów (trafniejsza waga uwagi, „zapisz to” znowu działa), instalator i aktualizacja (kontrola 48). Wcześniej 1.32.1 - audyt tura 6/20: pięciu niezależnych recenzentów przejrzało cały kod; poprawione m.in. zawieszanie serwera przez maskę sekretów, gregaipanicmode odcinający też otwarte połączenia z sieci, izolacja wgranych plików między rozmowami, zadania stałe bez wysyłania notatek bez zgody, mniej fałszywych narzędzi w zwykłych zdaniach, limity pobierania stron i liczby po polsku (kontrola 47). Wcześniej 1.32.0 - internet naprawiony warstwa po warstwie (pewniejsza bramka WARP, zapasowe wyszukiwarki, `/diagnoza` i `gregai diagnoza`), bramka odpowiedzi w kodzie, komendy `/` (`/pomoc`, `/plan`, `/badaj`, `/recenzja`, `/sprawdz`, `/lekcja`), lekcje zatwierdzane przez Ciebie i testy regresji `gregai eval` (pass@k) - wzorce z everything-claude-code. Wcześniej 1.31.0 - nowy wygląd „Kadr” w stylu napisów filmowych (turkusowe etykiety, wielkie kanciaste tytuły, ciepłe brązowe tło), kolor każdego panelu mówi o jego ważności, jeden nagłówek we wszystkich trzech widokach i podpowiedź pod polem rozmowy, co zrobić teraz. Wcześniej 1.30.31 - poprawki z Twojej rozmowy (gregaipanicmode naprawdę wyłącza komputer mimo blokad wyłączenia, pogoda z prognozy Open-Meteo i słońce liczone w kodzie, wyniki wyszukiwarki streszczane zamiast listy linków, prawdziwa odpowiedź na „z jakiego modelu korzystasz”, pełne zdania w alertach straży). Wcześniej 1.30.x - dane giełdowe bez klucza (krypto z Coinbase/CoinGecko z historią miesiąca i wykresem, akcje/indeksy/waluty/surowce z Yahoo Finance; martwy Stooq zastąpiony), czytanie całych stron w wyszukiwarce, "dodaj do węzłów" (zapis odpowiedzi jako węzeł typu Wiedza), warstwa UWAGI (skupienie 1-4: szum/rutyna/ważne/krytyczne, z checkpointem przy nieodwracalnych akcjach) oraz rozdzielnica (waga uwagi wybiera szynę - darmowa pula pierwsza, płatny Claude jako eskalacja - żeby zużywać jak najmniej tokenów). Wcześniej 1.29.0 - kontrola "jak sanepid" (pięciu niezależnych inspektorów, protokół w `PROTOKOL_KONTROLI.md`); od 1.20.0 do 1.28.0 kolejne rundy audytów, straż systemu, budżet Koryta, prowadzenie za rękę i sprawdzona wiedza. Wcześniej 1.19.0 - druga runda na Fundamencie A: historia rozmowy znowu dociera do Claude, polecenia (gregaipanicmode, freeram) działają w środku rozmowy, wyszukiwanie po polsku z odmianą, wyłącznik WARP w jądrze, `gregai update PLIK.zip` z automatycznym cofnięciem, odpowiedzi przypisane do swojej rozmowy i rozmowy po odświeżeniu, interfejs na telefonie. Wcześniej 1.18.0 - Fundament A (**`FUNDAMENT.md`**: jak GREGAI jest zbudowany i czego nie wolno zepsuć) i jedna spójna całość po 1.17.x: budżet całej wiadomości w korycie, wyszukiwanie w notatkach bez polskich znaków i z notatkami powiązanymi, pytania uzupełniające z tematem z kontekstu, Kopiuj/Esc/Spróbuj ponownie w interfejsie. Wcześniej 1.17.0 - KORYTO (`agent/koryto.py`): jedna kolejność dostawców dla całego myślenia, Claude Haiku jako główny, darmowa pula jako rezerwa, lokalny model jako ostatnia deska ratunku; tryb pełny SYSOP (`SYSOP_MODE=pelny`) dla GREGAI na wyizolowanym Ubuntu. Wcześniej 1.16.2 - gregaipanicmode wraca natychmiast, `agent/symbols.py`, panel „Postęp”. Wcześniej 1.16.1 - ikona strony. Wcześniej 1.16.0 - jeden system projektowy (`ui/sistem.css`): siatka, trzy promienie, spokojny kolor niosący znaczenie, brak nakładających się elementów. Wcześniej 1.15.0 - przeprojektowane Węzły (pasek, panel przeglądania, wybrana notatka, ściąga) i Nadzorca w zakładkach z banerem stanu. Wcześniej 1.14.0 - w Węzłach powiązania w osobnej karcie (dwa kierunki) i w osobnej sekcji edytora, inspektor w kartach. Wcześniej 1.13.0 - cukierkowy, spójny motyw (`ui/motyw.css`), szufladki w panelu rozmowy, ekran powitalny z kafelkami startowymi. Wcześniej 1.12.0 - menu rozmowy (trzy paski: Źródła, pliki, pamięć), tryb rozumowania pod polem wpisywania, przycisk Zatrzymaj, kosz rozmowy z plikami. Wcześniej 1.11.0 - jedna zwarta aplikacja: Nadzorca
(dawny `/debug`) jako trzeci segment czatu (Rozmowa / Węzły / Nadzorca,
skrót `/#nadzorca`), jedno polecenie `gregai` (status, check, update, install,
start/stop/restart, logs, open), historia zmian wyniesiona do `CHANGELOG.md`
(README 2500 -> ok. 550 linii), martwy kod usunięty.

## Instalacja jedną komendą, z dowolnego folderu

```bash
bash /dowolna/sciezka/GREGAI/install.sh
```

Folder możesz położyć gdziekolwiek (inna nazwa, nawet spacja w ścieżce) i
przenieść później gdzie indziej: ta sama komenda w nowym miejscu przepina
usługi systemd, poprawia `SYSOP_ROOTS` w `.env`, wypisuje **starą i nową
ścieżkę** i niczego nie kasuje. Skrypt sam: instaluje pakiety, Cloudflare
WARP (obowiązkowy), Ollamę i model 3B, tworzy `.env` z `.env.example` (pyta o
klucz Anthropic, bez echa; Enter = pomiń), zakłada usługi, sudo dla listy
usług, zaporę, swap 8 GB i ustawienia "laptop nie zasypia" (pokrywa, zasilanie), na końcu odpala
`check.sh`. Opcje: `--train` (trening router + planer + uczeń w tle),
`--no-host` (bez ustawień laptopa), `--here` (instaluj dokładnie tu), `--yes`
(bez pytań o klucz Anthropic i trening; hasło do `sudo` i rejestracja WARP
nadal mogą zapytać), `--help`. Jeśli folder leży na **dysku USB / wymiennym**, w katalogu
tymczasowym albo na FAT/exFAT/NTFS (usługa nie przetrwałaby restartu, a
`.env` nie miałby praw 600), skrypt sam kopiuje projekt razem z `.env` i
danymi do istniejącej instalacji, a bez niej do `~/Dokumenty/GREGAI` (albo `$GREGAI_HOME`), i instaluje stamtąd.

## Sprzęt

Tabela niżej to maszyna referencyjna, na której GREGAI jest rozwijany i
testowany (przykład end-to-end, patrz `INSTALACJA_UBUNTU_26_04.md`) - nie
minimalne wymagania. Realne minimum: jakikolwiek x86-64 z Ubuntu 22.04+,
Pythonem 3.10+ i kilkoma GB wolnego RAM wystarczy do uruchomienia serwera i
rozmowy przez chmurę/darmową pulę; bez własnej karty graficznej model
lokalny (ostatnia rezerwa, patrz niżej) będzie wolniejszy niż na sprzęcie
z tabeli, ale nie jest do niczego innego wymagany.

| | |
|---|---|
| Laptop | Dell Latitude E7270 |
| Procesor | Intel Core i7-6600U (2 rdzenie / 4 wątki, AVX2) |
| Grafika | Intel HD Graphics 520 - modele liczą się na CPU |
| RAM | 16 GB DDR4 (2 x 8 GB, pracuje z 2133 MHz) |
| Dysk | Lite-On CV1-8B256-HP, 256 GB, M.2 2280 SATA, szyfrowany (LUKS) |
| System | Ubuntu 26.04.1 LTS Desktop |

Bez karty graficznej szybkość modeli zależy od CPU i przepustowości RAM.
Dlatego od 1.17.0 myślenie idzie **korytem** (`agent/koryto.py`, `KORYTO` w
`.env`): Claude (Anthropic, płatny, domyślnie Haiku), darmowa pula dostawców i
lokalne, małe modele - te ostatnie jako rezerwa i jedyne, gdy nie ma
internetu/WARP. "Cały program to koryto; zmienia się tylko, co przez nie
płynie" - ta sama pula obowiązuje rozmowę, Namysł, decyzję o narzędziu i planer
zadań. Od 1.30.23 **kolejnością w korycie steruje rozdzielnica**
(`agent/skupienie.py` + `ROZDZIELNICA` w `.env`): waga uwagi 1-4 decyduje per
wiadomość, którą szyną puścić zapytanie. Domyślnie (polityka B) darmowa pula
idzie pierwsza, a płatny Claude tylko jako eskalacja przy sprawach ważnych i
krytycznych - żeby zużywać jak najmniej tokenów przy jak najlepszym wyniku.

## Jak GREGAI myśli (architektura)

| warstwa | model | rola |
|---|---|---|
| router | własny, baza **Qwen2.5-1.5B** dotrenowana (`training/run.sh`) | narzędzie czy rozmowa - w sekundy (do treningu: słowa kluczowe) |
| planer | własny, baza **Qwen2.5-0.5B** dotrenowana (`training/run_planner.sh`) | zadania wielokrokowe SYSOP |
| uczeń | własny, baza **Qwen2.5-1.5B** dystylowana (`training/run_student.sh`) | szybka, "swoja" osobowość GREGAI do zwykłej rozmowy |
| **koryto, etap 1: Claude** | Anthropic przez API, PŁATNY, domyślnie `claude-haiku-5-5` (`ANTHROPIC_MODEL`, `CLOUD_DAILY_LIMIT=300`; mocniejszy tylko do Namysłu wagi 4: `NAMYSL_MODEL`; wkład żonglera w `agent/juggler.py`) | dostawca rozmowy, Namysłu, decyzji o narzędziu (`KORYTO_ROUTING`) i planera zadań (`KORYTO_ZADANIA`). Od 1.30.23 rozdzielnica (polityka B) sięga po niego dopiero jako eskalację przy wadze uwagi 3-4, gdy darmowa pula zawiedzie; każda odpowiedź to przykład treningowy dla ucznia |
| **koryto, etap 2: darmowa pula** | Groq, Google Gemini, OpenRouter, Hugging Face, Cloudflare Workers AI (`agent/juggler.py`, kolejność prób w tym etapie losowana; w ramach jednej rozmowy "lepkość" trzyma tego samego dostawcę, ale nigdy przed Claude) | rezerwa, gdy Claude nie odpowie (błąd, limit, bezpiecznik); też przykłady treningowe; w zadaniach stałych (`agent/standing.py`) - jednorazowe streszczenie wyniku wyszukiwania |
| **koryto, etap 3: lokalnie** - uczeń, potem duży model | Qwen2.5-3B (`OLLAMA_MODEL` w `.env`, Ollama, lokalnie) | ostatnia rezerwa i jedyny etap bez internetu/WARP; "senior" składający odpowiedź z researchu juniorów; w zadaniach stałych - jedyny model, który decyduje "czy to już alert" (nigdy sieć, p. "Zadania stałe") |

Kolejność etapów to jeden wpis `KORYTO=anthropic,darmowe,lokalnie` w `.env`
(`agent/koryto.py`): etap pominięty nie jest używany, `KORYTO=lokalnie,...`
odwraca kolejność. Stare `JUGGLER_MODE`/`CLOUD_FALLBACK` są ignorowane.

Zablokowane rozmiary (decyzja 2026-10-08, na tę maszynę 16 GB): router
1.5B, uczeń 1.5B, planer 0.5B. Duży model 3B (decyzja 2026-10-12, zejście
z 7B dla szybkości na tym CPU; wcześniej 7B zamiast 14B). Na 8 GB bazy schodzą do 0.5B świadomie (zmienna `BASE_MODEL`).

**Skąd uczeń bierze wiedzę:** uczy się **od etapów sieciowych koryta + ręcznego
seedu** (`training/distill_seed.jsonl` + `training/teacher/*.jsonl` + pary
zebrane przez Claude i darmową pulę, rozróżnione polem
`"provider"` w `data/training/distill_pairs.jsonl`), **NIE od lokalnego
dużego modelu**. Duży model jest tylko zapasem do rozmowy, gdy ucznia jeszcze
nie ma, nie jest jego nauczycielem. Odkąd istnieje żongler, zbieranie par
treningowych NIE wymaga już płatnego API (2026-10-19) - pula darmowa
(Groq/Gemini/OpenRouter/Hugging Face/Cloudflare) wystarcza jako główny
nauczyciel; chmura Anthropic zostaje tylko dodatkowym zapasem, nie jedynym
źródłem.

Żongler i chmura mają dzienny limit, osobno PER DOSTAWCA
(`GROQ_DAILY_LIMIT`/`GEMINI_DAILY_LIMIT`/`OPENROUTER_DAILY_LIMIT`/
`CLOUD_DAILY_LIMIT`, doba liczona w UTC, czyli licznik zeruje się o
północy czasu UTC, nie lokalnego), a każdy błąd (sieć, limit, klucz)
oznacza po prostu przejście do następnego w łańcuchu, aż do odpowiedzi
lokalnej. Szczegóły treningu:
`training/README.md`.

## Bezpieczeństwo (priorytet projektu)

**Skąd ten priorytet.** GREGAI dostaje od instalatora prawdziwy dostęp do
komputera, na którym działa: SYSOP (`agent/sysop.py`) potrafi usługi,
procesy, aktualizacje i - na wyraźne polecenie w czacie -
`gregaipanicmode` (odcięcie sieci i wyłączenie maszyny). To świadomy
wybór bezpieczeństwa dla jednoosobowej, izolowanej maszyny, nie
techniczny wymóg samego programu: skoro model ma realną władzę nad
komputerem, obrona idzie warstwami (fail-closed WARP, zapora w jądrze,
brak przełącznika w `.env`), żeby błąd modelu albo wyciek klucza nie
oznaczał od razu otwartej furtki na zewnątrz. Kto uruchamia GREGAI w
innym kontekście (inny model zagrożeń, maszyna współdzielona z innymi
usługami) może chcieć inaczej rozłożyć te warstwy - to jednak realna
zmiana kodu (reguły `nftables` w `install.sh`, krok 7b; `agent/netguard.py`),
nie przełącznik instalatora, i wymaga świadomej decyzji, nie domyślnego
ustawienia.

**Skąd pochodzą polecenia.** Polecenie dla GREGAI pochodzi wyłącznie z Twojej
wiadomości w czacie, i to z jej początku. Wszystko, co GREGAI czyta (notatki,
pliki, Wikipedia, wyniki poleceń, nazwy urządzeń w sieci, nawet własne odpowiedzi
modeli), to dane. Pilnuje tego kod, nie model:
- słowa „zapamiętaj”, „wyszukaj”, „Wikipedia” uruchamiają narzędzie tylko w
  pierwszym zdaniu krótkiej wiadomości; w głębi wklejonego tekstu są zwykłym tekstem;
- w pętli zadań wynik każdego kroku trafia do modelu w jednej linii, w ramce
  `<<<...>>>`, której treść nie może zamknąć, a odpowiedź modelu to jedna linia,
  więc „KROK:” w pliku nie staje się krokiem;
- każda zmiana w systemie, każde zapytanie do internetu ułożone przez model, każde
  polecenie shella ułożone w pętli zadań (gdy shell włączony; poza pętlą wąska
  lista odczytów idzie od razu) i każdy zapis do pamięci po odczycie cudzych
  danych czeka na Twoje „tak” na karcie, która pokazuje narzędzie i jego
  argument; „tak” liczy się tylko z czatu (nie z pliku, nie z odpowiedzi modelu);
- uczenie szybkich wzorców bierze słowa wyłącznie z Twoich wiadomości, nigdy
  z argumentów ani z wyników;
- do żonglera (jeśli jest przynajmniej jeden klucz - Groq/Gemini/OpenRouter/
  Hugging Face/Cloudflare) i do
  chmury (jeśli jest klucz Anthropic) idzie Twoja wiadomość i rozmowa, nigdy
  odpowiedzi narzędzi, wycinki notatek ani wyniki skanu sieci; tury rozmowy są
  podpisane przez serwer, więc przeglądarka nie może „odznaczyć” odpowiedzi
  narzędzia; zawsze przez WARP (sprawdzanym od nowa tuż przed każdym żądaniem),
  bez proxy, do KAŻDEGO z nich jednakowo. Między tym sprawdzeniem a połączeniem
  zostaje okno milisekund: gdybyś rozłączył WARP dokładnie wtedy, w świat mogłaby
  wyjść nazwa hosta (DNS, SNI), nigdy treść. Dla pytań ryzykownych (finanse w
  kryzysie, zdrowie psychiczne, bezpieczeństwo - `juggler.is_risky`) żongler
  dodatkowo chowa osobowość GREGAI i historię rozmowy przed zewnętrznymi
  dostawcami (wzorzec "senior + juniorzy", patrz CHANGELOG.md, 1.7.2) - widzą
  tylko samo pytanie, bez kontekstu, kto je zadał;
- interfejs: CSP bez skryptów i stylów inline, każdy tekst z danych uciekany,
  żądania tylko z `localhost` (`Host`, `Origin`, `Sec-Fetch-Site`, JSON);
- jądro: `gregai.service` nie widzi `~/.ssh`, `~/.gnupg`, pęku kluczy ani
  poświadczeń chmur (`InaccessiblePaths`), a jednostka skanu sieci pisze tylko w
  `data/`.

- **Cloudflare WARP, na sztywno** (`agent/netguard.py`): GREGAI łączy się z
  internetem wyłącznie przez WARP i tylko przez `https`. Bez połączonego
  WARP żadne zapytanie nie wychodzi (fail-closed); rozmowa lokalna działa
  dalej. Nie ma przełącznika w `.env`.
- **Nic nie jest wystawione do sieci**: serwer słucha tylko na
  `127.0.0.1:7777` (`GREGAI_LAN=0`; `install.sh` dopisuje to, gdy w `.env` nie
  ma wpisu, także bez pulpitu, a istniejący wpis zostawia i na laptopie z pulpitem
  ostrzega przed `GREGAI_LAN=1`), Ollama tylko na `127.0.0.1:11434`, zapora
  `ufw` blokuje ruch przychodzący. `GREGAI_LAN=1` wpisujesz sam w `.env` albo
  przełącznikiem "Udostępnij w sieci lokalnej" na `/debug` (1.8.13,
  `agent/main.py` `_handle_lan_mode`): zapisuje te dwie zmienne w `.env`
  (token, jeśli go jeszcze nie ma, losowy jak w `install.sh`) i restartuje -
  **zapory samo NIE dotyka** (`ufw` jest w `agent/sysop.py` chroniony przed
  każdą zmianą, nawet z panelu), więc przy aktywnym `ufw` trzeba jeszcze
  ręcznie przepuścić port (polecenie w panelu) albo ponownie uruchomić
  `install.sh`. Przy `GREGAI_LAN=1` strona i token idą po sieci domowej
  zwykłym HTTP (bez szyfrowania): to tryb dla zaufanej sieci domowej, nie dla
  kawiarni.
- **Żądania przez pośrednika** (nagłówki proxy) i z sieci zawsze wymagają
  tokenu `GREGAI_TOKEN`, nagłówek `X-Gregai-Token` (`agent/main.py`, `_authorized`).
- **SYSOP = stałe, nazwane narzędzia** (`agent/sysop.py`, domyślnie od 1.0):
  stan komputera, usługi, logi, aktualizacje, sieć, procesy, timery, pliki w
  dozwolonych katalogach, kopia zapasowa, akcje na usługach z listy. Odczyt
  od razu, zmiany po Twoim "tak", niszczące zablokowane na stałe. **Dowolny
  shell (`sys_shell`) jest wyłączony** (`SYSOP_SHELL=0`): dla modelu i
  pętli agenta nie istnieje, a wywołanie wprost jest odrzucane. Włączasz go
  świadomie w `.env` (`SYSOP_SHELL=1`) i restartem. Zadania typu "sprawdź
  logi i jeśli są błędy, zrestartuj usługę" idą pętlą agenta krok po kroku
  (maks. 6 kroków, weryfikacja po zmianie, karta potwierdzenia w czacie;
  zapytanie wychodzące w internet i zapis faktu przeczytanego z pliku albo
  strony też czekają na Twoje „tak”);
  każde zadanie zapisuje epizod do `data/training/episodes.jsonl` (materiał
  do treningu planera), a każde wykonanie trafia do dziennika audytu
  `data/sysop_log.json`. Wyłączenie całości: `SYSOP_ENABLED=0` w `.env` +
  `bash install.sh` (instalator usuwa wtedy też reguły sudo z
  `/etc/sudoers.d/gregai-sysop`; sam restart usługi wyłączyłby narzędzia, ale
  reguły sudo zostałyby i `check.sh` by to zgłosił). Reguły `gregaipanicmode`
  (zapora + wyłączenie komputera) leżą od 1.19.0 w osobnym
  `/etc/sudoers.d/gregai-panic` i zostają także przy wyłączonym SYSOP:
  wyłącznik awaryjny ma działać zawsze. To wyłączenie przetrwa
  ponowną instalację na tej samej maszynie; włączasz je z powrotem przez
  `SYSOP_ENABLED=1` i `bash install.sh`. GREGAI **nie może
  osłabić własnych zabezpieczeń** (WARP, zapora, sudoers, SSH, źródła
  pakietów), nawet z potwierdzeniem - to robisz tylko Ty, w terminalu.
  Gdy świadomie włączysz `SYSOP_SHELL=1`, klasyfikator poleceń blokuje na
  stałe m.in. zmiany plików startowych powłoki, katalogów z programami
  użytkownika (`~/.local/bin`, `~/bin`), cron, jednostek systemd, `sudoers`,
  SSH, źródeł pakietów, własnego kodu GREGAI (`agent/`, `ui/`, `training/`, `install.sh`,
  `aktualizuj.sh`, `check.sh`, `requirements.txt`; zmiana i uruchamianie są zablokowane,
  odczyt działa), uruchamianie kodu przez interpretery z `-c`/`-e`,
  `find -exec` i `awk system()`. Klasyfikator widzi tekst polecenia, nie
  treść skryptu, który uruchomi `bash plik.sh`. To jest lista znanych
  furtek, a nie dowód, że żadnej nie ma: polecenie złożone w trakcie
  działania przez kogoś zdeterminowanego może ją ominąć, dlatego ostatnią linią
  obrony zostaje karta potwierdzenia, która pokazuje polecenie dokładnie
  tak, jak zostanie wykonane. Przy domyślnym `SYSOP_SHELL=0` ten tor w ogóle
  nie istnieje. Od 1.19.0 w OBU trybach: GREGAI nie zatrzyma, nie wyłączy i
  nie zabije sam siebie (także `SYSOP_PYTAJ=nigdy`); archiwum albo
  rekurencyjne przeszukanie katalogu z `.env` (np. `tar czf x.tgz .`,
  `grep -r ... .`) jest niebezpieczne; wyłączenie/restart komputera i zmiany
  tras, interfejsów i DNS (obejście WARP) też; przy rozłączonym WARP shell
  wykonuje zmiany tylko programami, o których wiadomo, że nie wychodzą do
  sieci; instalacje pakietów (`apt`, `dpkg`, `snap`) mają 30 minut, nie 60 s.
  Drugą warstwą jest jądro: zapora WARP w nftables (procesy usługi gregai
  wychodzą tylko przez WARP, localhost i sieć lokalną) oraz katalogi z
  kluczami i profilami przeglądarek niewidoczne dla usługi (InaccessiblePaths).
- **Tryb pełny SYSOP** (1.17.0, `SYSOP_MODE=pelny` w `.env` + `bash install.sh`
  + restart; `agent/sysop.py`, sekcja "Tryb PEŁNY"): dla GREGAI na
  **wyizolowanym Ubuntu, które jest tylko jego** (decyzja Grzegorza
  2026-10-21: "korzystał z całego Ubuntu pod siebie, pełen dostęp"). Wtedy
  wszystko wyżej przestaje być pytaniem "czy wolno", a staje się pytaniem
  "czy pytać": `sys_shell` istnieje zawsze (także z `sudo`), narzędzia plikowe
  widzą cały system (jedyny wyjątek: `.env` z kluczami), `sys_service_action`
  zarządza każdą usługą, `install.sh` pisze do sudoers jedną regułę
  `ALL=(ALL) NOPASSWD: ALL`. Odczyt i zwykłe zmiany wykonują się **bez karty**;
  polecenia nieodwracalne albo osłabiające zabezpieczenia (`rm -rf /`, `ufw
  disable`, `warp-cli disconnect`, sudoers, własny kod) **nie są już
  zablokowane na stałe - wykonują się po JEDNYM potwierdzeniu** (karta
  "niebezpieczne", z powodem z klasyfikatora). To jedyny hamulec, bo model pod
  wpływem instrukcji wstrzykniętej w notatkę/stronę/log może ZAPROPONOWAĆ
  zniszczenie maszyny, a jedno "tak" jest tańsze niż reinstalacja; kto nie
  chce i tego: `SYSOP_PYTAJ=nigdy` (zero kart), `SYSOP_PYTAJ=zmiany` (karta
  także dla zwykłych zmian). Co zostaje w obu trybach: dziennik audytu,
  maskowanie sekretów, WARP fail-closed dla poleceń sieciowych, odmowa dla
  poleceń, których nie da się bezpiecznie POKAZAĆ przed wykonaniem (puste,
  niewidoczne znaki, niedomknięty cudzysłów), "nie zatrzymam sam siebie" i
  zasada, że instrukcja z pliku/logu/strony nigdy nie jest poleceniem. Prompt
  systemowy dostaje wtedy osobny blok "Tryb pełny" (`sysop.full_mode_prompt_block`),
  a Nadzorca i `gregai status` pokazują tryb wprost. **Nie włączaj tego na
  laptopie z Twoimi prywatnymi danymi** - tylko na osobnej maszynie dla GREGAI.
- **Prywatność rozmów**: odpowiedzi narzędzi (z notatek, plików, logów,
  sieci domowej) nigdy nie idą do sieci w ROZMOWIE, a razem z nimi
  wcześniejsze polecenia, na które odpowiedziało narzędzie (wyjątek 1.17.0:
  planer zadań SYSOP przy `KORYTO_ZADANIA=1` - jego prompt zawiera zmaskowane
  obserwacje z narzędzi; `0` przywraca planer lokalny). Do zewnętrznego
  dostawcy (etapy sieciowe koryta: Claude albo Groq/Gemini/OpenRouter/Hugging
  Face/Cloudflare) wychodzą
  tylko Twoje pozostałe wiadomości z rozmowy, zwykłe odpowiedzi rozmowne i
  prompt systemowy GREGAI (osobowość i zasady z `agent/prompt.md`, w tym Twoje
  imię i nazwisko oraz opis Twoich zajęć, jakie tam wpisałeś, oraz opisy
  wszystkich narzędzi) - WYJĄTEK: pytania ocenione jako ryzykowne
  (`juggler.is_risky`) idą do żonglera BEZ osobowości i BEZ historii (patrz
  "Co nowego w 1.7.2"). Do sieci trafia każda rozmowa od razu, korytem
  (`KORYTO=anthropic,darmowe,lokalnie`): najpierw Claude (z kluczem
  `ANTHROPIC_API_KEY`, płatny, do `CLOUD_DAILY_LIMIT` zapytań dziennie), potem
  darmowa pula (o ile podałeś choć jeden jej klucz); bez żadnego klucza
  wszystko jest lokalne. Nie ma już gatingu po "trudności" pytania. Od 1.17.0
  siecią idzie także krok 1 (decyzja o narzędziu, sama wiadomość) i planer
  zadań SYSOP (jego prompt zawiera obserwacje z narzędzi - zmaskowane);
  każde z osobna wyłączasz wpisem `KORYTO_ROUTING=0` / `KORYTO_ZADANIA=0`.
  Jeśli nie chcesz darmowej puli, usuń `darmowe` z `KORYTO`; jeśli nie chcesz
  Claude, usuń `anthropic` (albo nie podawaj klucza). Sekrety z `.env` są
  maskowane w śladach, parach treningowych i epizodach, a pliki z danymi
  GREGAI (`data/`, zbiory treningowe) dostają prawa 600. Hasło wpisane w
  rozmowie jest maskowane tylko wtedy, gdy da się je rozpoznać (po słowie
  „hasło/token/klucz ... jest/to/:", z typowych formatów kluczy API, numerów
  kart albo jako długi losowy ciąg). Ta sama maska działa na wiadomości
  i historii wysyłanej do żonglera i do chmury, ale rozpoznaje tylko znane
  kształty, więc haseł nie wpisuj w rozmowie.
- **sudo tylko na listę**: `gregai` i `ollama` (+ `apt-get update/upgrade`),
  nie "dowolna usługa" (`SYSOP_UNITS` w `install.sh`; ta sama lista w kodzie:
  `MANAGED_UNITS` w `agent/sysop.py`). Osobny, równie wąski wpis sudo (ten sam
  plik, `PANIC_RULES` w `install.sh`) jest TYLKO dla `gregaipanicmode` (patrz
  "Tryby mocy" niżej): cofnięcie reguł zapory dla portu GREGAI z sieci
  prywatnych i `systemctl poweroff`, nic więcej. To jedyny, świadomy
  wyjątek od "GREGAI nie może osłabić własnych zabezpieczeń" wyżej - idzie
  wyłącznie w stronę BARDZIEJ restrykcyjną (blokada, nigdy otwarcie) i tylko
  z tej jednej, dosłownej frazy wpisanej przez Ciebie, nigdy z decyzji
  modelu czy pętli agenta.
- **Zapytania do internetu** idą tylko przez WARP, z krótkiej wiadomości-
  polecenia, obcięte do 200 znaków i bez sekretów z `.env`; długi wklejony
  tekst nigdy nie wychodzi do wyszukiwarki. W pętli agenta każde takie
  zapytanie czeka na Twoje „tak”.
- **Strony z internetu nie wyślą nic do GREGAI** (sprawdzanie Host,
  Origin, Sec-Fetch-Site; tylko JSON, limit 4 MiB) - ochrona przed CSRF i
  DNS rebinding. Każda odpowiedź ma nagłówki bezpieczeństwa (CSP
  `default-src 'self'` bez skryptów inline, `nosniff`, `X-Frame-Options:
  DENY`, `Referrer-Policy: no-referrer`), a serwer wydaje tylko pliki
  `html/js/css` z `ui/`.
- **Skan sieci i router HiLink tylko w domu** (`agent/homenet.py`: brama i
  jej MAC zapamiętany w domu). Hasło panelu nie idzie do bramy w obcej sieci,
  chyba że ktoś tam sklonuje MAC Twojego routera (adres MAC nie jest
  uwierzytelnieniem); to ryzyko jest znane i akceptowane przy użyciu na
  jednym laptopie. Przy `ROUTER_SCHEME=https` (domyślnie) most do routera
  przypina certyfikat zapamiętany przy pierwszym połączeniu
  (`data/router_cert.json`): inny certyfikat = odmowa. Po wymianie routera
  usuń ten plik, a zapamięta nowy. Uszkodzony plik z odciskiem to błąd z
  tą samą podpowiedzią, nie ciche przypięcie od nowa.
- **Dysk zaszyfrowany**, `.env` z prawami `600`, sekrety i klucze prywatne
  wycinane z wyników poleceń, instrukcje znalezione w notatkach i na
  stronach to dane, nigdy polecenia (`agent/prompt.md`).
- **Notatki**: GREGAI ich nie zapisuje ani nie kasuje sam (wyjątki: `zapamiętaj: ...`
  dopisuje jeden fakt do `memory/`, a własny bank wiedzy z Wikipedii i dziennik
  prowadzi w `data/wiki_cache` i `data/journal`); edycja, tworzenie i
  usuwanie notatek to przyciski w grafie, klikane przez Ciebie. Pliki
  `.md` i `.txt` są edytowalne, notatki z PDF-ów tylko do odczytu.
- **Zapisy atomowe** (`agent/fsutil.py`): notatki, `.env`, uczenie, ślady i
  inwentarz sieci zapisują się przez plik tymczasowy i podmianę, więc awaria
  prądu nie zostawia pustego ani urwanego pliku.

## Uruchomienie

Normalnie nic nie trzeba: usługa `gregai.service` startuje sama przy
włączeniu laptopa. Ręcznie (np. do testów, gdy usługa jest zatrzymana):

```bash
cd <folder projektu> && python3 agent/main.py
```

Jedno polecenie do codziennych spraw (od 1.11.0, `install.sh` dopisuje je do
`~/.local/bin`, działa z każdego folderu):

```bash
gregai              # stan: wersja, usługa, port, WARP, Ollama, żongler (bezpiecznik), chmura, SYSOP
gregai check        # kontrole po instalacji (= bash check.sh)
gregai update       # po wgraniu nowej wersji (= bash aktualizuj.sh)
gregai update ~/Pobrane/GREGAI-x.y.z.zip   # bezpiecznie z paczki: sprawdzenie, kopia, podmiana, automatyczny powrót
gregai rollback     # powrót do kodu sprzed ostatniej aktualizacji z paczki
gregai install      # instalacja/naprawa od zera (= bash install.sh, te same opcje)
gregai diagnoza     # internet warstwa po warstwie: co nie działa i jakim poleceniem to naprawić
gregai eval         # testy regresji (szybkie, bez sieci); gregai eval --zywo --k 3 = prawdziwe modele, pass@k
gregai restart | start | stop | logs [N] | open | version | help
```

### Komendy w czacie (1.32.0)

Wpisz `/` na początku wiadomości, a pojawi się lista (strzałki i Enter wybierają):

| komenda | co robi |
|---|---|
| `/pomoc` | lista komend |
| `/diagnoza` | internet warstwa po warstwie (WARP, tunel, DNS, wyszukiwarki, dostawcy AI) i co naprawić |
| `/sprawdz` | druga opinia INNEGO modelu o mojej ostatniej odpowiedzi + kontrola w kodzie |
| `/plan cel` | Namysł w trybie planu: kroki, zależności, ryzyka, jak poznać sukces, pierwszy krok na dziś |
| `/badaj temat` | Namysł w trybie badania: najpierw źródła i fakty, potem wnioski |
| `/recenzja tekst` | recenzja od najważniejszego problemu (bez tekstu: moja ostatnia odpowiedź) |
| `/lekcja [czego]` | szkic lekcji z rozmowy; zapis dopiero po Twoim „tak” |
| `/lekcje` | zapisane lekcje; `/lekcje usuń 2` |
| `/model` | kim jest GREGAI i z jakich modeli teraz korzysta |

Lekcje, które zatwierdzisz, GREGAI stosuje w każdej rozmowie (blok „Teraz”); widać je też
w Nadzorcy, w zakładce „Czego się nauczył”. Gdy go poprawisz („nie o to”, „jak to...”), sam
zaproponuje `/lekcja`.

Logi: `gregai logs` (albo `journalctl -u gregai -f`). Restart: `gregai restart`
albo przycisk w zakładce Debug czatu (tam też stan RAM, modeli, WARP,
żonglera, chmury, routera, ucznia, planera i SYSOP).

## Tryby mocy (wpisujesz w czacie)

Trzy słowa-przełączniki, wpisywane wprost w okienku rozmowy:

- **`freeram`** - zwalnia pamięć i oddaje moc maszynie: wyładowuje duży
  model i zatrzymuje Ollamę, żeby RAM i CPU były wolne (np. na trening);
  bez uprawnień do zatrzymania usługi mówi to wprost.
  GREGAI zostaje włączony i odpowiada dalej: polecenia i notatki działają jak
  zwykle, a pytanie, na które w notatkach nic nie ma, idzie etapami
  sieciowymi koryta (Claude, potem darmowa pula - o ile jest klucz, WARP i nie
  wyczerpano dziennego limitu PER DOSTAWCA). Lokalny model wraca
  dopiero po `fullon` (albo po restarcie komputera): zwykła wiadomość Ollamy
  nie uruchamia.
- **`fullon`** - pełna moc dla lokalnego AI: startuje Ollamę, wczytuje i
  **przypina** duży model w RAM, rozgrzewa, żeby odpowiadał od razu.
- **`gregaipanicmode`** (1.8.15) - awaryjna blokada: od razu cofa w zaporze
  reguły wpuszczające GREGAI z sieci domowej i wyłącza tryb LAN w `.env`
  (ten sam zapis co przełącznik na `/debug`), a POTEM wyłącza **cały
  komputer**, nie tylko usługę GREGAI. Działa też z telefonu/innego
  urządzenia, jeśli masz akurat włączony dostęp z sieci lokalnej - to
  właśnie dla takiej sytuacji powstał. Z powrotem (ponowne `GREGAI_LAN=1`)
  tylko z panelu `/debug` NA TYM komputerze, nie zdalnie. Działa z osobnym,
  wąskim wpisem sudo (patrz "Zabezpieczenia" wyżej) - jedynym miejscem, gdzie
  GREGAI SAM dotyka zapory, i tylko w stronę bardziej restrykcyjną.

Wszystkie trzy wpisujesz tylko Ty: model nigdy ich nie wybiera ani nie
proponuje (`user_only` w `agent/capabilities.py`). `freeram`/`fullon` są
odwracalne i **nie ruszają zabezpieczeń** (WARP, ufw, apparmor zostają),
sudo tylko na `ollama` (ta sama lista co reszta SYSOP); `fullon` nie
przestawia procesora na `performance` i tego nie podpowiada: na tym
procesorze taki tryb dodaje 1-2 W w bezczynności przez cały dzień, a
odpowiedzi przyspiesza o kilka procent. `gregaipanicmode` NIE jest
odwracalny z czatu (komputer jest wyłączony) i jest jedynym z trzech, który
dotyka zapory - zob. wyżej, dlaczego to świadomy, bezpieczny wyjątek. Kod:
`agent/tryby.py`.

## Zadania stałe (śledź coś w tle)

Polecenie w naturalnym języku, NIE sztywne słowo-przełącznik jak tryby
mocy wyżej: "śledź X i daj znać, gdy Y", "pilnuj ceny X, powiadom gdy
spadnie poniżej Y", "monitoruj, czy...". Rozpoznaje je model (plus wzorce
zapasowe, gdy Ollama akurat nie odpowiada) - w odróżnieniu od
`freeram`/`fullon`/`gregaipanicmode` to NIE jest `user_only`, bo wymaga
prawdziwego zrozumienia języka, nie jednego sztywnego słowa.

Jak działa (kod: `agent/standing.py`):
- Każde zadanie to jedna notatka w `data/standing_tasks` (korzeń grafu,
  jak `memory/`/`data/journal`) - dosłowna treść polecenia, bieżący stan,
  dziennik sprawdzeń i log alertów w jednym pliku, więc nic nie ginie
  między cyklami i jest przeszukiwalne jak każda inna notatka.
- Osobny wątek w tle (ten sam wzorzec co serce, `agent/heartbeat.py`)
  sprawdza co 5 minut, które zadania mają akurat swój interwał (minimum
  15 minut na zadanie - słaby i7-6600U i darmowe limity API).
- Research: najpierw Twój własny vault (`search_brain`, zero sieci),
  dopiero gdy stamtąd brak odpowiedzi - internet: precyzyjne notowanie
  (`market_quote`, p. CHANGELOG.md, 1.8.18, gdy zlecenie wprost wspomina
  ticker albo jedną z kilku popularnych nazw np. "bitcoin"), dopiero
  potem ogólne wyszukiwanie tekstowe (`research_web`, już samo przez
  WARP). Samo streszczenie świeżego wyniku - jednorazowe,
  bezstanowe - idzie do żonglera. Decyzję "czy to już alert" podejmuje
  ZAWSZE lokalna Ollama, nigdy żongler: jedyny krok, gdzie liczy się
  spójność oceny cykl po cyklu (ten sam model za każdym razem, bez
  losowej rotacji dostawców - dokładnie problem naprawiony w 1.8.16).
- Alert trafia do notatki od razu, a do Ciebie reaktywnie: Twoja
  najbliższa wiadomość (jakakolwiek) dostanie odpowiedź zaczynającą się
  od "🔔 ...". Zero nowych zależności, zero nowego ruchu wychodzącego
  poza to, co już istniało (`research_web`/żongler).
- "Co teraz śledzisz?" - lista aktywnych zadań. "Przestań śledzić X" -
  zatrzymuje (dopytuje, które, gdy jest ich kilka naraz i nie wiadomo, o
  które chodzi - nigdy nie zgaduje).

Bezpieczeństwo: narzędzie TYLKO informuje. Nigdy nie łączy się z żadnym
kontem, portfelem ani giełdą i nigdy nie wykonuje żadnej transakcji -
każdy alert to sygnał do Twojej własnej oceny, nie polecenie "kupuj/
sprzedawaj" wypowiedziane z fałszywą pewnością (GREGAI nie jest doradcą
finansowym). Sieć wyłącznie przez WARP (jak reszta GREGAI): gdy jest
zablokowana (ręcznie albo przez `gregaipanicmode`), zadania po prostu nie
wychodzą do internetu, bez dodatkowego kodu - `research_web` już to
zapewnia sam.

## Energooszczędność (laptop często na baterii)

Zasada: najwięcej pracy na wat, a w bezczynności prawie zero. Co z tego wynika
w kodzie (zmierzone na atrapie, liczby orientacyjne):

- **Serwer w bezczynności** budzi się raz na 5 s (pętla gniazda) i raz na 30 min
  (serce); nic nie odpytuje dysku ani modelu bez powodu. Indeks notatek jest
  sprawdzany tylko przy żądaniu, nie zegarem.
- **Interfejs**: pętla rysowania grafu śpi, gdy nic się nie rusza (pusta pętla
  animacji to ok. 4% rdzenia, a ozdobny impuls na krawędzi co 4 s kosztował
  kolejne 7%: teraz impuls raz na 30 s, poświata hubów bez rozmycia cienia).
  Znacznik modelu odpytywany co 30 s i tylko w widocznej karcie.
- **Duży model**: rozgrzewanie promptu po starcie (kilka minut dwóch rdzeni,
  ok. 1,5 Wh) tylko na zasilaczu; na baterii pierwsze pytanie samo rozgrzeje.
  Wytrenowany uczeń (1,5B) odpowiada za ok. 1/5 energii dużego modelu: trening
  ucznia to największa oszczędność na co dzień. `fullon` nie przestawia
  procesora na `performance`.
- **Skan sieci** (254 pingi, radio Wi-Fi poza oszczędzaniem): tylko na
  zasilaczu (`ConditionACPower=true` w jednostce), z 5-minutowym luzem timera,
  żeby budził się razem z innymi zadaniami. Poza domem nic nie wysyła.
- **Trening**: skrypty odmawiają startu na baterii (dni pracy procesora;
  `FORCE=1` wymusza). Ollama trzyma jeden model w RAM bez zużycia procesora.

Co możesz zrobić sam (poza GREGAI): `sudo apt install tlp` (albo
`powertop --auto-tune`) daje na tym laptopie ok. 1 W oszczędności na
zarządzaniu energią USB/PCIe/SATA; `vm.swappiness=10` ogranicza zbędne
zapisy na SSD przy przypiętym modelu.

## Po wgraniu nowej wersji: `aktualizuj.sh`

Gdy wgrywasz na laptop kolejną paczkę kodu (ten sam folder), po rozpakowaniu
uruchom (`install.sh` robi to samo i więcej, ale pełną instalację):

```bash
bash <folder projektu>/aktualizuj.sh
```

Skrypt jest idempotentny: wykrywa swoją ścieżkę, a jeśli folder zmienił
miejsce - wypisuje starą i **nową ścieżkę** oraz przepina usługi systemd na
nią (żeby nie wskazywały w próżnię). Na końcu restartuje `gregai`, więc nowy
kod (w tym tryby wyżej) jest od razu żywy. Ścieżkę z ostatniego uruchomienia
trzyma poza projektem (`~/.config/gregai/sciezka`), żeby przetrwała
nadpisanie folderu.

Gdy aktualizacja wypisze „pliki systemowe z poprzedniej wersji instalatora”
(np. przy przejściu na 1.32.4 lub nowszą: obowiązkowa zapora WARP), uruchom
raz `bash <folder projektu>/install.sh`. Bez tego usługa działa na starym
kształcie, a `gregai check` (kontrola 29) i `/diagnoza` pokażą zaporę jako błąd.

## Skąd GREGAI bierze dane

**Sieć domowa wymaga `ROUTER_HOST` = adres Twojej bramy** (domyślnie `192.168.8.1`,
fabryczny adres routerów Huawei). Jeśli Twoja brama to np. `192.168.1.1`
(`ip route | grep default`), wpisz `ROUTER_HOST=192.168.1.1` w `.env` PRZED
`install.sh` (albo przed `python3 agent/homenet.py --pin`); inaczej GREGAI uzna,
że nigdy nie jest w domu, i skan sieci nie ruszy.

Z folderu `notatki/` w folderze projektu (lista korzeni w `agent/data.py`,
jedyne miejsce, które wie, gdzie są Twoje dane), plus cztery foldery, które
GREGAI prowadzi sam: `data/wiki_cache` (bank wiedzy z Wikipedii),
`data/journal` (dziennik), `memory/` (to, co kazałeś zapamiętać) i
`data/standing_tasks` (zadania stałe, p. "Zadania stałe" wyżej).

Co GREGAI czyta z tych folderów: pliki `.md`, `.txt` i `.pdf` (PDF tylko do
odczytu), do 2 MB każdy (zapis większej notatki z interfejsu jest odrzucany z
komunikatem, bo po zapisie by zniknęła z grafu); ukryte katalogi (`.git`, `.obsidian`...) i
`node_modules` są pomijane, tak samo dowiązania symboliczne prowadzące poza
folder. Liczbę pominiętych plików widać w pasku u góry po wczytaniu grafu.
Zmiany zrobione poza interfejsem (inny edytor, menedżer plików) GREGAI
zauważa w ciągu kilku sekund; zapis z interfejsu odmawia nadpisania notatki,
która w międzyczasie zmieniła się na dysku. Dwie notatki nie mogą mieć tego
samego tytułu (wielkość liter i odstępy nie mają znaczenia): druga dostaje
komunikat o konflikcie, a zmiana tytułu przepisuje linki `[[...]]` tylko tam,
gdzie wskazywały właśnie tę notatkę. Zapis do notatki będącej dowiązaniem
symbolicznym zachowuje dowiązanie. Zapis z interfejsu działa tylko
dla plików w UTF-8 (inne kodowanie, np. Windows-1250, jest tylko do odczytu,
żeby nie zgubić polskich znaków). Kopie zapasowe (`backups/`, polecenie „zrób
kopię zapasową") obejmują notatki, pamięć, dane i kod GREGAI; zostaje 10 ostatnich.

Projekt nazywał się wcześniej SIECAI, a jego rozmówca WEBAI (do 2026-10-12;
usługa `webai`, modele `webai-*`). Stare nazwy kluczy w `.env` (`SIECAI_...`)
są nadal rozumiane, a `install.sh` zmienia je na `GREGAI_...`, usuwa wpisy
starych modeli `webai-*` i odsuwa starą usługę `webai`, jeśli taka jest.

## Struktura projektu

```
GREGAI/
├── agent/
│   ├── main.py          serwer HTTP + API (graf, notatki, czat, status, debug)
│   ├── diagnoza.py      diagnoza internetu warstwa po warstwie (/diagnoza, gregai diagnoza, Nadzorca)
│   ├── bramka.py        bramka odpowiedzi: kontrola tekstu modelu w kodzie przed wysłaniem do Ciebie
│   ├── komendy.py       komendy ukośnikowe w czacie (/pomoc, /plan, /badaj, /recenzja, /sprawdz, /lekcja...)
│   ├── lekcje.py        lekcje z rozmów, zapisywane po Twoim „tak”, stosowane w każdej rozmowie
│   ├── ewaluacja.py     testy regresji gregai eval (szybkie bez sieci, --zywo z pass@k)
│   ├── pogoda.py        pogoda (Open-Meteo, bez klucza, przez WARP) i słońce liczone w kodzie (wschód, zachód, dzień + noc = 24 h)
│   ├── tryby.py         tryby: freeram (zwolnij RAM) / fullon (pełna moc AI) / gregaipanicmode (zablokuj sieć, wyłącz komputer)
│   ├── koryto.py        KORYTO: jedna kolejność etapów (Claude -> darmowe -> lokalnie) dla całego myślenia
│   ├── router.py        router -> korytem: etapy sieciowe (juggler) i lokalny (uczeń/duży model); limity czasu
│   ├── juggler.py       wszyscy dostawcy sieciowi: Claude (etap anthropic) + pula darmowa (Groq/Gemini/OpenRouter/HF/Cloudflare), senior+juniorzy
│   ├── agentloop.py     zadania wielokrokowe (KROK/GOTOWE/PYTANIE)
│   ├── capabilities.py  JEDYNE miejsce rejestracji narzędzia
│   ├── tools.py         narzędzia (notatki, Wikipedia, wyszukiwanie, kursy giełdowe, plan dnia...)
│   ├── sysop.py         warstwa systemowa z poziomami i blokadami
│   ├── netguard.py      JEDYNA droga do internetu: tylko przez WARP, tylko https
│   ├── siec.py          skan sieci domowej (tylko odczyt, tylko w domu; timer co 15 min)
│   ├── homenet.py       rozpoznanie sieci domowej (brama + jej MAC, zapamiętany świadomie)
│   ├── router_bridge.py odczyt stanu routera Huawei HiLink (tylko gettery)
│   ├── vault.py         notatki -> przeszukiwalny graf
│   ├── data.py          JEDYNY plik, który wie, gdzie są prawdziwe dane
│   ├── memory.py        zapisuje wyłącznie do memory/ (to korzeń grafu, typ "Pamięć")
│   ├── standing.py      zadania stałe: "śledź X i daj znać gdy Y" w tle (data/standing_tasks)
│   ├── awareness.py     blok „Teraz": zegar, zapamiętane fakty, zadania w tle - dokładany do promptu przy każdej wiadomości
│   ├── namysl.py        Namysł: sześć faz myślenia (rozpoznanie, zbieranie, szkic, krytyka, poprawa, sprawdzenie) z narracją na żywo
│   ├── analiza.py       czytanie dokumentów (txt/md/pdf/docx/xlsx/csv/kod) i rozumienie ich częściami
│   ├── sources.py       Źródła: foldery i wgrane pliki INDYWIDUALNE dla każdej rozmowy (data/sources.json, data/wgrane/<rozmowa>/)
│   ├── rozmowa.py       pamięć rozmowy: streszczenie wątku co 8 tur (data/rozmowy/<rozmowa>.json), „gdzie skończyliśmy” po przerwie
│   ├── fsutil.py        atomowy zapis plików (plik tymczasowy + podmiana)
│   ├── persona.py, heartbeat.py, learning.py, trace.py, sysinfo.py, env_loader.py
│   └── prompt.md        osobowość i zasady GREGAI
├── ui/                  index.html (Rozmowa / Węzły / Nadzorca), app.js, graph.js, styles.css (tokeny, jeden :root) + sistem.css (system projektowy z dawnym motywem) + kadr.css (wygląd „Kadr” 1.31.0: kolory ważności, plansza z napisami), fonty/ (Oxanium i Barlow, lokalnie, licencja OFL), debug.js, debug.css; debug.html = strona zapasowa /debug
├── GREGAI.sha256        sumy kontrolne paczki (tylko w ZIP-ie; sha256sum -c po rozpakowaniu)
├── notatki/wiedza/      wbudowana obronna baza wiedzy (cyberbezpieczeństwo, Linux, programowanie, myślenie, biznes, technika; 60 notatek)
├── notatki/szkola/      wbudowana wiedza szkolna (7 przedmiotów, matura/ósmoklasista)
├── training/            samo-trening: router, planer, uczeń (osobny venv)
├── requirements.txt     jedyna zależność spoza stdlib (most do routera, opcjonalny)
├── .gitignore           sekrety, dane i modele zostają poza repozytorium
├── gregai               JEDNO polecenie: status, check, update, install, start/stop/restart, logs, open
├── install.sh           instalacja jedną komendą z dowolnego folderu (9 kroków)
├── aktualizuj.sh        po wgraniu nowego kodu; wykrywa przeniesienie folderu
├── check.sh             kontrole po instalacji (liczbę pokazuje sam skrypt)
├── VERSION              wersja (widoczna w /debug)
├── ROADMAP_1.0.md       decyzje 1.0 i bramki, które potwierdza dopiero laptop
├── CHANGELOG.md         historia zmian, każde wydanie od 1.1.0
├── .env.example         szablon konfiguracji (install.sh robi z niego .env)
├── INSTALACJA_UBUNTU_26_04.md  instalacja od zera, krok po kroku
├── CLAUDE.md            kim jest użytkownik (prywatny notatnik, poza gitem)
└── .env                 klucze i konfiguracja (NIGDY nie udostępniaj; nie ma go w paczce)
```

Katalogi z danymi (nie są częścią kodu, przychodzą ze starego laptopa):
`notatki/`, `memory/`, `data/`.

Wyjątek: dwie wbudowane bazy wiedzy w paczce (GREGAI przeszukuje je jak każdą
notatkę przez `search_brain` i graf; Twoje własne notatki ze starego laptopa
dokładają się obok, nie nadpisują ich):

- `notatki/wiedza/` - **obronne** cyberbezpieczeństwo i komendy Linuksa
  (16 notatek typu `Wiedza`, węzeł główny "Cyberbezpieczeństwo"; od 1.21.0 obok
  nich 44 notatki o programowaniu, myśleniu, biznesie i technice, węzły główne:
  "Programowanie", "Sztuka myślenia", "Biznes i projekty", "Nauka i technika"): podstawy
  bezpieczeństwa, utwardzanie systemu, sieci, kryptografia, komendy. Jak się
  bronić, wykrywać i utwardzać, nie jak atakować.
- `notatki/szkola/` - **wiedza szkolna** pod egzamin ósmoklasisty i maturę
  (43 notatki typu `Nauka`, węzeł główny "Wiedza szkolna"): matematyka,
  fizyka, chemia, biologia, geografia, historia, język polski - każdy
  przedmiot jako węzeł z notatkami tematycznymi.

Razem 59 połączonych notatek: jeden spójny graf, dwa kolorowe klastry.

## Koszty

- Modele lokalne (Ollama, router, planer, uczeń): **0 zł**.
- Cloudflare WARP: **0 zł** (darmowy klient).
- Wyszukiwanie (DuckDuckGo) i Wikipedia: **0 zł**.
- Darmowa pula (Groq, Google Gemini, OpenRouter, Cloudflare Workers AI): **0 zł** -
  darmowy poziom API każdego, z dziennym limitem per dostawca
  (`GROQ_DAILY_LIMIT` itd.). Od 1.17.0 to drugi etap koryta (rezerwa po
  Claude). Piąty, Hugging Face, ma inny rodzaj darmowego
  poziomu - nie limit zapytań/dzień, tylko niewielki kredyt w dolarach
  miesięcznie (`HUGGINGFACE_DAILY_LIMIT` to tylko ostrożne przybliżenie
  tego w liczbie zapytań, patrz `.env.example`) - w praktyce dalej 0 zł
  przy lekkim użyciu, ale inaczej liczony niż reszta puli.
- Claude (Anthropic): płatny za token, od 1.17.0 GŁÓWNY dostawca (pierwszy
  etap koryta), domyślnie Haiku (`claude-haiku-5-5` - najtańszy z rodziny) z
  dziennym limitem `CLOUD_DAILY_LIMIT=300` zapytań: przy krótkich rozmowach to
  rząd kilkudziesięciu groszy dziennie, rachunek rośnie z długością odpowiedzi
  i z Namysłem (kilka zapytań na jedną wiadomość). Bez `ANTHROPIC_API_KEY` w
  `.env` nie kosztuje nic; bez żadnego klucza (także darmowej puli) wszystko
  działa lokalnie.

## Wsparcie

GREGAI jest darmowy i nie wymaga żadnej płatności. Jeśli jest dla Ciebie
przydatny i chcesz postawić autorowi kawę, oto adresy kryptowalutowe
(żadnych zobowiązań, czysto dobrowolnie):

- **BTC:** `bc1qlreffajd4pax763pr7wamkket0je0k7xkxuhy6`
- **ETH:** `0x7AC87FD231D4eD98155a0Fff75AE5b19E32dbcF9`
- **SOL:** `ChyftaE4woKxPR5zwHidELteiUJcLwSjKSYBTs7qdsiJ`

## Znane ograniczenia

- Na i7-6600U duży model lokalny (3B) odpowiada w rzędzie kilkudziesięciu sekund na ciepło, a po
  każdym starcie najpierw kilka minut się rozgrzewa w tle (przetwarza
  prompt systemowy; stan w `/debug`). Długie odpowiedzi nie są przerywane
  przez przeglądarkę (czat dopytuje serwer co 240 s). Szczegóły i
  szacunkowe liczby (nie pomiary): `INSTALACJA_UBUNTU_26_04.md`, Krok 10. Na co dzień
  pracują małe, wytrenowane modele i żongler (pula darmowa).
- Trening na CPU trwa długo: według szacunku z liczby tokenów router ok. 12-26 h, planer 5-9 h, uczeń 20-40 h (razem 2-3 doby; to obliczenie, nie pomiar, `finetune.py` wypisuje prawdziwy czas po pierwszych krokach). Wszystkie modele są opcjonalne.
- **Głos (Piper/Whisper) usunięty z projektu na stałe** (decyzja 2026-10-12):
  GREGAI jest tekstowy, w kodzie i konfiguracji nie ma żadnych kluczy głosu.
- Serwer odcina klienta, który nie dośle żądania w ~20 s (ochrona przed
  powolnym połączeniem, które zajmowałoby miejsca); zwykła przeglądarka na
  localhost nigdy tego nie odczuje.
- Odczyt `.pdf` w `vault.py` jest minimalny (bez zależności): proste,
  nieszyfrowane PDF-y z tekstem w operatorach `Tj`/`TJ` (skany i PDF-y z
  własnymi czcionkami mogą wyjść puste).
- Poczta i kalendarz nie są podłączone (świadoma decyzja): `brief_me` składa
  podsumowanie z notatek i alertów sieci domowej i mówi to wprost.
