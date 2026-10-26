"""
main.py

Serwer HTTP GREGAI. Standardowa biblioteka Pythona + Ollama przez
zwykłe żądania HTTP (bez SDK).

Uruchomienie:
    python3 agent/main.py

Dostęp sieciowy sterowany GREGAI_LAN (odczytywany tylko tutaj):
    GREGAI_LAN=0 (domyślnie) -> tylko localhost
    GREGAI_LAN=1 -> nasłuch na 0.0.0.0, wymaga GREGAI_TOKEN w .env;
                     każde żądanie /api/ spoza 127.0.0.1 musi podać ten
                     token w nagłówku X-Gregai-Token, inaczej 403.

Pliki interfejsu (/, /debug, *.js, *.css) są dostępne bez tokenu: nie
zawierają żadnych danych, a przeglądarka i tak nie dołącza własnych
nagłówków do zwykłego wejścia na stronę, więc bez tego nie dałoby się
nawet otworzyć strony z innego komputera, żeby podać token. Wszystkie
dane i akcje idą przez /api/ i tam token jest wymagany.

Pośrednik (reverse proxy, tunel) łączy się z serwerem z 127.0.0.1, więc samo
IP nie odróżnia "ta maszyna" od "ktoś z internetu przez pośrednika".
Żądanie z nagłówkami pośrednika (CF-Connecting-IP, X-Forwarded-For itd.)
jest traktowane jak zdalne: token wymagany zawsze, także przy
GREGAI_LAN=0. Patrz _authorized().
"""

from __future__ import annotations

import errno
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))

from env_loader import load_env, set_env_vars  # noqa: E402

# KRYTYCZNE: load_env() MUSI wykonać się PRZED importem router.py i każdego
# innego modułu, który czyta os.environ na poziomie modułu (np. OLLAMA_MODEL w
# router.py liczone raz, przy imporcie). Inaczej moduł zamroziłby wartość
# domyślną zamiast tej z .env, także po restarcie przez os.execve.
# Kopia środowiska sprzed wczytania .env służy restartowi z /debug: nowy proces
# startuje od niej, więc ustawienie USUNIĘTE z .env nie przeżywa restartu.
_PRE_ENV_SNAPSHOT = dict(os.environ)
load_env()

import persona as persona_mod  # noqa: E402
import vault as vault_mod  # noqa: E402
import data as data_mod  # noqa: E402
import fsutil  # noqa: E402
import router as router_mod  # noqa: E402
import koryto as koryto_mod  # noqa: E402
import learning as learning_mod  # noqa: E402
import trace as trace_mod  # noqa: E402
import heartbeat as heartbeat_mod  # noqa: E402
import standing as standing_mod  # noqa: E402
import straz as straz_mod  # noqa: E402
import juggler as juggler_mod  # noqa: E402
import awareness as awareness_mod  # noqa: E402
import namysl as namysl_mod  # noqa: E402
import sources as sources_mod  # noqa: E402
import agentloop as agentloop_mod  # noqa: E402
import rozmowa as rozmowa_mod  # noqa: E402
import sysinfo as sysinfo_mod  # noqa: E402
import sysop as sysop_mod  # noqa: E402
import netguard as netguard_mod  # noqa: E402
import tryby as tryby_mod  # noqa: E402

UI_DIR = Path(__file__).parent.parent / "ui"


def _read_version() -> str:
    try:
        return (Path(__file__).parent.parent / "VERSION").read_text(encoding="utf-8", errors="replace").strip()[:40] or "?"
    except OSError:
        return "?"


VERSION = _read_version()
PROMPT_PATH = Path(__file__).parent / "prompt.md"
PORT = 7777

LAN_MODE = os.environ.get("GREGAI_LAN", "0") == "1"
BIND_HOST = "0.0.0.0" if LAN_MODE else "localhost"
GREGAI_TOKEN = os.environ.get("GREGAI_TOKEN", "")
# Nagłówki dokładane przez pośredników (Cloudflare Tunnel, reverse proxy):
# ich obecność = żądanie NIE pochodzi bezpośrednio z tej maszyny.
PROXY_HEADERS = ("CF-Connecting-IP", "CF-Ray", "CF-Visitor", "X-Forwarded-For", "X-Real-IP", "Forwarded")

# Największe przyjmowane żądanie POST (notatka, rozmowa z historią). Większe
# dostaje 413 bez wczytywania: jedno złośliwe Content-Length nie zje pamięci.
# Zapas ponad rozmiar notatki, bo JSON podwaja np. znaki nowej linii (\n).
MAX_BODY_BYTES = 2 * vault_mod.MAX_FILE_BYTES + 64 * 1024
# Wgrywanie pliku do rozmowy (POST /api/upload, agent/sources.py): JSON z
# zawartością w base64 (ten sam Content-Type co reszta POST-ów, więc ta sama
# ochrona CSRF), stąd limit ciała = limit pliku x 4/3 + zapas na nazwę.
MAX_UPLOAD_BODY_BYTES = sources_mod.MAX_UPLOAD_BYTES * 4 // 3 + 16 * 1024
# 1.30.0 (Twierdza): blokada zgadywania tokenu LAN.
AUTH_MAX_FAILS = 8
AUTH_WINDOW_S = 600
AUTH_BAN_S = 900
_AUTH_LOCK = threading.Lock()
_AUTH_FAILS: dict = {}
_AUTH_BANNED: dict = {}


def _security_event(kind: str, text: str) -> None:
    """Zdarzenie bezpieczeństwa: dziennik bezpieczeństwa (nie da się po cichu wyczyścić) + alert w rozmowie."""
    try:
        straz_mod.log_security(kind, text)
    except Exception:
        pass
    try:
        standing_mod._queue_alert("Straż systemu", text[:500])
    except Exception:
        pass


_BAD_TITLE_RE = re.compile(r"[\[\]|#]")
# 1.32.3 (audyt tura 8): znaki sterujące i kierunku tekstu (NUL, RTL override) w tytule -
# podrabiany wygląd tytułu, a plik z NUL narzędzia biorą za binarny.
_CTRL_TITLE_RE = re.compile("[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
BAD_TITLE_TEXT = "Tytuł nie może zawierać znaków [ ] | # (psują powiązania między notatkami). Zmień je, np. „C#” na „C sharp”."
NOTE_TOO_BIG = ("Notatka jest za duża (najwyżej 2 MB): GREGAI pomija większe pliki, więc "
                "po zapisie by zniknęła z grafu. Podziel ją na kilka notatek.")

# Tylko pliki tekstowe da się bezpiecznie zapisać z interfejsu. Notatka
# wczytana z PDF to wyciągnięty tekst: zapis go do pliku zniszczyłby oryginał.
WRITABLE_SUFFIXES = {".md", ".txt"}
READONLY_MESSAGE = ("Ta notatka pochodzi z pliku PDF (tylko do odczytu). "
                    "Zmień albo usuń oryginał w menedżerze plików.")
LOSSY_MESSAGE = ("Ten plik nie jest zapisany w UTF-8 (np. Windows-1250), więc jest tylko do odczytu: "
                 "zapis z interfejsu zgubiłby polskie znaki. Zapisz go w UTF-8 w edytorze tekstu.")

# Nagłówki bezpieczeństwa na każdej odpowiedzi. CSP: skrypty tylko z własnego
# serwera (żadnego inline, żadnych obcych), połączenia tylko do siebie, strona
# nie może być wstawiona w ramkę. Style też tylko z plików: bez „unsafe-inline”
# nawet wstrzyknięty znacznik nie nałoży własnego wyglądu (np. fałszywej karty).
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}

_vault_cache = None
_vault_gen = 0
_vault_lock = threading.Lock()
_vault_build_lock = threading.Lock()  # jedna budowa vault naraz (patrz get_vault)
# Notatki można zmienić poza interfejsem (edytor, menedżer plików). Raz na tyle
# sekund sprawdzamy tani odcisk plików (vault.disk_signature) i budujemy vault
# od nowa, gdy się zmienił; między sprawdzeniami służy cache.
VAULT_RESCAN_SECONDS = 3.0
_vault_sig = None
_vault_sig_at = 0.0
_system_prompt_cache = None
# Zapis, utworzenie i usunięcie notatki z interfejsu wykonują się po kolei:
# zapis z przepisywaniem linków w innych notatkach nie przeplata się z drugim.
_LAST_RESTART = -1e9
_NOTE_LOCK = fsutil.NOTES_LOCK  # 1.32.10: wspólna z tools.save_note
TRASH_DIR = data_mod.PROJECT_ROOT / "data" / "kosz"  # 1.32.10: usunięte notatki (do przywrócenia)

# --- Czat jako zadanie w tle (2026-10-09) -----------------------------------
# Duży model na tym CPU potrafi odpowiadać kilka minut (zimna pamięć
# podręczna, patrz router.py: RICH_TIMEOUT), a przeglądarka (Firefox)
# zrywa żądanie, na które serwer nie odpowiada 300 s. Dlatego POST /api/chat
# czeka na odpowiedź najwyżej CHAT_WAIT sekund: jeśli jest gotowa, wraca od
# razu jak dotąd; jeśli nie, wraca {"pending_job": id}, a przeglądarka pyta
# dalej przez POST /api/chat/wait {"job": id} (te same zabezpieczenia co
# każdy POST). Rozmowy wykonują się po kolei (_CHAT_LOCK): na dwóch rdzeniach
# równoległe i tak stałyby w kolejce Ollamy, a pliki nauki (learning,
# decision_log) zapisuje wtedy zawsze jeden wątek.
CHAT_WAIT = 240
# Pierwsze czekanie w POST /api/chat (1.9.0, narracja Namysłu na żywo): szybka
# odpowiedź (narzędzie, krótka rozmowa z sieci) nadal wraca od razu, ale gdy
# trwa dłużej, przeglądarka dostaje id zadania już po tylu sekundach i od
# razu zaczyna pokazywać, co się dzieje (GET /api/chat/progress), zamiast
# patrzeć w pusty dymek przez pierwsze minuty.
CHAT_FIRST_WAIT = 2.0
CHAT_JOB_TTL = 3600
# Rozmowa, o którą przeglądarka nie pytała dłużej niż tyle sekund (jedno pytanie
# trwa najwyżej CHAT_WAIT, potem przeglądarka od razu pyta znowu), jest porzucona.
CHAT_ABANDON_AFTER = CHAT_WAIT + 30
# Najdłuższa wiadomość czatu (znaki). Dłuższy wklejony tekst to notatka, nie czat.
MAX_CHAT_CHARS = 20000
# Ile rozmów może naraz czekać w kolejce na model (wykonują się po kolei).
MAX_ACTIVE_CHAT_JOBS = 8


def _pl_count(n, one: str, few: str, many: str) -> str:
    """„1 plik”, „3 pliki”, „5 plików”, „22 pliki”, „12 plików”."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return f"{n} {many}"
    if n == 1:
        return f"1 {one}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {few}"
    return f"{n} {many}"


def _scrub_surrogates(value):
    """JSON dopuszcza samotne surogaty ("\\ud800"), a takiego tekstu nie da się zapisać w
    UTF-8: wiadomość z nim zatruwała ślad decyzji (każdy kolejny zapis się wywalał).
    Usuwamy je zaraz po wczytaniu treści żądania, we wszystkich napisach."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return value
        except UnicodeEncodeError:
            return value.encode("utf-8", "ignore").decode("utf-8")
    if isinstance(value, list):
        return [_scrub_surrogates(v) for v in value]
    if isinstance(value, dict):
        return {_scrub_surrogates(k): _scrub_surrogates(v) for k, v in value.items()}
    return value


def _parse_body(raw_body: bytes):
    """Treść żądania POST jako JSON (ValueError, gdy to nie JSON albo jest zagnieżdżony
    tak głęboko, że parser by się przewrócił)."""
    try:
        return _scrub_surrogates(json.loads(raw_body or b"{}"))
    except RecursionError as e:
        raise ValueError("JSON zagnieżdżony zbyt głęboko") from e


def _error_text(e: Exception) -> str:
    """Komunikat dla użytkownika bez ścieżek i nazw plików tymczasowych (te
    zostają w dzienniku: journalctl -u gregai)."""
    sys.stderr.write(f"BŁĄD: {type(e).__name__}: {e}\n")
    if isinstance(e, PermissionError):
        return "Brak uprawnień do zapisu w folderze notatek."
    if isinstance(e, FileNotFoundError):
        return "Nie znaleziono pliku albo folderu."
    if isinstance(e, OSError):
        if e.errno == errno.ENOSPC:
            return "Brak miejsca na dysku."
        if e.errno == errno.EROFS:
            return "System plików jest tylko do odczytu."
        return "Błąd dysku przy zapisie albo odczycie."
    if isinstance(e, ValueError):
        return "Nieprawidłowe dane."
    return f"Błąd wewnętrzny ({type(e).__name__}); szczegóły w dzienniku serwera (journalctl -u gregai)."


_JSON_POST_PATHS = frozenset({"/api/chat", "/api/chat/wait", "/api/note", "/api/note/create", "/api/note/delete", "/api/note/przywroc", "/api/debug/learned/zapomnij",
                              "/api/debug/lan", "/api/namysl/settings", "/api/sources", "/api/upload", "/api/chat/cancel", "/api/rozmowa/usun"})


class ChatBusy(Exception):
    pass


class ChatCancelled(BaseException):
    """Użytkownik zatrzymał odpowiedź (przycisk Stop). BaseException, nie
    Exception: pośrednie `except Exception` (Narrator, router) nie mogą jej
    połknąć i pójść dalej do następnej fazy."""


_CHAT_JOBS: dict[str, dict] = {}
_CHAT_JOBS_LOCK = threading.Lock()
_CHAT_LOCK = threading.Lock()


def get_vault():
    """Vault z pamięci podręcznej. Budowa trwa dłużej niż przełączenie wątków
    (serce, czat i interfejs wołają to równolegle), więc wynik budowy trafia
    do cache tylko wtedy, gdy w międzyczasie nikt nie unieważnił cache
    (licznik _vault_gen): inaczej stary vault nadpisywałby świeżą zmianę.
    Co VAULT_RESCAN_SECONDS porównuje odcisk plików na dysku z odciskiem z
    ostatniej budowy: zmiana poza interfejsem unieważnia cache."""
    global _vault_cache, _vault_sig, _vault_sig_at
    with _vault_lock:
        cached, gen, sig, checked = _vault_cache, _vault_gen, _vault_sig, _vault_sig_at
    if cached is not None and time.monotonic() - checked < VAULT_RESCAN_SECONDS:
        return cached
    roots = data_mod.get_vault_roots()
    if cached is not None:
        try:
            now_sig = vault_mod.disk_signature(roots)
        except Exception:
            now_sig = sig  # nie da się sprawdzić: zostaje cache
        with _vault_lock:
            _vault_sig_at = time.monotonic()
        if now_sig == sig:
            return cached
    # Jedna budowa naraz: bez tego czat, serce i interfejs, które w tej samej chwili
    # zobaczą nieaktualny cache, budowałyby vault każdy po swojemu (przy kilku tysiącach
    # notatek to po kilka sekund CPU na wątek i zajęte miejsca w puli połączeń).
    with _vault_build_lock:
        with _vault_lock:
            cached2, gen, checked2 = _vault_cache, _vault_gen, _vault_sig_at
        if cached2 is not None and cached2 is not cached and time.monotonic() - checked2 < VAULT_RESCAN_SECONDS:
            return cached2  # ktoś zbudował świeży vault, gdy czekaliśmy na blokadę
        # Odcisk PRZED budową: zmiana w trakcie budowy da kolejną budowę, nie zgubi się.
        try:
            build_sig = vault_mod.disk_signature(roots)
        except Exception:
            build_sig = None
        built = vault_mod.build_vault(roots)
        with _vault_lock:
            if _vault_gen == gen:
                _vault_cache = built
                _vault_sig = build_sig
                _vault_sig_at = time.monotonic()
    return built


def invalidate_vault_cache():
    global _vault_cache, _vault_gen
    with _vault_lock:
        _vault_cache = None
        _vault_gen += 1


CHAT_TOOLS_SUMMARY = (
    f"Umiesz (robi to system, zanim dostaniesz wiadomość): szukać w notatkach {persona_mod.USER_NAME_GENITIVE}, w internecie i "
    "na Wikipedii, podać kurs, historię kursu i pogodę, sprawdzić sieć domową i stan komputera, ułożyć plan "
    "dnia z notatek, pokazać przegląd grafu notatek, zapamiętać fakt („zapamiętaj: ...”), zapisać odpowiedź "
    "jako węzeł („zapisz to”), pilnować tematu w tle („śledź ...”), pokazać i zatrzymać zadania w tle, "
    "powiedzieć, kim jesteś i z jakich modeli korzystasz. Sam niczego z tego nie uruchamiasz i nie wymieniasz "
    f"nazw narzędzi. Gdy czegoś z tego potrzeba, powiedz jednym zdaniem, co {persona_mod.USER_NAME} ma napisać (np. „sprawdź "
    "w internecie ...”). Wynik narzędzia widzi on jako krótką odpowiedź i kartę ze szczegółami. Tryby "
    f"freeram, fullon i gregaipanicmode obsługuje sam serwer, tylko na dosłowne polecenie {persona_mod.USER_NAME_GENITIVE}: nie "
    "opisujesz ich działania z głowy i nigdy ich nie podsuwasz, nawet żartem."
)


def get_system_prompt() -> str:
    """Prompt systemowy = agent/prompt.md (osobowość, zasady) + blok
    narzędzi wstawiony automatycznie z agent/capabilities.py w miejsce
    placeholdera {TOOLS_BLOCK}. Jedno miejsce (capabilities.py) na
    narzędzie = prompt i routing nie mogą się już rozjechać osobno."""
    global _system_prompt_cache
    if _system_prompt_cache is None:
        try:
            base = PROMPT_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError:
            base = "Jesteś GREGAI, osobistym asystentem użytkownika. Odpowiadaj po polsku.\n\n{TOOLS_BLOCK}"
        # 1.32.3 (audyt tura 8, prompty): w rozmowie zamiast pełnego katalogu narzędzi
        # (5 tys. znaków, 21% każdego wywołania, z rozkazami pisanymi dla routera typu
        # "zawsze powiedz, co zapisałeś") - krótki opis, co robi system. Pełny katalog
        # dostaje dalej router (router._routing_prompt).
        tools_block = CHAT_TOOLS_SUMMARY
        if sysop_mod.full():
            # Tryb pełny SYSOP (1.17.0, agent/sysop.py "Tryb PEŁNY"): model musi
            # WIEDZIEĆ, że na tej wyizolowanej maszynie ma pełen dostęp - inaczej
            # sekcja "Nigdy, bez wyjątków" z prompt.md kazałaby mu odmawiać tego,
            # na co kod (needs_confirmation/hard_blocked) już pozwala.
            tools_block += sysop_mod.full_mode_prompt_block()
        # 1.32.19/1.32.21 (przygotowanie pod open source): {CREATOR} i
        # {UZYTKOWNIK}/{UZYTKOWNIKA}/{UZYTKOWNIKU} tak samo jak {TOOLS_BLOCK} -
        # jedno miejsce (persona.py, z .env GREGAI_CREATOR_NAME/GREGAI_USER_NAME*)
        # zamiast literałów wpisanych na trwałe w prompt.md.
        _system_prompt_cache = (
            base.replace("{TOOLS_BLOCK}", tools_block)
            .replace("{CREATOR}", persona_mod.CREATOR)
            .replace("{UZYTKOWNIKA}", persona_mod.USER_NAME_GENITIVE)
            .replace("{UZYTKOWNIKU}", persona_mod.USER_NAME_VOCATIVE)
            .replace("{UZYTKOWNIK}", persona_mod.USER_NAME)
        )
    return _system_prompt_cache


def _strip_title_and_type(text: str) -> str:
    return vault_mod.strip_title_and_type(text)


def _excerpt(text: str, limit: int = 160) -> str:
    # Najpierw skrócenie: wycinek ma 160 znaków, a graf liczy go dla każdej notatki.
    body = vault_mod.WIKILINK_RE.sub(lambda m: m.group(1), _strip_title_and_type(text[: 40 * limit])[: 6 * limit])
    body = re.sub(r"\*\*|__|`|^#{1,6}[ \t]+|^[ \t]*[-*]\s+", "", body, flags=re.MULTILINE)  # wycinek bez znaków Markdownu
    body = " ".join(body.split())
    return (body[:limit] + "…") if len(body) > limit else body


def _is_writable(note) -> bool:
    return Path(note.path).suffix.lower() in WRITABLE_SUFFIXES and not note.lossy


def _readonly_message(note) -> str:
    return LOSSY_MESSAGE if note.lossy else READONLY_MESSAGE


def _readonly_reason(note) -> str:
    return "" if _is_writable(note) else ("kodowanie" if note.lossy else "pdf")


# --- Rozmowa przypisana do projektu (ui/app.js: szyna "Projekty" w Rozmowie) ---
# Projekt = notatka `type: Project` (vault_mod.PROJECT_TYPE). Przypisana rozmowa
# dostaje do route() OKROJONY vault (tylko podgraf tego projektu + wspólna pula,
# patrz vault_mod.project_scope/shared_pool_slugs) - "projekty nie mają wspólnej
# wiedzy" (prośba użytkownika): GREGAI fizycznie nie widzi notatek innych
# projektów w tej rozmowie, to nie tylko obietnica w prompcie.
MAX_PROJECT_ID_CHARS = 300  # tyle najwyżej ma sensowny slug (ścieżka notatki)


def _project_prompt_suffix(title: str) -> str:
    """Dopisek do pełnego prompt.md, WYŁĄCZNIE gdy rozmowa jest przypisana do
    projektu: tłumaczy modelowi, czemu widzi okrojony graf, i opisuje
    konwencję NOWY_WEZEL (patrz _extract_suggested_node), żeby propozycja
    nowego węzła kosztowała zero dodatkowych wywołań modelu - jest częścią
    TEJ SAMEJ odpowiedzi rozmowy, nie drugim zapytaniem do Ollamy."""
    safe_title = " ".join(title.split())[:200]
    return (
        f"\n\n--- Kontekst: projekt „{safe_title}” ---\n"
        f"Ta rozmowa jest przypisana do projektu „{safe_title}”. Widzisz tylko notatki "
        "należące do tego projektu (połączone z nim w grafie [[linkami]]) oraz wspólną, "
        "ogólną wiedzę (notatki niezwiązane z żadnym projektem) - notatki INNYCH projektów "
        "są dla Ciebie teraz niewidoczne, nie wspominaj o nich i nie zgaduj ich treści.\n"
        "Jeśli w TEJ wymianie pojawił się konkretny fakt, decyzja albo ustalenie warte "
        f"zapisania dla projektu „{safe_title}” - i TYLKO wtedy, nie przy każdej odpowiedzi - "
        "zakończ całą odpowiedź NOWĄ, OSTATNIĄ linią w dokładnym formacie:\n"
        "NOWY_WEZEL: krótki tytuł | treść notatki\n"
        "Nie dodawaj tej linii przy zwykłej rozmowie, pytaniu czy powitaniu. Sam NIGDY nie "
        "zapisujesz niczego - użytkownik zobaczy tę propozycję jako kartę w interfejsie i "
        "sam zdecyduje, czy ją zapisać."
    )


# Ostatnia taka linia w odpowiedzi (model czasem "myśli na głos" wcześniej i mógłby
# wspomnieć format przykładowo) - MULTILINE, bez kotwicy $ na końcu całego tekstu, żeby
# tolerować końcową spację/nowe linie, których małe modele dopisują bez znaczenia.
_NODE_SUGGEST_RE = re.compile(r"^[ \t]*NOWY_WEZEL:\s*(.+?)\s*\|\s*(.+?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
MAX_SUGGEST_TITLE_CHARS = 120
MAX_SUGGEST_BODY_CHARS = 2000


def _extract_suggested_node(speech: str) -> tuple[str, dict | None]:
    """(odpowiedź bez linii NOWY_WEZEL, propozycja|None). Treść jest tylko
    PROPOZYCJĄ pokazaną w interfejsie (patrz ui/app.js: appendSuggestedNodeCard)
    - serwer niczego tu nie zapisuje, dopiero POST /api/note/create po kliknięciu
    "Zapisz" robi to naprawdę, tą samą drogą co ręczne tworzenie węzła."""
    matches = list(_NODE_SUGGEST_RE.finditer(speech))
    if not matches:
        return speech, None
    m = matches[-1]
    title = " ".join(m.group(1).split())[:MAX_SUGGEST_TITLE_CHARS]
    body = m.group(2).strip()[:MAX_SUGGEST_BODY_CHARS]
    if not title or not body:
        return speech, None
    # Sekrety z .env (hasło routera, klucze) nie mają trafić do karty w interfejsie
    # ani (po "Zapisz") do pliku - ta sama maska co memory.remember.
    title, body = sysop_mod.mask_secrets(title), sysop_mod.mask_secrets(body)
    cleaned = (speech[:m.start()] + speech[m.end():]).rstrip()
    return cleaned, {"title": title, "body": body}


def _run_chat(payload: dict, job: dict | None = None) -> dict:
    message = str(payload.get("message") or "").strip()
    history = payload.get("history")  # czyści router.clean_history
    pending_clarify = payload.get("pending_clarify") or None
    # Echo karty potwierdzenia (agent/agentloop.py): sam id, treść działania
    # pamięta serwer.
    pending_action = payload.get("pending_action") or None
    project_id = payload.get("project")
    project_id = project_id.strip()[:MAX_PROJECT_ID_CHARS] if isinstance(project_id, str) and project_id.strip() else None
    # Pliki wgrane do TEJ wiadomości (spinacz, POST /api/upload): przeglądarka
    # przysyła same nazwy z data/wgrane, serwer przekłada je na ścieżki i
    # sprawdza, że tam leżą (nigdy ścieżka spoza katalogu wgranych).
    # Id rozmowy dla Źródeł i wgranych (agent/sources.py, 1.9.1: indywidualne
    # dla każdej rozmowy): slug projektu albo "ogolna" - TEN SAM podział, co
    # wątki rozmowy w przeglądarce i izolacja notatek projektu niżej.
    chat = sources_mod.chat_id(project_id)
    files = _upload_paths(chat, payload.get("files"))
    progress = (lambda ev: _job_progress(job, ev)) if job is not None else None
    with _CHAT_LOCK:
        # Rozmowa, o którą nikt nie pyta od dawna (karta przeglądarki zamknięta,
        # zanim kolejka doszła do niej), nie zajmuje modelu na minuty ani nie
        # wykonuje niczego, czego nikt nie zobaczy.
        if job is not None and time.monotonic() - job["last_poll"] > CHAT_ABANDON_AFTER:
            return {"error": "Nikt nie czekał już na tę odpowiedź, więc jej nie liczyłem. Napisz jeszcze raz."}
        if job is not None and job["cancel"].is_set():
            return {"anulowano": True}
        v = get_vault()
        route_vault = v
        system_prompt = get_system_prompt()
        active_project = None
        if project_id:
            candidate = v.notes.get(project_id)
            # Id z przeglądarki może być nieaktualne (projekt usunięty/zmieniony od
            # ostatniego odświeżenia grafu): wtedy rozmowa idzie dalej NIEprzypisana,
            # zamiast odmawiać odpowiedzi na zwykłą wiadomość.
            if candidate is not None and candidate.ntype == vault_mod.PROJECT_TYPE:
                active_project = candidate
                scope = v.project_scope(project_id) | v.shared_pool_slugs()
                route_vault = v.filtered(scope)
                system_prompt = system_prompt + _project_prompt_suffix(candidate.title)
        router_mod._CANCEL.check = (lambda: job["cancel"].is_set()) if job is not None else None
        try:
            result = router_mod.route(route_vault, system_prompt, history, message, pending_clarify, pending_action,
                                      progress=progress, files=files, chat=chat)
        finally:
            router_mod._CANCEL.check = None
        if job is not None and job["cancel"].is_set():
            return {"anulowano": True}  # zatrzymane: nic nie trafia do pamięci rozmowy ani do historii
        # wiki_lookup (agent/tools.py) dopisuje nową notatkę do
        # data/wiki_cache, jednego z korzeni vault (patrz
        # data.get_vault_roots): bez tego sygnału graf w pamięci nie
        # wiedziałby o niej, dopóki ktoś nie zapisałby/usunął czegoś innego
        # przez interfejs. Przeglądarce zamiast flagi idzie graph_changed.
        if result.pop("invalidate_vault", False):
            invalidate_vault_cache()
            result["graph_changed"] = True  # przeglądarka odświeży graf (nowa notatka z czatu)
        # Propozycja nowego węzła TYLKO dla zwykłej rozmowy (kind == "chat": chmura/uczeń/
        # duży model, patrz router._CHAT_STAGES) przypisanej do projektu - nigdy dla karty
        # narzędzia/zadania/potwierdzenia, gdzie "speech" nie jest swobodną odpowiedzią modelu.
        if active_project is not None and result.get("kind") == "chat" and isinstance(result.get("speech"), str):
            cleaned, suggestion = _extract_suggested_node(result["speech"])
            if suggestion is not None:
                result["speech"] = cleaned
                result["suggested_node"] = {
                    "title": suggestion["title"],
                    "body": suggestion["body"],
                    "project": active_project.title,
                    "project_id": active_project.slug,
                }
                # 1.23.0: podpis liczony był dla tekstu z linią NOWY_WEZEL; bez nowego
                # podpisu następna tura uznawała odpowiedź za narzędziową i wycinała
                # całą wymianę z historii do sieci.
                if result.get("sig"):
                    result["sig"] = router_mod._chat_sig(cleaned)
        # Pamięć rozmowy (agent/rozmowa.py, 1.10.0): para tur do pliku tej
        # rozmowy, a co TURN_STEP tur odświeżenie streszczenia W TLE - nigdy nie
        # opóźnia tej odpowiedzi. Błąd zapisu nie psuje rozmowy.
        try:
            if isinstance(result, dict) and not result.get("error"):
                # 1.29.0 (kontrola): tura z doklejonym alertem była zapisywana jako stub
                # narzędzia - pamięć rozmowy gubiła prawdziwą odpowiedź.
                mem_speech = result.pop("_speech_bez_alertu", None) or result.get("speech") or ""
                mem_kind = result.pop("_kind_bez_alertu", None) or result.get("kind")
                is_tool = mem_kind != "chat"
                label = (result.get("card") or {}).get("type") if isinstance(result.get("card"), dict) else None
                rozmowa_mod.record(chat, message, mem_speech, tool=is_tool, tool_name=label)
                if rozmowa_mod.pending_turns(chat) >= rozmowa_mod.TURN_STEP:
                    threading.Thread(target=_summarize_conversation_bg, args=(chat,), daemon=True).start()
        except Exception as e:
            print(f"UWAGA: pamięć rozmowy: {type(e).__name__}: {e}")
        if isinstance(result, dict):
            result.pop("_speech_bez_alertu", None)
            result.pop("_kind_bez_alertu", None)
    return result


def _safe_call(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}"}


def _summarize_conversation_bg(chat: str) -> None:
    """Streszczenie rozmowy w tle (patrz rozmowa.maybe_summarize); wpis w
    śladzie tylko przy zmianie, żeby /debug pokazał, że pamięć rozmowy żyje."""
    try:
        if rozmowa_mod.maybe_summarize(chat, router_mod.summarize_text):
            trace_mod.record("pamiec_rozmowy", f"streszczenie rozmowy „{chat}” odświeżone", tool=None)
    except Exception as e:
        try:
            trace_mod.record("pamiec_rozmowy_blad", f"{type(e).__name__}: {e}"[:200], tool=None)
        except Exception:
            pass


def _upload_paths(chat: str, names) -> list[str]:
    """Nazwy wgranych plików z przeglądarki -> ścieżki w data/wgrane/<rozmowa>
    (pliki wprost w tym katalogu) albo, gdy akurat tam nie trafiają (literówka
    w nazwie, plik przeniesiony/wgrany w innym momencie, rozmowa przełączona
    między wgraniem a wysłaniem), SAMA nazwa - Namysł i tak ją dostanie
    (namysl.wants(): załącznik = zawsze Namysł) i spróbuje jej lenientszym
    wyszukiwaniem po wszystkich źródłach tej rozmowy (sources.find_by_name_in_chat
    przez namysl._resolve_file), zamiast odpowiedzieć bez namysłu wcale i
    zapytać "nie dołączyłeś pliku", choć w wiadomości widać załącznik.
    1.32.15 (audyt, transkrypt "Przeanalizuj sobie dokładnie to"): dawniej
    plik, który nie trafił w ten jeden, konkretny katalog, po cichu znikał
    z `files` i Namysł nie startował wcale."""
    if not isinstance(names, list):
        return []
    root = sources_mod.upload_root(chat)
    out = []
    for n in names[:8]:
        if not isinstance(n, str) or not n or "/" in n or "\\" in n or n.startswith("."):
            continue
        p = root / n
        try:
            if p.is_file() and p.resolve().parent == root.resolve():
                out.append(str(p))
            else:
                out.append(n)
        except OSError:
            out.append(n)
    return out


def _job_progress(job: dict, ev: dict) -> None:
    """Zdarzenie postępu (agent/namysl.py: Narrator) przy zadaniu czatu - do
    GET /api/chat/progress. Bez blokady czatu: to tylko lista przy zadaniu."""
    try:
        if job.get("cancel") is not None and job["cancel"].is_set():
            raise ChatCancelled()  # Stop: przerwij między fazami, nie rób następnej
        events = job.setdefault("progress", [])
        if len(events) < namysl_mod.MAX_PROGRESS_EVENTS:
            events.append(ev)
    except Exception:
        pass


_CLIENT_JOBS: dict[str, tuple[str, float]] = {}  # client_id -> (job_id, kiedy)


def _start_chat_job(payload: dict) -> str:
    # 1.20.0: idempotencja. Ta sama wiadomość wysłana drugi raz z tym samym client_id
    # (odpowiedź serwera zgubiła się po drodze) wraca do TEGO zadania, nie startuje
    # drugiego (zapis i polecenie nie wykonają się dwa razy).
    client_id = payload.get("client_id") if isinstance(payload, dict) else None
    # 1.32.14: ten sam client_id, ale INNA treść (błąd przeglądarki) = nowe zadanie; a zadanie,
    # które skończyło się błędem, nie jest oddawane drugi raz przy "Spróbuj ponownie".
    _msg_h = hashlib.sha256(str((payload or {}).get("message") or "").encode("utf-8", "replace")).hexdigest()[:16]
    if isinstance(client_id, str) and 8 <= len(client_id) <= 64:
        with _CHAT_JOBS_LOCK:
            prev = _CLIENT_JOBS.get(client_id)
            if prev and prev[0] in _CHAT_JOBS and time.monotonic() - prev[1] < CHAT_JOB_TTL and (len(prev) < 3 or prev[2] == _msg_h):
                _old = _CHAT_JOBS.get(prev[0]) or {}
                if not (_old.get("done") is not None and _old["done"].is_set() and isinstance(_old.get("result"), dict) and _old["result"].get("error")):
                    return prev[0]
    else:
        client_id = None
    job_id = _start_chat_job_new(payload)
    if client_id:
        with _CHAT_JOBS_LOCK:
            now = time.monotonic()
            for k in [k for k, v in _CLIENT_JOBS.items() if now - v[1] > CHAT_JOB_TTL]:
                del _CLIENT_JOBS[k]
            _CLIENT_JOBS[client_id] = (job_id, now, _msg_h)
    return job_id


def _start_chat_job_new(payload: dict) -> str:
    job_id = secrets.token_urlsafe(16)
    now0 = time.monotonic()
    job_chat = sources_mod.chat_id(payload.get("project") if isinstance(payload, dict) else None)
    job = {"done": threading.Event(), "cancel": threading.Event(), "result": None, "created": now0,
           "last_poll": now0, "progress": [], "chat": job_chat}

    def _work():
        try:
            res = _run_chat(payload, job)
            if not job["cancel"].is_set():
                job["result"] = res
        except ChatCancelled:
            pass
        except Exception as e:
            if not job["cancel"].is_set():
                job["result"] = {"error": _error_text(e)}
        finally:
            if job["cancel"].is_set():
                job["result"] = {"anulowano": True}
            job["done"].set()

    with _CHAT_JOBS_LOCK:
        now = time.monotonic()
        # 1.19.0: tylko zakończone - żywe zadanie (długi Namysł) nie znika spod
        # oczekującej przeglądarki, nawet po TTL.
        for old_id in [k for k, j in _CHAT_JOBS.items() if now - j["created"] > CHAT_JOB_TTL and j["done"].is_set()]:
            del _CHAT_JOBS[old_id]
        if sum(1 for j in _CHAT_JOBS.values() if not j["done"].is_set()) >= MAX_ACTIVE_CHAT_JOBS:
            raise ChatBusy()
        _CHAT_JOBS[job_id] = job
    threading.Thread(target=_work, daemon=True).start()
    return job_id


def graph_json():
    v = get_vault()
    nodes = []
    for note in v.notes.values():
        nodes.append({
            "id": note.slug,
            "title": note.title,
            "type": note.ntype,
            "excerpt": _excerpt(note.text),
            # Wychodzące powiązania (1.14.0): inspektor pokazuje je osobno od
            # treści, w dwóch kierunkach (prowadzi do / wskazują na tę notatkę).
            "links": sorted(t for t in note.links if t != note.slug and t in v.notes),
            "readonly": not _is_writable(note),
            "readonly_reason": _readonly_reason(note),
        })
    edges = []
    seen = set()
    for note in v.notes.values():
        for target in note.links:
            if target == note.slug:
                continue  # link do samej siebie to nie połączenie (vault.degrees też go nie liczy)
            key = tuple(sorted([note.slug, target]))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": note.slug, "target": target})

    return {
        "nodes": nodes,
        "edges": edges,
        "errors": v.errors,
        "skipped": len(v.skipped),
    }


# Dłuższy tytuł (cała linia "# ..." może mieć 2 MB) nie buduje wzorca: kompilacja
# wyrażenia z setek tysięcy słów trwała sekundy przy każdym zapisie i usunięciu.
MAX_BACKLINK_TITLE = 300


def _backlink_pattern(title: str) -> re.Pattern:
    """Wzorzec linków [[title]], [[title#sekcja]], [[title|alias]] w innych notatkach (przy zmianie
    tytułu). Te same granice co vault.WIKILINK_RE: bez nich niedomknięte "[[Tytuł#" w długiej
    notatce skanowałoby ją do końca przy każdym wystąpieniu (czas kwadratowy)."""
    words = r"\s+".join(re.escape(w) for w in title.split())
    return re.compile(r"\[\[\s*" + words + r"\s*(#[^\[\]|]{0,200})?(\|[^\[\]]{0,200})?\]\]", re.IGNORECASE)


class Handler(BaseHTTPRequestHandler):
    CLIENT_DISCONNECT_ERRORS = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
    # 1.32.3 (audyt tura 8): bez wersji Pythona w nagłówku Server.
    server_version = "GREGAI"
    sys_version = ""

    def version_string(self) -> str:
        return "GREGAI"
    _ERROR_PL = {400: "Nieprawidłowe żądanie", 404: "Nie znaleziono", 405: "Metoda niedozwolona",
                 408: "Za długo czekałem na żądanie", 411: "Wymagany nagłówek Content-Length",
                 413: "Za duże żądanie", 414: "Za długi adres", 431: "Za duże nagłówki",
                 501: "Ta metoda nie jest obsługiwana", 505: "Nieobsługiwana wersja HTTP"}

    def send_error(self, code, message=None, explain=None):
        """Błędy z samej biblioteki (zła metoda, za duże nagłówki, zła wersja HTTP): po polsku,
        jako JSON z nagłówkami bezpieczeństwa, zamiast angielskiej strony HTML (1.32.3)."""
        try:
            self.close_connection = True
            self._send_json({"error": self._ERROR_PL.get(int(code), "Błąd żądania")}, status=int(code))
        except Exception:
            super().send_error(code, message, explain)
    # Gniazdo, które przez 30 sekund nic nie wyśle, jest zamykane (inaczej
    # jedno otwarte i milczące połączenie trzymałoby wątek w nieskończoność).
    # Dotyczy tylko odczytu żądania: czekanie na odpowiedź modelu odbywa się
    # po jego wczytaniu (patrz CHAT_WAIT).
    timeout = 30
    # Limit na PRZYJĘCIE całego żądania (linia, nagłówki, treść): timeout wyżej
    # liczy się od każdego odczytu z osobna, więc klient wysyłający bajt co 20 s
    # trzymałby gniazdo w nieskończoność. Zegar startuje z połączeniem i jest
    # zatrzymywany, gdy żądanie jest wczytane; potem czekanie na model nie ma limitu.
    REQUEST_READ_DEADLINE = 8   # 1.29.0 (kontrola): linia i nagłówki; treść dostaje czas wg rozmiaru
    BODY_RATE_BPS = 128 * 1024  # najwolniejsze rozsądne wysyłanie (telefon w słabym Wi-Fi)

    def _arm_deadline(self, seconds: float) -> None:
        self._request_read_done()
        self._read_deadline = threading.Timer(seconds, self._deadline_hit)
        self._read_deadline.daemon = True
        self._read_deadline.start()

    def handle_one_request(self):
        # Zegar dla KAŻDEGO żądania, także kolejnego na tym samym połączeniu (keep-alive):
        # wcześniej tylko pierwsze miało limit, a drugie można było sączyć bez końca.
        self._arm_deadline(self.REQUEST_READ_DEADLINE)
        try:
            super().handle_one_request()
        finally:
            self._request_read_done()

    def _deadline_hit(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)  # blokujący odczyt dostaje EOF
        except OSError:
            pass

    def _request_read_done(self):
        timer = getattr(self, "_read_deadline", None)
        if timer is not None:
            timer.cancel()

    def finish(self):
        self._request_read_done()
        super().finish()

    def log_message(self, format, *args):
        # Surowa linia żądania pochodzi od klienta: znaki sterujące (np. ESC)
        # w dzienniku systemowym pozwalałyby fałszować wpisy, więc je ucinamy.
        line = "%s - %s" % (self.address_string(), format % args)
        sys.stderr.write("".join(c if c.isprintable() else "?" for c in line) + "\n")

    def _end_headers_secure(self, cache: str):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Cache-Control", cache)
        self.end_headers()

    def _send_json(self, payload, status=200):
        # errors="replace": samotny surogat (nazwa pliku nie w UTF-8) nie może
        # zamienić całej odpowiedzi w 500.
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8", "replace")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._end_headers_secure("no-store")
            self.wfile.write(body)
        except self.CLIENT_DISCONNECT_ERRORS:
            self.log_message("klient rozłączył się przed odebraniem odpowiedzi (%s)", self.path)

    def _send_file(self, path: Path, content_type: str):
        # 1.24.0 (przegląd wydajności): Last-Modified + 304. Przeglądarka i tak pyta
        # przy każdym otwarciu (no-cache), ale niezmieniony plik nie leci drugi raz
        # (ok. 1 MB, w tym three.min.js) - ważne na telefonie w sieci domowej.
        try:
            mtime = int(path.stat().st_mtime)
        except OSError:
            mtime = None
        if mtime is not None:
            since = self.headers.get("If-Modified-Since")
            if since:
                try:
                    from email.utils import parsedate_to_datetime
                    # Równość, nie ">=": powrót do starszej wersji (gregai rollback) ma
                    # starsze pliki, a przeglądarka nie może zostać przy nowszych.
                    if int(parsedate_to_datetime(since).timestamp()) == mtime:
                        self.send_response(304)
                        self.send_header("Content-Length", "0")
                        self._end_headers_secure("no-cache")
                        return
                except (TypeError, ValueError, OverflowError, IndexError):
                    pass
        try:
            data = path.read_bytes()
        except OSError:  # brak pliku, katalog zamiast pliku, brak uprawnień
            self._send_json({"error": "Nie znaleziono"}, status=404)
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if mtime is not None:
                from email.utils import formatdate
                self.send_header("Last-Modified", formatdate(mtime, usegmt=True))
            self._end_headers_secure("no-cache")
            self.wfile.write(data)
        except self.CLIENT_DISCONNECT_ERRORS:
            self.log_message("klient rozłączył się przed odebraniem odpowiedzi (%s)", self.path)

    def _send_empty(self, status: int):
        try:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self._end_headers_secure("no-cache")
        except self.CLIENT_DISCONNECT_ERRORS:
            pass

    def _proxied(self) -> bool:
        """Czy żądanie przeszło przez pośrednika (tunel Cloudflare, reverse
        proxy). Cloudflare zawsze dokłada CF-Connecting-IP i CF-Ray, a
        nadpisuje je, jeśli klient próbował je podać sam, więc ktoś z
        internetu nie może ich usunąć, żeby udawać localhost."""
        return any(self.headers.get(h) for h in PROXY_HEADERS)

    def _authorized(self) -> bool:
        """Bez tokenu wpuszczamy WYŁĄCZNIE bezpośrednie żądania z tej samej
        maszyny (127.0.0.1/::1 i bez nagłówków pośrednika). Wszystko inne:
        LAN, tunel Cloudflare, cokolwiek przez proxy, musi podać poprawny
        X-Gregai-Token.

        Dlaczego nie "każde 127.0.0.1": cloudflared łączy się właśnie z
        127.0.0.1, więc samo IP nie odróżnia tej maszyny od tunelu."""
        client_ip = self.client_address[0]
        if client_ip in ("127.0.0.1", "::1") and not self._proxied():
            return True
        if tryby_mod.PANIC_LOCK.is_set():
            return False  # gregaipanicmode: nic spoza tego komputera, nawet z poprawnym tokenem
        if not GREGAI_TOKEN:
            return False  # brak tokenu w .env -> blokuj wszystko spoza tej maszyny
        given = self.headers.get("X-Gregai-Token") or ""
        return hmac.compare_digest(given.encode("utf-8"), GREGAI_TOKEN.encode("utf-8"))

    def _ban_key(self) -> str:
        """Adres do liczenia prób. 1.30.1 (red-team): ZAWSZE prawdziwy adres gniazda
        TCP, nigdy nagłówek od klienta. Wcześniej braliśmy CF-Connecting-IP, gdy
        żądanie wyglądało na "za pośrednikiem" - ale ten nagłówek może dołożyć KAŻDY
        klient, więc napastnik obchodził blokadę, zmieniając go co próbę, albo
        blokował właściciela, podszywając jego adres. Za prawdziwym tunnelem
        cloudflared wszyscy z internetu mają 127.0.0.1, czyli wspólny kubełek -
        to świadomy kompromis: właściciel przy laptopie (ścieżka zaufana, bez
        pośrednika) i tak nigdy nie jest tą blokadą objęty, a token to 32 losowe
        bajty, więc zgadywanie i tak jest beznadziejne."""
        # 1.32.10 (audyt tura 14): za PRAWDZIWYM tunelem (gniazdo z tej maszyny + Host z
        # GREGAI_TUNEL_HOSTY) cloudflared nadpisuje CF-Connecting-IP, więc da się mu ufać - inaczej
        # jedna osoba z internetu blokowała wszystkich, także Twój telefon.
        ip = self.client_address[0]
        cf = (self.headers.get("CF-Connecting-IP") or "").strip()
        if ip in ("127.0.0.1", "::1") and cf and re.fullmatch(r"[0-9a-fA-F:.]{2,45}", cf):
            host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
            tunnel = {h.strip().lower() for h in os.environ.get("GREGAI_TUNEL_HOSTY", "").split(",") if h.strip()}
            if host and host in tunnel:
                return "cf:" + cf
        return ip

    def _auth_gate(self) -> bool:
        """1.30.0: autoryzacja z blokadą zgadywania tokenu. Adres, który w ciągu
        AUTH_WINDOW_S podał zły token AUTH_MAX_FAILS razy, dostaje 429 na
        AUTH_BAN_S, a straż i dziennik bezpieczeństwa dostają wpis. Bezpośrednie
        żądanie z tej maszyny (zaufane, bez tokenu) nigdy nie jest liczone ani
        blokowane - inaczej napastnik mógłby odciąć właściciela od jego laptopa.
        Odpowiedź wysyła ta funkcja; False = nie obsługuj dalej."""
        # Zaufany localhost (fizycznie przy komputerze) wchodzi zawsze - poza blokadą.
        if self.client_address[0] in ("127.0.0.1", "::1") and not self._proxied():
            return True
        if tryby_mod.PANIC_LOCK.is_set():
            # gregaipanicmode: odmowa bez liczenia jako zły token (inaczej telefon z poprawnym
            # tokenem wywoływałby fałszywy alarm "błędne tokeny"; przegląd poprawek 1.32.1).
            self._send_json({"error": "GREGAI jest w trybie awaryjnym: dostęp tylko z tego komputera."}, status=403)
            return False
        ip = self._ban_key()
        now = time.time()
        with _AUTH_LOCK:
            until = _AUTH_BANNED.get(ip, 0.0)
            if until > now:
                left = int(until - now) + 1
                banned = True
            else:
                _AUTH_BANNED.pop(ip, None)
                banned = False
        if banned:
            try:
                self.send_response(429)
                body = json.dumps({"error": f"Za dużo błędnych prób. Spróbuj za {left} s."}, ensure_ascii=False).encode()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Retry-After", str(left))
                self._end_headers_secure("no-store")
                self.wfile.write(body)
            except self.CLIENT_DISCONNECT_ERRORS:
                pass
            return False
        if self._authorized():
            with _AUTH_LOCK:
                _AUTH_FAILS.pop(ip, None)  # 1.32.10: poprawny token zeruje licznik pomyłek
            return True
        # 1.32.10: brak nagłówka to nie zgadywanie (telefon bez tokenu) - 403, ale bez licznika
        # i bez fałszywego alarmu straży.
        if not self.headers.get("X-Gregai-Token"):
            self._send_json({"error": "Brak tokenu dostępu (X-Gregai-Token)."}, status=403)
            return False
        newly_banned = False
        with _AUTH_LOCK:
            fails = [t for t in _AUTH_FAILS.get(ip, []) if now - t < AUTH_WINDOW_S] + [now]
            _AUTH_FAILS[ip] = fails[-AUTH_MAX_FAILS:]
            if len(_AUTH_FAILS) > 4096:  # pamięć ograniczona nawet przy zalewie adresów
                for k in list(_AUTH_FAILS)[:2048]:
                    _AUTH_FAILS.pop(k, None)
            # 1.30.1 (red-team): _AUTH_BANNED też ograniczone - inaczej zalew różnych
            # adresów rósłby w nieskończoność (przy kluczu = adres gniazda to i tak
            # trudne, ale trzymamy twardy limit). Najpierw sprzątamy wygasłe.
            if len(_AUTH_BANNED) > 2048:
                for k in [k for k, t in list(_AUTH_BANNED.items()) if t <= now]:
                    _AUTH_BANNED.pop(k, None)
                while len(_AUTH_BANNED) > 2047:
                    _AUTH_BANNED.pop(min(_AUTH_BANNED, key=_AUTH_BANNED.get), None)
            if len(fails) >= AUTH_MAX_FAILS:
                _AUTH_BANNED[ip] = now + AUTH_BAN_S
                _AUTH_FAILS.pop(ip, None)
                newly_banned = True
        if newly_banned:
            _security_event("blokada_tokenu", f"{AUTH_MAX_FAILS} błędnych tokenów z adresu {ip} w {AUTH_WINDOW_S // 60} min - "
                                              f"adres zablokowany na {AUTH_BAN_S // 60} min")
        self._send_json({"error": "Brak autoryzacji"}, status=403)
        return False

    def _browser_origin_ok(self) -> tuple[bool, str]:
        """Ochrona przed stronami z internetu otwartymi w przeglądarce na tym
        samym laptopie (CSRF i DNS rebinding). Bez niej dowolna strona mogłaby
        wysłać do http://localhost:7777 żądanie w Twoim imieniu (rozmowa,
        notatki, restart), bo przychodzi ono z 127.0.0.1.

        - Host musi być adresem tej maszyny (localhost/127.0.0.1/::1, w
          trybie LAN także dowolny adres IP), nigdy nazwą domeny: obce
          domeny podpięte pod 127.0.0.1 (DNS rebinding) odpadają.
        - Origin, jeśli jest, musi być tym samym adresem.
        - Sec-Fetch-Site (przeglądarki go dokładają): tylko "same-origin"
          albo "none" (adres wpisany ręcznie).
        Żądania przez pośrednika: Host musi być na liście GREGAI_TUNEL_HOSTY (1.32.1;
        dawniej test Hosta był dla nich pomijany) i i tak muszą mieć token."""
        host = (self.headers.get("Host") or "").strip().lower()
        allowed = {f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"[::1]:{PORT}"}
        host_ok = host in allowed
        if not host_ok and LAN_MODE:
            name = host.rsplit(":", 1)[0].strip("[]") if host.endswith(f":{PORT}") else ""
            try:
                ipaddress.ip_address(name)
                host_ok = True
            except ValueError:
                host_ok = False
        if not host_ok and self._proxied():
            # Audyt 1.32.1: strona z DNS rebinding sama dokłada X-Forwarded-For i omijała
            # test Hosta (fałszywe alarmy straży, blokada wspólnego kubełka 127.0.0.1).
            # Za pośrednikiem wpuszczamy tylko nazwy wpisane w GREGAI_TUNEL_HOSTY.
            tunnel = {h.strip().lower() for h in os.environ.get("GREGAI_TUNEL_HOSTY", "").split(",") if h.strip()}
            host_ok = host in tunnel or host.rsplit(":", 1)[0] in tunnel
        if not host_ok:
            return False, f"nieznany Host: {host[:60]!r}"
        origin = (self.headers.get("Origin") or "").strip().lower()
        # Za tunelem TLS (cloudflared) przeglądarka widzi https://, serwer http://.
        same_origin = {f"http://{host}"} | ({f"https://{host}"} if self._proxied() else set())
        if origin and origin not in same_origin:
            return False, f"obcy Origin: {origin[:60]!r}"
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site and site not in ("same-origin", "none"):
            return False, f"żądanie z innej strony (Sec-Fetch-Site: {site})"
        return True, ""

    def do_GET(self):
        self._request_read_done()  # żądanie GET jest już w całości wczytane
        parsed = urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/"):
            ok, why = self._browser_origin_ok()
            if not ok:
                self._send_json({"error": f"Odrzucone: {why}"}, status=403)
                return

        # Token tylko dla /api/ (dane i akcje). Pliki interfejsu niżej są
        # publiczne, patrz docstring modułu.
        if route.startswith("/api/") and not self._auth_gate():
            return

        if route == "/api/graph":
            try:
                self._send_json(graph_json())
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/note":
            qs = parse_qs(parsed.query)
            slug = (qs.get("id") or [""])[0]
            self._handle_note_get(slug)
            return

        if route == "/api/status":
            # 1.24.0: pigułka w nagłówku rozmowy (straż + budżet), lekko: bez dziennika.
            try:
                sp = juggler_mod.spent_usd()
            except Exception:
                sp = None
            self._send_json({"model_active": router_mod.ollama_available(),
                             "straz": os.environ.get("STRAZ", "1") != "0", "usd": sp,
                             # Straż włączona, ale obchody się nie udają albo stoją.
                             "straz_blad": straz_mod.stuck()})
            return

        if route == "/api/debug/log":
            try:
                self._send_json({"entries": trace_mod.recent(200)})
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/debug/learned":
            try:
                self._send_json({"routes": learning_mod.all_routes(), "topic_words": learning_mod._load_topic_words()})
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/debug/topic_words":
            try:
                self._send_json({"topic_words": learning_mod.all_learned_topic_words()})
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/chat/progress":
            # Narracja Namysłu na żywo (agent/namysl.py): zdarzenia zebrane przy
            # zadaniu czatu, bez czekania na odpowiedź. Przeglądarka pyta co
            # ~1,5 s, dopóki zadanie trwa. Bez blokady czatu (_CHAT_LOCK).
            job_id = (parse_qs(parsed.query).get("job") or [""])[0]
            with _CHAT_JOBS_LOCK:
                job = _CHAT_JOBS.get(job_id)
            if job is None:
                self._send_json({"error": "Nie ma takiej rozmowy w toku"}, status=404)
                return
            job["last_poll"] = time.monotonic()
            since = (parse_qs(parsed.query).get("since") or ["0"])[0]
            try:
                since_i = max(0, int(since))
            except ValueError:
                since_i = 0
            events = list(job.get("progress") or [])
            self._send_json({"events": events[since_i:], "total": len(events), "done": job["done"].is_set()})
            return

        if route == "/api/namysl/settings":
            self._send_json(namysl_mod.load_settings())
            return

        # 1.32.0: diagnoza internetu warstwa po warstwie (agent/diagnoza.py) - w USŁUDZE,
        # bo tylko tu obowiązuje ta sama zapora jądra co dla prawdziwych zapytań.
        # Jedna naraz; wynik ważny 10 s (kilka kart Nadzorcy nie odpala jej kilka razy).
        if route == "/api/diagnoza":
            import diagnoza as diagnoza_mod
            self._send_json(diagnoza_mod.cached_run())
            return

        if route == "/api/komendy":
            import komendy as komendy_mod
            self._send_json({"komendy": komendy_mod.api_list()})
            return

        if route == "/api/lekcje":
            import lekcje as lekcje_mod
            self._send_json({"lekcje": lekcje_mod.all_lessons()})
            return

        if route == "/api/rozmowa/tury":
            # Odtworzenie rozmowy na innym urządzeniu (1.23.0): tylko tekst tur.
            chat = (parse_qs(parsed.query).get("chat") or [""])[0]
            try:
                self._send_json({"tury": rozmowa_mod.turns(chat)})
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/rozmowa/powrot":
            # "Gdzie skończyliśmy" (agent/rozmowa.py): po przerwie, bez modelu.
            chat = (parse_qs(parsed.query).get("chat") or [""])[0]
            try:
                out = rozmowa_mod.powrot(chat)
                out["streszczenie"] = rozmowa_mod.summary(chat)
                self._send_json(out)
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/sources":
            chat = (parse_qs(parsed.query).get("chat") or [""])[0]
            try:
                self._send_json(sources_mod.status(chat))
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/debug/teraz":
            # Blok „Teraz” (agent/awareness.py) dokładnie w tej postaci, w jakiej
            # trafi do modelu przy NAJBLIŻSZEJ wiadomości: wersja lokalna (pełna)
            # i chmurowa (sam zegar i liczby). Do panelu /debug: "co GREGAI wie w
            # tej chwili" ma być widoczne, nie domyślne. Sam blok, bez reszty
            # promptu (ten jest statyczny i stoi w agent/prompt.md).
            try:
                v = get_vault()
                self._send_json({
                    "local": awareness_mod.local_block(v).strip(),
                    "cloud": awareness_mod.cloud_block().strip(),
                    "max_chars": awareness_mod.MAX_BLOCK_CHARS,
                    "next_clock_change": awareness_mod.next_change_hint(),
                })
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/api/system_info":
            try:
                self._send_json({
                    "host": sysinfo_mod.host_info(),
                    "ollama": sysinfo_mod.ollama_info(router_mod.OLLAMA_HOST),
                    "ollama_model": router_mod.OLLAMA_MODEL,
                    # Wytrenowany router do kroku 1 (patrz router.py:
                    # ROUTER_MODEL i training/README.md): czy jest
                    # włączony i aktualny, a jeśli nie, to dlaczego -
                    # po polsku, do panelu /debug.
                    "router": router_mod.router_status(),
                    # Koryto (1.17.0, agent/koryto.py): JEDNA kolejność etapów
                    # dla całego myślenia (domyślnie Claude -> darmowa pula ->
                    # lokalnie) i przełączniki routingu/zadań przez sieć.
                    "koryto": koryto_mod.status(),
                    # Etap "anthropic" koryta (Claude): klucz, model, ile dziś
                    # wywołań z limitu. Bez klucza, nigdy.
                    "cloud": router_mod.cloud_status(),
                    # Etap "darmowe" koryta (agent/juggler.py): pula darmowych
                    # dostawców (Groq/Gemini/OpenRouter/Hugging Face/
                    # Cloudflare), który ma klucz, ile dziś wywołań z limitu PER
                    # DOSTAWCA (providers - razem z Claude). Bez klucza, nigdy.
                    "juggler": router_mod.juggler_status(),
                    # 1.24.0: straż i budżet widoczne w Nadzorcy (szacunek USD z dziennika koryta).
                    "straz": _safe_call(straz_mod.status),
                    "budzet": _safe_call(juggler_mod.spent_usd),
                    # Cloudflare WARP (agent/netguard.py): bez połączenia
                    # GREGAI nie wychodzi do internetu (fail-closed).
                    "warp": netguard_mod.status(),
                    # Uczeń rozmowy (router.py: STUDENT_MODEL): mały model z
                    # osobowością w wagach, krótki prompt zamiast prompt.md.
                    "student": router_mod.student_status(),
                    "planner": router_mod.planner_status(),
                    # Rozgrzewanie modeli po starcie (router.warm_status).
                    "warm": router_mod.warm_status(),
                    # Warstwa systemowa (agent/sysop.py): czy włączona, jakie
                    # katalogi dozwolone, ostatnie wpisy dziennika audytu.
                    "sysop": {"enabled": sysop_mod.enabled(), "shell": sysop_mod.shell_enabled(),
                              # 1.17.0: tryb (strazniczy/pelny) i polityka pytań o
                              # zgodę (SYSOP_PYTAJ) - patrz sysop.py, "Tryb pełny".
                              "mode": sysop_mod.mode(), "pytaj": sysop_mod.pytaj(), "full": sysop_mod.full(),
                              "tools": sorted(sysop_mod.active_tools()), "roots": [str(r) for r in sysop_mod.roots()],
                              "use_sudo": sysop_mod.use_sudo(), "recent": sysop_mod.recent_log(5)},
                    "version": VERSION,
                    "project_root": str(Path(__file__).resolve().parent.parent),
                    # Przełącznik z /debug (patrz _handle_lan_mode): aktualny stan z .env.
                    # Token wprost w odpowiedzi - ten endpoint i tak wymaga _authorized()
                    # (ta maszyna albo już poprawny token), jak każde /api/, więc to nie
                    # jest nowy wyciek: kto go czyta, już go ma albo jest na tym laptopie.
                    "lan": {"enabled": LAN_MODE, "token_configured": bool(GREGAI_TOKEN), "token": GREGAI_TOKEN},
                })
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return

        if route == "/" or route == "":
            self._send_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            return

        if route == "/debug" or route == "/debug/":
            self._send_file(UI_DIR / "debug.html", "text/html; charset=utf-8")
            return

        if route.startswith("/api/"):
            self._send_json({"error": "Nie znaleziono"}, status=404)
            return
        if route == "/favicon.ico":
            self._send_file(UI_DIR / "ikona-32.png", "image/png")  # ikona strony (1.17.0)
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".woff2": "font/woff2",  # 1.31.0: lokalne fonty interfejsu (ui/fonty, licencja OFL)
        }
        try:
            target = (UI_DIR / route.lstrip("/")).resolve()
        except (OSError, ValueError):  # np. bajt zerowy w adresie
            self._send_json({"error": "Nie znaleziono"}, status=404)
            return
        ext = target.suffix.lower()
        if UI_DIR.resolve() not in target.parents or ext not in content_types:
            # Wyłącznie html/js/css/svg/png/woff2 z folderu ui/: nic innego nie jest serwowane.
            self._send_json({"error": "Nie znaleziono"}, status=404)
            return
        self._send_file(target, content_types[ext])

    def do_POST(self):
        # 1.32.3 (audyt tura 8): ciała "chunked" nie czytamy (czytamy tylko Content-Length), więc
        # takie żądanie dawało puste {} - np. usunięcie rozmowy bez wskazania której.
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self._send_json({"error": "Wymagany nagłówek Content-Length (bez Transfer-Encoding)"}, status=411)
            return
        ok, why = self._browser_origin_ok()
        if not ok:
            self._send_json({"error": f"Odrzucone: {why}"}, status=403)
            return
        # Tylko JSON: formularz albo "text/plain" z obcej strony nie przejdzie
        # (przeglądarka nie wyśle application/json z obcej strony bez zgody
        # serwera, a tej zgody (CORS) serwer nie daje).
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._send_json({"error": "Odrzucone: wymagany Content-Type: application/json"}, status=415)
            return
        if not self._auth_gate():
            return

        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._send_json({"error": "Nieprawidłowy Content-Length"}, status=400)
            return
        body_limit = MAX_UPLOAD_BODY_BYTES if parsed.path == "/api/upload" else MAX_BODY_BYTES
        if length > body_limit:
            # Ciało czytamy i wyrzucamy (najwyżej 64 MB): odpowiedź przed końcem wysyłania kończyła
            # się zerwanym połączeniem, a przeglądarka pokazywała ogólny błąd sieci zamiast „za duże”.
            # 1.29.0 (kontrola): ale nie dłużej niż 2 s ciszy - pakiet z fałszywym
            # Content-Length: 50 MB trzymał wątek i miejsce połączenia przez 20 s.
            remaining = min(length, 64 * 1024 * 1024)
            try:
                self.connection.settimeout(2)
            except OSError:
                pass
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass
            self._request_read_done()
            self.close_connection = True
            self._send_json({"error": "Żądanie za duże"}, status=413)
            return
        if length:
            self._arm_deadline(self.REQUEST_READ_DEADLINE + min(600.0, length / self.BODY_RATE_BPS))
        raw_body = self.rfile.read(length) if length else b""
        self._request_read_done()
        if len(raw_body) != length:
            # Zerwane w trakcie wysyłania (albo zamknięte po terminie): ucięty JSON notatki
            # mógłby być poprawny i zostać zapisany jako cała notatka.
            self._send_json({"error": "Niepełne ciało żądania"}, status=400)
            return

        if parsed.path in _JSON_POST_PATHS:
            try:
                _parse_body(raw_body)
            except ValueError:
                self._send_json({"error": "Nieprawidłowy JSON"}, status=400)
                return

        if parsed.path == "/api/chat":
            self._handle_chat(raw_body)
            return
        if parsed.path == "/api/chat/wait":
            self._handle_chat_wait(raw_body)
            return
        if parsed.path == "/api/chat/cancel":
            self._handle_chat_cancel(raw_body)
            return
        if parsed.path == "/api/rozmowa/usun":
            self._handle_rozmowa_usun(raw_body)
            return
        if parsed.path == "/api/note":
            self._handle_note_save(raw_body)
            return
        if parsed.path == "/api/note/create":
            self._handle_note_create(raw_body)
            return
        if parsed.path == "/api/note/delete":
            self._handle_note_delete(raw_body)
            return
        if parsed.path == "/api/note/przywroc":
            self._handle_note_restore(raw_body)
            return
        if parsed.path == "/api/debug/learned/zapomnij":
            # 1.32.11 (audyt tura 15): wyuczony wzorzec da się usunąć z Nadzorcy (dotąd tylko korektą
            # w następnej wiadomości).
            try:
                payload = _parse_body(raw_body) or {}
                tool, words = payload.get("tool"), payload.get("words")
                if not isinstance(tool, str) or not isinstance(words, list) or not all(isinstance(w, str) for w in words):
                    self._send_json({"error": "Podaj narzędzie i listę słów wzorca."}, status=400)
                    return
                ok = learning_mod.forget_route(tool, words)
                self._send_json({"forgotten": bool(ok)})
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return
        if parsed.path == "/api/restart":
            self._handle_restart()
            return
        if parsed.path == "/api/debug/lan":
            self._handle_lan_mode(raw_body)
            return
        if parsed.path == "/api/namysl/settings":
            try:
                self._send_json(namysl_mod.save_settings(_parse_body(raw_body)))
            except ValueError as e:
                self._send_json({"error": str(e) if ("material_do_sieci" in str(e) or "tryb" in str(e)) else "Nieprawidłowy JSON"}, status=400)
            except Exception as e:
                self._send_json({"error": _error_text(e)}, status=500)
            return
        if parsed.path == "/api/sources":
            self._handle_sources(raw_body)
            return
        if parsed.path == "/api/upload":
            self._handle_upload(raw_body)
            return
        self._send_json({"error": "Nie znaleziono"}, status=404)

    def _handle_sources(self, raw_body: bytes):
        """{"chat": id, "dodaj": ścieżka} albo {"chat": id, "usun": ścieżka} ->
        stan listy źródeł TEJ rozmowy (agent/sources.py). Odmowa zawsze z
        powodem po polsku."""
        payload = _parse_body(raw_body)
        if not isinstance(payload, dict):
            self._send_json({"error": "Nieprawidłowe dane"}, status=400)
            return
        chat = sources_mod.chat_id(payload.get("chat"))
        try:
            if isinstance(payload.get("dodaj"), str):
                r = sources_mod.add(chat, payload["dodaj"])
            elif isinstance(payload.get("usun"), str):
                r = sources_mod.remove(chat, payload["usun"])
            else:
                self._send_json({"error": "Podaj 'dodaj' albo 'usun'"}, status=400)
                return
            r["status"] = sources_mod.status(chat)
            self._send_json(r, status=200 if r.get("ok") else 400)
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _handle_upload(self, raw_body: bytes):
        """{"chat": id, "name": nazwa, "data_base64": treść} -> plik w
        data/wgrane/<rozmowa> (agent/sources.py: limit rozmiaru, lista
        rozszerzeń, bezpieczna nazwa, nigdy nadpisanie). Odpowiedź: {"ok",
        "name", "size"} albo {"error"}."""
        import base64
        payload = _parse_body(raw_body)
        if not isinstance(payload, dict) or not isinstance(payload.get("name"), str) or not isinstance(payload.get("data_base64"), str):
            self._send_json({"error": "Podaj 'name' i 'data_base64'"}, status=400)
            return
        try:
            data = base64.b64decode(payload["data_base64"], validate=True)
        except (ValueError, TypeError):
            self._send_json({"error": "Nieprawidłowe base64"}, status=400)
            return
        try:
            r = sources_mod.save_upload(sources_mod.chat_id(payload.get("chat")), payload["name"], data)
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)
            return
        if not r.get("ok"):
            self._send_json({"error": r.get("why") or "Nie udało się zapisać pliku"}, status=400)
            return
        self._send_json({"ok": True, "name": r["name"], "size": r["size"]})

    def _handle_restart(self):
        """Restart GREGAI z przycisku na /debug, bez sudo: os.execve podmienia
        obraz TEGO procesu na świeży `python3 agent/main.py` (nowy import
        każdego modułu, nowy wątek serca), jak `systemctl restart`, ale z
        wnętrza procesu. Dla systemd to ten sam proces (ten sam PID).

        Odpowiedź idzie do przeglądarki NAJPIERW, exec dopiero po chwili
        (_delayed_restart): exec zastępuje cały proces. Nowy proces dostaje
        środowisko sprzed wczytania .env (_PRE_ENV_SNAPSHOT), bo load_env()
        nigdy nie nadpisuje klucza już obecnego w os.environ: bez tego restart
        zachowałby stare wartości (także te usunięte z .env, np. SYSOP_SHELL=1)."""
        # 1.32.10 (audyt tura 14): restart najwyżej raz na 30 s (pętla restartów z tokenem).
        global _LAST_RESTART
        now = time.monotonic()
        if now - _LAST_RESTART < 30:
            self._send_json({"error": "GREGAI dopiero co się restartował - spróbuj za chwilę."}, status=429)
            return
        _LAST_RESTART = now
        self._send_json({"restarting": True})

        def _delayed_restart():
            time.sleep(0.5)
            os.execve(sys.executable, [sys.executable] + sys.argv, _PRE_ENV_SNAPSHOT)

        threading.Thread(target=_delayed_restart, daemon=True).start()

    def _handle_lan_mode(self, raw_body: bytes):
        """Przełącznik 'udostępnij w sieci lokalnej' z /debug (prośba
        Grzegorza: chce dać dostęp do GREGAI z innego urządzenia do testów).

        Zapisuje GREGAI_LAN=0/1 w .env (i, przy włączaniu, dopisuje nowy
        GREGAI_TOKEN losowy jak w install.sh - secrets.token_urlsafe(32) -
        jeśli żadnego jeszcze nie ma) jednym atomowym zapisem
        (env_loader.set_env_vars), reszty .env nie dotykając.

        Realny nasłuch (gniazdo BIND_HOST/PORT) NIE zmienia się od razu -
        to wymaga restartu (przycisk na /debug woła ten endpoint, a potem
        /api/restart), bo gniazdo jest tworzone raz, przy starcie procesu.
        Moduły LAN_MODE/GREGAI_TOKEN/BIND_HOST aktualizujemy jednak w
        PAMIĘCI od razu (global niżej) - inaczej dwa kliknięcia "Zastosuj"
        przed zdążeniem restartu (albo zwykłe odświeżenie /debug w tym
        oknie) wygenerowałyby DRUGI token, cichcem gubiąc pierwszy, który
        użytkownik mógł już skopiować na drugie urządzenie.

        Zapora (ufw) jest celowo NIETKNIĘTA. agent/sysop.py traktuje ufw jako
        chronione (dozwolony tylko odczyt: 'ufw status', nigdy zmiana) -
        żadna ścieżka w kodzie GREGAI, także ta, nie ma prawa to złamać.
        Otwarcie portu w zaporze (gdy ufw jest aktywny) zostaje więc ręczną
        decyzją Grzegorza: install.sh (ten sam klucz .env, więc widzi nowe
        GREGAI_LAN) albo polecenia z ostrzeżenia w odpowiedzi niżej."""
        global LAN_MODE, GREGAI_TOKEN, BIND_HOST
        try:
            payload = _parse_body(raw_body)
        except ValueError:
            self._send_json({"error": "Nieprawidłowy JSON"}, status=400)
            return
        enabled = payload.get("enabled") if isinstance(payload, dict) else None
        if not isinstance(enabled, bool):
            self._send_json({"error": "Brak pola 'enabled' (true/false)"}, status=400)
            return
        token = GREGAI_TOKEN
        token_generated = False
        updates = {"GREGAI_LAN": "1" if enabled else "0"}
        if enabled and not token:
            token = secrets.token_urlsafe(32)
            updates["GREGAI_TOKEN"] = token
            token_generated = True
        comments = {
            "GREGAI_LAN": ("# Dostęp z sieci lokalnej (przełącznik na /debug). GREGAI_LAN=1: nasłuch\n"
                           "# na 0.0.0.0, wymaga GREGAI_TOKEN (niżej) od każdego poza tym komputerem.\n"
                           "# Samo to NIE wystarcza przy aktywnej zaporze (ufw) - patrz README/install.sh.\n"),
            "GREGAI_TOKEN": "# Token wygenerowany automatycznie przy pierwszym włączeniu dostępu z sieci.\n",
        }
        try:
            set_env_vars(updates, comments)
        except OSError as e:
            self._send_json({"error": f"Nie udało się zapisać .env: {_error_text(e)}"}, status=500)
            return
        LAN_MODE, GREGAI_TOKEN = enabled, token
        BIND_HOST = "0.0.0.0" if enabled else "localhost"
        self._send_json({
            "ok": True,
            "enabled": enabled,
            "token": token,
            "token_generated": token_generated,
            "restart_required": True,
        })

    def _handle_chat(self, raw_body: bytes):
        try:
            payload = _parse_body(raw_body)
        except ValueError:
            self._send_json({"error": "Nieprawidłowy JSON"}, status=400)
            return
        try:
            message = payload.get("message") if isinstance(payload, dict) else None
            if not isinstance(message, str) or not message.strip():
                self._send_json({"error": "Brak wiadomości"}, status=400)
                return
            if len(message) > MAX_CHAT_CHARS:
                self._send_json({"error": f"Wiadomość jest za długa ({len(message)} znaków, najwyżej {MAX_CHAT_CHARS})"}, status=413)
                return
            job_id = _start_chat_job(payload)
            self._send_chat_result(job_id, wait=CHAT_FIRST_WAIT)
        except ChatBusy:
            self._send_json({"error": "Za dużo rozmów czeka w kolejce. Poczekaj na odpowiedź i napisz jeszcze raz."}, status=429)
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _handle_chat_cancel(self, raw_body: bytes):
        """Stop: {"job": id} -> zadanie oznaczone jako zatrzymane, a oczekujący
        /api/chat/wait dostaje {"anulowano": true} od razu. Praca w tle kończy
        się przy najbliższej granicy fazy Namysłu; pojedyncze wywołanie modelu
        w toku dobiega końca, ale jego wynik jest wyrzucany (nic nie trafia do
        rozmowy ani pamięci)."""
        try:
            payload = _parse_body(raw_body)
            job_id = str(payload.get("job") or "") if isinstance(payload, dict) else ""
            with _CHAT_JOBS_LOCK:
                job = _CHAT_JOBS.get(job_id)
            if job is None:
                self._send_json({"ok": False, "why": "nie ma takiego zadania (już skończone albo wygasło)"})
                return
            # Zadanie już skończone (1.20.0): jego wynik zostaje, bo mogło coś
            # wykonać. Stop nie może go zafałszować na "anulowano".
            if job["done"].is_set():
                self._send_json({"ok": False, "why": "już skończone"})
                return
            job["cancel"].set()
            job["result"] = {"anulowano": True}
            job["done"].set()
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _handle_rozmowa_usun(self, raw_body: bytes):
        """Kosz rozmowy: {"chat": id} -> kasuje pamięć rozmowy (tury, streszczenie),
        listę folderów Źródeł i wgrane pliki TEJ rozmowy. Notatki, projekt w
        grafie i foldery użytkownika zostają. Trwające zadania tej rozmowy są
        zatrzymywane."""
        try:
            payload = _parse_body(raw_body)
            if not isinstance(payload, dict):
                self._send_json({"error": "Nieprawidłowe dane"}, status=400)
                return
            # 1.32.3 (audyt tura 8): bez identyfikatora (albo z takim, który się zmienia po
            # oczyszczeniu) chat_id wracał do "ogolna" - usuwanie kasowało Ogólną rozmowę.
            raw_chat = payload.get("chat")
            if (not isinstance(raw_chat, str) or not raw_chat.strip()
                    or (sources_mod.chat_id(raw_chat) == sources_mod.GENERAL_CHAT and raw_chat.strip() != sources_mod.GENERAL_CHAT)):
                self._send_json({"error": "Nieprawidłowy identyfikator rozmowy"}, status=400)
                return
            chat = sources_mod.chat_id(raw_chat)
            with _CHAT_JOBS_LOCK:
                for j in _CHAT_JOBS.values():
                    if j.get("chat") == chat and not j["done"].is_set():
                        j["cancel"].set(); j["result"] = {"anulowano": True}; j["done"].set()
            src = sources_mod.delete_chat(chat)
            mem = rozmowa_mod.delete(chat)
            try:
                agentloop_mod.forget_chat(sources_mod.chat_id(chat))
            except Exception:
                pass
            try:
                # 1.32.2 (audyt tura 7): nazwa dla człowieka i poprawna odmiana liczebnika.
                nazwa = "Ogólna rozmowa" if sources_mod.chat_id(chat) == "ogolna" else chat
                trace_mod.record("rozmowa_usunieta", f"usunięto rozmowę „{nazwa}”: {_pl_count(src['foldery'], 'folder', 'foldery', 'folderów')}, "
                                 f"{_pl_count(src['wgrane'], 'plik', 'pliki', 'plików')}", tool=None)
            except Exception:
                pass
            self._send_json({"ok": True, "chat": chat, "foldery": src["foldery"], "wgrane": src["wgrane"], "pamiec": mem})
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _handle_chat_wait(self, raw_body: bytes):
        try:
            payload = _parse_body(raw_body)
        except ValueError:
            self._send_json({"error": "Nieprawidłowy JSON"}, status=400)
            return
        try:
            job_id = str(payload.get("job") or "") if isinstance(payload, dict) else ""
            self._send_chat_result(job_id)
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _send_chat_result(self, job_id: str, wait: float = CHAT_WAIT):
        with _CHAT_JOBS_LOCK:
            job = _CHAT_JOBS.get(job_id)
        if job is None:
            self._send_json({"error": "Nie ma takiej rozmowy w toku (minęła godzina albo GREGAI był restartowany). Napisz jeszcze raz."}, status=404)
            return
        job["last_poll"] = time.monotonic()
        if not job["done"].wait(wait):
            self._send_json({"pending_job": job_id})
            return
        # Zadanie zostaje w pamięci do wygaśnięcia TTL (sprząta je
        # _start_chat_job): gdy przeglądarka zerwała połączenie przed
        # odebraniem odpowiedzi, kolejne /api/chat/wait dostanie ją jeszcze raz
        # zamiast 404, po którym użytkownik pytałby ponownie (i mógłby
        # drugi raz uruchomić potwierdzoną zmianę).
        result = job["result"] or {"error": "Pusta odpowiedź"}
        self._send_json(result, status=500 if "error" in result else 200)

    def _handle_note_get(self, slug: str):
        if not slug:
            self._send_json({"error": "Brak id notatki"}, status=400)
            return
        try:
            v = get_vault()
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)
            return
        note = v.notes.get(slug)
        if not note:
            self._send_json({"error": f"Nie znaleziono notatki: {slug}"}, status=404)
            return
        text, readonly, reason = note.text, not _is_writable(note), _readonly_reason(note)
        if not readonly:
            # Edytor dostaje to, co JEST na dysku (nie kopię z pamięci), razem ze
            # znacznikiem wersji: zapis odmówi, gdy plik zmieni się w międzyczasie.
            try:
                fresh, lossy_now = vault_mod._read_file(Path(note.path))
            except OSError:
                self._send_json({"error": "Tej notatki nie ma już na dysku."}, status=404)
                return
            if lossy_now:
                readonly, reason = True, "kodowanie"
            else:
                text = fresh
        self._send_json({
            "id": note.slug,
            "title": note.title,
            "type": note.ntype,
            "text": text,
            "body": _strip_title_and_type(text),
            "version": vault_mod.text_version(text),
            "readonly": readonly,
            "readonly_reason": reason,
        })

    def _handle_note_save(self, raw_body: bytes):
        try:
            payload = _parse_body(raw_body)
            slug = payload.get("id") if isinstance(payload, dict) else None
            new_text = payload.get("text") if isinstance(payload, dict) else None
            if not slug or not isinstance(slug, str) or not isinstance(new_text, str):
                self._send_json({"error": "Brak id lub text"}, status=400)
                return
            if not new_text.strip():
                self._send_json({"error": "Treść notatki nie może być pusta"}, status=400)
                return
            new_text = new_text.replace("\r\n", "\n").replace("\r", "\n")  # styl pliku wraca w restyle
            if len(new_text.encode("utf-8")) > vault_mod.MAX_FILE_BYTES:
                self._send_json({"error": NOTE_TOO_BIG}, status=413)
                return
            base = payload.get("base")
            if base is not None and not isinstance(base, str):
                self._send_json({"error": "Nieprawidłowa wersja notatki"}, status=400)
                return
            with _NOTE_LOCK:
                self._save_note_locked(slug, new_text, base)
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _save_note_locked(self, slug: str, new_text: str, base: str | None = None):
        invalidate_vault_cache()  # świeży build: backlinki do notatek z ostatnich sekund (1.20.0)
        v = get_vault()
        note = v.notes.get(slug)
        if not note:
            self._send_json({"error": f"Nie znaleziono notatki: {slug}"}, status=404)
            return
        if not _is_writable(note):
            self._send_json({"error": _readonly_message(note)}, status=400)
            return
        if base:
            # Edytor odsyła wersję, od której zaczął. Plik zmieniony od tamtej pory
            # (inny edytor, synchronizacja) nie może zostać po cichu nadpisany.
            try:
                current, lossy_now = vault_mod._read_file(Path(note.path))
            except OSError:
                self._send_json({"error": "Tej notatki nie ma już na dysku."}, status=404)
                return
            if lossy_now or vault_mod.text_version(current) != base:
                self._send_json({"error": "Ta notatka zmieniła się na dysku od otwarcia edycji, więc nie zapisuję "
                                          "(nie nadpiszę cudzych zmian). Skopiuj swój tekst, kliknij Anuluj i otwórz "
                                          "notatkę ponownie."}, status=409)
                return

        old_title = note.title
        # Bez nagłówka indeks nazwie notatkę po pliku: taki tytuł idzie do kontroli
        # zdublowania i do przepisania linków (inaczej [[stary tytuł]] cicho by zawisł).
        new_title = vault_mod.find_title(new_text) or Path(note.path).stem
        norm = vault_mod.normalize_title
        if norm(new_title) != norm(old_title):
            # Dwa różne pliki o tym samym tytule: [[link]] wskazywałby jeden z nich
            # (zależnie od kolejności plików), a zmiana nazwy przepisałaby cudze linki.
            clash = v.by_title.get(norm(new_title))
            if clash and clash != slug:
                self._send_json({"error": f"Inna notatka ma już tytuł „{new_title}”. Wybierz inny tytuł, "
                                          "żeby [[linki]] wskazywały jednoznacznie."}, status=409)
                return
        # Rozmiar liczymy PO przywróceniu stylu pliku: CRLF dodaje bajt na każdą linię, a plik
        # powyżej limitu zniknąłby z grafu przy następnym indeksowaniu.
        styled = vault_mod.restyle(new_text, *vault_mod.file_style(Path(note.path)))
        if len(styled.encode("utf-8")) > vault_mod.MAX_FILE_BYTES:
            self._send_json({"error": NOTE_TOO_BIG}, status=413)
            return
        fsutil.atomic_write_text(note.path, styled)

        backlinks_updated = backlinks_failed = 0
        backlinks_skipped = None
        # Linki przepisujemy tylko wtedy, gdy TA notatka jest adresatem linków do
        # starego tytułu (przy zdublowanym tytule wskazują na tę, która była pierwsza).
        owns_old_title = v.by_title.get(norm(old_title)) == slug
        # Tytuł z ] | # nie da się wpisać w [[link]] (parser linków ich nie przyjmuje):
        # przepisanie linków ucięłoby je i zgubiło krawędź grafu, więc zostają bez zmian,
        # a użytkownik dowiaduje się o tym wprost (inaczej "Zapisano." ukrywałoby zerwane połączenia).
        title_changed = bool(new_title) and new_title != old_title
        if title_changed and re.search(r"[\[\]|#]", new_title):
            backlinks_skipped = ("nowy tytuł zawiera [ ] | lub #, więc połączeń [[stary tytuł]] w innych notatkach "
                                 "nie przepisałem; wskazują teraz nieistniejącą notatkę.")
        elif title_changed and not owns_old_title:
            backlinks_skipped = "inna notatka miała ten sam stary tytuł, więc połączeń w innych notatkach nie przepisałem."
        elif title_changed and len(old_title) > MAX_BACKLINK_TITLE:
            backlinks_skipped = (f"stary tytuł ma ponad {MAX_BACKLINK_TITLE} znaków, więc połączeń [[stary tytuł]] "
                                 "w innych notatkach nie przepisałem.")
        if owns_old_title and title_changed and backlinks_skipped is None:
            # Rozwiązywanie [[linków]] ignoruje wielkość liter i różnice w
            # białych znakach (vault.normalize_title), więc przepisywanie
            # też; zachowujemy #sekcję i |alias.
            pattern = _backlink_pattern(old_title)
            for other in v.notes.values():
                if other.slug == slug or not _is_writable(other) or not pattern.search(other.text):
                    continue
                # Świeży odczyt z dysku, nie z cache: między budową vault a
                # zapisem plik mógł się zmienić (ręczna edycja, drugi zapis).
                try:
                    current, lossy_now = vault_mod._read_file(Path(other.path))
                except OSError:
                    continue
                if lossy_now:
                    continue  # plik nie jest czystym UTF-8: nie przepisujemy go
                # 1.27.1: dopasowania szukane w tekście z zamaskowanym kodem (ta sama długość),
                # podmiana w oryginale po pozycjach - `[[Kawa]]` w kodzie zostaje nietknięte.
                masked_now = vault_mod.mask_code(current)
                pieces, last = [], 0
                for m in pattern.finditer(masked_now):
                    orig = pattern.match(current, m.start(), m.end())
                    if orig is None:
                        continue
                    pieces.append(current[last:m.start()])
                    pieces.append(f"[[{new_title}{orig.group(1) or ''}{orig.group(2) or ''}]]")
                    last = m.end()
                pieces.append(current[last:])
                updated_text = "".join(pieces)
                if updated_text != current:
                    try:
                        styled_other = vault_mod.restyle(updated_text, *vault_mod.file_style(Path(other.path)))
                        if len(styled_other.encode("utf-8")) > vault_mod.MAX_FILE_BYTES:
                            # Dłuższy tytuł w linkach wypchnąłby cudzą notatkę ponad limit i zniknęłaby z grafu.
                            raise OSError("notatka przekroczyłaby limit rozmiaru")
                        fsutil.atomic_write_text(other.path, styled_other)
                        backlinks_updated += 1
                    except OSError as e:
                        # Notatka jest już zapisana: błąd w cudzym pliku nie cofa jej,
                        # tylko jest zgłoszony (reszta linków dalej się przepisuje).
                        backlinks_failed += 1
                        sys.stderr.write(f"BŁĄD: nie przepisano linku w {other.slug}: {e}\n")

        invalidate_vault_cache()
        result = {"saved": True, "id": slug, "backlinks_updated": backlinks_updated}
        if backlinks_failed:
            result["backlinks_failed"] = backlinks_failed
        if backlinks_skipped and (len(old_title) > MAX_BACKLINK_TITLE or any(
                _backlink_pattern(old_title).search(o.text) for o in v.notes.values() if o.slug != slug)):
            result["backlinks_skipped"] = backlinks_skipped
        self._send_json(result)

    def _handle_note_create(self, raw_body: bytes):
        try:
            payload = _parse_body(raw_body)
            if not isinstance(payload, dict):
                self._send_json({"error": "Nieprawidłowe dane"}, status=400)
                return
            raw = payload.get("raw")

            if raw is not None:
                if not isinstance(raw, str) or not raw.strip():
                    self._send_json({"error": "Brak treści notatki"}, status=400)
                    return
                content = raw.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
                title = vault_mod.find_title(content) or "Notatka"
                ntype = vault_mod.find_type(content) or "Note"
            else:
                # Tytuł w jednej linii, typ jednym słowem: inaczej nowa linia w
                # tytule dopisałaby własne pola nagłówka ("A\ntype: Sop").
                # 1.32.3 (audyt tura 8): tylko tekst (dawniej {"a":1} stawało się treścią "{'a': 1}").
                for key in ("title", "type", "text"):
                    if payload.get(key) is not None and not isinstance(payload.get(key), str):
                        self._send_json({"error": f"Pole {key} musi być tekstem"}, status=400)
                        return
                title = " ".join(str(payload.get("title") or "").split())
                ntype = str(payload.get("type") or "Note").strip()
                if not re.fullmatch(r"[\w-]{1,40}", ntype):
                    ntype = "Note"
                text = str(payload.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
                if not title:
                    self._send_json({"error": "Brak tytułu"}, status=400)
                    return
                content = f"# {title}\ntype: {ntype}\n\n{text.strip()}\n"

            # 1.27.0 (audyt): [[link]] czyta "#" jako sekcję, a "|" jako alias - do notatki
            # (albo projektu) o takim tytule nie da się niczego podpiąć.
            if _CTRL_TITLE_RE.search(title):
                self._send_json({"error": "Tytuł zawiera niewidoczne znaki sterujące - usuń je i spróbuj jeszcze raz"}, status=400)
                return
            if _BAD_TITLE_RE.search(title):
                self._send_json({"error": BAD_TITLE_TEXT}, status=400)
                return
            if len(content.encode("utf-8")) > vault_mod.MAX_FILE_BYTES:
                self._send_json({"error": NOTE_TOO_BIG}, status=413)
                return
            roots = data_mod.get_vault_roots()
            if not roots:
                self._send_json({"error": "Brak skonfigurowanego folderu do zapisu"}, status=500)
                return
            target_root = Path(roots[0])

            slug_base = vault_mod.slugify(title)
            filename = f"{slug_base}.md"
            counter = 2
            duplicate = False
            # Sprawdzenie tytułu i utworzenie pliku pod jedną blokadą, na świeżym vault:
            # dwa równoczesne zapisy (podwójne kliknięcie, dwie karty) nie zrobią dwóch
            # notatek o tym samym tytule ([[link]] byłby niejednoznaczny). Wyłączne
            # utworzenie (O_EXCL) dodatkowo chroni przed nadpisaniem pliku o tej nazwie.
            with _NOTE_LOCK:
                invalidate_vault_cache()
                effective_title = vault_mod.find_title(content) or slug_base
                # Wklejony tekst bez nagłówka "# ..." nie ma własnego tytułu: o nazwie
                # decyduje wolny plik (notatka-2.md...), nie odmowa "już istnieje".
                untitled_paste = raw is not None and not vault_mod.find_title(content)
                if not untitled_paste and any(vault_mod.normalize_title(t) in get_vault().by_title for t in {title, effective_title}):
                    duplicate = True
                else:
                    while not fsutil.create_new_text(target_root / filename, content, mode=0o644):
                        filename = f"{slug_base}-{counter}.md"
                        counter += 1
                    invalidate_vault_cache()
            if duplicate:
                self._send_json({"error": f"Notatka o tytule „{title}” już istnieje. Wybierz inny tytuł "
                                          "albo otwórz istniejącą notatkę."}, status=409)
                return
            self._send_json({"created": True, "id": filename, "title": title, "type": ntype})
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _handle_note_restore(self, raw_body: bytes):
        try:
            payload = _parse_body(raw_body)
            self._send_json(restore_from_trash((payload or {}).get("kosz") if isinstance(payload, dict) else None))
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            self._send_json({"error": str(e)}, status=409 if isinstance(e, FileExistsError) else 400)
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)

    def _handle_note_delete(self, raw_body: bytes):
        try:
            payload = _parse_body(raw_body)
            slug = payload.get("id") if isinstance(payload, dict) else None
            if not slug or not isinstance(slug, str):
                self._send_json({"error": "Brak id"}, status=400)
                return

            seen_title = payload.get("title")
            if seen_title is not None and not isinstance(seen_title, str):
                self._send_json({"error": "Pole title musi być tekstem"}, status=400)
                return
            # 1.32.3 (audyt tura 8): sprawdzenie i usunięcie pod JEDNĄ blokadą, na świeżym
            # odczycie - równoległy zapis (zmiana tytułu i treści) mógł wejść między nie,
            # a usunięcie kasowało już nową notatkę.
            with _NOTE_LOCK:
                invalidate_vault_cache()
                v = get_vault()
                note = v.notes.get(slug)
                if not note:
                    self._send_json({"error": f"Nie znaleziono notatki: {slug}"}, status=404)
                    return
                if not _is_writable(note):
                    self._send_json({"error": _readonly_message(note)}, status=400)
                    return
                if isinstance(seen_title, str) and seen_title.strip() and \
                        vault_mod.normalize_title(seen_title) != vault_mod.normalize_title(note.title):
                    self._send_json({"error": f"Pod tym adresem jest teraz inna notatka („{note.title}”). "
                                              "Odśwież widok i spróbuj jeszcze raz - nic nie usunąłem."}, status=409)
                    return
                # 1.32.10 (audyt tura 14): notatki, które wskazywały TĘ notatkę (po rozwiązaniu
                # linków, także po nazwie pliku i bez ogonków) - po usunięciu sprawdzamy, czy
                # ich link wisi, czy przeskoczył na inną notatkę o podobnym tytule.
                sources = [o.slug for o in v.notes.values() if o.slug != slug and slug in o.links]
                # Do kosza (data/kosz), nie na zawsze - "Cofnij" przywraca plik.
                kosz = fsutil.move_to_trash(note.path, TRASH_DIR, note.path)
                invalidate_vault_cache()
                v2 = get_vault()
                dangling = repointed = 0
                for s_ in sources:
                    o = v2.notes.get(s_)
                    if o is None:
                        continue
                    if o.links - set(v.notes[s_].links) - {slug}:
                        repointed += 1
                    else:
                        dangling += 1
            invalidate_vault_cache()
            self._send_json({"deleted": True, "id": slug, "dangling_links": dangling, "repointed_links": repointed,
                             "kosz": kosz})
        except Exception as e:
            self._send_json({"error": _error_text(e)}, status=500)


def restore_from_trash(name: str) -> dict:
    """1.32.10: przywraca notatkę z kosza na jej dawne miejsce (nie nadpisuje istniejącej)."""
    if not isinstance(name, str) or not re.fullmatch(r"[\w.\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]{1,300}", name) or name.endswith(".json") or ".." in name:
        raise ValueError("Nieprawidłowa nazwa wpisu w koszu.")
    src, meta = TRASH_DIR / name, TRASH_DIR / (name + ".json")
    if not src.is_file() or not meta.is_file():
        raise FileNotFoundError("Nie ma już tej notatki w koszu.")
    orig = Path(json.loads(meta.read_text(encoding="utf-8")).get("z") or "")
    roots = [Path(r).resolve() for r in data_mod.get_vault_roots()]
    if not orig.name or not any(orig.resolve().is_relative_to(r) for r in roots):
        raise ValueError("Dawne miejsce notatki jest poza folderami notatek - przywróć ją ręcznie z data/kosz.")
    with _NOTE_LOCK:
        if orig.exists():
            raise FileExistsError(f"W tym miejscu jest już plik {orig.name} - nic nie nadpisałem; plik czeka w data/kosz.")
        orig.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, orig)
        meta.unlink(missing_ok=True)
    invalidate_vault_cache()
    return {"restored": True, "file": orig.name}


class BoundedServer(ThreadingHTTPServer):
    """ThreadingHTTPServer z górnym limitem równoległych połączeń: tysiące
    otwartych, milczących gniazd nie wyczerpią wątków ani deskryptorów."""
    # 1.29.0 (kontrola): 64 milczące połączenia odcinały interfejs; teraz 256 i krótszy
    # limit na nagłówki (8 s), więc zapchanie wymaga dużo więcej i trwa krócej.
    MAX_CONNECTIONS = 256
    daemon_threads = True
    # Domyślne 5 przy kilkunastu naraz otwieranych połączeniach (przeglądarka
    # otwiera ich kilka od razu) kończyło się odrzuconymi próbami.
    request_queue_size = 128

    # 1.32.10 (audyt tura 14): ktoś z LAN (bez tokenu) zajmował wszystkie 256 miejsc milczącymi
    # gniazdami i odcinał też właściciela przy laptopie. Teraz: jeden adres spoza tej maszyny
    # najwyżej PER_IP_MAX połączeń naraz, a LOCAL_RESERVED miejsc tylko dla 127.0.0.1/::1.
    PER_IP_MAX = 16
    LOCAL_RESERVED = 32

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(self.MAX_CONNECTIONS - self.LOCAL_RESERVED)
        self._local_slots = threading.BoundedSemaphore(self.LOCAL_RESERVED)
        self._per_ip: dict = {}
        self._per_ip_lock = threading.Lock()

    @staticmethod
    def _is_local(client_address) -> bool:
        return bool(client_address) and client_address[0] in ("127.0.0.1", "::1")

    def _take(self, client_address):
        """Semafor, z którego wzięto miejsce, albo None (brak miejsca / limit adresu)."""
        ip = client_address[0] if client_address else ""
        local = self._is_local(client_address)
        if not local:
            with self._per_ip_lock:
                if self._per_ip.get(ip, 0) >= self.PER_IP_MAX:
                    return None
                self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        if self._slots.acquire(blocking=False):
            return self._slots
        if local and self._local_slots.acquire(blocking=False):
            return self._local_slots
        self._drop_ip(ip, local)
        return None

    def _drop_ip(self, ip, local):
        if local:
            return
        with self._per_ip_lock:
            n = self._per_ip.get(ip, 0) - 1
            if n > 0:
                self._per_ip[ip] = n
            else:
                self._per_ip.pop(ip, None)

    def process_request(self, request, client_address):
        sem = self._take(client_address)
        if sem is None:
            self.shutdown_request(request)  # za dużo połączeń: zamknij od razu
            return
        self._sem_of = getattr(self, "_sem_of", {})
        self._sem_of[id(request)] = sem
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._sem_of.pop(id(request), None)
            sem.release()  # wątek się nie wystartował: miejsce wraca do puli
            self._drop_ip(client_address[0] if client_address else "", self._is_local(client_address))
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            sem = getattr(self, "_sem_of", {}).pop(id(request), self._slots)
            sem.release()
            self._drop_ip(client_address[0] if client_address else "", self._is_local(client_address))


def main():
    if LAN_MODE and not GREGAI_TOKEN:
        print("UWAGA: GREGAI_LAN=1, ale GREGAI_TOKEN nie jest ustawiony w .env: "
              "wszystkie żądania spoza localhost będą odrzucane (403).")
    print(f"GREGAI działa: sieć LAN = {LAN_MODE}")
    print(f"Otwórz: http://{'localhost' if not LAN_MODE else '<adres-IP-tego-komputera>'}:{PORT}")
    # Najpierw zajmujemy port: gdy jest zajęty, proces kończy się od razu, ZANIM
    # wystartują wątki w tle (serce, rozgrzewanie Ollamy), które inaczej
    # pracowałyby obok działającej już drugiej kopii.
    server = BoundedServer((BIND_HOST, PORT), Handler)
    # Pozostałości po przerwanym zapisie (zabity proces, utrata prądu).
    # 1.29.0 (kontrola): cały data/ z podfolderami (training, rozmowy, straz, wgrane...).
    fsutil.sweep_stale_tmp([data_mod.PROJECT_ROOT],
                           recursive=list(data_mod.get_vault_roots()) + [data_mod.PROJECT_ROOT / "data"])
    # Serce GREGAI (agent/heartbeat.py): wątek w tle, zupełnie niezależny
    # od tego, czy akurat przyszło jakieś żądanie HTTP - pierwsza rzecz,
    # którą GREGAI robi SAM, bez bycia o to poproszonym w danej chwili.
    heartbeat_mod.start(get_vault, invalidate_vault_cache)
    # Zadania stałe (agent/standing.py): drugi, niezależny wątek w tle,
    # ten sam wzorzec co serce wyżej. W odróżnieniu od serca (które robi
    # zawsze te same rzeczy, zaszyte w kodzie) to pilnuje tego, o co
    # Grzegorz POPROSIŁ w rozmowie (standing_task_new) - zdolność, nie
    # zachowanie autonomiczne od zera.
    standing_mod.start(get_vault, invalidate_vault_cache)
    # Straż (agent/straz.py, 1.20.0): patrol komputera bez AI, model tylko przy anomalii.
    straz_mod.start()
    # Rozgrzej Ollamę w tle PRZY STARCIE (patrz router.warm_up_async):
    # wczytanie modeli i przetworzenie PRAWDZIWEGO promptu systemowego teraz,
    # a nie przy pierwszej wiadomości użytkownika.
    # 1.32.12 (audyt tura 16): rozgrzewamy TEN prompt, który naprawdę idzie do modelu lokalnego
    # (zwięzły, ok. 2 tys. znaków), nie pełny 19-tysięczny, którego lokalny model już nie widzi.
    try:
        _warm_prompt = awareness_mod.local_prompt(get_system_prompt(), get_vault())
    except Exception:
        _warm_prompt = get_system_prompt()
    router_mod.warm_up_async(_warm_prompt)
    router_mod.start_warm_watch(get_system_prompt)  # 1.26.0: rozgrzej bez internetu, zwolnij po powrocie
    tryby_mod.SYSTEM_PROMPT = get_system_prompt  # fullon rozgrzewa ten sam prompt (agent/tryby.py)
    try:
        server.serve_forever(poll_interval=5)  # nic nie woła shutdown(); 0,5 s budziło proces dwa razy na sekundę
    except KeyboardInterrupt:
        print("\nZatrzymano.")


if __name__ == "__main__":
    main()
