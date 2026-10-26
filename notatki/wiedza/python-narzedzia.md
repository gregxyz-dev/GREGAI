# Python: narzędzia
type: Wiedza

Część [[Programowanie]]. Poprzednia: [[Python: podstawy i idiomy]]. Ekosystem wokół języka: środowiska, instalacja pakietów, testy, typy, pliki, procesy, współbieżność. Na Ubuntu używaj `python3` (polecenie `python` może nie istnieć).

## Środowisko wirtualne (venv)

```bash
python3 -m venv .venv
source .venv/bin/activate     # prompt dostaje prefiks (.venv)
pip install requests
pip freeze > requirements.txt
deactivate
```

- Na Ubuntu może brakować modułu: `sudo apt install python3-venv`.
- Nowsze Ubuntu (23.04+ / Debian 12) blokuje `pip install` do systemowego Pythona (błąd "externally-managed-environment", PEP 668). Rozwiązanie: venv albo `pipx` dla aplikacji CLI. Nie używaj `--break-system-packages`, chyba że wiesz po co.
- `.venv/` dodaj do `.gitignore`. Nie commituj środowiska, commituj `requirements.txt`.
- Odtworzenie: `pip install -r requirements.txt`.
- Bez aktywacji: `.venv/bin/python skrypt.py`. To też działa w jednostce `systemd` (`ExecStart=/sciezka/.venv/bin/python /sciezka/main.py`).

## pip

- `pip install pakiet==1.2.3`, `pip install -U pakiet`, `pip uninstall pakiet`.
- `pip list`, `pip show pakiet`, `pip check` (konflikty zależności).
- Ogranicz zależności: biblioteka standardowa często wystarcza (`urllib.request`, `json`, `sqlite3`, `argparse`, `pathlib`, `csv`, `http.server`, `logging`).

## Testy: pytest

```bash
pip install pytest
pytest                # wykrywa test_*.py i funkcje test_*
pytest -x -q          # stop po pierwszym błędzie, krótko
pytest -k nazwa       # tylko pasujące nazwy
pytest tests/test_a.py::test_b
```

```python
def test_dodawanie():
    assert 1 + 1 == 2

import pytest
def test_blad():
    with pytest.raises(ValueError):
        int("x")
```

- `tmp_path` to wbudowany fixture z katalogiem tymczasowym na plik testowy.
- Fixture: `@pytest.fixture`, parametryzacja: `@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])`.
- Wbudowana alternatywa bez instalacji: `python3 -m unittest`. Szczegóły w [[Debugowanie i testowanie]].

## Typowanie

```python
def srednia(liczby: list[float]) -> float:
    return sum(liczby) / len(liczby)

def znajdz(id: int) -> dict | None:   # X | Y od 3.10
    ...
```

- Typy nie są sprawdzane w czasie działania; służą edytorowi i narzędziom (`mypy`, `pyright`).
- `list[int]`, `dict[str, int]` bez importu od 3.9. Starsze: `typing.List`.
- `Optional[X]` to to samo co `X | None`. `typing.TypedDict` opisuje słownik o znanych polach, `Protocol` typ strukturalny.
- Typuj granice modułów (funkcje publiczne); wnętrza opcjonalnie.

## Pliki i ścieżki

```python
from pathlib import Path
import json

baza = Path(__file__).parent
plik = baza / "dane" / "konfig.json"
plik.parent.mkdir(parents=True, exist_ok=True)
tekst = plik.read_text(encoding="utf-8")
dane = json.loads(tekst)
plik.write_text(json.dumps(dane, ensure_ascii=False, indent=2), encoding="utf-8")
for p in baza.glob("*.md"):
    print(p.name, p.stat().st_size)
```

- `ensure_ascii=False` zachowuje polskie znaki w JSON.
- Bezpieczny zapis (nie zepsuje pliku przy awarii): zapisz do `plik.tmp`, potem `os.replace("plik.tmp", "plik")` (atomowe w obrębie jednego systemu plików).
- CSV: moduł `csv`; otwieraj z `newline=""`.
- Duże pliki czytaj linia po linii, nie `read()` całości.

## subprocess

```python
import subprocess
wynik = subprocess.run(
    ["ls", "-l", "/tmp"],
    capture_output=True, text=True, check=True, timeout=10,
)
print(wynik.stdout)
```

- Przekazuj listę argumentów, nie sklejony napis. `shell=True` z danymi spoza programu to ryzyko wstrzyknięcia poleceń. Patrz [[Bezpieczeństwo aplikacji webowych]].
- `check=True` rzuca `CalledProcessError` przy kodzie wyjścia różnym od 0. `timeout` zapobiega zawieszeniu.
- `subprocess.Popen` gdy potrzebujesz strumieniowania wyjścia lub działania w tle.

## Argumenty wiersza poleceń

```python
import argparse
p = argparse.ArgumentParser(description="Opis")
p.add_argument("plik")
p.add_argument("-n", "--ile", type=int, default=5)
p.add_argument("--glosno", action="store_true")
args = p.parse_args()
```

`--help` jest generowane automatycznie.

## Logowanie

```python
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
log.info("start")
log.exception("błąd")   # w bloku except, dodaje traceback
```

Pod `systemd` wyjście na stdout/stderr trafia do `journalctl`.

## Współbieżność: kiedy co

- Praca głównie czeka na sieć lub dysk (I/O): wątki (`concurrent.futures.ThreadPoolExecutor`) albo `asyncio`.
- Praca obciąża CPU: procesy (`ProcessPoolExecutor`, `multiprocessing`), bo GIL w standardowym CPython pozwala w danej chwili wykonywać bajtkod Pythona tylko jednemu wątkowi. (W Pythonie 3.13 pojawiła się eksperymentalna wersja bez GIL; od 3.14 jest oficjalnie wspierana, ale to osobna kompilacja, np. `python3.14t`. Domyślny CPython nadal ma GIL.)
- `ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=8) as ex:
    wyniki = list(ex.map(pobierz, adresy))
```

- `asyncio`:

```python
import asyncio
async def zadanie(n):
    await asyncio.sleep(1)
    return n
async def main():
    print(await asyncio.gather(*(zadanie(i) for i in range(3))))
asyncio.run(main())
```

- W kodzie `async` nie wołaj blokujących funkcji (`time.sleep`, `requests.get`); to zatrzymuje całą pętlę. Blokujące wywołanie wyniesiesz przez `asyncio.to_thread(...)` (3.9+).
- Dane współdzielone między wątkami chroń `threading.Lock` albo użyj `queue.Queue`.
- Na słabym sprzęcie (4 wątki sprzętowe) nie przesadzaj z liczbą wątków; zacznij od kilku.

## Profilowanie w skrócie

- `python3 -m cProfile -s cumtime skrypt.py | head -30`
- `python3 -m timeit "sum(range(1000))"`
- Mierz, zanim optymalizujesz. Patrz [[Algorytmy i struktury danych]].
