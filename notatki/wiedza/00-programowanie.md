# Programowanie
type: Wiedza

Węzeł-rozdzielacz wiedzy o programowaniu w GREGAI. Nacisk jest praktyczny: Python (stdlib), vanilla JavaScript, Bash i Git na Ubuntu, czyli to, czego używa się przy własnych projektach (asystent GREGAI, strony, boty, generatory). Notatki podają sprawdzone fakty i zaznaczają, gdy coś zależy od wersji.

## Notatki

- [[Python: podstawy i idiomy]]: typy, kolekcje, comprehensions, funkcje, wyjątki, klasy, `with`, pułapki (mutowalne argumenty domyślne).
- [[Python: narzędzia]]: `venv`, `pip`, `pytest`, typowanie, `pathlib`, `subprocess`, `asyncio` i wątki.
- [[Bash: skrypty]]: `set -euo pipefail`, cytowanie, pętle, `trap`, pułapki.
- [[Git: codzienna praca i ratowanie sytuacji]]: commit, gałęzie, `rebase` kontra `merge`, `reflog`, cofanie zmian.
- [[Algorytmy i struktury danych]]: złożoność, kiedy `list`, `dict`, `set`, kolejka, sortowanie, wyszukiwanie.
- [[SQL i bazy danych]]: `SELECT`, `JOIN`, indeksy, transakcje, SQLite w Pythonie.
- [[Web: HTTP, API i podstawy frontendu]]: HTTP, JSON, HTML/CSS/JS, CORS, tokeny.
- [[Debugowanie i testowanie]]: metoda naukowa, bisekcja, minimalny przykład, logi, testy jednostkowe.
- [[Czysty kod i architektura]]: nazewnictwo, małe funkcje, separacja, kiedy NIE abstrahować.
- [[Regex w praktyce]]: składnia, grupy, pułapki, moduł `re`.

## Jak z tego korzystać

1. Zaczynasz projekt: [[Python: narzędzia]] (środowisko wirtualne), od razu `git init` ([[Git: codzienna praca i ratowanie sytuacji]]).
2. Coś nie działa: [[Debugowanie i testowanie]], zanim zaczniesz zgadywać.
3. Kod rośnie i się plącze: [[Czysty kod i architektura]].
4. Dane mają przeżyć restart programu: plik JSON dla małych rzeczy, SQLite dla większych ([[SQL i bazy danych]]).
5. Skrypt do automatyzacji na Ubuntu: [[Bash: skrypty]], a gdy robi się skomplikowany, przepisz go w Pythonie.

## Zasady, które się powtarzają

- Najpierw działa, potem czysto, potem szybko. Szybkość optymalizuj dopiero po pomiarze (`time`, `cProfile`, `timeit`).
- Mała zmiana, uruchom, commit. Duże kroki trudno debugować.
- Nie ufaj danym z zewnątrz (użytkownik, sieć, pliki): waliduj, ograniczaj, nie wykonuj ich jako kodu. Patrz [[Bezpieczeństwo aplikacji webowych]].
- Sekrety (klucze API, tokeny) nigdy do repozytorium; trzymaj je w zmiennych środowiskowych lub pliku poza gitem (`.gitignore`). Patrz [[Uwierzytelnianie i sekrety]].
- Czytaj komunikat błędu od końca: ostatnia linia mówi co, linie powyżej gdzie.
- Dokumentacja oficjalna (`python3 -m pydoc`, `help(obiekt)`, `man`, `git help polecenie`) jest zawsze pod ręką offline.

## Szybkie pomoce w terminalu

- `python3 -c "print(2**100)"` - jednolinijkowiec.
- `python3 -m http.server 8000` - szybki serwer plików statycznych z bieżącego katalogu (tylko do testów lokalnych).
- `python3 -m json.tool plik.json` - ładne formatowanie i walidacja JSON.
- `python3 -m venv .venv && source .venv/bin/activate` - nowe środowisko.
- `python3 -m pytest -x -q` - testy, stop na pierwszym błędzie.
- `git status -sb` - krótki stan repozytorium.
- `shellcheck skrypt.sh` - statyczna analiza Basha (pakiet `shellcheck`, trzeba doinstalować).

## Stos typowy dla projektów użytkownika

- Backend: Python, często sama biblioteka standardowa (`http.server`, `sqlite3`, `json`, `urllib`), czasem Flask (w text-story-generator).
- Frontend: vanilla JS, bez frameworków, fetch do własnego API.
- Uruchamianie na Ubuntu: usługa `systemd`, logi przez `journalctl -u usluga` (patrz [[Komendy Linuksa: system i procesy]]).
- Sprzęt bywa skromny (starszy laptop bez GPU), więc liczy się oszczędność pamięci i CPU: unikaj ciężkich zależności, gdy wystarczy stdlib.

## Kolejność nauki, gdy czegoś brakuje

1. Python podstawy, następnie pliki i JSON.
2. Git na poziomie commit, branch, merge.
3. HTTP i proste API.
4. Testy i debugowanie.
5. SQL (SQLite).
6. Dopiero potem asynchroniczność, wzorce projektowe i optymalizacja.
