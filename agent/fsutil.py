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

import errno
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:  # Linux/Unix; na innych systemach zostaje sam zamek wątków
    import fcntl
except ImportError:  # pragma: no cover - projekt docelowo działa na Ubuntu
    fcntl = None

# Nowy plik z danymi GREGAI (rozmowy, ślady, uczenie) jest prywatny. Istniejący
# plik zachowuje swoje prawa (np. .env = 600, notatka = 644).
PRIVATE_MODE = 0o600

# 1.32.28 (audyt #1): jeden zamek MIĘDZYPROCESOWY na data/. flock jest
# reentrantny w obrębie wątku (licznik głębokości), więc moduł może wołać
# data_lock() także z funkcji, która już go trzyma (np. _save wewnątrz
# learn_from_resolution).
_DATA_DIR = Path(__file__).parent.parent / "data"
_DATA_LOCK_PATH = _DATA_DIR / ".gregai.lock"
_DATA_LOCK_STATE = threading.local()


@contextmanager
def data_lock():
    """Wyłączny zamek na data/ dla TEJ instalacji (między procesami).

    Chroni read-modify-write plików JSON/JSONL, których pilnuje też zwykły
    threading.Lock w module: drugi proces (np. `gregai eval`) nie nadpisze
    zmiany pierwszego. Zamek jest reentrantny w obrębie wątku; błąd systemu
    plików nie może wywrócić zapisu danych - wtedy zostaje tylko zamek wątków."""
    depth = getattr(_DATA_LOCK_STATE, "depth", 0)
    if depth:
        _DATA_LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            _DATA_LOCK_STATE.depth = depth
        return
    handle = None
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        handle = open(_DATA_LOCK_PATH, "a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        handle = None
    _DATA_LOCK_STATE.depth = 1
    try:
        yield
    finally:
        _DATA_LOCK_STATE.depth = 0
        if handle is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                handle.close()
            except OSError:
                pass

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


def trash_name_ok(name: str) -> bool:
    """Czy nazwa wpisu w koszu jest bezpieczna: jeden segment ścieżki, bez
    przejścia w górę i bez NUL-a, najwyżej 255 bajtów UTF-8. 1.32.29 (audyt #3)."""
    if not isinstance(name, str) or not name or name in (".", "..") or "\x00" in name:
        return False
    if "/" in name or "\\" in name or ".." in name:
        return False
    try:
        return len(name.encode("utf-8", "surrogatepass")) <= 255
    except UnicodeEncodeError:
        return False


def _trim_filename_bytes(text: str, limit: int) -> str:
    """Obcina napis tak, żeby po zakodowaniu w UTF-8 miał najwyżej `limit` bajtów
    (limit dotyczy nazwy pliku na dysku, nie liczby znaków)."""
    limit = max(0, limit)
    if len(text.encode("utf-8", "surrogatepass")) <= limit:
        return text
    while text and len(text.encode("utf-8", "surrogatepass")) > limit:
        text = text[:-1]
    return text


def move_to_trash(path, trash_dir, original: str) -> str:
    """Przenosi plik do kosza (zamiast kasować) i zapisuje obok, skąd przyszedł.
    Zwraca nazwę wpisu w koszu (do przywrócenia). Nic nie jest usuwane na zawsze.

    1.32.29 (audyt #4): metadane powstają najpierw w pliku tymczasowym, plik
    idzie do kosza, a na końcu metadane są atomowo przemianowywane. Błąd
    któregokolwiek kroku cofa przeniesienie. Na innym systemie plików
    (EXDEV) zamiast os.replace jest shutil.move (kopiuj i usuń)."""
    trash = Path(trash_dir)
    trash.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = stamp + "-" + Path(path).name
    if len((base + ".json").encode("utf-8", "surrogatepass")) > 255:
        digest = hashlib.sha256(str(path).encode("utf-8", "surrogatepass")).hexdigest()[:12]
        tail = f"-{digest}"
        base = _trim_filename_bytes(base, 255 - len((tail + ".json").encode("utf-8"))) + tail
    name, i = base, 2
    while (trash / name).exists() or (trash / (name + ".json")).exists():
        suffix = f"-{i}"
        name = _trim_filename_bytes(base, 255 - len((suffix + ".json").encode("utf-8"))) + suffix
        i += 1
    dest = trash / name
    meta = trash / (name + ".json")
    fd, meta_tmp = tempfile.mkstemp(prefix=TMP_PREFIX, suffix=".tmp", dir=str(trash))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps({"z": str(original), "kiedy": time.time()}, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(meta_tmp, PRIVATE_MODE)
        moved = False
        try:
            try:
                os.replace(path, dest)
                moved = True
            except OSError as e:
                if e.errno != errno.EXDEV:
                    raise
                shutil.move(str(path), str(dest))
                moved = True
            os.replace(meta_tmp, meta)
            meta_tmp = None
        except BaseException:
            if moved:
                try:
                    if dest.exists():
                        try:
                            os.replace(dest, path)
                        except OSError as e:
                            if e.errno != errno.EXDEV:
                                raise
                            shutil.move(str(dest), str(path))
                except OSError:
                    pass
            raise
    finally:
        if meta_tmp is not None:
            try:
                os.unlink(meta_tmp)
            except OSError:
                pass
    return name
