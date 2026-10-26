"""
trace.py

Ślad decyzji routera: dla każdej wiadomości, którą dostał route() w
router.py, jeden zapis mówiący KTÓRA ścieżka odpowiedziała (dopytanie,
szybki wzorzec ręczny albo wyuczony, router, uczeń, chmura, Ollama jako
narzędzie albo rozmowa, zadanie pętli agenta, fallback bez modelu; pełna
lista etapów: STAGE_LABELS w ui/debug.js) i ile to zajęło czasu. Bez
tego jedyny sposób, żeby zobaczyć, co GREGAI właśnie zrobił i czemu, to
czytanie logów serwera linia po linii.

Z tego korzysta strona /debug (ui/debug.html + /api/debug/log w
main.py): tabela ostatnich decyzji w czasie zbliżonym do rzeczywistego,
plus osobno to, co GREGAI się do tej pory wyuczył (agent/learning.py).
Razem to "nadzorca": widać nie tylko ODPOWIEDŹ, ale PROCES, który do
niej doprowadził.

Ten sam styl i katalog co data/network_inventory.json w siec.py czy
data/learned_routes.json w learning.py: zwykły json.dumps/loads, jedna
osoba na jednym komputerze; jedyna blokada (threading.Lock) chroni pamięć
podręczną przed wyścigiem wątków serwera.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import fsutil

DATA_DIR = Path(__file__).parent.parent / "data"
TRACE_PATH = DATA_DIR / "decision_log.json"

MAX_TRACE_ENTRIES = 300
MESSAGE_PREVIEW_LIMIT = 300

_CACHE: list[dict] | None = None
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalize_entry(e: dict) -> None:
    """Pole o złym typie (plik edytowany ręcznie) naprawiamy na miejscu: strona /debug,
    budowa zbioru treningowego i statystyki czytają te pola bez sprawdzania."""
    for field in ("ts", "stage", "message"):
        if not isinstance(e.get(field, ""), str):
            e[field] = ""
    if not isinstance(e.get("tool"), (str, type(None))):
        e["tool"] = None
    if not isinstance(e.get("extra"), (dict, type(None))):
        e["extra"] = None
    took = e.get("took_ms")
    if took is not None and (isinstance(took, bool) or not isinstance(took, (int, float))):
        e["took_ms"] = None


def _load() -> list[dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data = []
    if TRACE_PATH.exists():
        try:
            data = json.loads(TRACE_PATH.read_text(encoding="utf-8-sig"))
            if not (isinstance(data, list) and all(isinstance(e, dict) for e in data)):
                raise ValueError("zły kształt")
            for e in data:
                _normalize_entry(e)
        except OSError:
            raise  # 1.29.0 (kontrola): chwilowy błąd odczytu to nie uszkodzony plik - nic nie odsuwamy
        except Exception:
            # Uszkodzony ślad nie jest po cichu nadpisywany: zostaje obok jako .corrupt-<data>.
            data = []
            fsutil.quarantine(TRACE_PATH)
    _CACHE = data
    return _CACHE


def _save() -> None:
    # 1.32.10 (audyt tura 14, SSD): bez wcięć - plik przepisywany przy każdej wiadomości był ~3x większy.
    fsutil.atomic_write_text(TRACE_PATH, json.dumps(_CACHE, ensure_ascii=False, separators=(",", ":")))


# Sekrety WPISANE w rozmowie (nie tylko te z .env): klucze API o znanych
# prefiksach, bloki kluczy prywatnych, "hasło do wifi to X", tokeny Bearer, PIN,
# numery kart (z sumą kontrolną Luhna), IBAN, PESEL, długie losowe ciągi.
# Ślad, nauczone frazy, pary dla ucznia i treść wysyłana do chmury to miejsca,
# do których wklejony sekret nie może trafić. Wzorce są ostrożne: lepiej
# zamaskować zwykłe słowo niż zapisać hasło.
def _luhn_card(match: "re.Match") -> str:
    """Ciąg 13-19 cyfr (ze spacjami lub myślnikami) maskowany tylko wtedy, gdy
    przechodzi sumę kontrolną Luhna: zwykłe długie numery zostają."""
    digits = re.sub(r"\D", "", match.group(0))
    if not 13 <= len(digits) <= 19:
        return match.group(0)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return "***" if total % 10 == 0 else match.group(0)


def _long_token(match: "re.Match") -> str:
    """Długi ciąg znaków bez spacji z cyfrą I literą to prawdopodobnie token.
    Warunek sprawdzany w kodzie, nie w lookaheadach: dwa lookaheady na całym
    ciągu dawały czas kwadratowy na długim tekście typu "1-1-1-..."."""
    token = match.group(0)
    if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
        return "***"
    return token


_TYPED_SECRETS = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "[KLUCZ PRYWATNY UKRYTY]"),
    (re.compile(r"\b(?:sk-ant-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9\-]{10,}|AIza[0-9A-Za-z_\-]{30,}"
                r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})"), "***"),
    (re.compile(r"\b(?:sk_(?:live|test)_[A-Za-z0-9]{16,}|rk_live_[A-Za-z0-9]{16,}|glpat-[A-Za-z0-9_\-]{16,}|npm_[A-Za-z0-9]{30,}"
                r"|hf_[A-Za-z0-9]{30,}|pypi-[A-Za-z0-9_\-]{20,}|ya29\.[A-Za-z0-9_\-]{20,})"), "***"),
    (re.compile(r"(?i)(\b(?:bearer|basic)\s+)[A-Za-z0-9._~+/=\-]{12,}"), r"\1***"),
    # Hasło w adresie (https://user:HASŁO@host), w "curl -u user:HASŁO", w nagłówku
    # Cookie i w "pass=" / "pwd:".
    (re.compile(r"(\b[A-Za-z][A-Za-z0-9+.\-]*://[^\s/:@]+:)[^\s/@]+(?=@)"), r"\1***"),
    (re.compile(r"(\s(?:-u|--user)[\s=]+[^\s:]+:)\S+"), r"\1***"),
    (re.compile(r"(?i)(\b(?:set-)?cookie\s*:\s*)[^\r\n]+"), r"\1***"),
    (re.compile(r"(?i)(\b(?:pass|pwd|passw)\s*[=:]\s*[\"']?)([^\s\"']{3,})"), r"\1***"),
    # Audyt 1.32.1: przecinek opcjonalny RAZEM ze swoimi spacjami - "\s*,?\s+" dzieliło
    # ciąg spacji na wiele sposobów w każdym z 5 powtórzeń (131 znaków = 66 s, cały serwer stał).
    # "hasło wifi: X", "hasło do wifi to X", "hasło brzmi X", "hasło to: X": do pięciu słów
    # między słowem kluczowym a spójnikiem/dwukropkiem ("hasło do mojego nowego konta
    # bankowego to X"), spójnik może mieć po sobie dwukropek.
    (re.compile(r"(?i)(\b(?:hasł\w*|haslo|hasla|password|passwd|secret|sekret\w*|pin|api[ _-]?key|pesel)\b"
                r"(?:(?:\s*,)?\s+(?!(?:to|jest|is|brzmi|wynosi)\b)[^\s:=]{1,24}){0,5}?"
                r"(?:\s*,)?\s*(?:(?:to|jest|is|brzmi|wynosi)\s*:?|=|:)\s*[\"']?)([^\s\"']{4,})"), r"\1***"),
    # Te same kształty ze słowami "token"/"klucz": w śladzie tak, w zapytaniu do internetu nie
    # ("token ERC-20 co to jest", "klucz do sukcesu to praca" to zwykłe tematy).
    (re.compile(r"(?i)(\b(?:token\w*|klucz\w*)\b"
                r"(?:(?:\s*,)?\s+(?!(?:to|jest|is|brzmi|wynosi)\b)[^\s:=]{1,24}){0,5}?"
                r"(?:\s*,)?\s*(?:(?:to|jest|is|brzmi|wynosi)\s*:?|=|:)\s*[\"']?)([^\s\"']{4,})"), r"\1***", "szeroki"),
    # "hasło do wifi Kr0wa123", "token do serwera abc12", "wpisz hasło Tajne123" (bez
    # spójnika): maskujemy tylko wartość z cyfrą.
    (re.compile(r"(?i)(\b(?:hasł\w*|haslo|hasla|password|passwd)\s+(?:(?:do|dla|na|of|for)\s+\S+\s+)?)"
                r"(?=[^\s\"']*\d)([^\s\"']{6,})"), r"\1***"),
    (re.compile(r"(?i)(\b(?:token\w*|klucz\w*)\s+(?:(?:do|dla|na|of|for)\s+\S+\s+)?)"
                r"(?=[^\s\"']*\d)([^\s\"']{6,})"), r"\1***", "szeroki"),
    # "PIN 1234", "PIN do karty 1234", "PIN karty to 1234".
    (re.compile(r"(?i)(\b(?:pin|cvv|cvc)\b(?:\s+(?:do\s+|dla\s+)?[^\s\d:=]{2,20})?\s*(?:to|jest|is|=|:)?\s*)(\d{3,8})\b"), r"\1***"),
    (re.compile(r"(?i)(\bpesel\b\W{0,4}(?:(?:to|jest|wynosi)\s*:?\s*)?)(\d{11})\b"), r"\1***"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){4,7}(?:\s?[A-Z0-9]{1,4})?\b"), "***"),
    (re.compile(r"\b\d{2}(?:\s?\d{4}){6}\b"), "***"),
    (re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), _luhn_card),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), _long_token, "szeroki"),
)


def redact_typed(text: str, outbound: bool = False) -> str:
    """outbound=True: tylko wzorce jednoznacznie tajne (hasła, PIN, PESEL, karty, klucze API);
    "szerokie" (słowa token/klucz, długie ciągi znaków) zostają, bo adres portfela albo skrót
    sha256 to zwykły temat zapytania do internetu, a ślad i tak je maskuje."""
    for entry in _TYPED_SECRETS:
        if outbound and len(entry) > 2:
            continue
        text = entry[0].sub(entry[1], text)
    return text


def mask(text: str, outbound: bool = False) -> str:
    """Sekrety (z .env oraz wpisane w rozmowie) nie trafiają do śladu: ślad służy
    też jako materiał do treningu. Samotny surogat zamieniany jest na "?": inaczej
    wpis nie dałby się zapisać jako UTF-8. Błąd maskowania = nic nie zapisujemy
    (nigdy tekst bez maski)."""
    try:
        text = text.encode("utf-8", "replace").decode("utf-8")
        try:
            import sysop
            text = sysop.mask_secrets(text)
        except ImportError:
            pass
        return redact_typed(text, outbound=outbound)
    except Exception:
        return "[ukryte: błąd maskowania]"


def _mask_obj(obj):
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, (list, tuple)):
        return [_mask_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _mask_obj(v) for k, v in obj.items()}
    return obj


def preview(text: str) -> str:
    """Skrót wiadomości w takiej postaci, w jakiej zapisuje go ślad (przycięty i
    bez sekretów z .env). Porównania z zapisanym śladem robimy tą samą funkcją."""
    # Maskujemy dłuższy początek, a dopiero potem przycinamy: sekret przecięty granicą
    # podglądu zostałby inaczej w połowie, już bez rozpoznawalnego kształtu.
    return mask(text[:MESSAGE_PREVIEW_LIMIT * 10])[:MESSAGE_PREVIEW_LIMIT]


def record(stage: str, message: str, tool: str | None = None, took_ms: float | None = None,
           model_active: bool | None = None, extra: dict | None = None) -> None:
    """Dopisuje jeden wpis do śladu decyzji. Decyzje routera są zapisywane z
    jednego miejsca (_finish w route()), więc każda ścieżka przez router
    ma ten sam komplet pól; wpisy serca (agent/heartbeat.py) idą tą samą
    funkcją, z własnymi etapami (serce_*)."""
    entry = {
        "ts": _now_iso(),
        "stage": stage,
        "message": preview(message),
        "tool": tool,
        "took_ms": took_ms,
        "model_active": model_active,
        "extra": _mask_obj(extra),
    }
    # Ślad jest dodatkiem do rozmowy: błąd zapisu (pełny dysk) nie może jej psuć.
    try:
        with _LOCK:
            entries = _load()
            entries.append(entry)
            try:
                if len(entries) > MAX_TRACE_ENTRIES:
                    del entries[: len(entries) - MAX_TRACE_ENTRIES]
                _save()
            except (OSError, ValueError, TypeError):
                # Wpis, którego nie udało się zapisać (pełny dysk, znak spoza UTF-8),
                # nie może zostać w pamięci: zatruwałby każdy kolejny zapis.
                if entries and entries[-1] is entry:
                    entries.pop()
                raise
    except (OSError, ValueError, TypeError) as e:
        print(f"UWAGA: nie zapisano śladu decyzji: {e}")


# 1.19.0: też streszczenie rozmowy (wątek w tle po odpowiedzi) i usunięcie rozmowy.
_BACKGROUND_STAGE_PREFIXES = ("serce_", "zadanie_stale_", "zadania_stale_", "pamiec_rozmowy", "rozmowa_usunieta")


def _last_decision_index(entries: list) -> int | None:
    """Indeks ostatniej DECYZJI routingu: wpisy serca ("serce_*": kontrola Ollamy,
    błędy w tle) też są w śladzie i mogły pojawić się po odpowiedzi, którą
    użytkownik właśnie poprawia. To samo wpisy zadań stałych ("zadanie_stale_*",
    "zadania_stale_*"), pisane w tle co cykl (przegląd 1.18.0)."""
    for i in range(len(entries) - 1, -1, -1):
        if isinstance(entries[i], dict) and not str(entries[i].get("stage", "")).startswith(_BACKGROUND_STAGE_PREFIXES):
            return i
    return None


def last_decision() -> dict | None:
    """Ostatni wpis routingu (z pominięciem wpisów serca) albo None."""
    with _LOCK:
        entries = _load()
        i = _last_decision_index(entries)
        return entries[i] if i is not None else None


def mark_last_corrected() -> None:
    """Użytkownik właśnie poprawił poprzednią odpowiedź ("nie o to mi chodziło"):
    ostatni wpis routingu dostaje extra.skorygowane=true, żeby training/build_dataset.py
    nie uczył na decyzji, którą sam użytkownik uznał za błędną. Błąd zapisu
    nie psuje rozmowy."""
    try:
        with _LOCK:
            entries = _load()
            i = _last_decision_index(entries)
            if i is None:
                return
            extra = entries[i].get("extra")
            if not isinstance(extra, dict):
                extra = {}
            extra["skorygowane"] = True
            entries[i]["extra"] = extra
            _save()
    except (OSError, ValueError) as e:
        print(f"UWAGA: nie oznaczono korekty w śladzie: {e}")


def recent(limit: int = 200) -> list[dict]:
    """Ostatnie wpisy, najnowszy pierwszy (odwrotna kolejność niż w
    pliku, bo w pliku dopisujemy na koniec, a na stronie /debug chcemy
    widzieć najpierw to, co się stało NAJPÓŹNIEJ)."""
    with _LOCK:
        try:
            entries = _load()
        except OSError:
            return []
        return list(reversed(entries[-limit:]))
