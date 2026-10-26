"""
sources.py - Źródła: foldery na tym komputerze, które GREGAI ma prawo
czytać i analizować, dodawane przez użytkownika z interfejsu, oraz pliki
wgrane wprost do rozmowy.

Prośba Grzegorza (2026-10-19): "połącz z komputerem, tzn daj możliwość
dodawania sobie ścieżek do folderów oraz analizy plików, które mu się da".

Dotąd jedyny sposób to SYSOP_ROOTS w .env (lista ścieżek po ":") plus
restart usługi - a zasada projektu mówi, że .env jest plikiem sekretów,
którego GREGAI sam nie dotyka. Stąd osobny, zwykły plik stanu
data/sources.json (jak heartbeat_state.json czy standing_alerts.json):
użytkownik dodaje i usuwa foldery z interfejsu (sekcja "Źródła tej
rozmowy"), bez restartu, a reguły bezpieczeństwa są DOKŁADNIE te same, co
dla SYSOP_ROOTS (sysop.roots): nigdy cały katalog domowy, nigdy "/", nigdy
katalog zawierający domowy, nigdy foldery prywatne (klucze SSH, profile
przeglądarek, menedżery haseł - sysop._PRIVATE_HOME) ani katalogi
systemowe z sekretami (/etc, /root...). Folder musi istnieć i być
katalogiem w chwili dodania. Odrzucenie zawsze mówi dlaczego.

INDYWIDUALNIE DLA KAŻDEJ ROZMOWY (1.9.1, decyzja Grzegorza: "niech źródła
będą indywidualne do każdego czatu"): rozmowa to "Ogólna rozmowa" (id
"ogolna") albo projekt (id = slug projektu, ten sam, który główna rozmowa
dostaje jako `project` z przeglądarki). Każda ma WŁASNĄ listę folderów i
WŁASNY katalog plików wgranych (data/wgrane/<id>/). Folder dodany w
rozmowie o fakturach nie istnieje dla rozmowy o YouTube; plik wgrany w
projekcie A nie jest znajdowany po nazwie w projekcie B. To ten sam duch,
co izolacja notatek projektu (vault.project_scope): rozmowa widzi tylko to,
co do niej należy. Stary format pliku (jedna wspólna lista "foldery")
jest przy pierwszym odczycie przepisywany do "Ogólnej rozmowy".

Pliki wgrane z rozmowy (spinacz w interfejsie, POST /api/upload) trafiają
do data/wgrane/<id rozmowy>/ - plik "dany" GREGAI w tej rozmowie jest z
definicji do przeczytania w tej rozmowie. Limit rozmiaru, lista rozszerzeń
(te, które agent/analiza.py umie przeczytać), bezpieczna nazwa (bez
ścieżek, bez kropki na początku), nigdy nadpisanie istniejącego.

Uprawnienia: narzędzia plikowe SYSOP (fs_read/fs_list/fs_search) nie
znają kontekstu rozmowy, więc widzą TYLKO SYSOP_ROOTS jak dotąd. Namysł
(agent/namysl.py) dostaje id rozmowy i czyta w: SYSOP_ROOTS + foldery TEJ
rozmowy + wgrane TEJ rozmowy (chat_roots, resolve_in_chat). Nigdy więcej.

Ten moduł nie czyta treści plików (to analiza.py) i nie decyduje, co z
nimi zrobić (to namysl.py). Tylko: gdzie wolno patrzeć w tej rozmowie, i
szukanie pliku po nazwie w tych miejscach (find_by_name), żeby
"przeanalizuj umowę.pdf" działało bez wpisywania pełnej ścieżki.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

import data as data_mod
import fsutil

DATA_DIR = Path(data_mod.PROJECT_ROOT) / "data"
STATE_PATH = DATA_DIR / "sources.json"
UPLOAD_DIR = DATA_DIR / "wgrane"

MAX_SOURCES = 24
# Rozmiar jednego wgranego pliku: 25 MB wystarcza na obszerny PDF/arkusz,
# a nie pozwala zapchać dysku jednym żądaniem.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UPLOADS_TOTAL_BYTES = 1024 * 1024 * 1024
UPLOAD_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".conf", ".log", ".py", ".js", ".ts", ".html", ".htm", ".css", ".sh", ".sql", ".xml", ".tex", ".srt", ".vtt",
    ".pdf", ".docx", ".xlsx",
})
# Szukanie pliku po nazwie: najwyżej tyle katalogów przeglądamy (głębokość i
# liczba), żeby "przeanalizuj raport.pdf" nie kazało czekać na skan dysku.
FIND_MAX_DEPTH = 4
FIND_MAX_DIRS = 400

# Katalogi, których NIGDY nie dodamy jako źródło (poza regułami z sysop.roots):
# zawierają sekrety systemu albo cudze dane.
_FORBIDDEN_ABS = ("/etc", "/root", "/boot", "/proc", "/sys", "/dev", "/run", "/var/lib", "/var/log")

_LOCK = threading.Lock()
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ._ -]+")
_CHAT_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
GENERAL_CHAT = "ogolna"
MAX_CHAT_ID = 80


def chat_id(raw) -> str:
    """Id rozmowy jako bezpieczny fragment ścieżki: slug projektu (litery,
    cyfry, kropka, -, _; slug notatki ma rozszerzenie, np. "faktury.md" - kropka
    zostaje, żeby id po obu stronach, w przeglądarce i tu, było identyczne)
    albo "ogolna" dla Ogólnej rozmowy / braku / śmieci. Nigdy "..", nigdy
    kropka na początku: to ma być JEDEN segment ścieżki w data/wgrane/."""
    text = raw.strip() if isinstance(raw, str) else ""
    text = _CHAT_ID_RE.sub("-", text)
    text = re.sub(r"\.{2,}", ".", text).strip("-._")[:MAX_CHAT_ID]
    return text or GENERAL_CHAT


def _load(strict: bool = False) -> dict:
    """{"czaty": {id: [ścieżki]}}; stary format {"foldery": [...]} (1.9.0)
    trafia do Ogólnej rozmowy. 1.32.3 (audyt tura 8): strict=True (zapis) przy błędzie
    odczytu dysku rzuca wyjątek - dawniej puste {} i zapis kasował foldery innych rozmów;
    poprawny JSON złego typu idzie do kwarantanny jak zepsuty."""
    try:
        raw = STATE_PATH.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {"czaty": {}}
    except OSError:
        if strict:
            raise
        return {"czaty": {}}
    try:
        state = json.loads(raw)
    except ValueError:
        fsutil.quarantine(STATE_PATH)
        return {"czaty": {}}
    if not isinstance(state, dict):
        fsutil.quarantine(STATE_PATH)
        return {"czaty": {}}
    czaty = state.get("czaty")
    if not isinstance(czaty, dict):
        czaty = {}
        legacy = state.get("foldery")
        if isinstance(legacy, list) and legacy:
            czaty[GENERAL_CHAT] = legacy
    clean: dict[str, list[str]] = {}
    for key, val in czaty.items():
        if isinstance(key, str) and isinstance(val, list):
            lst = [f for f in val if isinstance(f, str) and f]
            if lst:
                clean[chat_id(key)] = lst
    return {"czaty": clean}


def _save(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write_text(STATE_PATH, json.dumps(state, ensure_ascii=False, indent=2))


def folders(chat: str | None = None) -> list[Path]:
    """Foldery TEJ rozmowy (tylko te, które nadal istnieją i nadal spełniają
    reguły - folder usunięty z dysku albo podmieniony na dowiązanie do
    katalogu domowego po prostu znika z listy, bez wyjątku)."""
    cid = chat_id(chat)
    with _LOCK:
        state = _load()
    out = []
    for raw in state["czaty"].get(cid, []):
        ok, _why, resolved = _validate(raw)
        if ok and resolved is not None:
            out.append(resolved)
    return out


def upload_root(chat: str | None = None) -> Path:
    return UPLOAD_DIR / chat_id(chat)


def _private_names() -> tuple[str, ...]:
    try:
        import sysop as sysop_mod
        return tuple(sysop_mod._PRIVATE_HOME)
    except Exception:
        return (".ssh", ".gnupg", ".mozilla", ".aws", ".password-store")


def _validate(raw: str) -> tuple[bool, str, Path | None]:
    text = (raw or "").strip()
    if not text:
        return False, "podaj ścieżkę folderu", None
    p = Path(os.path.expanduser(text))
    if not p.is_absolute():
        return False, "podaj ścieżkę bezwzględną (zaczynającą się od / albo ~)", None
    try:
        r = p.resolve()
    except Exception:
        return False, "nie da się rozwiązać tej ścieżki", None
    if not r.exists():
        return False, "ten folder nie istnieje", None
    if not r.is_dir():
        return False, "to nie jest folder (plik dodaj spinaczem w rozmowie)", None
    home = Path(os.path.expanduser("~")).resolve()
    if r == Path("/") or r == home or r in home.parents:
        return False, "cały katalog domowy (ani katalog nad nim, ani /) nie może być źródłem - są tam klucze i hasła; wskaż konkretny folder, np. ~/Dokumenty/Faktury", None
    for forb in _FORBIDDEN_ABS:
        fp = Path(forb)
        if r == fp or fp in r.parents:
            return False, f"katalogi systemowe ({forb}) nie mogą być źródłem", None
        # 1.27.0 (audyt): także folder NAD katalogiem systemowym ("/var" zawiera /var/log).
        if r in fp.parents:
            return False, f"ten folder zawiera katalog systemowy ({forb}); wskaż węższy folder", None
    for name in _private_names():
        private = (home / name).resolve()
        if r == private or private in r.parents:
            return False, f"folder prywatny (~/{name}) nie może być źródłem", None
    # 1.32.3 (audyt tura 8): data/ GREGAI (wgrane pliki wszystkich rozmów, historie, dziennik
    # bezpieczeństwa) nie może być źródłem. Folder NAD nim (np. ~/Dokumenty) może - pliki z
    # data/ i tak odpadają przy odczycie (resolve_in_chat).
    try:
        d = DATA_DIR.resolve()
        if r == d or d in r.parents:
            return False, "folder danych GREGAI (data/) nie może być źródłem", None
    except Exception:
        pass
    return True, "", r


def add(chat: str | None, raw: str) -> dict:
    """{"ok", "why", "foldery": [...]} - dodanie do TEJ rozmowy z walidacją;
    duplikat to nie błąd (lista bez zmian)."""
    cid = chat_id(chat)
    ok, why, resolved = _validate(raw)
    if not ok or resolved is None:
        return {"ok": False, "why": why, "chat": cid, "foldery": [str(f) for f in folders(cid)]}
    with _LOCK:
        state = _load(strict=True)
        current = list(state["czaty"].get(cid, []))
        if str(resolved) not in current:
            if len(current) >= MAX_SOURCES:
                return {"ok": False, "why": f"najwyżej {MAX_SOURCES} źródeł w jednej rozmowie - usuń jakieś, zanim dodasz kolejne",
                        "chat": cid, "foldery": current}
            current.append(str(resolved))
            state["czaty"][cid] = current
            _save(state)
    return {"ok": True, "why": "", "chat": cid, "foldery": [str(f) for f in folders(cid)]}


def remove(chat: str | None, raw: str) -> dict:
    cid = chat_id(chat)
    text = (raw or "").strip()
    with _LOCK:
        state = _load(strict=True)
        current = list(state["czaty"].get(cid, []))
        before = len(current)
        try:
            resolved = str(Path(os.path.expanduser(text)).resolve()) if text else ""
        except Exception:
            resolved = ""
        current = [f for f in current if f != text and f != resolved]
        changed = len(current) != before
        if changed:
            if current:
                state["czaty"][cid] = current
            else:
                state["czaty"].pop(cid, None)
            _save(state)
    return {"ok": changed, "why": "" if changed else "nie ma takiego źródła w tej rozmowie",
            "chat": cid, "foldery": [str(f) for f in folders(cid)]}


def delete_chat(chat: str | None) -> dict:
    """Usuwa WSZYSTKO, co rozmowa ma w Źródłach (1.12.0, kosz w szynie rozmów):
    listę folderów z data/sources.json i katalog wgranych plików
    data/wgrane/<rozmowa>/. Foldery użytkownika (np. ~/Dokumenty/Faktury) NIE
    są ruszane - znika tylko wpis "ta rozmowa może je czytać". Kasowane jest
    wyłącznie to, co leży WPROST w upload_root (nigdy dowiązanie, nigdy nic
    spoza katalogu wgranych)."""
    cid = chat_id(chat)
    with _LOCK:
        state = _load(strict=True)
        had_folders = len(state["czaty"].get(cid, []))
        if cid in state["czaty"]:
            state["czaty"].pop(cid, None)
            _save(state)
    removed = 0
    root = upload_root(cid)
    try:
        base = UPLOAD_DIR.resolve()
        if root.exists() and not root.is_symlink() and root.resolve().parent == base:
            removed = sum(1 for p in root.iterdir() if p.is_file())
            shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass
    return {"chat": cid, "foldery": had_folders, "wgrane": removed}


def status(chat: str | None = None) -> dict:
    cid = chat_id(chat)
    with _LOCK:
        state = _load()
    rows = []
    for raw in state["czaty"].get(cid, []):
        ok, why, resolved = _validate(raw)
        rows.append({"sciezka": raw, "ok": ok, "why": why})
    root = upload_root(cid)
    try:
        uploads = sorted(p.name for p in root.iterdir() if p.is_file() and not p.name.startswith("."))
    except OSError:
        uploads = []
    return {"chat": cid, "foldery": rows, "wgrane": uploads[-50:], "wgrane_katalog": str(root), "limit": MAX_SOURCES}


def safe_upload_name(filename: str) -> str | None:
    """Sama nazwa (bez katalogów), dozwolone znaki, dozwolone rozszerzenie,
    nigdy ukryty plik ani .env*. None = odrzucone."""
    base = os.path.basename((filename or "").replace("\\", "/")).strip()
    base = _SAFE_NAME_RE.sub("_", base).strip(" ._")
    if not base or base.startswith(".env") or len(base) > 120:
        return None
    if Path(base).suffix.lower() not in UPLOAD_SUFFIXES:
        return None
    return base


def save_upload(chat: str | None, filename: str, data: bytes) -> dict:
    """{"ok", "why", "path", "name", "size"} - plik do data/wgrane/<rozmowa>/
    <data>-<nazwa>, wyłączne utworzenie (nigdy nadpisanie), licznik przy
    kolizji nazw."""
    if len(data) > MAX_UPLOAD_BYTES:
        return {"ok": False, "why": f"plik ma {len(data) // (1024 * 1024)} MB, limit to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"}
    if not data:
        return {"ok": False, "why": "pusty plik"}
    name = safe_upload_name(filename)
    if name is None:
        return {"ok": False, "why": "niedozwolona nazwa albo rozszerzenie (umiem: tekst, markdown, kod, csv, json, pdf, docx, xlsx)"}
    root = upload_root(chat)
    root.mkdir(parents=True, exist_ok=True)
    # 1.32.17 (audyt tura 19): liczenie "used" i zapis pliku to jedna operacja
    # check-then-act - BEZ blokady dwa równoległe wgrania (dwie karty, dwa
    # żądania naraz) liczyły "used" PRZED tym, jak którekolwiek zapisało swój
    # plik, więc oba widziały miejsce pod limitem i oba przechodziły, omijając
    # MAX_UPLOADS_TOTAL_BYTES łącznie o rozmiar dodatkowego pliku. Cała funkcja
    # (liczenie + zapis) idzie teraz pod _LOCK, tak jak już robią to
    # folders()/remove()/delete_chat()/status() w tym module.
    with _LOCK:
        # 1.32.10 (audyt tura 14): łączny limit wgranych plików (dysk i pamięć laptopa).
        try:
            used = sum(p.stat().st_size for p in upload_root(None).parent.rglob("*") if p.is_file())
        except OSError:
            used = 0
        if used + len(data) > MAX_UPLOADS_TOTAL_BYTES:
            return {"ok": False, "why": f"wgrane pliki zajmują już {used // (1024 * 1024)} MB z {MAX_UPLOADS_TOTAL_BYTES // (1024 * 1024)} MB; "
                                        "usuń starą rozmowę z plikami (kosz w panelu rozmowy)"}
        stem, suffix = Path(name).stem, Path(name).suffix
        date = datetime.now().strftime("%Y-%m-%d")
        candidate = root / f"{date}-{stem}{suffix}"
        counter = 2
        # 1.29.0 (kontrola): zapis przez plik tymczasowy z fsync i twardym dowiązaniem
        # (jak fsutil.create_new_text) - pełny dysk albo utrata prądu nie zostawiają
        # uciętego pliku, który dałoby się potem dołączyć jako "wgrany".
        import tempfile
        try:
            fd, tmp = tempfile.mkstemp(prefix=fsutil.TMP_PREFIX, suffix=".tmp", dir=str(root))
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as e:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            return {"ok": False, "why": f"nie udało się zapisać pliku ({type(e).__name__}; pełny dysk?)"}
        while True:
            try:
                os.link(tmp, candidate)
                break
            except FileExistsError:
                candidate = root / f"{date}-{stem}-{counter}{suffix}"
                counter += 1
                if counter > 999:
                    os.unlink(tmp)
                    return {"ok": False, "why": "za dużo plików o tej nazwie"}
            except OSError as e:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return {"ok": False, "why": f"nie udało się zapisać pliku ({type(e).__name__})"}
        try:
            os.unlink(tmp)
        except OSError:
            pass
        try:
            os.chmod(candidate, 0o644)
        except OSError:
            pass
        return {"ok": True, "why": "", "path": str(candidate), "name": candidate.name, "size": len(data)}


def chat_roots(chat: str | None) -> list[Path]:
    """Gdzie wolno czytać w TEJ rozmowie: SYSOP_ROOTS (z .env, jak dotąd) +
    foldery tej rozmowy + jej katalog wgranych. Nic z innych rozmów."""
    import sysop as sysop_mod  # leniwie: sysop importuje data/fsutil, nie ten moduł, ale trzymamy jeden kierunek
    out: list[Path] = []
    for p in list(sysop_mod.roots()) + folders(chat) + [upload_root(chat)]:
        try:
            r = p.resolve()
        except Exception:
            continue
        if r not in out:
            out.append(r)
    return out


def resolve_in_chat(chat: str | None, path_text: str) -> Path | None:
    """Pełna ścieżka pliku, jeśli leży w korzeniach tej rozmowy i nie jest
    plikiem sekretów ani prywatnym (te same reguły co sysop.resolve_in_roots,
    tylko z korzeniami rozmowy)."""
    import sysop as sysop_mod
    try:
        p = Path((path_text or "").strip().strip("'\"")).expanduser()
        if not p.is_absolute():
            p = Path(data_mod.PROJECT_ROOT) / p
        p = p.resolve()
    except Exception:
        return None
    name = p.name.lower()
    if name.startswith(".env") or ".env." in name or name.endswith(".env"):
        return None
    sp = str(p)
    if any(sp == f or sp.startswith(f + "/") for f in _FORBIDDEN_ABS):
        return None  # 1.27.0: katalogi systemowe także per plik (np. dowiązanie do /var/log)
    try:
        if sysop_mod._is_private(str(p)) or sysop_mod._PRIVATE_WORD.search(str(p)):
            return None
    except Exception:
        return None
    # Audyt 1.32.1: domyślny SYSOP_ROOTS to katalog projektu, a w nim data/ - z
    # wgranymi plikami WSZYSTKICH rozmów, historią i dziennikami. Z data/ wolno
    # czytać tylko katalog wgranych TEJ rozmowy.
    try:
        data_dir = DATA_DIR.resolve()
        if p == data_dir or data_dir in p.parents:
            # Wyjątki: wgrane TEJ rozmowy i folder W ŚRODKU data/, który Grzegorz sam dodał do
            # TEJ rozmowy (dodany folder NAD data/, np. ~/Dokumenty, nie otwiera data/).
            allowed = [upload_root(chat).resolve()] + [
                f.resolve() for f in folders(chat) if f.resolve() == data_dir or data_dir in f.resolve().parents]
            if not any(p == a or a in p.parents for a in allowed):
                return None
        # 1.32.10 (audyt tura 14): fakty z „Zapamiętaj” (memory/) i kod/prompty GREGAI (agent/)
        # nie są "plikami do analizy" - inaczej szły jako materiał do AI w sieci.
        for closed in (Path(data_mod.MEMORY_ROOT).resolve(), (Path(data_mod.PROJECT_ROOT) / "agent").resolve()):
            if p == closed or closed in p.parents:
                return None
    except Exception:
        return None
    for root in chat_roots(chat):
        if p == root or root in p.parents:
            return p
    return None


def find_by_name(name: str, roots: list[Path]) -> list[Path]:
    """Pliki o tej nazwie (bez względu na wielkość liter) w dozwolonych
    korzeniach, płytko (FIND_MAX_DEPTH), z limitem przejrzanych katalogów.
    Pomija katalogi prywatne i ukryte."""
    wanted = os.path.basename(name or "").strip().lower()
    if not wanted:
        return []
    hits: list[Path] = []
    seen_dirs = 0
    private = set(_private_names())
    for root in roots:
        try:
            root = root.resolve()
        except Exception:
            continue
        stack = [(root, 0)]
        while stack and seen_dirs < FIND_MAX_DIRS:
            d, depth = stack.pop()
            seen_dirs += 1
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for e in entries:
                n = e.name
                if n.startswith(".") or n in private or n in ("__pycache__", "node_modules", "backups"):
                    continue
                try:
                    # 1.27.0 (audyt): nie schodzimy w dowiązania do katalogów (cfg -> ~/.docker).
                    if e.is_dir() and not e.is_symlink():
                        if depth < FIND_MAX_DEPTH:
                            stack.append((e, depth + 1))
                    elif e.is_file() and n.lower() == wanted:
                        hits.append(e)
                except OSError:
                    continue
    return hits[:10]


def find_by_name_in_chat(chat: str | None, name: str, roots: list[Path]) -> list[Path]:
    """find_by_name + te same reguły co pełna ścieżka (resolve_in_chat): plik będący
    dowiązaniem do klucza SSH czy ~/.docker/config.json odpada (1.27.0, audyt)."""
    out: list[Path] = []
    for hit in find_by_name(name, roots):
        ok = resolve_in_chat(chat, str(hit))
        if ok is not None and ok not in out:
            out.append(ok)
    return out
