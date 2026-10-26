"""
heartbeat.py

Serce GREGAI: wątek w tle, który NIE czeka na żadną wiadomość. Dotąd
GREGAI był czysto reaktywny (request -> router.route() -> odpowiedź);
to tutaj jest pierwsza rzecz, którą robi SAM, bez bycia o to poproszonym
w danej chwili - różnica między "odpowiada, gdy się do niego zagadnie"
a "ma własną, ciągłą egzystencję w tle", jedną z rzeczy w stronę pełnej
autonomii, o którą poprosił użytkownik.

Co robi, co jakiś czas (patrz TICK_SECONDS), bez pytania:

1. Pisze własny Dziennik (notatka type: Journal w data/journal, patrz
   data.JOURNAL_ROOT), raz na dzień, z PRAWDZIWYMI, POLICZONYMI
   wnioskami z self_status/_draw_conclusions (agent/tools.py) - nigdy
   zmyślonym podsumowaniem. To jest literalna pamięć GREGAI o samym
   sobie W CZASIE: różnica między statyczną wiedzą a kimś, kto pamięta,
   co było wczoraj.
2. Ponawia tematy z Wikipedii, które się wcześniej nie udały (patrz
   tools.retry_open_questions): czasem to tylko chwilowy problem z
   siecią, nie trwały brak artykułu, a nikt nie musi pytać drugi raz.
3. Sprawdza, czy lokalny model (Ollama) odpowiada, i loguje do
   trace.py WYŁĄCZNIE przy zmianie stanu (dostępna <-> niedostępna),
   żeby decision_log.json nie zapychał się powtórkami tej samej
   informacji.

Granica bezpieczeństwa (patrz prompt.md, "Granice autonomii"): ten
plik czyta i zapisuje WYŁĄCZNIE dane (notatki markdown, pliki JSON w
data/), nigdy kod .py. Nowa ZDOLNOŚĆ (nowe narzędzie, nowy mechanizm)
to zawsze zmiana w kodzie, czyli zawsze z udziałem człowieka
(Grzegorza) albo Claude'a, nigdy samodzielna decyzja wątku w tle.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import data as data_mod
import fsutil
import router as router_mod
import tools as tools_mod
import trace as trace_mod
import vault as vault_mod

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_PATH = DATA_DIR / "heartbeat_state.json"

# Pół godziny: rzadko na tyle, żeby nie zasypywać słabego CPU (i7-6600U,
# bez GPU) ani Wikipedii niepotrzebnymi żądaniami, często na tyle, żeby
# dziennik i ponowienia tematów działy się tego samego dnia, bez
# czekania na restart serwera.
TICK_SECONDS = 1800


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            raw = STATE_PATH.read_text(encoding="utf-8-sig")
        except OSError:
            return {}  # chwilowy błąd odczytu to nie uszkodzony plik: nie odsuwamy go
        try:
            state = json.loads(raw)
            if isinstance(state, dict):
                return state
        except ValueError:
            pass
        fsutil.quarantine(STATE_PATH)  # uszkodzony plik odsuwamy, jak każdy inny plik stanu
    return {}


def _report_error(state: dict, kind: str, error) -> None:
    """Ten sam błąd po raz kolejny (np. niezapisywalny katalog dziennika: co 30 minut to samo)
    nie trafia znów do śladu decyzji: 48 wpisów na dobę wypychałoby z niego prawdziwe decyzje,
    a ślad służy też za materiał do treningu."""
    message = f"{kind}: {error}"
    errors = state.get("errors")
    if not isinstance(errors, dict):
        errors = state["errors"] = {}
    if errors.get(kind) == message:
        return
    errors[kind] = message
    trace_mod.record("serce_blad", message, tool=None)


def _clear_error(state: dict, kind: str) -> None:
    errors = state.get("errors")
    if isinstance(errors, dict):
        errors.pop(kind, None)


def _save_state(state: dict) -> None:
    fsutil.atomic_write_text(STATE_PATH, json.dumps(state, ensure_ascii=False, indent=2))


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _write_journal_entry(vault) -> None:
    """Notatka Dziennika = to samo, co self_status (agent/tools.py)
    faktycznie POLICZYŁ o stanie GREGAI w tym dniu, nigdy nic więcej -
    ta sama zasada co _draw_conclusions: brak materiału = mniej w
    dzienniku, nigdy zmyślona treść, żeby wpis "wyglądał pełniej"."""
    status = tools_mod.self_status(vault)
    title = f"Dziennik {_today()}"
    content = f"# {title}\ntype: Journal\n\n{status['speech']}\n"
    path = Path(data_mod.JOURNAL_ROOT) / f"{vault_mod.slugify(title)}.md"
    # Wyłączne utworzenie: wpis z dzisiaj, który już jest (utracony stan serca, cofnięty
    # zegar), albo dopiski użytkownika w nim nie mogą zostać nadpisane.
    fsutil.create_new_text(path, content, mode=0o644)


def _tick(get_vault, invalidate_vault) -> None:
    """Jedno 'uderzenie serca'. Każda z trzech rzeczy niżej jest
    opakowana własnym try/except: błąd w jednej (np. Wikipedia akurat
    nie odpowiada) nigdy nie blokuje pozostałych, i nigdy nie zabija
    wątku w tle na resztę działania serwera (patrz start() niżej)."""
    state = _load_state()
    needs_invalidate = False

    today = _today()
    if state.get("last_journal_date") != today:
        try:
            _write_journal_entry(get_vault())
            state["last_journal_date"] = today
            needs_invalidate = True
            _clear_error(state, "dziennik")
        except Exception as e:
            _report_error(state, "dziennik", e)

    try:
        result = tools_mod.retry_open_questions(get_vault())
        if result.get("invalidate_vault"):
            needs_invalidate = True
        _clear_error(state, "ponow_wiki")
    except Exception as e:
        _report_error(state, "ponow_wiki", e)

    try:
        available = router_mod.ollama_available()
        was_available = state.get("ollama_available")
        if was_available is not None and was_available != available:
            trace_mod.record(
                "serce_kontrola_ollama",
                "model lokalny odzyskał dostępność" if available else "model lokalny nie odpowiada",
                tool=None,
                model_active=available,
            )
        state["ollama_available"] = available
        _clear_error(state, "kontrola_ollama")
    except Exception as e:
        _report_error(state, "kontrola_ollama", e)

    _save_state(state)
    if needs_invalidate:
        invalidate_vault()


def start(get_vault, invalidate_vault, tick_seconds: int = TICK_SECONDS) -> threading.Thread:
    """Startuje wątek-serce w tle. daemon=True: nigdy nie blokuje
    zamknięcia serwera (Ctrl+C/systemctl stop działają tak samo jak
    przed tą zmianą). Wołane raz, z main.py:main(), przed
    server.serve_forever()."""

    def loop():
        last_error = None
        while True:
            try:
                _tick(get_vault, invalidate_vault)
                last_error = None
            except Exception as e:
                try:
                    if str(e) != last_error:  # ten sam błąd co pół godziny zapełniłby ślad
                        trace_mod.record("serce_blad", str(e), tool=None)
                    last_error = str(e)
                except Exception:
                    pass
            time.sleep(tick_seconds)

    thread = threading.Thread(target=loop, name="gregai-heartbeat", daemon=True)
    thread.start()
    return thread
