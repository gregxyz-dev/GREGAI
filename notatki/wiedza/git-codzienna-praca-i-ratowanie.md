# Git: codzienna praca i ratowanie sytuacji
type: Wiedza

Część [[Programowanie]]. Git zapisuje historię projektu jako migawki (commity). Prawie nic, co zacommitowałeś, nie ginie na dobre: da się to odzyskać przez `reflog`. Zasada: commituj często, małe zmiany.

## Pierwsze użycie

```bash
git config --global user.name "Imię Nazwisko"
git config --global user.email "ja@example.com"
git config --global init.defaultBranch main
git init                    # nowe repo w bieżącym katalogu
git clone URL               # kopia istniejącego
```

Plik `.gitignore` wyklucza pliki ze śledzenia: `.venv/`, `__pycache__/`, `*.log`, `.env`, `node_modules/`. Plik już śledzony trzeba odśledzić: `git rm --cached plik`.

## Codzienny cykl

```bash
git status -sb              # co się zmieniło
git diff                    # zmiany niezestageowane
git diff --staged           # to, co pójdzie do commita
git add plik1 plik2         # stage (unikaj ślepego git add .)
git add -p                  # wybieraj kawałki zmian
git commit -m "Dodaj walidację wejścia"
git log --oneline --graph --decorate -20
git show HEAD               # ostatni commit
```

- Dobra wiadomość commita: krótka linia w trybie rozkazującym, opisuje co i po co.
- Nie commituj sekretów (klucze API, hasła). Jeśli wyciekły do historii, usunięcie pliku nie wystarcza: unieważnij sekret u dostawcy (patrz [[Uwierzytelnianie i sekrety]]).

## Gałęzie

```bash
git switch -c funkcja-x     # nowa gałąź i przełączenie (starsze: git checkout -b)
git switch main
git branch -a               # lista
git branch -d funkcja-x     # usuń scaloną (-D wymusza)
git push -u origin funkcja-x
git pull                    # fetch + fast-forward; przy rozbieżnej historii wybierz: --rebase albo --no-rebase
git fetch                   # tylko pobierz, nic nie zmieniaj
```

## merge kontra rebase

- `git merge funkcja-x` łączy gałęzie, zachowuje prawdziwą historię, może dodać commit scalający. Bezpieczne, nie przepisuje niczego.
- `git rebase main` (stojąc na `funkcja-x`) odtwarza Twoje commity na czubku `main`: historia liniowa i czysta, ale commity dostają nowe identyfikatory.
- **Złota zasada:** nie rebase'uj commitów, które ktoś inny już pobrał (opublikowanych we wspólnej gałęzi). Własne, nieopublikowane gałęzie rebase'uj do woli.
- Po rebase i wcześniejszym pushu potrzebny jest push wymuszony; używaj bezpieczniejszego `git push --force-with-lease` zamiast `--force`.
- Konflikt: Git zaznacza w pliku `<<<<<<<`, `=======`, `>>>>>>>`. Edytujesz, usuwasz znaczniki, `git add plik`, potem `git merge --continue` albo `git rebase --continue`. Przerwanie: `git merge --abort` / `git rebase --abort`.
- Dla projektu jednoosobowego wystarczy prosty `merge`, albo praca wprost na `main`.

## Cofanie: co do czego

| Sytuacja | Polecenie |
|---|---|
| Odrzuć zmiany w pliku (niezacommitowane) | `git restore plik` |
| Wycofaj plik ze stage'a | `git restore --staged plik` |
| Popraw ostatni commit (nieopublikowany) | `git commit --amend` |
| Cofnij commit, zostaw zmiany w plikach | `git reset --soft HEAD~1` |
| Cofnij commit i stage, zostaw zmiany | `git reset HEAD~1` (domyślnie `--mixed`) |
| Cofnij commit i zmiany (niszczące) | `git reset --hard HEAD~1` |
| Cofnij opublikowany commit bezpiecznie | `git revert <hash>` (nowy commit odwracający) |
| Schowaj bieżącą pracę na chwilę | `git stash`, potem `git stash pop` |
| Usuń nieśledzone pliki | `git clean -n` (podgląd), `git clean -f` |

- `reset --hard` i `clean -f` kasują niezacommitowaną pracę bez odzysku. Najpierw `git status` i `git stash`.
- Na opublikowanej historii używaj `revert`, nie `reset`.

## Ratowanie: reflog

`git reflog` pokazuje, gdzie wskazywał `HEAD` w ostatnim czasie (domyślnie wpisy trzymane około 90 dni, a nieosiągalne około 30; zależy od konfiguracji). Dzięki temu odzyskasz "zgubione" commity.

```bash
git reflog
# a1b2c3d HEAD@{2}: commit: ważna zmiana
git reset --hard a1b2c3d        # wróć do tego stanu
# albo bezpieczniej:
git switch -c odzyskane a1b2c3d # nowa gałąź w tym punkcie
git cherry-pick a1b2c3d         # weź pojedynczy commit
```

Typowe katastrofy i wyjścia:
- Pomyłkowy `reset --hard`: reflog, powrót do hasha sprzed resetu (działa dla zacommitowanych zmian; niezacommitowanych nie odzyskasz).
- Usunięta gałąź: reflog, `git switch -c nazwa hash`.
- Commit na złej gałęzi: `git switch właściwa`, `git cherry-pick hash`, potem na złej `git reset --hard HEAD~1` (po upewnieniu się, że commit jest bezpieczny).
- Wiszący "detached HEAD": utwórz gałąź `git switch -c nazwa`, zanim przełączysz się gdzie indziej.
- Pomyłkowy rebase: `git rebase --abort`, a po zakończeniu reflog i reset do stanu sprzed rebase (wpis `ORIG_HEAD` też pomaga: `git reset --hard ORIG_HEAD`).

## Szukanie przyczyny błędu

- `git log -p plik` - historia zmian pliku. `git blame plik` - kto i kiedy zmienił linię.
- `git log -S"tekst"` - commity, które dodały lub usunęły tekst. `git log --grep="słowo"` - po wiadomościach.
- `git bisect` - binarne szukanie commita, który coś zepsuł. Szczegóły w [[Debugowanie i testowanie]].

```bash
git bisect start
git bisect bad            # obecny stan jest zły
git bisect good v1.0      # ten był dobry
# Git przełącza na środek; testujesz i wpisujesz good/bad
git bisect reset
```

## Zdalne repozytoria

- `git remote -v`, `git remote add origin URL`, `git push -u origin main`.
- SSH (`ssh-keygen -t ed25519`, klucz publiczny do GitHuba) jest wygodniejsze niż hasła; klucz prywatny nigdy nie opuszcza komputera.
- `git tag v1.0` oznacza wersję; `git push --tags`.
- Kopia zapasowa projektu = push do zdalnego repo, ale nie zastępuje kopii zapasowej danych spoza gita (bazy, pliki użytkownika).

## Dobre nawyki

- Jedna logiczna zmiana na commit; testy przed commitem.
- Nie commituj dużych plików binarnych i modeli (historia puchnie na zawsze).
- Przed ryzykowną operacją utwórz gałąź zapasową: `git branch kopia`.
- `git help polecenie` albo `git polecenie -h` dla szybkiej pomocy.
