"""
standing.py

Zadania stałe GREGAI: "śledź X i daj znać, gdy Y". W odróżnieniu od
heartbeat.py (który robi rzeczy GREGAI bez bycia proszonym, ale zawsze te
same, zaszyte w kodzie) to jest zdolność, którą Grzegorz URUCHAMIA własnym
poleceniem w naturalnym języku (capabilities.py: standing_task_new), a
GREGAI sam pilnuje jej w tle, dopóki jej nie zatrzyma.

Architektura wprost z polecenia Grzegorza (2026-10-19):

    "wszystko co potrzeba względem spójności niech będzie na serwerze,
    a to co może oddelegować innej sztucznej inteligencji niech jej
    oddeleguje" + "niech kolejnosc wiedzy bedzie lokalna wiedza>wiedza
    z sieci"

Co zostaje LOKALNIE (na serwerze, zawsze ten sam model):
  - Treść zadania i cała jego historia: JEDNA notatka w
    data/standing_tasks (ten sam wzorzec co JOURNAL_ROOT/MEMORY_ROOT/
    WIKI_CACHE_ROOT w data.py), więc nic nie ginie między cyklami i jest
    przeszukiwalne jak każda inna notatka (search_brain, graf).
  - Research: NAJPIERW lokalny vault (tools.search_brain), dopiero gdy
    tam brak odpowiedzi - internet: precyzyjne notowanie (tools.market_quote,
    gdy zlecenie wspomina ticker/symbol), dopiero potem ogólne wyszukiwanie
    tekstowe (tools.research_web). Zero sieci, gdy odpowiedź już jest w
    notatkach Grzegorza.
  - Decyzja "czy to już alert" (_judge): JEDEN, STAŁY model, żeby ocena
    była spójna cykl po cyklu, a nie zależała od tego, kto akurat
    odpowiedział. Od 1.18.0 według koryta (agent/koryto.py, decyzja
    Grzegorza 2026-10-21: "w trybie sieciowym TYLKO AI sieciowe, lokalny
    dopiero gdy wysiądzie internet"): gdy internet/WARP działa - Claude
    (etap "anthropic"; bez jego klucza darmowa pula z "lepkością" na
    dostawcę, który oceniał poprzednio, zapisanym w notatce zadania); lokalna
    Ollama tylko bez internetu albo przy KORYTO_LOKALNIE=zawsze. Do 1.17.x
    ocena była WYŁĄCZNIE lokalna, więc po `freeram` albo bez Ollamy zadania
    stałe cicho przestawały działać.

Co idzie na ZEWNĄTRZ (etapami sieciowymi koryta, juggler.chat - od 1.17.0
domyślnie najpierw Claude, potem darmowa pula):
  - Samo streszczenie świeżo znalezionego tekstu do kilku zdań.
    Jednorazowe, bezstanowe, bez potrzeby pamiętania wątku - dokładnie
    kryterium delegacji, o które poprosił Grzegorz. Wynik streszczenia
    i tak trafia z powrotem do LOKALNEJ notatki (p. wyżej), więc nawet
    gdyby dostawca "zgubił wątek" w jednym cyklu, to nie uszkadza
    spójności zadania - kolejny cykl i tak czyta stan z notatki.

Granica bezpieczeństwa (ta sama filozofia co heartbeat.py, p. jego
docstring): ten plik czyta i zapisuje WYŁĄCZNIE dane (notatki w
data/standing_tasks, kolejka alertów w data/standing_alerts.json). Nowe
zadanie powstaje WYŁĄCZNIE przez capability (capabilities.py), czyli
zawsze z polecenia Grzegorza w danej chwili - wątek w tle nigdy sam nie
wymyśla, czego ma pilnować, i nigdy nie dodaje sobie nowych zdolności.

Bezpieczeństwo finansowe: to narzędzie TYLKO informuje. Nigdy nie łączy
się z żadnym kontem, portfelem ani giełdą, nigdy nie składa ani nie
wykonuje żadnej transakcji. Każdy alert to sygnał do oceny Grzegorza,
nigdy polecenie "kupuj/sprzedawaj" wypowiedziane z fałszywą pewnością -
GREGAI nie jest doradcą finansowym.

Sieć: wyłącznie pośrednio, przez tools.research_web, czyli wyłącznie
przez WARP (netguard.py). Gdy WARP/LAN jest zablokowany (ręcznie albo
przez gregaipanicmode), research_web sam o tym wie i kończy się
czytelnym błędem, złapanym niżej jak każdy inny - nic dodatkowego nie
trzeba tu pilnować, żeby gwarancja panicmode ("blokuje serwer od
środka") została nienaruszona przez wątek w tle.

Jak się dowiesz o alercie: reaktywnie (p. router.py:_finish). Alert
trafia do notatki NATYCHMIAST, a kolejka w standing_alerts.json czeka
na Twoją najbliższą wiadomość - wtedy odpowiedź zacznie się od niej.
Zero nowych zależności, zero nowego ruchu wychodzącego poza to, co już
istnieje (research_web/juggler.chat przez WARP).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import data as data_mod
import fsutil
import juggler as juggler_mod
import koryto as koryto_mod
import netguard as netguard_mod
import symbols as symbols_mod
import sysop as sysop_mod
import tools as tools_mod
import trace as trace_mod
import vault as vault_mod

# router_mod NIE jest importowany tutaj na poziomie modułu: router.py
# importuje capabilities.py, które importuje ten plik - import router_mod
# tutaj na górze zapętliłby się (router -> capabilities -> standing ->
# router), zanim router.py zdążyłby się w ogóle doładować. Ten sam
# problem i to samo rozwiązanie co w agentloop.py/router.py ("leniwie:
# capabilities importuje nas pośrednio") - import wewnątrz funkcji, które
# faktycznie go używają (_check_task/_judge), nie na górze pliku.

TASKS_DIR = Path(data_mod.STANDING_TASKS_ROOT)
DATA_DIR = Path(__file__).parent.parent / "data"
ALERTS_PATH = DATA_DIR / "standing_alerts.json"

# Dolna granica chroni słaby sprzęt (i7-6600U, bez GPU - ten sam powód co
# TICK_SECONDS w heartbeat.py) i darmowe limity API przed zbyt częstym
# odpytywaniem jednego zadania. Górna to po prostu "raz na dobę", żeby
# ktoś przez pomyłkę nie ustawił zadania na "nigdy".
MIN_INTERVAL_MINUT = 15
MAX_INTERVAL_MINUT = 1440
DEFAULT_INTERVAL_MINUT = 60

# Jak często wątek W OGÓLE sprawdza, czy COŚ jest do zrobienia (tanie -
# samo czytanie znaczników czasu z notatek, bez sieci). Realny odstęp
# między sprawdzeniami JEDNEGO zadania to jego własny interwal_minut
# (>= MIN_INTERVAL_MINUT), ustawiany przy tworzeniu zadania.
TICK_SECONDS = 300

MAX_STAN_CHARS = 600
MAX_ZLECENIE_CHARS = 500
MAX_DZIENNIK_WPISOW = 100
MAX_RAW_FINDINGS_CHARS = 4000


# --- Format notatki ----------------------------------------------------
# Celowo prosty tekst (żadnego YAML/JSON w treści), żeby notatka zadania
# była tak samo czytelna i ręcznie edytowalna jak każda inna notatka w
# vault - dokładnie filozofia reszty projektu (p. vault.py).

# Jedna blokada na zapisy notatek zadań (stop, utworzenie, zapis cyklu) i na
# kolejkę alertów (1.20.0).
_TASK_LOCK = threading.RLock()
_ALERT_LOCK = threading.Lock()
_RETRY_AT: dict[str, float] = {}


def _flat(text: str) -> str:
    """Tekst z zewnątrz (strona WWW, odpowiedź sędziego) wstawiany do notatki:
    jedna linia, bez wiodącego '#', więc nie podszyje się pod nagłówek sekcji."""
    # 1.26.0 (audyt): "[[...]]" z cudzego tekstu nie tworzy powiązań w grafie notatek.
    flat = " ".join(str(text or "").split()).lstrip("#").strip()
    return flat.replace("[[", "[ [").replace("]]", "] ]")


_FRONT_RE = re.compile(r"^\s*([A-Za-z_]+):[ \t]*(.*)$")  # 1.32.11: spacja przed kluczem i "Status:" też
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
_SECTIONS_ORDER = ("Zlecenie", "Stan", "Dziennik sprawdzeń", "Alerty")
_META_ORDER = ("type", "status", "interwal_minut", "utworzono", "ostatnie_sprawdzenie",
               "nastepne_sprawdzenie", "alertow", "oceniajacy", "stan_z_notatek")


def _parse_note(text: str) -> dict:
    lines = text.splitlines()
    meta: dict = {}
    i = 0
    if i < len(lines) and lines[i].startswith("# "):
        meta["tytul"] = lines[i][2:].strip()
        i += 1
    while i < len(lines):
        # 1.27.0 (audyt): pusta linia w nagłówku (zapis z edytora notatek wstawia ją pod
        # "type:") nie kończy nagłówka - inaczej "status: aktywne" znikał i zadanie stawało.
        if not lines[i].strip():
            i += 1
            continue
        m = _FRONT_RE.match(lines[i])
        if not m:
            break
        meta[m.group(1).lower()] = m.group(2).strip()
        i += 1
    body = "\n".join(lines[i:])
    sections: dict = {}
    for m in _SECTION_RE.finditer(body):
        sections.setdefault(m.group(1).strip(), m.group(2).strip())  # PIERWSZE wystąpienie wygrywa (1.20.0)
    meta["_sections"] = sections
    return meta


def _render_note(meta: dict, sections: dict) -> str:
    lines = [f"# {meta.get('tytul', 'Zadanie')}"]
    for key in _META_ORDER:
        if meta.get(key, "") != "":
            lines.append(f"{key}: {meta[key]}")
    lines.append("")
    for name in _SECTIONS_ORDER:
        lines.append(f"## {name}")
        lines.append(sections.get(name, "").strip() or "(brak)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_BROKEN_REPORTED: set = set()
_SUMMARY_CACHE: dict = {}


def _safe_parse(path: Path) -> dict | None:
    try:
        meta = _parse_note(path.read_text(encoding="utf-8-sig", errors="replace"))  # 1.32.11: BOM z edytora
    except OSError:
        return None
    # 1.32.11 (audyt tura 15): zepsuty plik zadania (bez statusu albo bez "## Zlecenie") nie
    # milczy - raz trafia do śladu decyzji, żeby Nadzorca pokazał, że zadanie stoi.
    if (meta.get("status") not in ("aktywne", "zakończone", "wstrzymane")
            or not meta.get("_sections", {}).get("Zlecenie", "").strip()) and path.name not in _BROKEN_REPORTED:
        _BROKEN_REPORTED.add(path.name)
        try:
            trace_mod.record("zadanie_stale_uszkodzone", f"{path.name}: brak statusu albo sekcji Zlecenie - zadanie nie działa", tool=None)
        except Exception:
            pass
    return meta


def _all_task_paths() -> list[Path]:
    if not TASKS_DIR.exists():
        return []
    return sorted(TASKS_DIR.glob("*.md"))


def _now() -> datetime:
    # 1.32.8 (audyt tura 12, zmiana czasu): czas ze strefą (+02:00/+01:00), więc o 02:50 CEST
    # termin "03:20+02:00" po cofnięciu zegara na 02:00 CET to dalej 30 minut, a nie 90.
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s) if s else None
        return dt.astimezone() if dt is not None and dt.tzinfo is None else dt  # stare wpisy bez strefy
    except ValueError:
        return None


# --- Tworzenie / lista / zatrzymanie (wołane z capabilities.py) --------

_INTERVAL_RE = re.compile(r"\bco\s+(\d+(?:[.,]\d+)?|p[óo][łl]|dwie|trzy|cztery|pi[ęe][ćc]|sze[śs][ćc]|dziesi[ęe][ćc])\s*(min\b\.?|minut\w*|godz\b\.?|godzin\w*|h\b)", re.IGNORECASE)
_DAILY_RE = re.compile(r"\b(?:codziennie|raz\s+dziennie|raz\s+na\s+dzie[ńn]|co\s+dzie[ńn])\b", re.IGNORECASE)
_NUM_WORDS = {"pół": 0.5, "pol": 0.5, "dwie": 2, "trzy": 3, "cztery": 4, "pięć": 5, "piec": 5, "sześć": 6, "szesc": 6, "dziesięć": 10, "dziesiec": 10}


def _extract_interval(text: str) -> int:
    """Jeśli Grzegorz podał częstotliwość wprost ("co 30 minut", "co 2
    godziny"), użyj jej (w granicach MIN/MAX). W przeciwieństwie do TREŚCI
    warunku, samo wyciągnięcie liczby i jednostki nie wymaga rozumienia
    języka - robi to deterministyczny wzorzec, nie model (ta sama
    filozofia co reszta capabilities.py: mechaniczna gwarancja tam, gdzie
    się da)."""
    if _DAILY_RE.search(text):
        return max(MIN_INTERVAL_MINUT, min(MAX_INTERVAL_MINUT, 1440))
    m = _INTERVAL_RE.search(text)
    if not m:
        return DEFAULT_INTERVAL_MINUT
    raw = m.group(1).lower().replace(",", ".")
    value = _NUM_WORDS.get(raw) if raw in _NUM_WORDS else float(raw)
    if m.group(2).lower().startswith(("godz", "h")):
        value *= 60
    return max(MIN_INTERVAL_MINUT, min(MAX_INTERVAL_MINUT, int(round(value))))


def _format_interval(minuty: int) -> str:
    if minuty % 60 == 0 and minuty >= 60:
        godziny = minuty // 60
        return f"co {godziny} godz." if godziny > 1 else "co godzinę"
    return f"co {minuty} minut"


MAX_TASKS = 10


def create_task(instruction: str) -> dict:
    """Nowe zadanie stałe. `instruction` to CAŁE polecenie Grzegorza,
    zapisywane dosłownie, bez parafrazy - ta sama zasada co
    capabilities.py:_call_remember: nigdy nie zgaduj, o co dokładnie
    chodziło, zapisz to, co faktycznie powiedział. Interpretacja WARUNKU
    alertu zostaje dla _judge() przy każdym cyklu, nie dzieje się tutaj -
    to właśnie wymaga rozumienia języka za każdym razem, nie jednorazowo
    przy tworzeniu."""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    instruction = instruction.encode("utf-8", "replace").decode("utf-8").replace("\x00", "").strip()
    if not instruction:
        return {"ok": False, "speech": "Czego mam dla Ciebie pilnować i po czym mam poznać, że masz dostać znać?", "card": None}
    instruction = _flat(sysop_mod.mask_secrets(instruction))[:MAX_ZLECENIE_CHARS]
    interval = _extract_interval(instruction)
    # 1.32.11 (audyt tura 15): to samo zlecenie drugi raz = to samo zadanie (dwa identyczne nie
    # dały się zatrzymać z rozmowy i podwajały koszt); twardy limit liczby zadań (każde to
    # wyszukiwanie i dwa wywołania modelu na cykl - 60 zadań zjadało dzienny budżet w 40 min).
    # 1.32.16 (audyt tura 18): sprawdzenie duplikatu + limitu + sam zapis pliku pod JEDNĄ
    # blokadą (_TASK_LOCK) - bez niej dwa wywołania create_task blisko w czasie (dwie karty,
    # dwa urządzenia, odświeżone okno wysyłające to samo polecenie dwa razy) czytały TĘ SAMĄ,
    # jeszcze nieaktualną listę zadań i obie przechodziły obie kontrole: repro potwierdziło 20
    # utworzonych zadań przy MAX_TASKS=10 z 20 równoległych wywołań.
    with _TASK_LOCK:
        _norm = " ".join(instruction.lower().split())
        for _z, _iv in active_tasks():
            if " ".join(_z.lower().split()) == _norm:
                return {"ok": True, "speech": f"To zadanie już pilnuję: „{_z}” ({_format_interval(_iv)}). Nie zakładam drugiego.",
                        "card": {"type": "standing_task_list", "liczba": len(active_tasks())}}
        if len(active_tasks()) >= MAX_TASKS:
            return {"ok": False, "speech": f"Pilnuję już {MAX_TASKS} zadań stałych, to górna granica (każde kosztuje prąd i zapytania). "
                                           "Zatrzymaj któreś („przestań śledzić ...”), a założę nowe.", "card": None}
        now = _now()
        title = " ".join(instruction.split())[:80]
        slug = vault_mod.slugify(instruction, 40, default="zadanie")

        meta = {
            "tytul": f"Zadanie: {title}",
            "type": "Zadanie",
            "status": "aktywne",
            "interwal_minut": str(interval),
            "utworzono": _iso(now),
            "ostatnie_sprawdzenie": "",
            "nastepne_sprawdzenie": _iso(now),  # pierwszy cykl przy najbliższym ticku, nie trzeba czekać interwału
            "alertow": "0",
        }
        sections = {
            "Zlecenie": instruction,
            "Stan": "(jeszcze nie sprawdzane)",
            "Dziennik sprawdzeń": "",
            "Alerty": "",
        }
        content = _render_note(meta, sections)

        path = TASKS_DIR / f"{slug}.md"
        counter = 2
        while not fsutil.create_new_text(path, content, mode=0o644):
            path = TASKS_DIR / f"{slug}-{counter}.md"
            counter += 1

        return {
            "ok": True,
            "speech": f"Zapisałem zadanie stałe: „{instruction}”, sprawdzam {_format_interval(interval)}. "
                      f"Dam znać przy następnej wiadomości, gdy coś się wydarzy.",
            "card": {"type": "standing_task_new", "plik": path.name, "interwal_minut": interval},
            "invalidate_vault": True,
        }


def active_tasks() -> list[tuple[str, int]]:
    """[(zlecenie, interwał w minutach)] dla zadań ze statusem „aktywne" -
    jedno miejsce prawdy dla list_tasks niżej i bloku „Teraz"
    (agent/awareness.py), żeby obie listy nigdy się nie rozjechały."""
    out = []
    for p in _all_task_paths():
        meta = _safe_parse(p)
        if not meta or meta.get("status") != "aktywne":
            continue
        zlecenie = meta.get("_sections", {}).get("Zlecenie", "").strip()
        interval = _interval_of(meta)
        out.append((zlecenie, interval))
    return out


def list_tasks() -> dict:
    active = active_tasks()
    if not active:
        return {"ok": True, "speech": "Nie pilnuję teraz żadnego zadania stałego.", "card": None}
    lines = []
    for zlecenie, interval in active:
        lines.append(f"- „{zlecenie}” ({_format_interval(interval)})")
    return {
        "ok": True,
        "speech": "Zadania stałe, które teraz pilnuję:\n" + "\n".join(lines),
        "card": {"type": "standing_task_list", "liczba": len(active)},
    }


_STOP_STOPWORDS = {
    "zadanie", "zadania", "zadanie", "zlecenie", "prosze", "proszę", "przestan", "przestań",
    "zatrzymaj", "stop", "koniec", "wylacz", "wyłącz", "sledzic", "śledzić", "monitorowac",
    "monitorować", "pilnowac", "pilnować", "juz", "już", "tego", "moje", "mojego",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Ząćęłńóśźż]{4,}", text.lower())
    return {w for w in words if w not in _STOP_STOPWORDS}


def stop_task(arg: str) -> dict:
    active = [(p, m) for p, m in ((p, _safe_parse(p)) for p in _all_task_paths())
              if m and m.get("status") == "aktywne"]
    if not active:
        return {"ok": True, "speech": "Nie pilnuję teraz żadnego zadania stałego, nie ma czego zatrzymywać.", "card": None}

    if len(active) == 1:
        path, meta = active[0]
    else:
        want = _tokens(arg or "")
        scored = sorted(
            ((len(want & _tokens(m.get("_sections", {}).get("Zlecenie", ""))), p, m) for p, m in active),
            key=lambda t: t[0], reverse=True,
        )
        # 1.32.11: remis między zadaniami o IDENTYCZNYM zleceniu (stare duplikaty) = zatrzymaj wszystkie.
        _top = [t for t in scored if t[0] == scored[0][0]]
        if want and scored[0][0] > 0 and len(_top) > 1 and len({" ".join(t[2].get("_sections", {}).get("Zlecenie", "").lower().split()) for t in _top}) == 1:
            with _TASK_LOCK:
                for _s, _p, _m in _top:
                    _fresh = _safe_parse(_p) or _m
                    _fresh["status"] = "zakończone"
                    fsutil.atomic_write_text(_p, _render_note(_fresh, _fresh.get("_sections", {})), mode=0o644)
            return {"ok": True, "speech": f"Zatrzymałem zadanie „{_top[0][2].get('_sections', {}).get('Zlecenie', '')}” ({len(_top)} wpisy, były zdublowane).",
                    "card": {"type": "standing_task_stop", "liczba": len(_top)}, "invalidate_vault": True}
        if not want or scored[0][0] == 0 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
            lines = [f"- „{m.get('_sections', {}).get('Zlecenie', '')}”" for _p, m in active]
            return {
                "ok": True,
                "speech": "Pilnuję kilku zadań naraz i nie jestem pewien, które zatrzymać:\n" + "\n".join(lines) +
                          "\nPowiedz dokładniej, o które chodzi.",
                "card": None,
            }
        _score, path, meta = scored[0]

    with _TASK_LOCK:
        fresh = _safe_parse(path) or meta  # świeży odczyt: cykl w tle mógł coś zmienić
        fresh["status"] = "zakończone"
        fsutil.atomic_write_text(path, _render_note(fresh, fresh.get("_sections", {})), mode=0o644)
    zlecenie = meta.get("_sections", {}).get("Zlecenie", "")
    return {
        "ok": True,
        "speech": f"Zatrzymałem: „{zlecenie}”. Nie będę już tego sprawdzał.",
        "card": {"type": "standing_task_stop", "plik": path.name},
        "invalidate_vault": True,
    }


# --- Kolejka alertów (do odczytania przy najbliższej wiadomości) -------

def _load_alerts() -> list[dict]:
    if not ALERTS_PATH.exists():
        return []
    try:
        raw = ALERTS_PATH.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except ValueError:
        pass
    fsutil.quarantine(ALERTS_PATH)
    return []


MAX_ALERTOW_W_KOLEJCE = 20


def _queue_alert(zlecenie: str, tresc: str) -> None:
    """1.32.2 (audyt tura 7): jedno zadanie = jeden wpis w kolejce (najnowszy, z licznikiem
    powtórzeń), najwyżej MAX_ALERTOW_W_KOLEJCE. Dawniej warunek spełniony przez dwa tygodnie
    bez rozmowy dawał 1344 alerty wklejone przed jedną odpowiedź."""
    with _ALERT_LOCK:
        alerts = _load_alerts()
        prev = next((a for a in alerts if isinstance(a, dict) and a.get("zlecenie") == zlecenie), None)
        n = 1
        if prev is not None:
            alerts.remove(prev)
            n = int(prev.get("razy") or 1) + 1
        rec = {"ts": _iso(_now()), "zlecenie": zlecenie, "tresc": tresc}
        if n > 1:
            rec["razy"] = n
            rec["tresc"] = f"{tresc} (to już {n}. raz od Twojej ostatniej wiadomości)"
        alerts.append(rec)
        if len(alerts) > MAX_ALERTOW_W_KOLEJCE:
            # 1.32.11: alert straży nigdy nie wypada; o wyrzuconych mówimy jednym wpisem.
            keep = [a for a in alerts if isinstance(a, dict) and a.get("zlecenie") == "Straż systemu"]
            rest = [a for a in alerts if a not in keep]
            dropped = len(rest) - (MAX_ALERTOW_W_KOLEJCE - len(keep) - 1)
            rest = rest[dropped:] if dropped > 0 else rest
            alerts = keep + rest
            if dropped > 0:
                alerts.insert(0, {"ts": _iso(_now()), "zlecenie": "kolejka alertów",
                                  "tresc": f"pominięto {dropped} starszych alertów (pełna lista w notatkach zadań)"})
        fsutil.atomic_write_text(ALERTS_PATH, json.dumps(alerts, ensure_ascii=False, indent=2))


def pop_pending_alerts() -> list[dict]:
    """Odczytuje i CZYŚCI kolejkę: każdy alert trafia do Grzegorza raz, przy
    jego najbliższej wiadomości (p. router.py:_finish) - skrzynka pocztowa,
    nie log (log zostaje osobno, w sekcji „Alerty” notatki zadania, p.
    _check_task niżej)."""
    with _ALERT_LOCK:
        alerts = _load_alerts()
        if alerts:
            fsutil.atomic_write_text(ALERTS_PATH, "[]")
        return alerts


# --- Jeden cykl jednego zadania -----------------------------------------

# Rozpoznawanie tickera z treści zlecenia: agent/symbols.py (wydzielone stąd
# w 1.16.2 - zob. jego docstring; capabilities.py korzysta z tego samego
# modułu, zamiast sięgać tutaj po prywatne atrybuty).


def _gather(vault, zlecenie: str) -> tuple[str, str]:
    """(surowe_dane, zrodlo). Najpierw lokalny vault (zero sieci), i
    WYŁĄCZNIE gdy stamtąd nic konkretnego - internet. Kolejność wprost z
    polecenia Grzegorza (2026-10-19): "lokalna wiedza > wiedza z sieci".
    W internecie: gdy zlecenie wprost wspomina ticker/symbol (albo jedną z
    kilku popularnych nazw), NAJPIERW precyzyjna liczba z market_quote,
    dopiero potem ogólne wyszukiwanie tekstowe (research_web) - obie to
    "wiedza z sieci", market_quote jest tylko konkretniejsza, gdy akurat
    pasuje; żadna awaria tego kroku nie blokuje zwykłej ścieżki niżej."""
    try:
        local = tools_mod.search_brain(vault, zlecenie)
    except Exception:
        local = None
    # 1.19.0 (audyt wiedzy): notatki zadań stałych same są w vaulcie, a notatka
    # zadania zawiera zlecenie słowo w słowo - zawsze "trafiała" i zadanie nigdy
    # nie sięgało po notowania ani do sieci, tylko czytało samo siebie.
    local_items = [it for it in (((local or {}).get("card") or {}).get("results") or [])
                   if str(it.get("type", "")).lower() != "zadanie"]
    if local_items:
        text = "\n".join(f"{it.get('title', '')}: {it.get('excerpt', '')}" for it in local_items)
        return text[:MAX_RAW_FINDINGS_CHARS], "vault"

    symbol = symbols_mod.detect(zlecenie)
    if symbol:
        try:
            quote = tools_mod.market_quote(symbol)
        except Exception:
            quote = None
        if quote is not None and quote.get("ok") is not False and quote.get("speech"):
            return quote["speech"][:MAX_RAW_FINDINGS_CHARS], "market"

    try:
        web = tools_mod.research_web(zlecenie)
    except Exception:
        web = None
    if web is None or web.get("ok") is False:
        return "", "brak"
    web_items = (web.get("card") or {}).get("results") or []
    if not web_items:
        return "", "brak"
    text = "\n".join(f"{it.get('title', '')}: {it.get('snippet', '')}" for it in web_items)
    return text[:MAX_RAW_FINDINGS_CHARS], "internet"


_SUMMARY_SYSTEM = (
    "Streszczasz surowy wynik wyszukiwania do 2-3 zwięzłych zdań, wyłącznie "
    "na podstawie podanego tekstu, bez dodawania własnych faktów ani "
    "domysłów. Zero wstępu w stylu \"oto streszczenie\" - od razu treść."
)


def _summarize(raw: str) -> str:
    """Jednorazowe, bezstanowe streszczenie - etapami sieciowymi koryta
    (juggler.chat: domyślnie Claude, potem darmowa pula), zgodnie z zasadą
    Grzegorza: co nie wymaga pamiętania wątku, można oddelegować. Bez
    preferred_provider: ten cykl nie jest częścią żadnej rozmowy. Gdy żaden
    dostawca nie odpowiada, zwraca surowy tekst przycięty - ocena niżej i
    tak dostanie materiał do pracy."""
    if not raw:
        return raw
    try:
        reply, _provider = juggler_mod.chat(_SUMMARY_SYSTEM, [], raw)
        if reply:
            return reply.strip()
    except Exception:
        pass
    return raw[:400]


_JUDGE_SYSTEM = (
    "Jesteś modułem oceny GREGAI dla jednego zadania stałego. Dostajesz "
    "dosłowne zlecenie użytkownika, dotychczasowy stan tematu i nowo "
    "znalezioną informację. Odpowiedz WYŁĄCZNIE dwiema liniami, bez "
    "niczego więcej:\n"
    "ALERT: tak albo ALERT: nie\n"
    "STAN: krótkie (maks. 2-3 zdania), konkretne podsumowanie tego, co "
    "teraz wiadomo o temacie - to zastąpi poprzedni stan.\n"
    "ALERT: tak WYŁĄCZNIE, gdy nowa informacja naprawdę spełnia warunek "
    "podany w zleceniu. Nigdy na wszelki wypadek, nigdy gdy nic istotnego "
    "się nie zmieniło względem dotychczasowego stanu."
)

# 1.32.11: także "**ALERT:** tak", "- ALERT: tak" i "ALERT: tak - STAN: ..." w jednej linii.
_ALERT_LINE_RE = re.compile(r"^\W*ALERT\W*:\W*(tak|nie)\b", re.IGNORECASE | re.MULTILINE)
_STAN_LINE_RE = re.compile(r"(?:^|\s[-|]\s)[^\w\n]*STAN[^\w\n]*:[^\w\n]*(.+)", re.IGNORECASE | re.MULTILINE)  # tylko pierwsza linia (1.20.0)


def _private_material_blocked() -> bool:
    """Audyt 1.32.1: fragmenty notatek Grzegorza nie idą do sieciowych AI bez jego
    zgody (ustawienie Namysłu „material_do_sieci”) - ta sama zasada co w rozmowie
    (router._answer_from_notes). Zadanie stałe dotąd wysyłało je co cykl."""
    try:
        import namysl as namysl_mod  # leniwie: namysl ciągnie dużo modułów
        return not namysl_mod.load_settings().get("material_do_sieci")
    except Exception:
        return True  # nie wiadomo -> jak bez zgody


def _judge_reply(message: str, last_provider: str | None, local_only: bool = False) -> tuple[str, str]:
    """(odpowiedź, kto oceniał) dla _judge - według koryta (p. docstring
    modułu). Rzuca RuntimeError z powodem, gdy nie ma kto ocenić.
    local_only: materiał z notatek bez zgody na sieć - tylko model lokalny."""
    import router as router_mod  # leniwie, p. komentarz przy importach na górze pliku
    if local_only:
        if router_mod.ollama_available():
            return router_mod._ollama_chat(_JUDGE_SYSTEM, [], message, num_predict=200), "lokalnie"
        raise RuntimeError("materiał z notatek bez zgody na wysyłkę do sieci, a lokalny model niedostępny")
    try:
        internet_ok = bool(netguard_mod.internet_allowed()[0])
    except Exception:
        internet_ok = False
    errors = []
    if internet_ok:
        # Pierwszy etap sieciowy KORYTA, który ma klucz (przegląd 1.18.0: dotąd
        # "anthropic" na sztywno, więc KORYTO=darmowe,lokalnie z kluczem Claude
        # w .env i tak płaciło Claude za ocenę).
        etap = next((e for e in koryto_mod.network_order() if juggler_mod.providers_pool(e)), None)
        if etap:
            try:
                # 1.32.4: samodopasowanie (darmowa pula, Claude dopiero gdy ona zawiedzie).
                reply, provider = juggler_mod.chat(_JUDGE_SYSTEM, [], message, timeout=60.0,
                                                   preferred_provider=last_provider)
                if reply:
                    return reply, provider
            except Exception as e:
                errors.append(f"{etap}: {type(e).__name__}: {e}"[:200])
        else:
            errors.append("brak klucza dla etapów sieciowych")
    local_ok = koryto_mod.local_allowed(bool(juggler_mod.providers_pool()), internet_ok)
    if local_ok and router_mod.ollama_available():
        return router_mod._ollama_chat(_JUDGE_SYSTEM, [], message, num_predict=200), "lokalnie"
    if local_ok:
        errors.append("lokalny model niedostępny")
    else:
        errors.append("lokalny pominięty: " + ("nie ma go w KORYTO" if "lokalnie" not in koryto_mod.order()
                                               else "internet działa (KORYTO_LOKALNIE=bez_internetu)"))
    raise RuntimeError("; ".join(errors))


def _judge(zlecenie: str, poprzedni_stan: str, nowa_informacja: str,
           last_provider: str | None = None, local_only: bool = False) -> tuple[bool, str, str]:
    """JEDYNE miejsce, które decyduje "czy to już alert" - jeden stały
    model według koryta (p. docstring modułu i _judge_reply).
    -> (alert, nowy stan, kto oceniał)."""
    message = (
        f"ZLECENIE: {zlecenie}\n\n"
        f"DOTYCHCZASOWY STAN: {poprzedni_stan or '(pierwsze sprawdzenie)'}\n\n"
        f"NOWA INFORMACJA: {nowa_informacja or '(brak nowych informacji w tym cyklu)'}"
    )
    reply, who = _judge_reply(message, last_provider, local_only=local_only)
    alert_match = _ALERT_LINE_RE.search(reply)
    stan_match = _STAN_LINE_RE.search(reply)
    alert = bool(alert_match) and alert_match.group(1).lower() == "tak"
    if stan_match:
        nowy_stan = stan_match.group(1).strip()
    elif alert:
        nowy_stan = nowa_informacja or poprzedni_stan or "(bez zmian)"  # alert bez STAN: treść znaleziska, nie stary stan
    else:
        nowy_stan = poprzedni_stan or "(bez zmian)"
    if not alert_match and not stan_match and reply:
        try:
            trace_mod.record("zadanie_stale_nieczytelna_ocena", reply[:200], tool=None)
        except Exception:
            pass
    nowy_stan = _flat(sysop_mod.mask_secrets(nowy_stan))[:MAX_STAN_CHARS]
    # 1.32.11 (audyt tura 15): stan pochodzi ze streszczenia tekstu z internetu - adresy www i
    # wezwania do działania ("wyślij", "kliknij") to dane, nie polecenia dla Grzegorza.
    nowy_stan = re.sub(r"https?://\S+", "[adres usunięty]", nowy_stan)
    if alert and re.search(r"(?i)\b(wyślij|wyslij|przelej|kliknij|zaloguj|podaj\s+(?:hasło|haslo|kod|pin))\b", nowy_stan):
        nowy_stan = "(treść z internetu, niezweryfikowana, zawiera wezwanie do działania - nie wykonuj) " + nowy_stan
    return alert, nowy_stan, who


def _check_task(vault, path: Path) -> bool:
    """Jeden cykl jednego zadania. Zwraca True, jeśli notatka się
    zmieniła (do decyzji o invalidate_vault() w _tick_all). Błędy łapie
    WOŁAJĄCY (_tick_all), żeby jedno uszkodzone/padające zadanie nigdy nie
    zablokowało pozostałych - ta sama izolacja co heartbeat._tick()."""
    meta = _safe_parse(path)
    if meta is None or meta.get("status") != "aktywne":
        return False
    nastepne = _parse_iso(meta.get("nastepne_sprawdzenie", ""))
    # 1.29.0 (kontrola): termin dalej niż jeden interwał w przyszłości = zegar
    # skoczył (np. RTC o rok do przodu, potem korekta NTP); bez tego zadanie stało.
    # 1.32.2 (audyt tura 7): +61 min zapasu na zmianę czasu (03:00 -> 02:00 cofa zegar
    # lokalny o godzinę; bez zapasu zadanie wyglądało na "skok zegara" i szło od razu).
    if nastepne and _now() < nastepne <= _now() + timedelta(minutes=_interval_of(meta) + 61):
        return False
    if _RETRY_AT.get(path.name, 0) > time.time():
        return False  # niedawno nie było kto ocenić: nie powtarzamy płatnego cyklu co tick
    try:
        mtime0 = path.stat().st_mtime_ns
    except OSError:
        return False

    sections = meta.get("_sections", {})
    zlecenie = sections.get("Zlecenie", "").strip()
    poprzedni_stan = sections.get("Stan", "").strip()
    if not zlecenie:
        return False

    raw, zrodlo = _gather(vault, zlecenie)
    private = zrodlo == "vault" and _private_material_blocked()
    if private:
        # Bez streszczenia w sieci: surowy fragment (z maską sekretów) idzie tylko do lokalnej oceny.
        raw = sysop_mod.mask_secrets(raw)
        streszczenie = _flat(raw[:400])
    else:
        # 1.32.11: krótki surowiec (notowanie: jedna linia) nie wymaga płatnego streszczenia.
        if zrodlo == "brak":
            streszczenie = "(brak nowych informacji w tym cyklu - ani w notatkach, ani w internecie)"
        elif zrodlo == "market" or len(raw) < 400:
            streszczenie = _flat(raw)[:400]
        else:
            # 1.32.11: to samo źródło po nieudanej ocenie nie jest streszczane drugi raz (płatne).
            _key = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]
            _c = _SUMMARY_CACHE.get(path.name)
            streszczenie = _c[1] if _c and _c[0] == _key else _flat(_summarize(raw))
            _SUMMARY_CACHE[path.name] = (_key, streszczenie)

    try:
        if zrodlo == "brak" and poprzedni_stan and not poprzedni_stan.startswith("(jeszcze"):
            # Nic nowego: bez pytania modelu o ocenę (oszczędność budżetu, 1.20.0).
            alert, nowy_stan, who = False, poprzedni_stan, None
        else:
            # Przegląd poprawek 1.32.1: stan zbudowany z prywatnych notatek nie idzie do
            # sieci także w późniejszym cyklu z internetu - wtedy oceniający dostaje zamiast
            # niego krótką informację, a znacznik znika po pierwszym takim cyklu.
            stan_do_oceny = poprzedni_stan
            if not private and meta.get("stan_z_notatek") == "tak":
                stan_do_oceny = "(poprzedni stan oparty na prywatnych notatkach - pominięty)"
            alert, nowy_stan, who = _judge(zlecenie, stan_do_oceny, streszczenie, meta.get("oceniajacy") or None,
                                           local_only=private)
            if private:
                meta["stan_z_notatek"] = "tak"
            else:
                meta.pop("stan_z_notatek", None)
    except Exception as e:
        _RETRY_AT[path.name] = time.time() + max(300, _interval_of(meta) * 60)
        # Nie ma kto ocenić (sieć padła i lokalny niedozwolony/niedostępny):
        # pomiń cykl, spróbuj przy następnym ticku - ale ze śladem w /debug,
        # dotąd taki cykl znikał bez słowa (1.18.0).
        trace_mod.record("zadanie_stale_bez_oceny", zlecenie, tool="standing_task",
                         extra={"plik": path.name, "powod": f"{type(e).__name__}: {e}"[:300]})
        return False
    if who and who != "lokalnie":
        meta["oceniajacy"] = who  # "lepkość": następny cykl oceni ten sam dostawca, jeśli żyje

    now = _now()
    interval = _interval_of(meta)
    meta["ostatnie_sprawdzenie"] = _iso(now)
    meta["nastepne_sprawdzenie"] = _iso(now + timedelta(minutes=interval))
    sections["Stan"] = nowy_stan

    dziennik = [l for l in sections.get("Dziennik sprawdzeń", "").splitlines() if l.strip() and l.strip() != "(brak)"]
    dziennik.append(f"- {_iso(now)} [{zrodlo}]: {streszczenie[:200]} | alert: {'tak' if alert else 'nie'}")
    sections["Dziennik sprawdzeń"] = "\n".join(dziennik[-MAX_DZIENNIK_WPISOW:])

    if alert:
        alerty = [l for l in sections.get("Alerty", "").splitlines() if l.strip() and l.strip() != "(brak)"]
        alerty.append(f"- {_iso(now)}: {nowy_stan}")
        sections["Alerty"] = "\n".join(alerty[-MAX_DZIENNIK_WPISOW:])  # 1.32.2: bez końca rosło
        meta["alertow"] = str(int(meta.get("alertow") or 0) + 1)

    with _TASK_LOCK:
        # Zadanie mogło zostać zatrzymane albo edytowane w trakcie cyklu (sieć trwa
        # sekundy-minuty): wtedy nie nadpisujemy cudzej zmiany (1.20.0).
        try:
            if path.stat().st_mtime_ns != mtime0:
                return False
        except OSError:
            return False
        if alert:
            _queue_alert(zlecenie, nowy_stan)
            trace_mod.record("zadanie_stale_alert", zlecenie, tool="standing_task", extra={"plik": path.name})
        fsutil.atomic_write_text(path, _render_note(meta, sections), mode=0o644)
    return True


# --- Wątek w tle ---------------------------------------------------------

def _interval_of(meta: dict) -> int:
    """1.26.0 (audyt): interwał z notatki (edytowalnej w interfejsie) bez wyjątku.
    "30 minut" dawniej rzucało ValueError PO płatnej ocenie, więc zadanie nie
    przesuwało terminu i oceniało co 5 minut bez końca."""
    m = re.search(r"\d+", str(meta.get("interwal_minut") or ""))
    value = int(m.group(0)) if m else DEFAULT_INTERVAL_MINUT
    return max(MIN_INTERVAL_MINUT, min(MAX_INTERVAL_MINUT, value))


def _tick_all(get_vault, invalidate_vault) -> None:
    changed = False
    vault = None
    for path in _all_task_paths():
        try:
            if vault is None:
                vault = get_vault()
            if _check_task(vault, path):
                changed = True
        except Exception as e:
            # Każdy błąd odkłada to zadanie (jak brak sieci): nigdy pętla płatnych prób co 5 min.
            _RETRY_AT[path.name] = time.time() + 1800
            try:
                trace_mod.record("zadania_stale_blad", str(e), tool=None, extra={"plik": path.name})
            except Exception:
                pass
    if changed:
        invalidate_vault()


def start(get_vault, invalidate_vault, tick_seconds: int = TICK_SECONDS) -> threading.Thread:
    """Startuje wątek-planistę zadań stałych w tle. Ten sam wzorzec co
    heartbeat.start(): daemon=True (nigdy nie blokuje zamknięcia serwera,
    Ctrl+C/systemctl stop działają tak samo jak przed tą zmianą), wołane
    raz z main.py, przed server.serve_forever()."""

    def loop():
        last_error = None
        while True:
            try:
                _tick_all(get_vault, invalidate_vault)
                last_error = None
            except Exception as e:
                try:
                    if str(e) != last_error:
                        trace_mod.record("zadania_stale_blad_petli", str(e), tool=None)
                    last_error = str(e)
                except Exception:
                    pass
            time.sleep(tick_seconds)

    thread = threading.Thread(target=loop, name="gregai-standing-tasks", daemon=True)
    thread.start()
    return thread
