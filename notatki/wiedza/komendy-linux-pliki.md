# Komendy Linuksa: pliki i tekst
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Poruszanie się, pliki, prawa dostępu,
przetwarzanie tekstu. Praktyczny leksykon pod Ubuntu. Dalej: [[Komendy
Linuksa: system i procesy]], [[Komendy Linuksa: sieć i bezpieczeństwo]].

## Poruszanie się i podgląd

- `pwd` - gdzie jestem. `ls -la` - lista z ukrytymi i prawami. `ls -lh` -
  rozmiary czytelnie. `cd /sciezka`, `cd ~`, `cd -` (poprzedni katalog).
- `tree -L 2` - drzewo katalogów do 2 poziomów.
- `cat plik` - wypisz. `less plik` - przewijaj (q wychodzi). `head -n 20`,
  `tail -n 20`, `tail -f plik` - podgląd na żywo (logi).
- `file plik` - co to za typ. `stat plik` - szczegóły (czas, prawa,
  rozmiar). `wc -l` - liczba linii.

## Operacje na plikach

- `cp a b`, `cp -r kat1 kat2` (rekurencyjnie). `mv a b` - przenieś/zmień
  nazwę. `rm plik`, `rm -r kat` (ostrożnie!), `rmdir` (pusty katalog).
- `mkdir -p a/b/c` - z katalogami pośrednimi. `touch plik` - utwórz/odśwież
  czas.
- `ln -s cel link` - dowiązanie symboliczne (skrót).
- `du -sh kat` - rozmiar katalogu. `df -h` - wolne miejsce na dyskach.

## Prawa dostępu (ważne dla bezpieczeństwa)

- Zapis `rwx` dla: właściciel / grupa / inni. `chmod 600 plik` -
  właściciel czyta i pisze, reszta nic (tak dla sekretów, jak `.env`).
  `chmod 700 kat` - tylko właściciel. `chmod +x skrypt` - wykonywalny.
- `chown user:grupa plik` - zmień właściciela. `umask` - domyślne prawa
  nowych plików.
- Zasada: sekrety `600`, katalogi prywatne `700`, nic "światu do zapisu".
  Patrz [[Utwardzanie Linuksa]].

## Szukanie

- `find . -name "*.md"` - po nazwie. `find . -type f -mtime -1` - pliki
  zmienione w ostatniej dobie. `find . -perm -o+w` - pliki zapisywalne
  przez wszystkich (podejrzane).
- `grep "wzor" plik` - szukaj w treści. `grep -r "wzor" kat` -
  rekurencyjnie. `grep -i` (ignoruj wielkość), `grep -n` (numery linii),
  `grep -v` (odwrotnie). `rg "wzor"` (ripgrep) - szybszy odpowiednik.
- `locate nazwa` - szybkie szukanie z indeksu (`updatedb`).

## Przetwarzanie tekstu (potoki)

- Potok `|` łączy wyjście jednej komendy z wejściem następnej:
  `cat log | grep BŁĄD | wc -l`.
- `sort`, `uniq -c` (policz powtórzenia), `cut -d: -f1` (kolumny),
  `tr`, `wc`. `sed 's/stare/nowe/g'` - zamiana. `awk '{print $1}'` -
  kolumny i logika.
- Przekierowania: `>` (nadpisz plik), `>>` (dopisz), `2>` (błędy),
  `2>&1` (błędy razem z wyjściem), `< plik` (wejście z pliku).

## Archiwa i szyfrowanie

- `tar -czf a.tgz katalog` - spakuj (gzip). `tar -xzf a.tgz` - rozpakuj.
  `tar -tzf a.tgz` - podejrzyj zawartość bez rozpakowania.
- `zip -r a.zip kat`, `unzip a.zip`.
- `gpg --symmetric --cipher-algo AES256 plik` - zaszyfruj hasłem (tak
  robimy archiwum danych w GREGAI). `gpg --decrypt plik.gpg` - odszyfruj.
- `sha256sum plik` - suma kontrolna (integralność). `sha256sum -c plik.sha256`
  - sprawdź paczkę (tak weryfikujemy GREGAI.zip i ISO). Patrz [[Kryptografia
  w praktyce]].

## Edytory

- `nano plik` - prosty (Ctrl+O zapis, Ctrl+X wyjście). `vim`/`vi` -
  potężny, stroma krzywa (`:wq` zapisz i wyjdź, `:q!` wyjdź bez zapisu).
