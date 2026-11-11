"""
wezly_grow.py (1.43.0) - automatyczne dowęzłowywanie grafu z rozmów.

Zasady (celowo konserwatywne):
  - zgoda: `data/profil.json` -> `wierzchowanie.auto_dowezlywanie` (domyślnie
    false), a `.env WEZLY_AUTO=off` jest twardym wyłączeniem dla zaawansowanych,
  - bez nowego magazynu grafu: węzeł to plik `.md`, krawędź to `[[wikilink]]`,
  - tworzymy tylko typy z whitelisty (Note, Concept, Wiedza, Nauka); NIGDY
    nowego typu ani nowego węzła-kategorii,
  - kategorie/huby i linki muszą wskazywać istniejące notatki (walidacja przez
    `Vault.by_title`), maks. 3 linki na węzeł,
  - maks. 3 węzły na przebieg, 6 dziennie, cooldown 15 min na rozmowę,
  - prywatność: bez zgody `material_do_sieci` wolno tylko lokalnemu modelowi;
    tytuły notatek nie idą do sieci bez tej zgody. Bez lokalnego i bez zgody
    przebieg jest pomijany,
  - zapis wyłącznie przez `fsutil.create_new_text` pod `fsutil.NOTES_LOCK`,
  - błąd modelu, sieci albo zapisu nic nie psuje: to praca w tle.

Moduł nie importuje `main` (unika cyklu). O unieważnieniu cache vaulta po
zapisie decyduje wywołujący przez `on_created`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

import config_loader as config_mod
import data as data_mod
import fsutil
import vault as vault_mod

PATH = Path(__file__).resolve().parent.parent / "data" / "wezly_grow.json"
SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "namysl.json"
SCHEMA = 1

ALLOWED_TYPES = ("Note", "Concept", "Wiedza", "Nauka")
MAX_TITLE = 60
MAX_BODY = 600
MAX_LINKS = 3
MAX_HUBS = 12
MAX_TITLES = 40
MAX_TRANSCRIPT = 6000
GLOBAL_COOLDOWN_S = 60

_TYPE_ALIASES = {
    "note": "Note",
    "notatka": "Note",
    "notatki": "Note",
    "concept": "Concept",
    "koncept": "Concept",
    "pojecie": "Concept",
    "pojęcie": "Concept",
    "wiedza": "Wiedza",
    "nauka": "Nauka",
}

_OFF = {"0", "off", "nie", "false", "no", "disable", "disabled"}

_LOCK = threading.RLock()
_RUN_LOCK = threading.Lock()


def _today() -> str:
    return date.today().isoformat()


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _pos_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def max_per_run() -> int:
    return _env_int("WEZLY_AUTO_MAX_RUN", 3, 1, 10)


def max_per_day() -> int:
    return _env_int("WEZLY_AUTO_MAX_DZIEN", 6, 1, 50)


def cooldown_minutes() -> int:
    return _env_int("WEZLY_AUTO_COOLDOWN_MIN", 15, 1, 1440)


def _default_state() -> dict:
    return {
        "schema": SCHEMA,
        "dzien": "",
        "utworzone_dzis": 0,
        "last_run_ts": 0,
        "last_run": "",
        "runs": {},
        "ostatnie": [],
        "odrzucone": [],
    }


def _read_state() -> dict:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    state = _default_state()
    state["schema"] = SCHEMA
    state["dzien"] = str(raw.get("dzien") or "")
    state["utworzone_dzis"] = _pos_int(raw.get("utworzone_dzis"))
    state["last_run_ts"] = _pos_int(raw.get("last_run_ts"))
    state["last_run"] = str(raw.get("last_run") or "")
    runs = raw.get("runs") if isinstance(raw.get("runs"), dict) else {}
    state["runs"] = {str(k): _pos_int(v) for k, v in runs.items() if _pos_int(v) > 0}
    if len(state["runs"]) > 50:
        state["runs"] = dict(sorted(state["runs"].items(), key=lambda kv: kv[1])[-50:])
    for key in ("ostatnie", "odrzucone"):
        items = raw.get(key) if isinstance(raw.get(key), list) else []
        state[key] = [x for x in items if isinstance(x, dict)][:20]
    if state["dzien"] != _today():
        state["dzien"] = _today()
        state["utworzone_dzis"] = 0
    return state


def _write_state(state: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write_text(PATH, json.dumps(state, ensure_ascii=False, indent=2))


def _notes_consent() -> bool:
    """Czy wolno pokazać tytuły notatek etapom sieciowym (material_do_sieci)."""
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and raw.get("material_do_sieci") is True


def enabled() -> bool:
    """Czy funkcja jest włączona: zgoda w profilu, a WEZLY_AUTO może ją TYLKO
    wyłączyć (twardy override dla zaawansowanych). Włączenie wymaga profilu,
    żeby .env nie omijał świadomej zgody użytkownika."""
    mode = os.environ.get("WEZLY_AUTO", "").strip().lower()
    if mode in _OFF:
        return False
    try:
        import profil as profil_mod
        return profil_mod.auto_dowezlywanie()
    except Exception:
        return False


def _local_ok() -> bool:
    """Czy lokalny etap jest teraz dozwolony i Ollama odpowiada."""
    try:
        import juggler as juggler_mod
        import koryto as koryto_mod
        import netguard as netguard_mod
        import router as router_mod
        internet_ok = netguard_mod.internet_allowed()[0]
        if not koryto_mod.local_allowed(bool(juggler_mod.providers_pool()), internet_ok):
            return False
        return router_mod.ollama_available()
    except Exception:
        return False


def _clean_line(text: str) -> str:
    text = str(text or "").replace("\u00a0", " ").strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = text.strip("*_`")
    text = re.sub(r"^[-•]\s*", "", text)
    text = re.sub(r"^\d+[.)]\s*", "", text)
    return " ".join(text.split())


def _clean_inline(text: str) -> str:
    text = _clean_line(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = text.strip(" \t\"'„”")
    return " ".join(text.split())


def _clean_link(text: str) -> str:
    text = _clean_inline(text)
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.strip("[]")
    if "|" in text:
        text = text.split("|", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    return _clean_inline(text)


def _links_from(text: str) -> list[str]:
    found = re.findall(r"\[\[([^\]]+)\]\]", str(text or ""))
    parts = found if found else re.split(r"[,;]", str(text or ""))
    out = []
    for part in parts:
        link = _clean_link(part)
        if link:
            out.append(link)
    return out


def _pipe_parts(text: str) -> list[str]:
    # Treść może zawierać "|" - dzielimy tylko na pierwsze dwa separatory.
    return [p.strip() for p in str(text or "").split("|", 2)]


def parse_candidates(text: str) -> list[dict]:
    """Parser linii WEZEL/KAT/LINK. Toleruje bold, spacje i brak treści."""
    out: list[dict] = []
    cur: dict | None = None
    for raw in str(text or "").splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        m = re.match(r"(?i)^WEZEL\s*:\s*(.+)$", line)
        if m:
            if cur is not None:
                out.append(cur)
            parts = _pipe_parts(m.group(1))
            typ = _clean_inline(parts[0]) if parts else ""
            title = _clean_inline(parts[1]) if len(parts) > 1 else ""
            body = _clean_inline(parts[2]) if len(parts) > 2 else ""
            cur = {"typ": typ, "title": title, "body": body, "hub": "", "links": []}
            continue
        m = re.match(r"(?i)^KAT\s*:\s*(.+)$", line)
        if m and cur is not None:
            cur["hub"] = _clean_link(m.group(1))
            continue
        m = re.match(r"(?i)^LINK\s*:\s*(.+)$", line)
        if m and cur is not None:
            for link in _links_from(m.group(1)):
                cur["links"].append(link)
            continue
    if cur is not None:
        out.append(cur)
    return out[:10]


def _canonical_type(raw: str) -> str:
    key = _clean_inline(raw).lower().strip(" .,:;()[]")
    return _TYPE_ALIASES.get(key, "Note")


def _title_ok(title: str) -> bool:
    if not title or len(title) < 3 or len(title) > MAX_TITLE:
        return False
    if re.search(r"[\[\]|#\x00-\x1f]", title):
        return False
    return True


def _existing_title(vault, raw: str) -> str:
    """Dokładny tytuł istniejącej notatki albo pusty string."""
    cleaned = _clean_link(raw)
    if not cleaned:
        return ""
    slug = vault.by_title.get(vault_mod.normalize_title(cleaned))
    if not slug or slug not in vault.notes:
        return ""
    return vault.notes[slug].title


def _build_context(vault) -> tuple[str, str, str, set[str]]:
    """(typy, kategorie, tytuły, normy hubów)."""
    counts = vault.counts_by_type()
    types = ", ".join(f"{name} ({counts.get(name, 0)})" for name in ALLOWED_TYPES)
    try:
        degrees = vault.degrees()
    except Exception:
        degrees = {}
    notes = list(vault.notes.values())

    def degree(note) -> int:
        return int(degrees.get(note.slug) or 0)

    hubs = [n for n in notes if n.ntype in ("Wiedza", "Nauka") or n.title.startswith("00-")]
    hubs.sort(key=lambda n: (-degree(n), n.title.lower()))
    hubs = hubs[:MAX_HUBS]
    hub_slugs = {n.slug for n in hubs}
    hub_norms = {vault_mod.normalize_title(n.title) for n in hubs}

    links = [n for n in notes if n.slug not in hub_slugs]
    links.sort(key=lambda n: (-degree(n), n.title.lower()))
    links = links[:MAX_TITLES]

    hub_lines = "\n".join(f"- [[{n.title}]]" for n in hubs) or "- (brak - pomiń KAT)"
    link_lines = "\n".join(f"- [[{n.title}]]" for n in links) or "- (brak - pomiń LINK)"
    return types, hub_lines, link_lines, hub_norms


def _prompt() -> str:
    template = config_mod.text("prompts.wezly", "").strip()
    if template:
        return template
    return (
        "Dodajesz nowe węzły do grafu wiedzy GREGAI. Odpowiadaj WYŁĄCZNIE liniami:\n"
        "WEZEL: typ | Tytuł | Treść jednym zdaniem\nKAT: [[tytuł huba]]\nLINK: [[tytuł]]\n"
        "Typ tylko z listy TYPY. KAT i LINK tylko z podanych list. Max 3 WEZEL. "
        "Jeśli nie ma nowego, wartościowego tematu, napisz BRAK.\n\n"
        "TYPY: {TYPY}\nKATEGORIE:\n{KATEGORIE}\nWĘZŁY:\n{WEZLY}"
    )


def _ask_model(system: str, user: str, local_only: bool, ask=None) -> str:
    if ask is not None:
        return str(ask(system, user, local_only) or "")
    try:
        import router as router_mod
        if _local_ok():
            try:
                text = router_mod._ollama_chat(system, [], user, timeout=60, num_predict=380)
                if isinstance(text, str) and text.strip():
                    return text
            except Exception:
                pass
        if local_only:
            return ""
        # Zgoda material_do_sieci jest już sprawdzona przez wołającego.
        return router_mod.summarize_text(system, user)
    except Exception:
        return ""


def _write_candidate(root: Path, vault, cand: dict, hub_norms: set[str]) -> tuple[dict | None, str]:
    title = _clean_inline(cand.get("title") or "")[:MAX_TITLE]
    if not _title_ok(title):
        return None, "zły tytuł"
    norm = vault_mod.normalize_title(title)
    if norm in vault.by_title:
        return None, "duplikat"
    body = _clean_inline(cand.get("body") or "")[:MAX_BODY]
    # Krawędzie mają powstać wyłącznie z zwalidowanych LINK, nie z dowolnego
    # [[...]] wpisanego przez model w treści.
    body = re.sub(r"\[\[[^\]]*\]\]", "", body).strip()
    ntype = _canonical_type(cand.get("typ") or "")
    hub = ""
    raw_hub = cand.get("hub") or ""
    if raw_hub:
        candidate = _existing_title(vault, raw_hub)
        if candidate and vault_mod.normalize_title(candidate) in hub_norms:
            hub = candidate
    links: list[str] = []
    for raw in cand.get("links") or []:
        existing = _existing_title(vault, raw)
        if not existing or existing == title or existing == hub:
            continue
        if existing not in links:
            links.append(existing)
        if len(links) >= MAX_LINKS:
            break
    lines = [f"# {title}", f"type: {ntype}", ""]
    if body:
        lines.extend([body, ""])
    if hub:
        lines.append(f"Do: [[{hub}]]")
    if links:
        lines.append("Z: " + ", ".join(f"[[{link}]]" for link in links))
    content = "\n".join(lines).rstrip() + "\n"

    stem = vault_mod.slugify(title)
    target = root / f"{stem}.md"
    with fsutil.NOTES_LOCK:
        created = False
        for counter in range(1, 20):
            name = f"{stem}.md" if counter == 1 else f"{stem}-{counter}.md"
            target = root / name
            if fsutil.create_new_text(target, content):
                created = True
                break
        if not created:
            return None, "kolizja pliku"
    slug = target.relative_to(root).as_posix()
    # Kolejne kandydaty w tym samym przebiegu nie mogą powtórzyć tytułu.
    vault.by_title[norm] = slug
    return {"slug": slug, "title": title, "type": ntype, "hub": hub,
            "links": links}, ""


def run_once(chat: str, message: str, speech: str, roots=None, ask=None,
             force: bool = False, now: float | None = None,
             vault_getter=None) -> list[dict]:
    """Jeden przebieg. Zwraca listę utworzonych węzłów (może być pusta)."""
    if not force and not enabled():
        return []
    chat = str(chat or "ogolna")
    now = time.time() if now is None else float(now)
    with _LOCK:
        state = _read_state()
        if state["utworzone_dzis"] >= max_per_day():
            return []
        if not force:
            if now - state["last_run_ts"] < GLOBAL_COOLDOWN_S:
                return []
            if now - int(state["runs"].get(chat, 0)) < cooldown_minutes() * 60:
                return []
    if not _RUN_LOCK.acquire(blocking=False):
        return []
    try:
        # Ponowne sprawdzenie pod blokadą przebiegu: dwie wiadomości naraz.
        with _LOCK:
            state = _read_state()
            remaining = max(0, max_per_day() - state["utworzone_dzis"])
            limit = min(max_per_run(), remaining)
            if limit <= 0:
                return []
            if not force:
                if now - state["last_run_ts"] < GLOBAL_COOLDOWN_S:
                    return []
                if now - int(state["runs"].get(chat, 0)) < cooldown_minutes() * 60:
                    return []

        roots = [Path(p) for p in (roots or data_mod.get_vault_roots())]
        if not roots:
            return []
        v = vault_getter() if vault_getter is not None else vault_mod.build_vault([str(p) for p in roots])
        consent = _notes_consent()
        if ask is None and not consent and not _local_ok():
            return []
        types, hub_lines, link_lines, hub_norms = _build_context(v)
        system = _prompt().replace("{TYPY}", types).replace("{KATEGORIE}", hub_lines).replace("{WEZLY}", link_lines)
        transcript = f"ROZMOWA:\nU: {str(message or '')[:2500]}\nA: {str(speech or '')[:3500]}"
        try:
            import trace as trace_mod
            transcript = trace_mod.mask(transcript)[:MAX_TRANSCRIPT]
        except Exception:
            # Bez maski nie wysyłamy treści (nawet do lokalnego modelu).
            return []
        raw = _ask_model(system, transcript, local_only=not consent, ask=ask)
        created: list[dict] = []
        rejected: list[dict] = []
        for cand in parse_candidates(raw):
            if len(created) >= limit:
                break
            item, reason = _write_candidate(roots[0], v, cand, hub_norms)
            if item:
                item.update({"chat": chat, "at": int(now)})
                created.append(item)
            else:
                rejected.append({"tytul": _clean_inline(cand.get("title") or "")[:MAX_TITLE],
                                 "powod": reason, "at": int(now)})
        with _LOCK:
            state = _read_state()
            state["dzien"] = _today()
            state["utworzone_dzis"] = int(state.get("utworzone_dzis") or 0) + len(created)
            state["last_run_ts"] = int(now)
            state["last_run"] = _iso_now()
            state["runs"][chat] = int(now)
            if len(state["runs"]) > 50:
                state["runs"] = dict(sorted(state["runs"].items(), key=lambda kv: kv[1])[-50:])
            if created:
                state["ostatnie"] = (created + state["ostatnie"])[:20]
            if rejected:
                state["odrzucone"] = (rejected + state["odrzucone"])[:20]
            _write_state(state)
        if created:
            try:
                import trace as trace_mod
                trace_mod.record("wezly_auto", f"dodano {len(created)} węzł: " +
                                 ", ".join(i["title"] for i in created)[:200], tool=None)
            except Exception:
                pass
        return created
    finally:
        _RUN_LOCK.release()


def _cooldown_ok(chat: str) -> bool:
    now = time.time()
    with _LOCK:
        state = _read_state()
        if state["utworzone_dzis"] >= max_per_day():
            return False
        if now - state["last_run_ts"] < GLOBAL_COOLDOWN_S:
            return False
        if now - int(state["runs"].get(chat, 0)) < cooldown_minutes() * 60:
            return False
    return True


def maybe_start(chat: str, message: str, speech: str, on_created=None,
                vault_getter=None) -> bool:
    """Uruchamia przebieg w tle, jeśli zgoda i limity pozwalają. True = start."""
    if not enabled():
        return False
    if not isinstance(speech, str) or len(speech.strip()) < 200:
        return False
    if not _cooldown_ok(chat):
        return False

    def _work() -> None:
        try:
            created = run_once(chat, message, speech, vault_getter=vault_getter)
            if created and on_created is not None:
                try:
                    on_created(created)
                except Exception:
                    pass
        except Exception as e:
            try:
                import trace as trace_mod
                trace_mod.record("wezly_auto_blad", f"{type(e).__name__}: {e}"[:200], tool=None)
            except Exception:
                pass

    threading.Thread(target=_work, name="wezly-auto", daemon=True).start()
    return True


def recent(chat: str, since: int = 0) -> list[dict]:
    """Utworzone węzły tej rozmowy od `since` (epoch, sekundy) - dla UI."""
    chat = str(chat or "ogolna")
    try:
        since_i = max(0, int(since or 0))
    except (TypeError, ValueError):
        since_i = 0
    with _LOCK:
        state = _read_state()
    return [item for item in state.get("ostatnie", [])
            if item.get("chat") == chat and _pos_int(item.get("at")) >= since_i]
