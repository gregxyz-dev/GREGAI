# Python: podstawy i idiomy
type: Wiedza

Część [[Programowanie]]. Rdzeń języka, który wystarcza do większości skryptów i małych projektów. Dalej: [[Python: narzędzia]]. Przykłady działają w Pythonie 3.10+ (miejsca zależne od wersji są zaznaczone).

## Typy i kolekcje

- Liczby: `int` (bez limitu rozmiaru), `float` (binarny, `0.1 + 0.2 != 0.3`; do pieniędzy użyj `decimal.Decimal` lub groszy jako `int`), `bool`.
- `str` jest niezmienny, Unicode. `bytes` to surowe bajty; konwersja: `s.encode("utf-8")`, `b.decode("utf-8")`.
- `list` (zmienna, uporządkowana), `tuple` (niezmienna), `dict` (klucz do wartości, zachowuje kolejność wstawiania od 3.7), `set` (unikalne, bez kolejności).
- Puste `{}` to słownik, pusty zbiór to `set()`.
- Wycinki: `a[1:3]`, `a[::-1]` (odwrócona kopia), `a[-1]` (ostatni).
- Rozpakowanie: `x, y = para`, `pierwszy, *reszta = lista`.
- Zamiana: `a, b = b, a`.

## Napisy

- f-string: `f"{nazwa}: {wartosc:.2f}"`, `f"{n:05d}"`, `f"{x!r}"`.
- `", ".join(lista_str)`, `s.split()` (po białych znakach), `s.strip()`, `s.startswith("x")`, `s.replace("a", "b")`.
- Wielolinijkowe: potrójne cudzysłowy. Surowe (dla regex i ścieżek Windows): `r"\d+"`.

## Pętle i comprehensions

```python
kwadraty = [x * x for x in range(10) if x % 2 == 0]
slownik = {k: len(k) for k in ["a", "bb"]}
unikalne = {x % 3 for x in range(10)}
suma = sum(x * x for x in range(10))   # generator, bez listy w pamięci

for i, wartosc in enumerate(["a", "b"], start=1):
    print(i, wartosc)
for a, b in zip([1, 2], ["x", "y"]):
    print(a, b)
```

- `zip` kończy na najkrótszej (od 3.10 jest `strict=True`, które zgłasza błąd przy różnych długościach).
- Nie modyfikuj listy, po której iterujesz; zbuduj nową.
- `any(...)` i `all(...)` zastępują wiele pętli z flagą.
- `for ... else`: blok `else` wykonuje się, gdy pętla nie została przerwana `break`.

## Funkcje

```python
def pobierz(url, *, timeout=10, naglowki=None):
    naglowki = naglowki or {}
    ...
```

- `*args` zbiera pozycyjne, `**kwargs` nazwane. Parametr po gołej `*` jest tylko nazwany.
- **Pułapka:** mutowalny argument domyślny (`def f(x, lista=[])`) jest tworzony raz i współdzielony między wywołaniami. Użyj `None` i utwórz listę w środku.
- Funkcja bez `return` zwraca `None`.
- Lambda tylko do krótkich kluczy: `sorted(lista, key=lambda r: r["wiek"])`.
- Dekorator to funkcja opakowująca funkcję; `functools.wraps` zachowuje nazwę i docstring.

## Wyjątki

```python
try:
    dane = json.loads(tekst)
except json.JSONDecodeError as e:
    print("zły JSON:", e)
else:
    ...          # tylko gdy nie było wyjątku
finally:
    ...          # zawsze
```

- Łap konkretne wyjątki. Goły `except:` (i często `except Exception:`) ukrywa błędy, w tym literówki.
- `raise ValueError("opis")`; `raise NowyBlad(...) from e` zachowuje przyczynę.
- Zasada EAFP: spróbuj i obsłuż błąd, zamiast sprawdzać wszystko wcześniej (`try: d[k]` zamiast `if k in d` bywa idiomatyczne, zwłaszcza przy wyścigach na plikach).

## Słowniki i zbiory w praktyce

- `d.get(k, domyslna)`, `d.setdefault(k, [])`, `d.items()`.
- `collections.Counter("abca")`, `collections.defaultdict(list)`, `collections.deque` (kolejka O(1) po obu końcach).
- Scalanie: `{**a, **b}` lub (3.9+) `a | b`.
- Sortowanie po wartości: `sorted(d.items(), key=lambda kv: kv[1], reverse=True)`.
- `x in zbior` jest szybkie (średnio O(1)), `x in lista` liniowe. Patrz [[Algorytmy i struktury danych]].

## Klasy i dataclass

```python
from dataclasses import dataclass

@dataclass
class Zadanie:
    tytul: str
    gotowe: bool = False
```

- `dataclass` generuje `__init__`, `__repr__`, `__eq__`. Mutowalne pole domyślne: `field(default_factory=list)`.
- Zwykła klasa: `__init__(self, ...)`, metody mają `self`. `@staticmethod`, `@classmethod` rzadko potrzebne.
- Dziedziczenie bywa nadużywane; często wystarczy funkcja lub kompozycja. Patrz [[Czysty kod i architektura]].

## with i pliki

```python
with open("dane.txt", encoding="utf-8") as f:
    for linia in f:
        print(linia.rstrip("\n"))
```

- `with` zamyka zasób nawet przy wyjątku. Zawsze podawaj `encoding="utf-8"` przy tekście.
- Własny menedżer: `contextlib.contextmanager`.

## Idiomy i pułapki

- Porównuj z `None` przez `is None`, nie `== None`.
- Prawdziwość: puste kolekcje, `0`, `""`, `None` są fałszem. `if lista:` zamiast `if len(lista) > 0:`.
- `is` sprawdza tożsamość obiektu, `==` równość wartości.
- Płytka kopia: `lista.copy()`, `copy.copy`; głęboka: `copy.deepcopy`. Przypisanie `b = a` nie kopiuje.
- `if __name__ == "__main__":` odpala kod tylko przy uruchomieniu pliku, nie przy imporcie.
- Importy: stdlib, potem zewnętrzne, potem własne. Unikaj `from x import *`.
- Nazwy: `snake_case` funkcje i zmienne, `CamelCase` klasy, `STALE` stałe (PEP 8).
- `print` do debugowania w porządku, ale dla trwałych programów użyj `logging`. Patrz [[Debugowanie i testowanie]].
- Wbudowane `sorted`, `min`, `max`, `sum`, `len`, `reversed`, `map`, `filter` znasz na pamięć; reszta jest w `itertools` i `functools`.
- Wersja zależna: `match`/`case` (od 3.10), `X | Y` w typach (3.10), `tomllib` (3.11).
