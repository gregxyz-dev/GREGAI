# Debugowanie i testowanie
type: Wiedza

Część [[Programowanie]]. Debugowanie to szukanie przyczyny, nie zgadywanie poprawki. Testy sprawiają, że błędy wychodzą wcześnie i że poprawka nie psuje innych rzeczy. Narzędzia: [[Python: narzędzia]], historia zmian: [[Git: codzienna praca i ratowanie sytuacji]].

## Metoda naukowa

1. **Odtwórz błąd** powtarzalnie. Bez tego nie wiesz, czy naprawiłeś. Zapisz kroki i dane wejściowe.
2. **Przeczytaj komunikat** dokładnie. W tracebacku Pythona ostatnia linia to typ i opis błędu, a linie powyżej to stos wywołań (od najstarszego do najnowszego). Szukaj pierwszej linii z Twojego kodu.
3. **Postaw hipotezę** ("zmienna jest `None`, bo funkcja zwraca przed końcem").
4. **Sprawdź ją** jednym eksperymentem: `print`, debugger, test. Zmieniaj jedną rzecz naraz.
5. **Napraw przyczynę**, nie objaw. Zapytaj "dlaczego" kilka razy.
6. **Dodaj test**, który wcześniej padał, a teraz przechodzi (zapobiega powrotowi błędu).
7. Jeśli utknąłeś: wyjaśnij problem na głos (metoda gumowej kaczki) albo napisz pytanie; często odpowiedź przychodzi w trakcie.

Zasada: błąd jest prawie zawsze w Twoim kodzie lub założeniach, rzadziej w bibliotece czy interpreterze. Najpierw sprawdź swoje założenia (typy, zawartość zmiennych, wersje, bieżący katalog).

## Narzędzia debugowania w Pythonie

- `print(f"{x=}")` (3.8+) wypisuje nazwę i wartość. Użyj `repr`, by zobaczyć ukryte znaki: `print(repr(tekst))`.
- Debugger: wstaw `breakpoint()` (3.7+), uruchom skrypt. W `pdb`: `n` następna linia, `s` wejdź do funkcji, `c` kontynuuj, `p wyrazenie` wypisz, `l` pokaż kod, `bt` stos, `q` wyjdź.
- Po awarii: `python3 -m pdb skrypt.py` zatrzymuje się w miejscu wyjątku (post-mortem).
- `python3 -X dev skrypt.py` włącza dodatkowe ostrzeżenia trybu deweloperskiego; `python3 -W error` zamienia ostrzeżenia w błędy.
- `traceback.print_exc()` i `logging.exception("...")` w `except` zachowują pełny ślad.
- `type(x)`, `dir(x)`, `help(x)`, `len(x)` rozstrzygają wiele wątpliwości.

## Minimalny przykład

Gdy błąd siedzi w dużym projekcie, zredukuj go:

1. Skopiuj problem do osobnego pliku.
2. Usuwaj wszystko, co nie jest potrzebne, po każdym kroku sprawdzając, czy błąd nadal występuje.
3. Zostaje kilkanaście linii: często w tym momencie przyczyna staje się oczywista.
4. Ten przykład jest też idealny do zgłoszenia błędu lub pytania (zawiera wersję Pythona/biblioteki, dane, oczekiwany i faktyczny wynik).

## Bisekcja

Dziel przestrzeń poszukiwań na pół, aż zostanie jedna przyczyna.

- **Po kodzie:** zakomentuj połowę, sprawdź, czy błąd jest w drugiej połowie. Albo wstaw kontrolny `print` w środku przepływu: dane poprawne przed czy po?
- **Po historii (git):** `git bisect` znajduje commit, który wprowadził błąd w około log2(n) krokach.

```bash
git bisect start
git bisect bad                 # obecny stan zły
git bisect good <hash_lub_tag> # stary stan dobry
# po każdym przełączeniu uruchom test, wpisz: git bisect good | bad
git bisect reset
```

Automatycznie: `git bisect run ./test.sh` (skrypt kończy się kodem 0 dla dobrego, 1 do 127 poza 125 dla złego).
- **Po danych:** znajdź najmniejszy wiersz/plik wejściowy, który wywołuje błąd.
- **Po konfiguracji:** czy działa na świeżym venv, na innej maszynie, bez zmiennych środowiskowych?

## Logi

- Poziomy: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. W produkcji `INFO`, przy szukaniu błędu `DEBUG`.
- Loguj zdarzenia i kontekst (identyfikator, parametry), nigdy sekretów (hasła, tokeny, klucze API).
- Usługa pod systemd: `journalctl -u usluga -f` (na żywo), `-n 100`, `--since "1 hour ago"`, `-p err`. Patrz [[Komendy Linuksa: system i procesy]].
- Przeszukiwanie: `grep -n "ERROR" plik.log`, `tail -f plik.log`.
- Przeglądarka: F12, zakładka Console (błędy JS), Network (żądania, kody, czasy, ciała odpowiedzi), Application (localStorage). Patrz [[Web: HTTP, API i podstawy frontendu]].
- Duży ruch logów: rotacja (`logging.handlers.RotatingFileHandler` albo `logrotate`), żeby nie zapełnić dysku (`df -h`).

## Testy jednostkowe

Test jednostkowy sprawdza małą część kodu (funkcję) w izolacji, szybko i deterministycznie.

```python
# kalkulator.py
def dziel(a, b):
    if b == 0:
        raise ValueError("dzielenie przez zero")
    return a / b

# test_kalkulator.py
import pytest
from kalkulator import dziel

def test_dziel_zwykle():
    assert dziel(6, 3) == 2

def test_dziel_przez_zero():
    with pytest.raises(ValueError):
        dziel(1, 0)

@pytest.mark.parametrize("a,b,wynik", [(4, 2, 2), (9, 3, 3)])
def test_tabela(a, b, wynik):
    assert dziel(a, b) == wynik
```

- Uruchom: `pytest -q`. Bez zewnętrznych bibliotek: `python3 -m unittest`.
- Wzorzec: przygotuj (arrange), wykonaj (act), sprawdź (assert).
- Testuj przypadki brzegowe: puste dane, zero, `None`, jeden element, duże wartości, zły typ, polskie znaki, białe znaki.
- Jeden test, jedna myśl; nazwa opisuje zachowanie (`test_dziel_przez_zero`).
- Testy mają być niezależne od kolejności i od stanu poprzednich. Pliki twórz w `tmp_path`.
- Wyniki zmiennoprzecinkowe: `pytest.approx(0.3)`.
- Zewnętrzne zależności (sieć, czas, losowość) podmieniaj atrapami (`unittest.mock.patch`) albo przekazuj jako parametry; testy sieciowe są wolne i niestabilne.
- Test regresji: dla każdego naprawionego błędu dodaj test.
- Piramida: dużo szybkich testów jednostkowych, mniej integracyjnych (kilka modułów, np. prawdziwy SQLite w pamięci: `sqlite3.connect(":memory:")`), garstka end-to-end.
- Pokrycie kodu (`pytest --cov`, wymaga pakietu `pytest-cov`) pokazuje, czego nie uruchomiono; wysoki odsetek nie gwarantuje dobrych testów.
- TDD (test najpierw) pomaga przy logice z jasną specyfikacją; nie jest obowiązkiem.

## Typowe źródła błędów

- Zła wersja interpretera lub biblioteki, nie ta aktywna wirtualna (`which python`, `pip list`).
- Zły katalog roboczy i ścieżki względne (użyj `Path(__file__).parent`).
- Mutowalne argumenty domyślne, modyfikacja listy w trakcie iteracji ([[Python: podstawy i idiomy]]).
- Kodowanie znaków, zakończenia linii, ukryte białe znaki.
- Wyścigi i stan współdzielony przy wątkach.
- Pamięć podręczna: przeglądarka pokazuje starą wersję (twarde odświeżenie Ctrl+Shift+R).
- Niezapisany plik lub nieuruchomiony ponownie serwer.
- Założenie, że dane zewnętrzne mają dany format.

## Czego unikać

- Zmieniania wielu rzeczy na raz.
- "Naprawiania" przez `try/except: pass`.
- Debugowania z pamięci zamiast z danych: sprawdź faktyczne wartości.
- Przerwy: po godzinie bez postępu odpocznij lub zredukuj problem do minimalnego przykładu.
