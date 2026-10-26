# SQL i bazy danych
type: Wiedza

Część [[Programowanie]]. SQL to język zapytań do baz relacyjnych: dane w tabelach (wiersze i kolumny), powiązane kluczami. Do własnych projektów najwygodniejszy jest SQLite: cała baza w jednym pliku, bez serwera, wbudowana w Pythona (`import sqlite3`). Składnia poniżej jest standardowa; różnice między silnikami (SQLite, PostgreSQL, MySQL) zaznaczono.

## Tabela i typy

```sql
CREATE TABLE IF NOT EXISTS uzytkownicy (
  id      INTEGER PRIMARY KEY,
  email   TEXT NOT NULL UNIQUE,
  imie    TEXT,
  utworzono TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS zamowienia (
  id      INTEGER PRIMARY KEY,
  uzytkownik_id INTEGER NOT NULL REFERENCES uzytkownicy(id),
  kwota_gr INTEGER NOT NULL
);
```

- Klucz główny (`PRIMARY KEY`) identyfikuje wiersz; klucz obcy (`REFERENCES`) łączy tabele.
- W SQLite typy są "afiniczne" (elastyczne): `INTEGER`, `TEXT`, `REAL`, `BLOB`. Daty zwykle jako tekst ISO (`2026-10-22`) lub liczba.
- Kwoty trzymaj jako liczby całkowite w groszach, nie jako `REAL`.
- Klucze obce w SQLite są domyślnie wyłączone: włącz `PRAGMA foreign_keys = ON;` przy każdym połączeniu.

## SELECT, INSERT, UPDATE, DELETE

```sql
SELECT imie, email FROM uzytkownicy
WHERE imie LIKE 'A%' AND id > 10
ORDER BY imie ASC
LIMIT 20 OFFSET 0;

INSERT INTO uzytkownicy (email, imie) VALUES ('a@x.pl', 'Ala');
UPDATE uzytkownicy SET imie = 'Ola' WHERE id = 1;
DELETE FROM uzytkownicy WHERE id = 1;
```

- **Zawsze `WHERE` przy `UPDATE` i `DELETE`**, inaczej zmienisz wszystkie wiersze. Najpierw sprawdź tym samym `WHERE` w `SELECT`.
- `NULL` to "brak wartości": porównuj `IS NULL` / `IS NOT NULL`, nie `= NULL`. `NULL` w porównaniach daje "nieznane".
- `IN (1, 2, 3)`, `BETWEEN a AND b`, `DISTINCT`, `COALESCE(x, 'domyślna')`.

## Agregacje i grupowanie

```sql
SELECT uzytkownik_id, COUNT(*) AS ile, SUM(kwota_gr) AS suma
FROM zamowienia
GROUP BY uzytkownik_id
HAVING SUM(kwota_gr) > 10000
ORDER BY suma DESC;
```

- `WHERE` filtruje wiersze przed grupowaniem, `HAVING` filtruje grupy po agregacji.
- Funkcje: `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`. Każda kolumna w `SELECT` poza agregatami powinna być w `GROUP BY`.

## JOIN

```sql
SELECT u.email, z.kwota_gr
FROM uzytkownicy u
JOIN zamowienia z ON z.uzytkownik_id = u.id;          -- INNER: tylko pasujące

SELECT u.email, COUNT(z.id) AS ile
FROM uzytkownicy u
LEFT JOIN zamowienia z ON z.uzytkownik_id = u.id      -- wszyscy użytkownicy
GROUP BY u.id;
```

- `INNER JOIN` (czyli `JOIN`): tylko wiersze z dopasowaniem po obu stronach.
- `LEFT JOIN`: wszystkie z lewej, brak dopasowania daje `NULL` po prawej (przydatne do "użytkownicy bez zamówień": `WHERE z.id IS NULL`).
- `RIGHT` i `FULL JOIN` mają ograniczone wsparcie w starszych wersjach SQLite (dostępne od 3.39).
- Zawsze podawaj warunek `ON`, inaczej powstaje iloczyn kartezjański.

## Indeksy

- Indeks przyspiesza wyszukiwanie, `JOIN` i sortowanie po kolumnie, kosztem miejsca i wolniejszych zapisów.
- `CREATE INDEX idx_zam_uzyt ON zamowienia(uzytkownik_id);`
- Klucz główny i `UNIQUE` mają indeks automatycznie. Kolumny klucza obcego zwykle warto zaindeksować samemu.
- Indeks nie pomoże przy `LIKE '%tekst'` (wiodący znak wieloznaczny) ani przy funkcji na kolumnie (`WHERE lower(email) = ...` bez indeksu funkcyjnego).
- Sprawdź plan: `EXPLAIN QUERY PLAN SELECT ...` w SQLite (`SCAN` = przegląd całej tabeli, `SEARCH ... USING INDEX` = użyty indeks); w PostgreSQL `EXPLAIN ANALYZE`.
- Nie indeksuj wszystkiego; dla małych tabel (setki wierszy) różnicy nie zobaczysz.

## Transakcje

Transakcja grupuje operacje: wszystkie się udają (`COMMIT`) albo żadna (`ROLLBACK`). Własności ACID: atomowość, spójność, izolacja, trwałość.

```sql
BEGIN;
UPDATE konta SET saldo = saldo - 100 WHERE id = 1;
UPDATE konta SET saldo = saldo + 100 WHERE id = 2;
COMMIT;
```

- Używaj transakcji dla zmian zależnych od siebie oraz dla wielu wstawień (masowy `INSERT` w jednej transakcji jest wielokrotnie szybszy w SQLite niż osobne zatwierdzenia).
- Aktualizuj atomowo (`saldo = saldo - 100`), nie czytaj-modyfikuj-zapisuj w kodzie aplikacji.

## SQLite w Pythonie

```python
import sqlite3

con = sqlite3.connect("dane.db")
con.row_factory = sqlite3.Row            # wiersze jak słowniki: r["email"]
con.execute("PRAGMA foreign_keys = ON")

with con:                                # commit przy sukcesie, rollback przy wyjątku
    con.execute("INSERT INTO uzytkownicy (email, imie) VALUES (?, ?)",
                (email, imie))

for r in con.execute("SELECT * FROM uzytkownicy WHERE imie = ?", (imie,)):
    print(r["email"])
con.close()
```

- **Parametry `?` zamiast sklejania napisów** (f-stringów) w zapytaniu. To chroni przed wstrzyknięciem SQL. Parametrami nie podstawisz nazw tabel/kolumn; te waliduj z listy dozwolonych. Patrz [[Bezpieczeństwo aplikacji webowych]].
- `with con:` zarządza transakcją, ale nie zamyka połączenia (`con.close()` osobno).
- `executemany(sql, lista_krotek)` do wielu wstawień. `cursor.lastrowid` zwraca id ostatniego wstawienia.
- `fetchone()`, `fetchall()`, iteracja po kursorze (oszczędza pamięć).
- Jednoczesny dostęp: SQLite pozwala wielu czytelnikom, ale jednemu piszącemu naraz. Tryb `PRAGMA journal_mode = WAL;` poprawia współbieżność odczytu i zapisu. Wątki: domyślnie obiekt połączenia jest związany z wątkiem utworzenia (`check_same_thread`); najprościej otwierać połączenie w każdym wątku.
- Kopia zapasowa: nie kopiuj pliku w trakcie zapisu; użyj `con.backup(inne_polaczenie)` lub polecenia `sqlite3 dane.db ".backup kopia.db"`.
- Podgląd z terminala: `sqlite3 dane.db`, komendy `.tables`, `.schema tabela`, `.headers on`, `.mode column`, `.quit` (pakiet `sqlite3` na Ubuntu).

## Projektowanie schematu

- Jedna informacja w jednym miejscu (normalizacja): zamiast powtarzać imię użytkownika w każdym zamówieniu, trzymaj `uzytkownik_id`.
- Relacja wiele-do-wielu: tabela pośrednia z dwoma kluczami obcymi.
- Nie zapisuj list w jednej kolumnie ("a,b,c"); utwórz tabelę podrzędną. Dla elastycznych danych SQLite ma funkcje JSON (zależne od wersji, w nowszych wbudowane).
- Migracje: zmiany schematu `ALTER TABLE ... ADD COLUMN` zapisuj w skryptach pod kontrolą wersji; SQLite ma ograniczone `ALTER` (usuwanie i zmiana kolumn bywa trudna, zależy od wersji).

## Kiedy plik JSON, kiedy SQLite, kiedy serwer

- Mała konfiguracja, kilkaset rekordów: plik JSON ([[Python: narzędzia]]).
- Filtrowanie, zapisy z wielu miejsc, tysiące rekordów: SQLite.
- Wielu piszących przez sieć, replikacja: serwer (PostgreSQL).
- Struktury w pamięci: [[Algorytmy i struktury danych]].
