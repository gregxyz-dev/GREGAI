# Bash: skrypty
type: Wiedza

Część [[Programowanie]]. Bash jest świetny do sklejania poleceń i automatyzacji na Ubuntu. Gdy skrypt ma więcej niż kilkadziesiąt linii, złożoną logikę lub strukturę danych, przejdź na [[Python: narzędzia]]. Polecenia pomocnicze: [[Komendy Linuksa: pliki i tekst]].

## Szkielet bezpiecznego skryptu

```bash
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

cd "$(dirname "${BASH_SOURCE[0]}")"
echo "start"
```

- `set -e`: przerwij przy błędzie polecenia (z wyjątkami: warunki `if`, `&&`/`||`, części listy). Nie traktuj tego jako pełnej gwarancji.
- `set -u`: użycie niezdefiniowanej zmiennej to błąd (łapie literówki).
- `set -o pipefail`: potok zwraca błąd, jeśli zawiedzie którykolwiek jego element, nie tylko ostatni.
- Debug: `bash -x skrypt.sh` lub `set -x` w środku. Składnia bez uruchamiania: `bash -n skrypt.sh`.
- `chmod +x skrypt.sh`, potem `./skrypt.sh`.

## Cytowanie (najważniejsza zasada)

- Zawsze cytuj rozwinięcia: `"$zmienna"`, `"$@"`, `"$(polecenie)"`. Bez cudzysłowu napis z spacją rozpada się na słowa, a `*` rozwija się na nazwy plików.
- Pojedyncze cudzysłowy nic nie rozwijają: `'$HOME'` to dosłownie napis.
- Zmienna: `nazwa="Jan Kowalski"` (bez spacji wokół `=`).
- Wartość domyślna: `"${ILE:-5}"`; wymagana: `"${KLUCZ:?brak KLUCZ}"`.
- Podmiana: `"${plik%.txt}"` (utnij końcówkę), `"${plik##*/}"` (sama nazwa), `"${s^^}"` wielkie litery (Bash 4+).

## Warunki

```bash
if [[ -f "$plik" && -r "$plik" ]]; then ... fi
if [[ "$a" == "tak" ]]; then ... fi
if (( liczba > 3 )); then ... fi
if command -v git >/dev/null 2>&1; then ... fi
```

- Testy plików: `-f` zwykły plik, `-d` katalog, `-e` istnieje, `-s` niepusty, `-x` wykonywalny.
- `[[ ... ]]` (Bash) jest bezpieczniejsze niż `[ ... ]`, ale nie jest przenośne do `sh`. Wzorce: `[[ $s == abc* ]]`, regex: `[[ $s =~ ^[0-9]+$ ]]`.
- Porównanie liczb w `[ ]`: `-eq -ne -lt -gt`; w `(( ))` zwykłe operatory.
- Kod wyjścia ostatniego polecenia: `$?` (0 oznacza sukces).

## Pętle

```bash
for plik in *.txt; do
  [[ -e "$plik" ]] || continue
  echo "$plik"
done

while IFS= read -r linia; do
  echo "linia: $linia"
done < plik.txt

for i in {1..5}; do echo "$i"; done
```

- Nie rób `for f in $(ls)`: psuje się na spacjach. Używaj globów lub `find ... -print0 | while IFS= read -r -d '' f; do ...; done`.
- `read -r` wyłącza interpretację odwrotnych ukośników; `IFS=` zachowuje wiodące spacje.
- Pętla `while` na końcu potoku działa w podpowłoce, więc zmienne ustawione w środku znikają po niej. Rozwiązanie: `while ...; done < <(polecenie)`.

## Funkcje i argumenty

```bash
uzycie() { echo "Użycie: $0 PLIK [ILE]" >&2; exit 1; }
[[ $# -ge 1 ]] || uzycie
plik="$1"; ile="${2:-10}"

licz() {
  local n=0          # local, żeby nie zaśmiecać globalnych
  n=$(wc -l < "$1")
  echo "$n"
}
wynik=$(licz "$plik")
```

- `$0` nazwa skryptu, `$1..` argumenty, `$#` liczba, `"$@"` wszystkie osobno.
- Funkcja zwraca kod 0 do 255 przez `return`; wartości tekstowe przez `echo` i `$(...)`.
- Błędy kieruj na stderr: `echo "błąd" >&2`.

## Przekierowania i potoki

- `> plik` nadpisz, `>> plik` dopisz, `2>&1` błędy do tego samego miejsca, `&> plik` oba do pliku (Bash), `> /dev/null` wyrzuć.
- `polecenie | tee log.txt` pokazuje i zapisuje.
- Podstawienie procesu: `diff <(sort a) <(sort b)`.
- Heredoc: `cat > plik <<'EOF'` ... `EOF` (cudzysłowy wokół EOF wyłączają rozwijanie zmiennych).

## Sprzątanie i blokady

```bash
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
```

- `trap ... EXIT` wykona się przy każdym zakończeniu skryptu.
- Przed `rm -rf "$zmienna/"` upewnij się, że zmienna nie jest pusta (`set -u` pomaga; można dodać `${zmienna:?}`).
- Jedna instancja skryptu: `flock -n /tmp/skrypt.lock polecenie` (pakiet `util-linux`).

## Pułapki

- Spacje w nazwach plików i brak cudzysłowów: najczęstsza przyczyna błędów.
- `cd katalog` bez sprawdzenia: `cd katalog || exit 1` (przy `set -e` wystarczy samo `cd`).
- `A && B || C` to nie jest `if/else`: gdy B się nie powiedzie, uruchomi się C.
- `$(...)` ucina końcowe znaki nowej linii.
- Liczby z zerem wiodącym w `(( ))` są traktowane jako ósemkowe (`08` to błąd); użyj `10#08`.
- Bash nie ma tablic wielowymiarowych; są tablice proste (`arr=(a b c); echo "${arr[@]}"`) i asocjacyjne (`declare -A m; m[k]=v`).
- Cron ma minimalne środowisko (`PATH`): podawaj pełne ścieżki do poleceń i plików.
- Do JSON użyj `jq` (pakiet do doinstalowania), nie `grep`/`sed`.
- Przenośność: `#!/bin/sh` oznacza powłokę POSIX (na Ubuntu to `dash`), w której nie ma `[[ ]]` ani tablic.
- Sprawdzaj skrypty `shellcheck`; wskazuje większość pułapek z tej listy.
