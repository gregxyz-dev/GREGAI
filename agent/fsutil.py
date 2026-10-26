"""
fsutil.py

Jeden bezpieczny zapis plików dla całego agenta: najpierw plik tymczasowy
w tym samym katalogu, potem atomowa podmiana (os.replace). Zwykłe
`path.write_text(...)` najpierw OBCINA plik, a dopiero potem pisze: awaria
prądu, zabicie procesu albo pełny dysk w tej chwili zostawiają plik pusty
albo urwany w połowie. Dla notatek to utrata treści, dla inwentarza sieci
fałszywe alarmy "nowe urządzenie" dla wszystkich urządzeń, dla .env utrata
kluczy. Po tej podmianie czytelnik widzi albo całą starą wersję, albo całą
nową, nigdy połowę.

Tylko stdlib. Używane też przez training/export*.py (update_env).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

# Nowy plik z danymi GREGAI (rozmowy, ślady, uczenie) jest prywatny. Istniejący
# plik zachowuje swoje prawa (np. .env = 600, notatka = 644).
PRIVATE_MODE = 0o600

# Plik tymczasowy ma krótką, stałą nazwę (rozszerzenie .tmp: vault go pomija). Nazwa
# docelowego pliku w nazwie tymczasowego przekraczała limit 255 bajtów dla długich,
# polskich tytułów notatek (zewnętrzne edytory) i zapis kończył się błędem ENAMETOOLONG.
TMP_PREFIX = ".gregai-"


def atomic_write_text(path, text: str, *, mode: int | None = None, encoding: str = "utf-8", errors: str = "strict") -> None:
    """Zapisuje `text` do `path` atomowo. `mode`: prawa NOWEGO pliku (gdy plik
    już istnieje, zostają jego dotychczasowe prawa, chyba że `mode` podano
    jawnie). Brakujące katalogi nadrzędne są tworzone. `errors="surrogateescape"`
    pozwala zapisać bajt w bajt tekst wczytany tak samo (plik w innym kodowaniu)."""
    target = Path(path)
    if target.is_symlink():
        # Zapis przez dowiązanie ma zmienić plik, na który wskazuje: os.replace
        # na samym dowiązaniu zamieniłoby je w zwykły plik, a oryginał zostałby
        # nietknięty.
        target = Path(os.path.realpath(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = target.stat().st_mode & 0o777
        except OSError:
            mode = PRIVATE_MODE
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, errors=errors, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
        _fsync_dir(target.parent)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fsync_dir(directory) -> None:
    """1.32.3 (audyt tura 8): po os.replace sama zmiana nazwy też musi trafić na dysk -
    inaczej po zaniku prądu może wrócić stara wersja pliku (kotwica, dziennik wydatków)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


MAX_QUARANTINE_COPIES = 5


def sweep_stale_tmp(directories, max_age: float = 600.0, recursive=()) -> int:
    """Usuwa osierocone pliki tymczasowe (`.gregai-*.tmp`) z podanych katalogów (bez
    zagłębiania się) oraz z `recursive` (z podkatalogami, bez ukrytych: notatki leżą też
    w podfolderach): zostają po zabiciu procesu albo utracie prądu w trakcie zapisu.
    Tylko nasz prefiks i rozszerzenie oraz tylko pliki starsze niż `max_age` sekund,
    żeby nie ruszyć zapisu, który właśnie trwa. Zwraca liczbę usuniętych."""
    removed = 0
    now = time.time()
    directories = list(directories)
    for root in recursive:
        for dirpath, dirnames, _files in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
            directories.append(dirpath)
    for directory in directories:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if not (name.startswith(TMP_PREFIX) and name.endswith(".tmp")):
                continue
            try:
                if entry.is_symlink() or not entry.is_file() or now - entry.stat().st_mtime < max_age:
                    continue
                os.unlink(entry.path)
                removed += 1
            except OSError:
                continue
    return removed


def quarantine(path) -> None:
    """Uszkodzony plik z danymi odsuwamy obok (`<nazwa>.corrupt-<data UTC>`), zamiast
    nadpisać go pustym. Znacznik czasu w nazwie: kolejne uszkodzenie nie niszczy
    kopii z poprzedniego."""
    p = Path(path)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    dest = p.with_name(f"{p.name}.corrupt-{stamp}")
    for n in range(1, 100):  # dwa uszkodzenia w tej samej sekundzie nie nadpisują się
        if not os.path.lexists(dest):
            break
        dest = p.with_name(f"{p.name}.corrupt-{stamp}-{n}")
    try:
        os.replace(p, dest)
    except OSError:
        pass
    # 1.32.3 (audyt tura 8): najwyżej MAX_QUARANTINE_COPIES kopii na plik - psujący się dysk
    # nie zapcha data/ tysiącami kopii. Najstarsze znikają (nazwy mają znacznik czasu UTC).
    try:
        copies = sorted(c for c in os.listdir(p.parent) if c.startswith(p.name + ".corrupt-"))
        for old in copies[:-MAX_QUARANTINE_COPIES]:
            try:
                os.unlink(p.parent / old)
            except OSError:
                pass
    except OSError:
        pass


def create_new_text(path, text: str, *, mode: int = 0o644, encoding: str = "utf-8") -> bool:
    """Tworzy NOWY plik wyłącznie, gdy jeszcze nie istnieje. True = utworzono,
    False = już istnieje. Używane tam, gdzie nazwa pliku wynika z tytułu i
    kolizja nie może nadpisać cudzej notatki.

    Treść trafia najpierw do pliku tymczasowego, a pod docelową nazwę wchodzi
    twardym dowiązaniem (os.link nie nadpisuje i jest atomowe): czytelnik widzi
    albo brak pliku, albo cały plik, nigdy pusty ani urwany. Systemy plików bez
    twardych dowiązań (FAT/exFAT na pendrive) dostają wariant O_EXCL."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(target):
        return False
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        try:
            os.link(tmp, target)
            return True
        except FileExistsError:
            return False
        except OSError:
            pass  # brak twardych dowiązań na tym systemie plików
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return _create_exclusive(target, text, mode, encoding)


def _create_exclusive(target: Path, text: str, mode: int, encoding: str) -> bool:
    """Wariant awaryjny: O_CREAT|O_EXCL (bez wyścigu "sprawdź, potem zapisz"),
    ale przerwany zapis zostawia plik niepełny, dlatego go sprzątamy."""
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError:
        return False
    try:
        os.fchmod(fd, mode)  # niezależnie od umask
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    return True


def json_line(obj) -> str:
    """Jedna linia JSONL. json.dumps(ensure_ascii=False) zostawia surowe U+2028,
    U+2029 i U+0085, a str.splitlines() (którym czytamy te pliki) łamie na nich
    linie: rekord z takim znakiem (tekst wklejony ze strony) rozpadałby się na
    dwie nieczytelne połówki. Zamieniamy je na ucieczki JSON, które są równoważne."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("\x85", "\\u0085"))


def append_private_line(path, line: str, *, encoding: str = "utf-8") -> None:
    """Dopisuje jedną linię (JSONL) do pliku. Nowy plik powstaje z prawami 0600
    (rozmowy i ślady decyzji to dane prywatne), istniejący zachowuje swoje."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_APPEND, PRIVATE_MODE)
    try:  # plik urwany w pół linii: zacznij od nowej, żeby nie skleić dwóch rekordów
        size = os.fstat(fd).st_size
        torn = size > 0 and os.pread(fd, 1, size - 1) != b"\n"
    except OSError:
        torn = False
    with os.fdopen(fd, "a", encoding=encoding, newline="") as handle:
        if torn:
            handle.write("\n")
        handle.write(line if line.endswith("\n") else line + "\n")


# 1.32.10 (audyt tura 14): JEDNA blokada notatek dla edytora (main.py), zmiany nazwy z
# przepisaniem linków i dopisywania przez save_note (tools.py) - dopisek nie ginie już pod
# równoległym os.replace przepisywanych powiązań.
import threading as _threading
NOTES_LOCK = _threading.Lock()


def move_to_trash(path, trash_dir, original: str) -> str:
    """Przenosi plik do kosza (zamiast kasować) i zapisuje obok, skąd przyszedł.
    Zwraca nazwę wpisu w koszu (do przywrócenia). Nic nie jest usuwane na zawsze."""
    import json as _json
    import time as _time
    from pathlib import Path as _P
    trash = _P(trash_dir)
    trash.mkdir(parents=True, exist_ok=True)
    base = _time.strftime("%Y%m%d-%H%M%S") + "-" + _P(path).name
    name, i = base, 2
    while (trash / name).exists() or (trash / (name + ".json")).exists():
        name, i = f"{base}-{i}", i + 1
    os.replace(path, trash / name)
    atomic_write_text(trash / (name + ".json"), _json.dumps({"z": str(original), "kiedy": _time.time()}, ensure_ascii=False))
    return name
