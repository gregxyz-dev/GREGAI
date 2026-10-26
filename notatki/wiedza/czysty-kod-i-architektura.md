# Czysty kod i architektura
type: Wiedza

Część [[Programowanie]]. Kod czyta się znacznie częściej, niż pisze, więc priorytetem jest czytelność. Ale czysty kod nie oznacza więcej abstrakcji: najczęstszy błąd to komplikowanie rzeczy prostych. Przykłady w Pythonie ([[Python: podstawy i idiomy]]), zasady są ogólne.

## Nazewnictwo

- Nazwa mówi, co to jest lub co robi, bez komentarza: `liczba_prob`, `pobierz_uzytkownika`, `czy_wazny`.
- Funkcje: czasowniki (`wczytaj_konfig`), wartości logiczne: `czy_...`, `jest_...`, `ma_...` (`is_`, `has_` w angielskim kodzie).
- Unikaj skrótów rozumianych tylko przez Ciebie (`tmp2`, `dat`, `x1`), poza krótkimi indeksami w małej pętli (`i`, `k`, `v`).
- Jedna konwencja w całym projekcie: `snake_case` w Pythonie, `camelCase` w JS, `CamelCase` dla klas, `STALE` dla stałych.
- Jeden język w identyfikatorach (polski albo angielski); mieszanie męczy. Komentarze i teksty dla użytkownika mogą być po polsku.
- Nie nazywaj po typie (`lista_danych`), tylko po znaczeniu (`zamowienia`).
- Jeśli trudno nazwać funkcję, robi zbyt wiele rzeczy.

## Małe funkcje

- Funkcja robi jedną rzecz na jednym poziomie abstrakcji. Wskaźnik: da się opisać jednym zdaniem bez "i".
- Krótka (zwykle kilkanaście do kilkudziesięciu linii), mało parametrów (powyżej około 4 rozważ obiekt lub `dataclass`).
- Wczesny powrót zamiast głębokiego zagnieżdżenia:

```python
def przetworz(zadanie):
    if zadanie is None:
        return None
    if not zadanie.gotowe:
        return None
    return zadanie.wynik * 2
```

- Unikaj parametrów-flag zmieniających zachowanie (`zapisz(x, tryb=True)`); rozdziel na dwie funkcje.
- Preferuj czyste funkcje (te same wejście daje to samo wyjście, bez efektów ubocznych): łatwo je testować ([[Debugowanie i testowanie]]).
- Nie modyfikuj argumentów po cichu; zwracaj nową wartość albo nazwij funkcję tak, by było jasne (`sortuj_w_miejscu`).
- Stałe zamiast "magicznych liczb": `MAX_PROB = 3`.

## Komentarze

- Komentarz tłumaczy dlaczego (decyzja, obejście błędu, nieoczywiste ograniczenie), nie co (to mówi kod).
- Nieaktualny komentarz jest gorszy niż brak. Martwy kod usuń; historię ma git ([[Git: codzienna praca i ratowanie sytuacji]]).
- Docstring dla funkcji publicznych: co robi, parametry, wyjątki, jednym lub dwoma zdaniami.

## Separacja odpowiedzialności

Rozdziel, co się zmienia z różnych powodów:

- **Logika** (reguły, obliczenia) osobno od **wejścia/wyjścia** (pliki, sieć, baza, interfejs). Logika jako czyste funkcje, I/O na brzegach. Dzięki temu logikę testujesz bez sieci i dysku.
- **Konfiguracja** (ścieżki, klucze, adresy) w jednym miejscu, wczytywana ze zmiennych środowiskowych lub pliku, nie rozsiana po kodzie. Sekrety poza repozytorium ([[Uwierzytelnianie i sekrety]]).
- **Dane** (struktura) osobno od **prezentacji** (HTML, tekst).
- Warstwy dla typowej aplikacji: interfejs (HTTP/CLI) -> logika -> dostęp do danych ([[SQL i bazy danych]]). Zależności płyną w jedną stronę; warstwa niższa nie wie o wyższej.
- Moduły: plik ma jedną spójną rolę; gdy plik przekracza kilkaset linii i robi trzy rzeczy, podziel. Unikaj cyklicznych importów.
- Granice systemu (wejście użytkownika, odpowiedzi API) waliduj; wewnątrz ufaj własnym typom ([[Bezpieczeństwo aplikacji webowych]]).

## Obsługa błędów

- Błędy zgłaszaj jawnie (wyjątek), nie zwracaj magicznych wartości (`-1`, pusty napis), chyba że to udokumentowany kontrakt.
- Obsługuj błąd tam, gdzie możesz coś sensownego z nim zrobić; wyżej tylko loguj i pokaż komunikat użytkownikowi.
- Komunikaty zawierają kontekst (jaki plik, jaka wartość), ale bez sekretów.
- Nie połykaj wyjątków (`except: pass`).

## Powtórzenia i DRY: kiedy NIE abstrahować

- DRY (nie powtarzaj się) dotyczy **wiedzy**, nie przypadkowo podobnych linii. Dwa fragmenty podobne dziś, a zmieniające się z różnych powodów, powinny pozostać osobne.
- **Reguła trzech:** skopiuj raz, przy trzecim wystąpieniu wydziel funkcję. Wtedy znasz już prawdziwy wzorzec. Zbyt wczesna abstrakcja zwykle jest źle dopasowana i trudniejsza do usunięcia niż kopia.
- Nie dodawaj "na zapas": klas bazowych, fabryk, wtyczek, parametrów konfiguracyjnych dla wymagań, których nie ma (YAGNI, nie będziesz tego potrzebować).
- Niepotrzebne wzorce: klasa z jedną metodą zwykle jest funkcją; interfejs z jedną implementacją zwykle nie jest potrzebny; warstwa opakowująca bibliotekę, której nigdy nie zmienisz, to koszt bez korzyści.
- Sygnały nadmiernej abstrakcji: trzeba otworzyć pięć plików, żeby zrozumieć jedną czynność; nazwy typu `Manager`, `Handler`, `Helper`, `Util` bez treści; kod ogólny, używany w jednym miejscu.
- Prostota: najprostsze rozwiązanie, które działa i jest zrozumiałe za pół roku. Plik JSON zamiast bazy, funkcja zamiast klasy, biblioteka standardowa zamiast frameworka, dopóki to wystarcza.
- Abstrahuj, gdy: ta sama zmiana wymaga edycji wielu miejsc, logika jest rzeczywiście wspólna, albo musisz coś podmienić w testach.

## Refaktoryzacja

- Zmieniasz strukturę, nie zachowanie. Najpierw testy (choćby kilka sprawdzających obecne działanie), potem małe kroki, po każdym uruchom testy i zrób commit.
- Nie mieszaj refaktoryzacji z nową funkcją w jednym commicie.
- Przydatne ruchy: wydziel funkcję, zmień nazwę, usuń martwy kod, zastąp zagnieżdżone `if` wczesnymi powrotami, zastąp słownik o stałych polach `dataclass`.
- Format i styl: automaty (`ruff`, `black` dla Pythona; narzędzia zewnętrzne, instalowane przez `pip`) kończą spory o spacje. Sprawdzanie błędów statycznie: `ruff check`, `pyflakes`, `mypy` ([[Python: narzędzia]]).

## Struktura małego projektu

```
projekt/
  README.md
  requirements.txt
  .gitignore
  app/
    __init__.py
    logika.py        # czyste funkcje
    dane.py          # dostęp do pliku/bazy
    api.py           # warstwa HTTP
  tests/
    test_logika.py
  main.py            # punkt startowy
```

- Cały stan trwały w jednym katalogu danych (łatwa kopia zapasowa), kod osobno.
- README z dwoma akapitami: co to jest i jak uruchomić.
- Zależności zapisane, wersja Pythona podana.
