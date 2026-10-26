# Algorytmy i struktury danych
type: Wiedza

Część [[Programowanie]]. Cel praktyczny: wybrać właściwą strukturę i wiedzieć, kiedy kod będzie wolny. Przykłady w Pythonie ([[Python: podstawy i idiomy]]). Najpierw poprawność, optymalizuj po pomiarze.

## Złożoność (notacja O)

Opisuje, jak rośnie czas (lub pamięć) wraz z rozmiarem danych n, z pominięciem stałych.

- O(1) - stały (dostęp do elementu słownika średnio, indeks listy).
- O(log n) - logarytmiczny (wyszukiwanie binarne). Dla miliona elementów to rząd 20 kroków.
- O(n) - liniowy (przejście po liście).
- O(n log n) - dobre sortowanie.
- O(n^2) - dwie zagnieżdżone pętle po tych samych danych; przy n = 10 000 to rząd 100 milionów operacji.
- O(2^n), O(n!) - wykładnicze/silnia, tylko dla bardzo małych n.

Zasady: liczy się najwyższy człon, stałe pomijamy, ale w praktyce O(n) w Pythonie z dużą stałą bywa wolniejsze niż O(n log n) w wbudowanej funkcji napisanej w C. Mierz (`timeit`).

## Struktury w Pythonie i koszty (typowe, średnie)

| Struktura | Dostęp/szukanie | Dodanie | Uwagi |
|---|---|---|---|
| `list` | indeks O(1), `x in l` O(n) | `append` O(1) zamortyzowane, `insert(0, x)` O(n) | tablica dynamiczna |
| `dict` | O(1) | O(1) | tablica mieszająca, klucze muszą być hashowalne |
| `set` | `x in s` O(1) | O(1) | unikalne, operacje mnogościowe |
| `collections.deque` | końce O(1), środek O(n) | `append`/`appendleft` O(1) | kolejka, bufor |
| `heapq` (na liście) | min O(1) | `heappush` O(log n) | kolejka priorytetowa |
| `tuple` | indeks O(1) | niezmienna | może być kluczem słownika |

- `list.pop(0)` jest O(n); do kolejki użyj `deque.popleft()`.
- Klucze słownika/zbioru: liczby, napisy, krotki z takich elementów. Lista nie może być kluczem (zmienna).
- Sprawdzanie przynależności w pętli: zamień listę na `set`, gdy lista jest duża.

```python
# wolne: O(n*m)
wspolne = [x for x in a if x in b]
# szybkie: O(n+m)
sb = set(b)
wspolne = [x for x in a if x in sb]
```

## Wybór struktury: kiedy co

- Kolejność i duplikaty, dostęp po indeksie: `list`.
- Szybkie "czy jest" i unikalność: `set`.
- Klucz do wartości, liczniki, grupowanie: `dict`, `Counter`, `defaultdict`.
- Kolejka FIFO: `deque`. Stos LIFO: zwykła `list` (`append`/`pop` z końca).
- Zawsze bierz najmniejszy/największy: `heapq` (`heappush`, `heappop`).
- Posortowane dane i szukanie pozycji: `bisect`.
- Rekordy o stałych polach: `dataclass` lub `tuple`/`NamedTuple`.
- Dane trwałe, wyszukiwanie po wielu polach: baza, [[SQL i bazy danych]].

## Sortowanie i wyszukiwanie

- `sorted(lista, key=..., reverse=True)` zwraca nową listę; `lista.sort()` sortuje w miejscu. Timsort: O(n log n), stabilne (równe elementy zachowują kolejność), więc można sortować wieloetapowo (najpierw po kluczu mniej ważnym).
- Wyszukiwanie liniowe: O(n), działa na wszystkim.
- Wyszukiwanie binarne: wymaga posortowanych danych, O(log n).

```python
import bisect
a = [1, 3, 5, 7]
i = bisect.bisect_left(a, 5)    # 2
znaleziono = i < len(a) and a[i] == 5
```

- `min`, `max`, `sum` są szybkie (C). Dla n największych: `heapq.nlargest(n, dane)`.

## Wzorce algorytmiczne

- **Dwa wskaźniki / okno przesuwne:** jedno przejście zamiast dwóch pętli (np. suma podtablicy, wykrywanie duplikatów w posortowanych).
- **Słownik jako indeks:** zamiast szukać w pętli, zbuduj `{klucz: rekord}` raz. Typowy ratunek przed O(n^2).
- **Rekurencja:** wymaga warunku bazowego; Python domyślnie ogranicza głębokość (około 1000, sprawdź `sys.getrecursionlimit()`). Głębokie przetwarzanie zrób iteracyjnie.
- **Memoizacja:** `functools.cache` (3.9+) lub `lru_cache`. Zamienia wykładnicze rekurencje typu Fibonacci w liniowe.
- **Programowanie dynamiczne:** zapamiętuj wyniki podproblemów (plecak, najdłuższy wspólny podciąg).
- **Zachłanność:** wybór lokalnie najlepszy; poprawny tylko dla pewnych problemów (np. wydawanie reszty w typowych nominałach), nie zakładaj tego z góry.
- **Dziel i zwyciężaj:** merge sort, wyszukiwanie binarne.
- **Przeszukiwanie grafu:** BFS (kolejka `deque`) znajduje najkrótszą ścieżkę w grafie nieważonym; DFS (stos lub rekurencja) do eksploracji, cykli, składowych. Graf jako `dict`: `{"A": ["B", "C"], ...}` oraz zbiór `odwiedzone`.

```python
from collections import deque
def bfs(graf, start):
    odw, q = {start}, deque([start])
    while q:
        v = q.popleft()
        for s in graf.get(v, []):
            if s not in odw:
                odw.add(s); q.append(s)
    return odw
```

- Najkrótsza ścieżka w grafie z wagami nieujemnymi: algorytm Dijkstry (z `heapq`).

## Pamięć i skala

- Generatory (`(x for x in ...)`) przetwarzają dane strumieniowo bez trzymania wszystkiego w RAM; ważne na skromnym laptopie.
- Napisy są niezmienne: sklejanie w pętli przez `+=` bywa kosztowne, użyj `"".join(lista)`.
- Zbiory i słowniki zajmują więcej pamięci niż listy.
- Dla dużych tablic liczbowych biblioteka NumPy jest dużo szybsza niż pętle Pythona (zewnętrzna, wymaga `pip`).

## Pułapki

- Przedwczesna optymalizacja: n rzędu setek nie wymaga sprytu.
- Ukryta złożoność: `x in lista`, `lista.remove(x)`, `lista.insert(0, x)`, `s1 + s2` w pętli, `list(set(...))` bez potrzeby.
- Liczby zmiennoprzecinkowe nie nadają się do porównań `==`: `math.isclose(a, b)`.
- Kopiowanie dużych struktur w pętli (`lista[:]`) ukrywa O(n) w każdym obrocie.
- Hashowalność: własne klasy używane w zbiorach potrzebują spójnych `__eq__` i `__hash__` (`dataclass(frozen=True)` robi to za Ciebie).
- Profilowanie zamiast zgadywania: `python3 -m cProfile -s cumtime skrypt.py`. Patrz [[Debugowanie i testowanie]].
