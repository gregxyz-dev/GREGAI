"""
ewaluacja.py (1.32.0) - `gregai eval`

Testy regresji GREGAI na wzór "eval harness" z everything-claude-code
(skills/eval-harness): przypadki zdefiniowane z góry, oceniacze w kodzie
("deterministyczne > probabilistyczne"), metryki pass@k i pass^k, historia
przebiegów i porównanie z poprzednim (co się zepsuło, co naprawiło).

Przypadki: training/ewaluacja/regresja.jsonl - każdy z prawdziwej wpadki albo
z poprawki (pole "zrodlo"). Dwa tryby:

  szybki (domyślny)  bez sieci i bez modeli: routing szybkiej ścieżki, komendy,
                     bramka odpowiedzi, Namysł dla podziękowań, słońce, straż,
                     nauka. Deterministyczny - wynik 100% albo regresja. Ten sam
                     zestaw sprawdza kontrola 46 w check.sh.
  --zywo [--k N]     przypadki "rozmowa" przez PRAWDZIWY router.route(): każdy N
                     razy (domyślnie 3), oceniany kodem (po polsku, bez cudzej
                     tożsamości, bez fałszywego "nie mam internetu", pełne
                     zakończenie, ...). pass@k = choć jedna próba dobra (czy umie),
                     pass^k = wszystkie dobre (czy jest niezawodny). KOSZTUJE tokeny
                     (liczone w tym samym budżecie Koryta co rozmowa).

Historia: data/ewaluacja/historia.jsonl. Każdy przebieg porównywany z poprzednim
w tym samym trybie: REGRESJA (było dobrze, jest źle) i NAPRAWIONE.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "training" / "ewaluacja" / "regresja.jsonl"
HISTORY_PATH = ROOT / "data" / "ewaluacja" / "historia.jsonl"
OFFLINE_TYPES = ("routing", "komenda", "bramka", "spoleczne", "slonce", "straz", "nauka", "pretensja", "devtools",
                 "lokalny_timeout", "izolacja", "audyt_1329", "audyt_1330", "audyt_1331", "audyt_1332", "audyt_1333", "audyt_1334",
                 "audyt_1351", "lokalny_cache", "lokalny_budzet", "lokalny_styl", "lokalny_parametry", "lokalny_walidacja",
                 "lokalny_kolejka", "lokalny_retry", "lokalny_sesja", "lokalny_warmup",
                 "spoleczne_1380", "czas_1380", "plik_1380", "plik_upload_1381", "namysl_413_1382", "awaryjny_1382",
                 "duplikat_1383", "prompt_ctx_1383", "notatki_1384", "normalizacja_1385", "dedup_1386", "namysl_once_1387")

# 1.32.28 (audyt #1): pliki, których eval --zywo NIE MOŻE zmienić.
_PRODUCTION_FILES = (
    ROOT / "data" / "decision_log.json",
    ROOT / "data" / "learned_routes.json",
    ROOT / "data" / "learned_topic_words.json",
    ROOT / "data" / "training" / "distill_pairs.jsonl",
    ROOT / "data" / "koryto_dziennik.json",
)
_ISOLATION: dict = {"dir": None}


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(json.loads(line))
    return out


# --- Izolacja eval (1.32.28, audyt #1) ---------------------------------------------

def _production_hashes() -> dict[str, str | None]:
    """Odcisk produkcyjnych plików, których eval nie może zmienić. None = brak pliku."""
    out = {}
    for path in _PRODUCTION_FILES:
        try:
            out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            out[str(path)] = None
    return out


def prepare_isolation() -> str:
    """Własny katalog danych dla eval --zywo. Zwraca ścieżkę katalogu.

    Ustawia KORYTO_DZIENNIK_PLIK PRZED importem routera/jugglera (juggler
    liczy JOURNAL_PATH raz, przy imporcie), a modułom już zaimportowanym
    podmienia ścieżki i czyści cache, żeby nie pisały do produkcji."""
    if _ISOLATION.get("dir"):
        return _ISOLATION["dir"]
    directory = tempfile.mkdtemp(prefix="gregai-eval-")
    base = Path(directory)
    previous_journal = os.environ.get("KORYTO_DZIENNIK_PLIK")
    os.environ["KORYTO_DZIENNIK_PLIK"] = str(base / "koryto_dziennik.json")
    os.environ["GREGAI_EVAL_IZOLACJA"] = "1"
    restore: list[tuple[object, str, object]] = []
    try:
        import trace as trace_mod
        restore.append((trace_mod, "TRACE_PATH", trace_mod.TRACE_PATH))
        trace_mod.TRACE_PATH = base / "decision_log.json"
        trace_mod._CACHE = None
        import learning as learning_mod
        for attr, filename in (("LEARNED_PATH", "learned_routes.json"),
                               ("TOPIC_WORDS_PATH", "learned_topic_words.json")):
            restore.append((learning_mod, attr, getattr(learning_mod, attr)))
            setattr(learning_mod, attr, base / filename)
            setattr(learning_mod, {"LEARNED_PATH": "_CACHE", "TOPIC_WORDS_PATH": "_TOPIC_CACHE"}[attr], None)
    except Exception:
        pass
    # Moduły już zaimportowane (np. przez wcześniejszy test offline).
    juggler = sys.modules.get("juggler")
    if juggler is not None:
        restore.append((juggler, "JOURNAL_PATH", juggler.JOURNAL_PATH))
        juggler.JOURNAL_PATH = base / "koryto_dziennik.json"
        juggler._JOURNAL.clear()
        juggler._JOURNAL_LOADED = False
    router = sys.modules.get("router")
    if router is not None:
        restore.append((router, "DISTILL_PAIRS_PATH", router.DISTILL_PAIRS_PATH))
        router.DISTILL_PAIRS_PATH = base / "distill_pairs.jsonl"
    _ISOLATION.update(dir=directory, restore=restore, previous_journal=previous_journal)
    return directory


def cleanup_isolation() -> None:
    """Usuwa katalog tymczasowy i przywraca modułom produkcyjne ścieżki."""
    if not _ISOLATION.get("dir"):
        return
    directory = _ISOLATION.get("dir")
    previous_journal = _ISOLATION.get("previous_journal")
    for module, attr, old in _ISOLATION.get("restore", []):
        try:
            setattr(module, attr, old)
        except Exception:
            pass
    if previous_journal is None:
        os.environ.pop("KORYTO_DZIENNIK_PLIK", None)
    else:
        os.environ["KORYTO_DZIENNIK_PLIK"] = previous_journal
    # Moduły zaimportowane DOPIERO po prepare_isolation nie mają wpisu restore.
    juggler = sys.modules.get("juggler")
    if juggler is not None:
        juggler.JOURNAL_PATH = Path(previous_journal or (ROOT / "data" / "koryto_dziennik.json"))
        juggler._JOURNAL.clear()
        juggler._JOURNAL_LOADED = False
    router = sys.modules.get("router")
    if router is not None:
        router.DISTILL_PAIRS_PATH = ROOT / "data" / "training" / "distill_pairs.jsonl"
    if sys.modules.get("trace") is not None:
        sys.modules["trace"]._CACHE = None
    if sys.modules.get("learning") is not None:
        sys.modules["learning"]._CACHE = None
        sys.modules["learning"]._TOPIC_CACHE = None
    _ISOLATION.clear()
    _ISOLATION["dir"] = None
    if directory:
        shutil.rmtree(directory, ignore_errors=True)


# --- Oceniacze szybkie (bez sieci) --------------------------------------------------

def _check_devtools() -> tuple[bool, str]:
    """Sprawdza rejestr i wywołania narzędzi deweloperskich na atrapie runnera."""
    import capabilities as cap_mod
    import devtools as dt

    expected = {"run_eval", "run_check", "env_status", "service_status", "docs_check"}
    missing = sorted(name for name in expected if name not in cap_mod.CAPABILITIES)
    if missing:
        return False, "brak w CAPABILITIES: " + ", ".join(missing)

    calls = []
    original = dt._run

    def fake(argv, timeout=120):
        calls.append((list(argv), timeout))
        text = " ".join(argv)
        if "ewaluacja.py" in text:
            return {"rc": 0, "out": "Zaliczone: 1/1\nWerdykt: GOTOWE", "err": ""}
        if argv[-1] == "--version":
            return {"rc": 0, "out": "Python 3.14.4", "err": ""}
        if "-c" in argv:
            return {"rc": 0, "out": '{"httpx": "0.28.1", "huawei-lte-api": "1.10.0"}', "err": ""}
        if argv[:2] == ["systemctl", "is-active"]:
            return {"rc": 0, "out": "active", "err": ""}
        if argv[:2] == ["ollama", "list"]:
            return {"rc": 0, "out": "NAME ID SIZE\nqwen2.5:3b abc 2GB", "err": ""}
        return {"rc": 0, "out": "MOCK", "err": ""}

    try:
        dt._run = fake
        offline = dt.run_eval(False)
        live = dt.run_eval(True)
        check = dt.run_check()
        env = dt.env_status()
        service = dt.service_status()
        docs = dt.docs_check()
    finally:
        dt._run = original

    offline_argv = next(argv for argv, _ in calls if "ewaluacja.py" in " ".join(argv))
    live_calls = [argv for argv, _ in calls if "ewaluacja.py" in " ".join(argv)]
    ok = (
        offline.get("ok") is True and "--bez-zapisu" in offline_argv and "--zywo" not in offline_argv
        and live.get("ok") is True and any("--zywo" in argv for argv in live_calls)
        and check.get("ok") is True and "check.sh" in check.get("speech", "")
        and "httpx" in env.get("speech", "") and "Ollama" in env.get("speech", "")
        and "gregai" in service.get("speech", "")
        and isinstance(docs.get("speech"), str) and bool(docs.get("speech"))
    )
    return ok, f"rejestr 5/5, wywołania: {len(calls)}"


def _check_isolation() -> tuple[bool, str]:
    """1.32.28: eval nie uczy, nie zapisuje śladu i nie gubi "/" w chat_id;
    maska outbound nie zjada adresu portfela, ale nadal chowa hasło."""
    import learning as learning_mod
    import sources as sources_mod
    import trace as trace_mod

    problems = []
    if sources_mod.chat_id("projekty/klient.md") == sources_mod.chat_id("projekty-klient.md"):
        problems.append("chat_id: / zlepia się z -")
    if len({sources_mod.chat_id("x" * 100 + "a"), sources_mod.chat_id("x" * 100 + "b")}) != 2:
        problems.append("chat_id: dwa długie id zlepiają się po przycięciu")
    if sources_mod.chat_id(sources_mod.chat_id("projekty/klient.md")) != sources_mod.chat_id("projekty/klient.md"):
        problems.append("chat_id: nie jest idempotentny (podwójne kodowanie %)")

    addr = "0x52908400098527886E0F7030069857D2E4169EE7"
    masked = trace_mod.mask("adres " + addr, outbound=True)
    if addr not in masked:
        problems.append("outbound: adres portfela zamaskowany")
    if "tajne123" in trace_mod.mask("hasło: tajne123", outbound=True):
        problems.append("outbound: hasło nie zamaskowane")

    trace_writes, learning_writes = [], []
    old_trace_save, old_learning_save = trace_mod._save, learning_mod._save
    trace_mod._save = lambda: trace_writes.append(1)
    learning_mod._save = lambda: learning_writes.append(1)
    try:
        with trace_mod.suppress():
            trace_mod.record("test-izolacja", "nie zapisuj")
            if not trace_mod.suppressed():
                problems.append("trace: suppress nie działa")
        with learning_mod.suppress_learning():
            learning_mod.learn_from_resolution("sprawdź pogodę w Warszawie", "weather", "Warszawa", by="test")
            if not learning_mod.suppressed():
                problems.append("learning: suppress nie działa")
    finally:
        trace_mod._save, learning_mod._save = old_trace_save, old_learning_save
    if trace_writes:
        problems.append("trace: zapis w trybie suppress")
    if learning_writes:
        problems.append("learning: zapis w trybie suppress")

    import router as router_mod
    seen = {}
    original = router_mod._route

    def fake(*_a, **_k):
        seen["trace"] = trace_mod.suppressed()
        seen["learning"] = learning_mod.suppressed()
        return {"speech": "test", "card": None}

    try:
        router_mod._route = fake
        router_mod.route(None, "", [], "test", nie_ucz=True, nie_zapisuj_sladu=True)
    finally:
        router_mod._route = original
    if not seen.get("trace") or not seen.get("learning"):
        problems.append("router.route: flagi nie docierają do _route")

    directory = prepare_isolation()
    try:
        if not os.environ.get("KORYTO_DZIENNIK_PLIK", "").startswith(directory):
            problems.append("prepare_isolation: dziennik nie jest w katalogu tymczasowym")
    finally:
        cleanup_isolation()

    return (not problems), "; ".join(problems) if problems else "izolacja, chat_id i maska outbound OK"


def _check_audyt_1329() -> tuple[bool, str]:
    """Testy poprawek audytu 1.32.29: kosz, PDF, blok offline, BOM, limit
    tytułu, .env.example, minimum LOKALNY_TIMEOUT i kolejność wpisów .env."""
    import contextlib
    import errno
    import io
    import shutil
    import tempfile
    from pathlib import Path
    import awareness as awareness_mod
    import devtools as devtools_mod
    import fsutil
    import router as router_mod
    import vault as vault_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-audyt-1329-"))
    try:
        # #3: nazwy z nawiasami, plusem, przecinkiem i ampersandem są poprawne.
        for good in ("Raport (2026).md", "C++ basics.md", "a, b & c.md", "zwykla.md"):
            if not fsutil.trash_name_ok(good):
                problems.append(f"kosz: odrzucona poprawna nazwa {good!r}")
        for bad in ("../x.md", "a/b.md", "a\\b.md", "x\x00y.md", "..", "x" * 256):
            if fsutil.trash_name_ok(bad):
                problems.append(f"kosz: przepuszczona niebezpieczna nazwa {bad!r}")

        # #4: metadane, przeniesienie, EXDEV i rollback po błędzie metadanych.
        root = tmp / "notatki"
        trash = tmp / "kosz"
        root.mkdir()
        trash.mkdir()
        note = root / "Raport (2026).md"
        note.write_text("# Raport (2026)\n", encoding="utf-8")
        name = fsutil.move_to_trash(note, trash, note)
        if note.exists() or not (trash / name).is_file() or not (trash / (name + ".json")).is_file():
            problems.append("kosz: plik albo metadane nie trafiły do kosza")

        note2 = root / "drugi.md"
        note2.write_text("# Drugi\n", encoding="utf-8")
        original_replace = fsutil.os.replace
        calls = {"n": 0}

        def exdev_once(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(errno.EXDEV, "EXDEV")
            return original_replace(src, dst)

        fsutil.os.replace = exdev_once
        try:
            name2 = fsutil.move_to_trash(note2, trash, note2)
        finally:
            fsutil.os.replace = original_replace
        if note2.exists() or not (trash / name2).is_file() or not (trash / (name2 + ".json")).is_file():
            problems.append("kosz: fallback EXDEV nie przeniósł pliku")

        note3 = root / "trzeci.md"
        note3.write_text("# Trzeci\n", encoding="utf-8")
        calls["n"] = 0

        def fail_metadata(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError(errno.ENOSPC, "ENOSPC")
            return original_replace(src, dst)

        failed = False
        fsutil.os.replace = fail_metadata
        try:
            fsutil.move_to_trash(note3, trash, note3)
        except OSError:
            failed = True
        finally:
            fsutil.os.replace = original_replace
        if not failed or not note3.exists():
            problems.append("kosz: brak rollbacku po błędzie metadanych")

        # #5: UTF-8, UTF-16 z BOM, cp1252 i brak NUL-i.
        for raw in ("Zażółć".encode("utf-8"), "Zażółć".encode("utf-16"), b"caf\xe9"):
            text = vault_mod._pdf_unescape(raw)
            if "\x00" in text or (raw == b"caf\xe9" and text != "café") or (raw != b"caf\xe9" and text != "Zażółć"):
                problems.append(f"PDF: złe dekodowanie {raw!r} -> {text!r}")

        # #6: lokalny model dostaje zdanie o braku internetu.
        old_offline = awareness_mod._offline_line
        awareness_mod._offline_line = lambda: "\nMARKER_OFFLINE_1329"
        try:
            class _V:
                notes = {}
            block = awareness_mod.local_block(_V())
        finally:
            awareness_mod._offline_line = old_offline
        if "MARKER_OFFLINE_1329" not in block:
            problems.append("blok Teraz: brak _offline_line")

        # #8: BOM nie ukrywa H1 i typu.
        raw_note = "\ufeff# Tytuł\ntype: Project\n\ntreść\n"
        if vault_mod.find_title(vault_mod.strip_bom(raw_note)) != "Tytuł":
            problems.append("notatka: BOM nadal ukrywa tytuł")

        # #9: tytuł z H1 jest przycięty, treść zostaje.
        vroot = tmp / "vault"
        vroot.mkdir()
        long_note = vroot / "dluga.md"
        long_note.write_text("# " + "x" * 1000 + "\ntype: Note\n", encoding="utf-8")
        built = vault_mod.build_vault([str(vroot)])
        title = next(iter(built.notes.values())).title
        if len(title) > vault_mod.MAX_TITLE_CHARS:
            problems.append(f"vault: tytuł ma {len(title)} znaków")

        # #10: .env.example dokumentuje trzy wewnętrzne zmienne.
        example = (ROOT / ".env.example").read_text(encoding="utf-8", errors="replace")
        for key in ("KORYTO_DZIENNIK_PLIK", "SYSOP_LOG_OPCJONALNY", "GREGAI_STRAZ_ANCHOR"):
            if not re.search(rf"(?m)^\s*#?\s*{re.escape(key)}\s*=", example):
                problems.append(f".env.example: brak {key}")

        # #11: LOKALNY_TIMEOUT poniżej 60 jest podnoszony do 60.
        old_timeout = os.environ.get("LOKALNY_TIMEOUT")
        os.environ["LOKALNY_TIMEOUT"] = "30"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                low_timeout = router_mod._namysl_local_timeout()
        finally:
            if old_timeout is None:
                os.environ.pop("LOKALNY_TIMEOUT", None)
            else:
                os.environ["LOKALNY_TIMEOUT"] = old_timeout
        if low_timeout != 60:
            problems.append(f"LOKALNY_TIMEOUT=30 dało {low_timeout}, nie 60")

        # #12: ostatni wpis w .env wygrywa.
        old_root = devtools_mod.ROOT
        devtools_mod.ROOT = tmp / "devtools"
        devtools_mod.ROOT.mkdir()
        (devtools_mod.ROOT / ".env").write_text("GREGAI_LAN=1\nGREGAI_LAN=0\n", encoding="utf-8")
        try:
            value = devtools_mod._env_value("GREGAI_LAN")
        finally:
            devtools_mod.ROOT = old_root
        if value != "0":
            problems.append(f"_env_value: pierwszy wpis zamiast ostatniego ({value!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return (not problems), "; ".join(problems) if problems else "audyt 1.32.29: wszystkie 9 testów OK"


def _check_audyt_1330() -> tuple[bool, str]:
    """Testy poprawek audytu 1.32.29 (#1-#5): efektywne koryto per waga,
    fallback przy pustej polityce, awaryjny lokalny wg wagi, NetGuardBlocked
    w trakcie wiadomości i praca w tle przez rozdzielnicę (nie surowe KORYTO)."""
    import juggler as juggler_mod
    import koryto as koryto_mod
    import namysl as namysl_mod
    import netguard as netguard_mod
    import router as router_mod

    problems: list[str] = []
    env_keys = ("KORYTO", "ROZDZIELNICA", "KORYTO_ZADANIA")
    old_env = {k: os.environ.get(k) for k in env_keys}

    def set_env(**kw):
        for key, value in kw.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    orig_chat = juggler_mod.chat
    orig_pool = juggler_mod.providers_pool
    orig_internet = netguard_mod.internet_allowed
    try:
        # #1: /api/system_info (router.koryto_status) niesie efektywną kolejność
        # per waga i politykę; koryto.status() umie ją przyjąć.
        set_env(KORYTO="anthropic,darmowe,lokalnie", ROZDZIELNICA="B", KORYTO_ZADANIA="1")
        st = router_mod.koryto_status()
        if st.get("efektywna", {}).get("2") != ["darmowe", "lokalnie"]:
            problems.append(f"#1 status waga 2: {st.get('efektywna', {}).get('2')}")
        if st.get("efektywna", {}).get("3") != ["darmowe", "anthropic", "lokalnie"]:
            problems.append(f"#1 status waga 3: {st.get('efektywna', {}).get('3')}")
        if st.get("rozdzielnica") != "B" or st.get("poziom_domyslny") != 2:
            problems.append("#1 status: brak polityki albo poziomu domyślnego")
        if koryto_mod.status(effective={"2": ["x"]}, rozdzielnica="B").get("efektywna") != {"2": ["x"]}:
            problems.append("#1 koryto.status nie przyjmuje efektywnej mapy")

        # #2: polityka wycina wszystkie etapy sieciowe -> wracamy do surowego KORYTO.
        set_env(KORYTO="anthropic,lokalnie")
        if router_mod._stage_order_for(2) != ["anthropic", "lokalnie"]:
            problems.append(f"#2 fallback waga 2: {router_mod._stage_order_for(2)}")
        if router_mod._stage_order_for(3) != ["anthropic", "lokalnie"]:
            problems.append(f"#2 waga 3: {router_mod._stage_order_for(3)}")
        set_env(KORYTO="darmowe,lokalnie,anthropic")
        if router_mod._stage_order_for(2) != ["darmowe", "lokalnie"]:
            problems.append(f"#2 bez zmian waga 2: {router_mod._stage_order_for(2)}")

        # #3: awaryjny lokalny patrzy na etapy dozwolone dla wagi, nie na wszystkich.
        set_env(KORYTO="anthropic,darmowe,lokalnie")

        def fake_pool(etap=None):
            return {"anthropic": ["anthropic"], "darmowe": ["groq"],
                    None: ["anthropic", "groq"], "lokalnie": []}.get(etap, [])

        juggler_mod.providers_pool = fake_pool
        if router_mod._allowed_providers(2) != ["groq"]:
            problems.append(f"#3 pula wagi 2: {router_mod._allowed_providers(2)}")
        if router_mod._allowed_providers(3) != ["groq", "anthropic"]:
            problems.append(f"#3 pula wagi 3: {router_mod._allowed_providers(3)}")
        if not router_mod.emergency_local_allowed(False, True, ["darmowe", "lokalnie"], ["groq"], False, {"groq"}):
            problems.append("#3 wyczerpana pula dozwolona nie uruchamia lokalnego")
        if router_mod.emergency_local_allowed(False, True, ["darmowe", "lokalnie"], ["groq", "anthropic"],
                                               False, {"groq"}):
            problems.append("#3 zdrowy Claude blokuje awaryjny lokalny")

        # #4: NetGuardBlocked traktowany jak wyczerpanie i dopisuje lokalny etap
        # w Namśle, mimo że na starcie internet działał.
        if not router_mod.emergency_local_allowed(False, True, ["darmowe", "lokalnie"], ["groq"], True, set()):
            problems.append("#4 warp_blocked nie uruchamia lokalnego")
        if router_mod.emergency_local_allowed(True, True, ["darmowe", "lokalnie"], ["groq"], True, set()):
            problems.append("#4 lokalny już próbowany, a helper chce go drugi raz")

        cloud_calls: list[int] = []

        def blocked(*_a, **_k):
            cloud_calls.append(1)
            raise netguard_mod.NetGuardBlocked("test: WARP padł w trakcie")

        ctx = namysl_mod.Context(
            vault=None, message="test", history_local=[], history_cloud=[], files=[],
            sys_local="", sys_cloud="", local_up=True,
            local_chat=lambda _s, _h, _m: "lokalnie ok",
            cloud_chat=blocked, cloud_pool=lambda: ["groq"],
            research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [], settings={"tryb": "zawsze", "material_do_sieci": False},
        )
        models = namysl_mod._Models(ctx, namysl_mod.Narrator(None))
        if models.local_allowed:
            problems.append("#4 test: lokalny nie powinien być dozwolony na starcie")
        got_text, got_who = models.ask("test", "sys", "sys", "user", private=False, history=False)
        if (got_text, got_who) != ("lokalnie ok", "lokalnie"):
            problems.append(f"#4 NetGuardBlocked -> lokalnie: {got_text!r}, {got_who!r}")
        got_text2, got_who2 = models.ask("test", "sys", "sys", "user", private=False, history=False)
        if (got_text2, got_who2) != ("lokalnie ok", "lokalnie") or len(cloud_calls) != 1:
            problems.append(f"#4 druga faza znów pyta chmurę: {got_text2!r}, {got_who2!r}, chmura={len(cloud_calls)}")

        # #5: planner i streszczenie idą rozdzielnicą (darmowa pula pierwsza),
        # nie surowym koryto.order(); samodopasowanie to ta sama polityka.
        calls: list[list] = []

        def fake_chat(_system, _msgs, _msg, timeout=60.0, preferred_provider=None, exclude_provider=None,
                      etapy=None, max_tokens=None, model=None):
            calls.append(list(etapy or []))
            return "TOOL: BRAK", "groq"

        juggler_mod.chat = fake_chat
        router_mod._planner_ask("SYS", "user")
        if not calls or calls[0] != ["darmowe"]:
            problems.append(f"#5 planner nie idzie rozdzielnicą: {calls[:1]}")
        calls.clear()
        netguard_mod.internet_allowed = lambda *_a, **_k: (True, "")
        router_mod.summarize_text("SYS", "user")
        if not calls or calls[0] != ["darmowe"]:
            problems.append(f"#5 streszczenie nie idzie rozdzielnicą: {calls[:1]}")
        if juggler_mod.samodopasowanie() != ["darmowe", "anthropic"]:
            problems.append(f"#5 samodopasowanie: {juggler_mod.samodopasowanie()}")
    finally:
        juggler_mod.chat = orig_chat
        juggler_mod.providers_pool = orig_pool
        netguard_mod.internet_allowed = orig_internet
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    return (not problems), "; ".join(problems) if problems else "audyt 1.32.30: wszystkie 5 poprawek OK"


def _check_audyt_1331() -> tuple[bool, str]:
    """Test poprawki 1.32.31: fazy Namysłu mają gwarancję modelu - po porażce
    chmury (dowolnej, nie tylko NetGuardBlocked) faza spada na lokalny, z
    wariantem promptu napisanym dla modelu lokalnego (bez materiału 16k)."""
    import namysl as namysl_mod
    import netguard as netguard_mod

    problems: list[str] = []

    def blocked_or_fail(*_a, **_k):
        raise RuntimeError("HTTP 413: Request too large (groq TPM 8000,Requested 8411)")

    seen_local: list[tuple[str, list, str]] = []

    def local_capture(system, history, message):
        seen_local.append((system, list(history), message))
        return "szkic lokalny"

    ctx = namysl_mod.Context(
        vault=None, message="test", history_local=[], history_cloud=[], files=[],
        sys_local="SYS", sys_cloud="SYS", local_up=True,
        local_chat=local_capture,
        cloud_chat=blocked_or_fail, cloud_pool=lambda: ["groq"],
        research=None, search_notes=lambda _v, _q: [], research_web=None,
        wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
        internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
        violates_style=lambda _text: [], settings={"tryb": "zawsze", "material_do_sieci": True},
    )
    models = namysl_mod._Models(ctx, namysl_mod.Narrator(None))
    if models.local_allowed:
        problems.append("test: lokalny nie powinien być dozwolony na starcie"
                        " (KORYTO_LOKALNIE=bez_internetu, internet działa)")
    text, who = models.ask("szkic", "SYS-s", "SYS-c", "USER-cloud + MATERIAŁ 16k", private=True,
                           history=False, user_local="USER-local + MATERIAŁ 7k")
    if (text, who) != ("szkic lokalny", "lokalnie"):
        problems.append(f"awaryjny lokalny nie zadziałał: {text!r}, {who!r}")
    if len(seen_local) != 1 or seen_local[0][0] != "SYS-s" or seen_local[0][2] != "USER-local + MATERIAŁ 7k":
        problems.append(f"lokalny nie dostaje wariantu user_local: {seen_local[:1]}")
    # Druga faza: ten sam awaryjny lokalny ma działać też, gdy chmury w ogóle
    # nie wolno używać (materiał prywatny bez zgody).
    seen_local.clear()
    ctx2 = namysl_mod.Context(**{**ctx.__dict__, "settings": {"tryb": "zawsze", "material_do_sieci": False}})
    models2 = namysl_mod._Models(ctx2, namysl_mod.Narrator(None))
    text2, who2 = models2.ask("krytyka", "SYS-s", "SYS-c", "USER-bez-zgody", private=True, history=False,
                              user_local="USER-bez-zgody-local")
    if (text2, who2) != ("szkic lokalny", "lokalnie"):
        problems.append(f"lokalny jako jedyna droga nie zadziałał: {text2!r}, {who2!r}")
    if len(seen_local) != 1 or seen_local[0][2] != "USER-bez-zgody-local":
        problems.append("lokalny bez zgody nie dostaje wariantu user_local")

    return (not problems), "; ".join(problems) if problems else "audyt 1.32.31: gwarancja modelu w fazach Namysłu OK"


def _check_audyt_1332() -> tuple[bool, str]:
    """Testy poprawek 1.33.2: akcje w powitaniach (#6), wąska maska outbound
    (#11), przywrócenie checkboxa zgody (#14), brak martwych trybów (#16)
    i dokładna godzina w bloku „Teraz” (#17)."""
    import inspect
    import re
    from datetime import datetime
    from pathlib import Path

    import awareness
    import namysl
    import trace

    problems: list[str] = []
    settings = {"tryb": "zawsze", "material_do_sieci": False}

    # #6: powitanie + krótka REALNA prośba nie może omijać Namysłu.
    for msg in ("hej, przeczytaj to", "cześć, wyjaśnij mi to", "hej, otwórz plik", "cześć, uruchom testy",
                "hej, zainstaluj to", "cześć, streść notatki", "hej, przeanalizuj to", "cześć, opowiedz o routerze",
                "hej, pokaż notatki", "cześć, znajdź plik", "hej, sprawdź porty", "cześć, dodaj to",
                "hej, usuń to", "cześć, zmień to", "hej, porównaj to"):
        got, why = namysl.wants(msg, None, settings)
        if not got:
            problems.append(f"#6 {msg!r} -> False ({why})")
    if namysl.wants("dzięki", None, settings)[0]:
        problems.append("#6 podziękowanie uruchamia Namysł")

    # #11: prefiksy muszą być maskowane także w tekście wychodzącym do sieci.
    secrets = {
        "openrouter": "sk-or-PLACEHOLDER0123456789",
        "groq": "gsk_0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJ",
        "ssh-rsa": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7",
        "ssh-ed25519": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExample",
        "AKIA": "AKIAIOSFODNN7EXAMPLE",
        "slack": "xoxb-123456789012-abcdefghijkl",
        "ghp": "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "gho": "gho_0123456789abcdefghijklmnopqrstuvwxyz",
    }
    for name, value in secrets.items():
        masked = trace.mask(value, outbound=True)
        if "***" not in masked:
            problems.append(f"#11 {name} nie zamaskowany: {masked}")
    wallet = "0x52908400098527886E0F7030069857D2E4169EE7"
    if wallet not in trace.mask("adres " + wallet, outbound=True):
        problems.append("#11 adres portfela zamaskowany (fałszywy alarm)")

    # #14: statycznie - catch w saveNamyslSettings przywraca checkbox.
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"async function saveNamyslSettings\(patch\) \{.*?\n\}", app, re.S)
    block = m.group(0) if m else ""
    if "consent.checked = !!namyslSettings.material_do_sieci" not in block:
        problems.append("#14 brak przywrócenia checkboxa w catch")

    # #16: w wants() nie ma już gałęzi starych trybów.
    src = inspect.getsource(namysl.wants)
    if 'settings["tryb"] == "wylaczony"' in src or 'settings["tryb"] == "auto"' in src:
        problems.append("#16 martwa gałąź trybu nadal w wants()")

    # #17: dokładna godzina w bloku „Teraz” (lokalny i sieciowy).
    now = datetime(2026, 11, 4, 14, 5)
    stub = type("V", (), {"notes": {}})()
    for name, block in (("clock_line", awareness.clock_line(now)),
                        ("cloud_block", awareness.cloud_block(now)),
                        ("local_block", awareness.local_block(stub, now))):
        if "Godzina: 14:05" not in block:
            problems.append(f"#17 {name} bez godziny")

    return (not problems), "; ".join(problems) if problems else "audyt 1.33.2: wszystkie 5 poprawek OK"


def _check_audyt_1333() -> tuple[bool, str]:
    """Testy 1.33.3: jeden timer i numerowane fazy w stepperze (#18) oraz
    prywatny plik w prompcie lokalnego modelu, gdy chmura padnie (#19)."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod

    problems: list[str] = []

    # #18: statycznie - jeden timer, numeracja 1-6, jeden wiersz po zakończeniu.
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    for i, name in enumerate(("Rozpoznanie", "Zbieranie", "Szkic", "Krytyka", "Poprawa", "Sprawdzenie"), 1):
        if f'>{i}. {name}</span>' not in html:
            problems.append(f"#18 brak numeru {i}. {name}")
    if "pending-status-timer" in app:
        problems.append("#18 pending status nadal ma własny timer")
    if "Namysł \\u2014" not in app:
        problems.append("#18 brak jednowierszowego „Namysł — Ns”")
    if "nt-track-clickable" not in app:
        problems.append("#18 stepper nie przejął kliknięcia w panel Postęp")

    # #19: załączony plik + padnięta chmura + lokalny jako rezerwa. Snapshot
    # `local_up=False`, ale świeże sprawdzenie mówi, że Ollama wróciła. Plik
    # musi być przeczytany i wejść do promptu szkicu lokalnego.
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1333-"))
    fake = tmp / "fake.txt"
    fake.write_text("SUROWY WYCIAG 77", encoding="utf-8")
    seen: list[str] = []
    events: list[dict] = []

    def local_chat(_system, _history, message):
        seen.append(message)
        return "ODPOWIEDZ LOKALNA"

    def cloud_chat(*_a, **_k):
        raise RuntimeError("HTTP 413: Request too large")

    def read_document(_path):
        return {"ok": True, "text": "SUROWY WYCIAG 77", "name": "fake.txt", "kind": "txt",
                "chars": 16, "truncated": False, "why": ""}

    def describe(_doc):
        return "krótki plik tekstowy"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 3, "streszczone": 3, "doslownie": False}

    originals = (analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand)
    try:
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        ctx = namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="przeczytaj to", history_local=[], history_cloud=[],
            files=[str(fake)], sys_local="SYS", sys_cloud="SYS", local_up=False,
            local_chat=local_chat, local_recheck=lambda: True,
            cloud_chat=cloud_chat, cloud_pool=lambda: ["groq"],
            research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )
        out = namysl_mod.run(ctx)
        first_prompt_ok = any("DIGEST:ODPOWIEDZ LOKALNA" in prompt for prompt in seen)
        # Drugi wariant: model nie streścił pliku (pusty digest) - lokalny i tak
        # ma dostać surowy wycinek, a nie "pominięty".
        seen.clear()
        events.clear()

        def understand_empty(_doc, _cel, _ask, progress=None, should_stop=None):
            return {"digest": "", "pominiete": 0, "czesci": 3, "streszczone": 0, "doslownie": False}

        analiza_mod.understand = understand_empty
        ctx2 = namysl_mod.Context(**{**ctx.__dict__, "progress": events.append})
        out2 = namysl_mod.run(ctx2)
    finally:
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = originals
        shutil.rmtree(tmp, ignore_errors=True)

    labels = [str(e.get("label") or "") for e in events]
    if out is None or out2 is None:
        problems.append("#19 Namysł nie zwrócił odpowiedzi")
    if not any("Czytam plik" in label for label in labels):
        problems.append("#19 plik nie został przeczytany (pusty digest)")
    if any("nie mogę przeczytać" in label for label in labels):
        problems.append("#19 plik pominięty, choć lokalny model był dostępny")
    if not first_prompt_ok:
        problems.append("#19 digest pliku nie trafił do promptu szkicu lokalnego")
    if not any("SUROWY WYCIAG 77" in prompt for prompt in seen):
        problems.append("#19 surowy plik nie trafił do promptu przy pustym digestcie")

    return (not problems), "; ".join(problems) if problems else "audyt 1.33.3: timer/numeracja i plik w lokalnym promptcie OK"


def _check_audyt_1334() -> tuple[bool, str]:
    """#19b: faza Zbierania sama sprawdza, czy lokalny model odpowiada.
    - material_do_sieci=false + Ollama działa -> plik czytany, digest tylko
      w prompcie lokalnym (nie w chmurowym);
    - material_do_sieci=false + brak Ollamy -> plik pominięty z powodem."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1334-"))
    fake = tmp / "fake.txt"
    fake.write_text("SUROWY WYCIAG 77", encoding="utf-8")

    originals = (analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand,
                 analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks)

    def read_document(_path):
        return {"ok": True, "text": "SUROWY WYCIAG 77", "name": "fake.txt", "kind": "txt",
                "chars": 16, "truncated": False, "why": ""}

    def describe(_doc):
        return "krótki plik tekstowy"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 3, "streszczone": 3, "doslownie": False}

    def make_ctx(local_recheck, events, seen, cloud_prompts):
        def local_chat(_system, _history, message):
            seen.append(message)
            return "ODPOWIEDZ LOKALNA"

        def cloud_chat(_system, _messages, message, **_kw):
            cloud_prompts.append(str(message))
            raise RuntimeError("HTTP 413: Request too large")

        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="przeczytaj to", history_local=[], history_cloud=[],
            files=[str(fake)], sys_local="SYS", sys_cloud="SYS", local_up=False,
            local_chat=local_chat, local_recheck=local_recheck,
            cloud_chat=cloud_chat, cloud_pool=lambda: ["groq"],
            research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )

    try:
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1, lambda _text: ["a", "b", "c"]

        # A) Ollama działa (recheck=True), mimo że snapshot local_up=False.
        events, seen, cloud_prompts = [], [], []
        out = namysl_mod.run(make_ctx(lambda: True, events, seen, cloud_prompts))
        labels = [str(e.get("label") or "") for e in events]
        if out is None:
            problems.append("#19b A: Namysł nie zwrócił odpowiedzi")
        if not any("Czytam plik fake.txt: część 1/3" in label for label in labels):
            problems.append("#19b A: brak narracji „Czytam plik ... część 1/3”")
        if any("nie mogę przeczytać" in label for label in labels):
            problems.append("#19b A: plik pominięty, choć Ollama działa")
        if not any("DIGEST:ODPOWIEDZ LOKALNA" in prompt for prompt in seen):
            problems.append("#19b A: digest nie trafił do promptu lokalnego")
        if any("SUROWY WYCIAG 77" in prompt for prompt in cloud_prompts):
            problems.append("#19b A: treść pliku wyciekła do promptu chmurowego")

        # B) brak Ollamy (snapshot i recheck=False) i brak zgody -> pominięty.
        events2, seen2, cloud_prompts2 = [], [], []
        out2 = namysl_mod.run(make_ctx(lambda: False, events2, seen2, cloud_prompts2))
        labels2 = [str(e.get("label") or "") for e in events2]
        if not any("nie mogę przeczytać" in label for label in labels2):
            problems.append("#19b B: brak uczciwego „nie mogę przeczytać” bez żadnego dostawcy")
        if any("DIGEST:" in prompt for prompt in seen2):
            problems.append("#19b B: lokalny dostał plik, choć nie odpowiadał")
        _ = out2
    finally:
        (analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand,
         analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks) = originals
        shutil.rmtree(tmp, ignore_errors=True)

    return (not problems), "; ".join(problems) if problems else "audyt 1.33.4: recheck w Zbieraniu i digest tylko lokalnie OK"


def _check_audyt_1351() -> tuple[bool, str]:
    """1.35.1: usunięcie zadania stałego usuwa też powiązaną notatkę Task
    (type: Task, tytuł = nazwa zadania) do kosza; brak notatki = no-op;
    po usunięciu węzły znikają z grafu (get_vault już ich nie zwraca)."""
    import shutil
    import tempfile
    from pathlib import Path

    import main as main_mod
    import standing as standing_mod
    import vault as vault_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1351-"))
    tasks = tmp / "standing_tasks"
    notes = tmp / "notatki"
    tasks.mkdir()
    notes.mkdir()

    def task_note(plik: str, tytul: str) -> None:
        (tasks / plik).write_text(
            f"# {tytul}\ntype: Zadanie\nstatus: aktywne\ninterwal_minut: 60\n\n"
            f"## Zlecenie\ntest\n\n## Stan\n(brak)\n\n## Dziennik sprawdzeń\n(brak)\n\n## Alerty\n(brak)\n",
            encoding="utf-8",
        )

    task_note("test-zadanie.md", "Zadanie: test")
    (notes / "test.md").write_text("# test\ntype: Task\n\npowiązana notatka\n", encoding="utf-8")
    (notes / "inny.md").write_text("# inny\ntype: Task\n\nnie ruszać\n", encoding="utf-8")

    orig = (standing_mod.TASKS_DIR, standing_mod.DATA_DIR, main_mod.DATA_DIR,
            main_mod.get_vault, main_mod.invalidate_vault_cache)
    try:
        standing_mod.TASKS_DIR = tasks
        standing_mod.DATA_DIR = tmp
        main_mod.DATA_DIR = tmp
        main_mod.get_vault = lambda: vault_mod.build_vault([str(tasks), str(notes)])
        main_mod.invalidate_vault_cache = lambda: None

        out = main_mod.delete_standing_task("test-zadanie.md")
        if out.get("removed") is not True:
            problems.append("#1351 A: zadanie nie zostało usunięte")
        if out.get("note_removed") is not True:
            problems.append("#1351 A: powiązana notatka Task nie została usunięta")
        if (tasks / "test-zadanie.md").exists():
            problems.append("#1351 A: plik zadania nadal istnieje")
        if (notes / "test.md").exists():
            problems.append("#1351 A: plik notatki Task nadal istnieje")
        if not (notes / "inny.md").exists():
            problems.append("#1351 A: usunięto niepowiązaną notatkę Task")
        ids = {n.get("id") for n in main_mod.graph_json().get("nodes", [])}
        if "test" in ids or "test-zadanie" in ids:
            problems.append("#1351 A: węzły nadal w /api/graph po usunięciu")

        task_note("bez-notatki.md", "Zadanie: bez notatki")
        out2 = main_mod.delete_standing_task("bez-notatki.md")
        if out2.get("removed") is not True:
            problems.append("#1351 B: zadanie bez notatki nie zostało usunięte")
        if out2.get("note_removed") is not False:
            problems.append("#1351 B: brak notatki powinien być no-op")
        if (tasks / "bez-notatki.md").exists():
            problems.append("#1351 B: plik zadania bez notatki nadal istnieje")
    finally:
        (standing_mod.TASKS_DIR, standing_mod.DATA_DIR, main_mod.DATA_DIR,
         main_mod.get_vault, main_mod.invalidate_vault_cache) = orig
        shutil.rmtree(tmp, ignore_errors=True)

    return (not problems), "; ".join(problems) if problems else "audyt 1.35.1: usuwanie zadania czyści też notatkę Task i węzeł z grafu"


def _check_local_timeout() -> tuple[bool, str]:
    """LOKALNY_TIMEOUT: domyślnie 180 s i naprawdę przekazany do _ollama_chat."""
    import router as router_mod

    seen = []
    original = router_mod._ollama_chat
    old_env = os.environ.get("LOKALNY_TIMEOUT")

    def fake(system, history, message, **kwargs):
        seen.append(kwargs.get("timeout"))
        return "szkic"

    try:
        router_mod._ollama_chat = fake
        os.environ.pop("LOKALNY_TIMEOUT", None)
        router_mod._namysl_local_chat("SYS", [], "pytanie")
        default_timeout = seen[-1] if seen else None
        os.environ["LOKALNY_TIMEOUT"] = "240"
        router_mod._namysl_local_chat("SYS", [], "pytanie")
        override_timeout = seen[-1] if seen else None
    finally:
        router_mod._ollama_chat = original
        if old_env is None:
            os.environ.pop("LOKALNY_TIMEOUT", None)
        else:
            os.environ["LOKALNY_TIMEOUT"] = old_env

    ok = default_timeout == 180 and override_timeout == 240
    return ok, f"domyślny {default_timeout}, z .env {override_timeout}"


# --- 1.37.0: lokalny model 3B (cache, budżety, jakość, kolejka, sesja) ------

class _FakeResponse:
    """Minimalna odpowiedź HTTP dla netguard.read_json (read + context manager)."""

    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self, n: int = -1):
        if n is None or n < 0:
            raw, self._raw = self._raw, b""
            return raw
        raw, self._raw = self._raw[:n], self._raw[n:]
        return raw

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _fake_ollama(replies: list, callback):
    """Podstawia netguard.local_urlopen; `replies` to dicti odpowiedzi albo
    wyjątki. Zwraca (wynik callbacku, przechwycone ciała żądań)."""
    import netguard as netguard_mod
    import router as router_mod

    original = netguard_mod.local_urlopen
    bodies: list[dict] = []
    queue = list(replies)
    old_log = router_mod.OLLAMA_LOG_PATH

    def fake(req, timeout=120, **_kw):
        bodies.append(json.loads(req.data.decode("utf-8")))
        if not queue:
            raise AssertionError("nieoczekiwane dodatkowe zapytanie do Ollamy")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _FakeResponse(item)

    try:
        netguard_mod.local_urlopen = fake
        router_mod.OLLAMA_LOG_PATH = Path(tempfile.mkdtemp(prefix="gregai-ollama-log-")) / "uzycie.jsonl"
        result = callback()
    finally:
        netguard_mod.local_urlopen = original
        router_mod.OLLAMA_LOG_PATH = old_log
    return result, bodies


def _reply(text: str, tokens: int = 20) -> dict:
    return {"message": {"content": text}, "eval_count": tokens,
            "eval_duration": 1_000_000_000, "total_duration": 2_000_000_000}


def _check_local_cache() -> tuple[bool, str]:
    """1.37.0 #1: stabilny system (data + pora dnia), ulotny blok w user message."""
    import router as router_mod
    import awareness as aw
    from datetime import datetime as _dt

    problems = []
    t1 = _dt(2026, 11, 5, 10, 1)
    t2 = _dt(2026, 11, 5, 10, 59)
    t3 = _dt(2026, 11, 5, 22, 1)
    v = type("V", (), {"notes": {}})()
    s1, s2, s3 = aw.local_system("## Kryzys\n116 123.", t1), aw.local_system("## Kryzys\n116 123.", t2), aw.local_system("## Kryzys\n116 123.", t3)
    if s1 != s2:
        problems.append("system zmienia się w ramach tej samej pory dnia")
    if s1 == s3:
        problems.append("system nie zmienia się przy innej porze dnia")
    if "Godzina:" in s1:
        problems.append("dokładna godzina w systemie (psuje cache)")
    if router_mod._est_tokens(s1) > router_mod.LOCAL_SYSTEM_MAX_TOKENS:
        problems.append(f"system {router_mod._est_tokens(s1)} tokenów")
    block = aw.local_block(v, t1)
    if "Godzina:" not in block or "## Teraz (" not in block:
        problems.append("blok Teraz bez godziny/nagłówka")
    msgs = router_mod._build_messages(s1, [], "Która godzina?", router_mod.OLLAMA_NUM_CTX, 400, volatile=block)
    if "## Teraz (" in msgs[0]["content"]:
        problems.append("blok Teraz w systemie")
    if "## Teraz (" not in msgs[-1]["content"] or "Godzina:" not in msgs[-1]["content"]:
        problems.append("blok Teraz poza ostatnią wiadomością")
    return (not problems), "; ".join(problems) if problems else "system stabilny w porze dnia, Teraz w user message"


def _check_local_budget() -> tuple[bool, str]:
    """1.37.0 #2: system 800 tok, user 2000 tok, materiał lokalny 5300 znaków."""
    import router as router_mod
    import awareness as aw
    import namysl as namysl_mod

    problems = []
    system, user = router_mod._local_prompt_budget("S" * 20_000, "Pytanie testowe.",
                                                   notes="N" * 20_000, file_text="F" * 20_000)
    st, ut = router_mod._est_tokens(system), router_mod._est_tokens(user)
    if st > router_mod.LOCAL_SYSTEM_MAX_TOKENS:
        problems.append(f"system {st} > 800")
    if ut > router_mod.LOCAL_USER_MAX_TOKENS:
        problems.append(f"user {ut} > 2000")
    if st + ut > router_mod.LOCAL_PROMPT_MAX_TOKENS:
        problems.append(f"całość {st + ut} > 3000")
    if "notatka skrócona" not in user:
        problems.append("notatka nie została oznaczona jako skrócona")
    if "pełna treść pliku" not in user:
        problems.append("plik bez odesłania do pełnej treści")
    _s2, huge_user = router_mod._local_prompt_budget("", "U" * 30_000)
    if router_mod._est_tokens(huge_user) > router_mod.LOCAL_USER_MAX_TOKENS:
        problems.append(f"wklejony tekst {router_mod._est_tokens(huge_user)} > 2000")
    if namysl_mod.MATERIAL_CHARS_LOCAL > 5300:
        problems.append(f"materiał lokalny {namysl_mod.MATERIAL_CHARS_LOCAL} znaków")
    variant = namysl_mod._local_user("M" * 20_000, "## Teraz (x)\nGodzina: 10:00")
    if len(variant) > namysl_mod.LOCAL_USER_MAX_CHARS:
        problems.append(f"wariant lokalny Namysłu {len(variant)} znaków")
    if "## Teraz (" not in variant:
        problems.append("Namysł zgubił blok Teraz")
    return (not problems), "; ".join(problems) if problems else f"system {st} tok, user {ut} tok, materiał 5300 znaków"


def _check_local_style() -> tuple[bool, str]:
    """1.37.0 #3: instrukcje pod 3B - krótkie, numerowane, konkretne."""
    import awareness as aw

    rules = aw._local_rules()
    problems = []
    for must in ("1.", "2.", "NIE zgaduj", "NIE pisz", "mocniejszego modelu", "Odpowiedz po polsku"):
        if must not in rules:
            problems.append(f"brak „{must}”")
    if "uprzejmie" in rules.lower() or "proszę" in rules.lower():
        problems.append("zbędna uprzejmość")
    if any(ch in rules for ch in "😀🙂✅❌"):
        problems.append("emoji w instrukcjach")
    for line in rules.splitlines():
        body = line.split(".", 1)[1] if line[:2].strip().rstrip(".").isdigit() and "." in line else line
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            words = len(re.findall(r"\w+", sentence))
            if words > 15:
                problems.append(f"zdanie {words} słów: {sentence[:40]}")
    return (not problems), "; ".join(problems) if problems else "8 krótkich, numerowanych zasad"


def _check_local_params() -> tuple[bool, str]:
    """1.37.0 #4: parametry inferencji naprawdę w body żądania."""
    import router as router_mod

    router_mod._BIG_WARM_DONE.set()
    result, bodies = _fake_ollama([_reply("Odpowiedź po polsku.")],
                                  lambda: router_mod._ollama_chat("SYS", [], "Pytanie", num_predict=router_mod.OLLAMA_NUM_PREDICT))
    if not bodies:
        return False, "brak żądania do Ollamy"
    opts = bodies[0].get("options") or {}
    problems = []
    if opts.get("temperature", 9) > 0.5:
        problems.append("temperature > 0.5")
    if opts.get("top_p") != 0.85:
        problems.append(f"top_p {opts.get('top_p')}")
    if opts.get("top_k") != 40:
        problems.append(f"top_k {opts.get('top_k')}")
    if opts.get("repeat_penalty") != 1.2:
        problems.append(f"repeat_penalty {opts.get('repeat_penalty')}")
    if opts.get("num_predict") != 1024:
        problems.append(f"num_predict {opts.get('num_predict')}")
    if opts.get("num_ctx", 99999) > router_mod.OLLAMA_NUM_CTX:
        problems.append(f"num_ctx {opts.get('num_ctx')}")
    stop = opts.get("stop") or []
    if "\nUser:" not in stop or "\nAsystent:" not in stop:
        problems.append("brak stop dla User:/Asystent:")
    if not bodies[0].get("keep_alive"):
        problems.append("brak keep_alive")
    if result != "Odpowiedź po polsku.":
        problems.append(f"odpowiedź {result!r}")
    return (not problems), "; ".join(problems) if problems else "temperature 0.2, top_p 0.85, top_k 40, repeat 1.2, 1024 tok"


def _check_local_validation() -> tuple[bool, str]:
    """1.37.0 #5: detekcja pustego, echa promptu, angielskiego i urwania."""
    import router as router_mod

    problems = []
    cases = [
        ("", "cokolwiek", (False, "pusty", False)),
        ("To jest dokładnie powtórzony prompt użytkownika, który model odbił zamiast odpowiedzi.",
         "To jest dokładnie powtórzony prompt użytkownika, który model odbił zamiast odpowiedzi.",
         (False, "powtorzenie promptu", True)),
        ("Sure! Here is the answer you need with the price of gold today and more details.",
         "kurs złota", (False, "angielski", True)),
        ("To jest odpowiedź, która urywa się w połowie zdania i nie ma końca " * 12, "pytanie", (True, "urwane", False)),
        ("Krótka, poprawna odpowiedź po polsku.", "pytanie", (True, "", False)),
    ]
    for text, prompt, want in cases:
        got = router_mod._validate_local_response(text, prompt)
        if got != want:
            problems.append(f"{want[1] or 'ok'}: dostałem {got}")
    # 1.38.3 (#25b): pusta odpowiedź NIE jest ponawiana - to zwykle przekroczony
    # kontekst, więc retry z tym samym promptem dałby ten sam błąd.
    reply, bodies = _fake_ollama([_reply("")],
                                 lambda: router_mod._ollama_chat("SYS", [], "Pytanie"))
    if reply != "" or len(bodies) != 1:
        problems.append(f"pusta odpowiedź bez retry: {reply!r}, {len(bodies)} żądań")
    # Retry po angielsku: drugie żądanie musi nieść "Odpowiedz po polsku".
    reply2, bodies2 = _fake_ollama([_reply("Sure! Here is the answer you need with the price of gold today and more."),
                                    _reply("Poprawna odpowiedź po polsku.")],
                                   lambda: router_mod._ollama_chat("SYS", [], "Pytanie"))
    sent = json.dumps(bodies2[-1].get("messages") or [], ensure_ascii=False) if len(bodies2) > 1 else ""
    if reply2 != "Poprawna odpowiedź po polsku." or "Odpowiedz po polsku" not in sent:
        problems.append(f"retry angielskiego: {reply2!r}, {len(bodies2)} żądań")
    return (not problems), "; ".join(problems) if problems else "pusty bez retry, echo/angielski z retry, urwane tylko oznaczane"


def _check_local_queue() -> tuple[bool, str]:
    """1.37.0 #6: semafor 1 liczy + 2 czekają, trzecie żądanie odpada."""
    import threading as _th
    import time as _time
    import router as router_mod

    old_timeout = router_mod._LOCAL_QUEUE_TIMEOUT
    router_mod._LOCAL_QUEUE_TIMEOUT = 0.4
    problems = []
    release = _th.Event()
    errors: list[str] = []

    def holder():
        try:
            with router_mod._local_slot():
                release.wait(3)
        except Exception as e:  # pragma: no cover - diagnostyka testu
            errors.append(f"holder: {type(e).__name__}: {e}")

    def waiter():
        try:
            with router_mod._local_slot():
                pass
        except Exception as e:
            errors.append(f"waiter: {type(e).__name__}: {e}")

    try:
        t0 = _th.Thread(target=holder, daemon=True)
        t0.start()
        # dwaj czekający (active = 3: holder + 2)
        waiters = [_th.Thread(target=waiter, daemon=True) for _ in range(2)]
        for t in waiters:
            t.start()
        deadline = _time.monotonic() + 2
        while _time.monotonic() < deadline:
            with router_mod._LOCAL_QUEUE_LOCK:
                if router_mod._LOCAL_QUEUE_ACTIVE >= 3:
                    break
            _time.sleep(0.02)
        third_error = ""
        try:
            with router_mod._local_slot():
                pass
            third_error = "trzecie weszło"
        except RuntimeError as e:
            third_error = str(e)
        if "kolejka pełna" not in third_error:
            problems.append(f"trzecie żądanie: {third_error!r}")
    finally:
        release.set()
        for t in locals().get("waiters", []):
            t.join(timeout=3)
        try:
            t0.join(timeout=3)
        except Exception:
            pass
        router_mod._LOCAL_QUEUE_TIMEOUT = old_timeout
    if errors:
        problems.append("; ".join(errors))
    return (not problems), "; ".join(problems) if problems else "2 czekających, trzecie odpada bez crasha"


def _check_local_retry() -> tuple[bool, str]:
    """1.37.0 #7: po timeoucie jedna próba bez ulotnego bloku (faktów)."""
    import router as router_mod

    problems = []
    router_mod._BIG_WARM_DONE.set()
    reply, bodies = _fake_ollama([TimeoutError("timed out"), _reply("Odpowiedź po timeoucie, po polsku.")],
                                 lambda: router_mod._ollama_chat("SYS", [], "Pytanie", volatile="TAJNE_NOTATKI"))
    if reply != "Odpowiedź po timeoucie, po polsku.":
        problems.append(f"wynik {reply!r}")
    if len(bodies) != 2:
        problems.append(f"{len(bodies)} żądań zamiast 2")
    else:
        first = json.dumps(bodies[0].get("messages") or [], ensure_ascii=False)
        second = json.dumps(bodies[1].get("messages") or [], ensure_ascii=False)
        if "TAJNE_NOTATKI" not in first:
            problems.append("pierwsze żądanie bez bloku")
        if "TAJNE_NOTATKI" in second:
            problems.append("retry nadal niesie notatki")
    return (not problems), "; ".join(problems) if problems else "timeout -> retry bez notatek, potem wynik"


def _check_local_session() -> tuple[bool, str]:
    """1.37.0 #8: licznik dzisiejszej sesji i ostrzeżenia 5000/10000 tokenów."""
    import router as router_mod
    import tempfile as _tf

    old = router_mod.OLLAMA_LOG_PATH
    tmp = Path(_tf.mkdtemp(prefix="gregai-sesja-")) / "uzycie.jsonl"
    today = time.strftime("%Y-%m-%d")
    rows = [
        {"ts": today + "T10:00:00", "tokeny": 3000, "tok_s": 5.0},
        {"ts": today + "T10:05:00", "tokeny": 4000, "tok_s": 7.0},
        {"ts": "2020-01-01T10:00:00", "tokeny": 9999, "tok_s": 1.0},
    ]
    problems = []
    try:
        tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        router_mod.OLLAMA_LOG_PATH = tmp
        st = router_mod.local_session_stats()
        if (st["tokeny"], st["inferencje"], st["tok_s_mediana"]) != (7000, 2, 7.0):
            problems.append(f"licznik: {st}")
        if "5000" not in st["ostrzezenie"]:
            problems.append("brak ostrzeżenia po 5000")
        rows.append({"ts": today + "T11:00:00", "tokeny": 4000, "tok_s": 6.0})
        tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        st2 = router_mod.local_session_stats()
        if "10000" not in st2["ostrzezenie"] or "restart" not in st2["ostrzezenie"].lower():
            problems.append("brak propozycji restartu po 10000")
    finally:
        router_mod.OLLAMA_LOG_PATH = old
    return (not problems), "; ".join(problems) if problems else "7000 tokenów, mediana 7 tok/s, progi 5000/10000"


def _check_local_warmup() -> tuple[bool, str]:
    """1.37.0 #9: keep_alive 30m w instalatorze i nota o wolnym starcie."""
    import router as router_mod

    problems = []
    installer = (ROOT / "install.sh").read_text(encoding="utf-8", errors="replace")
    if "OLLAMA_KEEP_ALIVE=30m" not in installer:
        problems.append("install.sh bez OLLAMA_KEEP_ALIVE=30m")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8", errors="replace")
    if "OLLAMA_KEEP_ALIVE=30m" not in env_example:
        problems.append(".env.example bez OLLAMA_KEEP_ALIVE")
    original = dict(router_mod._WARM_STATE)
    try:
        router_mod._WARM_STATE.update(state="gotowe", detail="qwen2.5:3b gotowy", started=time.time() - 200,
                                      finished=time.time())
        st = router_mod.warm_status()
        if st.get("seconds") != 200 or "wolny start" not in (st.get("detail") or ""):
            problems.append(f"warm_status: {st}")
    finally:
        router_mod._WARM_STATE.clear()
        router_mod._WARM_STATE.update(original)
    return (not problems), "; ".join(problems) if problems else "keep_alive 30m + nota po 120 s"


def _check_spoleczne_1380() -> tuple[bool, str]:
    """1.38.0 #21: "dzięki"/"cześć" -> krótka odpowiedź z kodu, bez modelu."""
    import namysl as namysl_mod
    import router as router_mod
    import standing as standing_mod

    problems: list[str] = []
    settings = {"tryb": "zawsze", "material_do_sieci": False}
    expected = {
        "dzięki": "Nie ma za co!",
        "Dziękuję bardzo": "Nie ma za co!",
        "Dzięki za pomoc": "Nie ma za co!",
        "cześć": "Cześć! W czym mogę pomóc?",
        "hej": "Cześć! W czym mogę pomóc?",
    }
    for msg, want in expected.items():
        got = router_mod._social_reply(msg, settings)
        if got != want:
            problems.append(f"{msg!r} -> {got!r}, oczekiwano {want!r}")
    for msg in ("dzięki, zrób mi plan na jutro", "hej, przeczytaj to", "hej, co u ciebie?"):
        if router_mod._social_reply(msg, settings) is not None:
            problems.append(f"{msg!r} niesłusznie przechwycone")

    original = (router_mod._ollama_chat, router_mod.ollama_available, namysl_mod.load_settings,
                standing_mod.pop_pending_alerts)
    calls: list[int] = []

    def fake_chat(*_a, **_k):
        calls.append(1)
        return "ODPOWIEDŹ MODELU"

    try:
        router_mod._ollama_chat = fake_chat
        router_mod.ollama_available = lambda: True
        namysl_mod.load_settings = lambda: settings
        standing_mod.pop_pending_alerts = lambda: []
        vault = type("V", (), {"notes": {}})()
        t0 = time.monotonic()
        res = router_mod.route(vault, "SYS", [], "dzięki", nie_ucz=True, nie_zapisuj_sladu=True)
        took = time.monotonic() - t0
        speech = res.get("_speech_bez_alertu") or res.get("speech") or ""
        if speech != "Nie ma za co!":
            problems.append(f"route: {speech!r}")
        if calls:
            problems.append(f"model wywołany {len(calls)} raz")
        if took >= 1.0:
            problems.append(f"odpowiedź trwała {took:.2f} s")
        if "Internet działa" in speech or "WARP" in speech or "koryto" in speech.lower():
            problems.append("w odpowiedzi opis koryta zamiast podziękowania")
    finally:
        (router_mod._ollama_chat, router_mod.ollama_available, namysl_mod.load_settings,
         standing_mod.pop_pending_alerts) = original
    return (not problems), "; ".join(problems) if problems else "dzięki/cześć bez modelu, <1 s"


def _check_czas_1380() -> tuple[bool, str]:
    """1.38.0 #22: warianty pytania o godzinę/datę trafiają w szybką ścieżkę."""
    import namysl as namysl_mod
    import router as router_mod
    import standing as standing_mod

    problems: list[str] = []
    time_cases = ("Która godzina?", "Która jest godzina?", "Jaka jest aktualna godzina?",
                  "Jaka jest aktualna godzina w Polsce?", "aktualna godzina", "ile jest?",
                  "Podaj godzinę.")
    for msg in time_cases:
        got = router_mod._time_answer(msg)
        if not re.match(r"^Jest \d{2}:\d{2}( \w+)?\.$", got or ""):
            problems.append(f"{msg!r} -> {got!r}")
    date_cases = ("Jaka jest data?", "Jaki jest dzisiaj dzień?", "Który jest dzień?",
                  "Jaki mamy dziś dzień?", "Podaj dzisiejszą datę.")
    for msg in date_cases:
        got = router_mod._time_answer(msg)
        if not (got or "").startswith("Dziś:"):
            problems.append(f"{msg!r} -> {got!r}")
    for msg in ("w jakich godzinach otwarte?", "Która godzina w strefie UTC?",
                "ile jest osób w pokoju?", "ile godzin ma doba?"):
        if router_mod._time_answer(msg) is not None:
            problems.append(f"{msg!r} niesłusznie odpowiedziane jako zegar")

    settings = {"tryb": "zawsze", "material_do_sieci": False}
    original = (router_mod._ollama_chat, router_mod.ollama_available, namysl_mod.load_settings,
                standing_mod.pop_pending_alerts)
    calls: list[int] = []

    def fake_chat(*_a, **_k):
        calls.append(1)
        return "ODPOWIEDŹ MODELU"

    try:
        router_mod._ollama_chat = fake_chat
        router_mod.ollama_available = lambda: True
        namysl_mod.load_settings = lambda: settings
        standing_mod.pop_pending_alerts = lambda: []
        vault = type("V", (), {"notes": {}})()
        t0 = time.monotonic()
        res = router_mod.route(vault, "SYS", [], "Jaka jest aktualna godzina w Polsce?",
                               nie_ucz=True, nie_zapisuj_sladu=True)
        took = time.monotonic() - t0
        speech = res.get("_speech_bez_alertu") or res.get("speech") or ""
        if not re.match(r"^Jest \d{2}:\d{2}( \w+)?\.$", speech):
            problems.append(f"route: {speech!r}")
        if calls:
            problems.append(f"model wywołany {len(calls)} raz")
        if took >= 1.0:
            problems.append(f"odpowiedź trwała {took:.2f} s")
    finally:
        (router_mod._ollama_chat, router_mod.ollama_available, namysl_mod.load_settings,
         standing_mod.pop_pending_alerts) = original
    return (not problems), "; ".join(problems) if problems else "godzina/data z kodu, bez modelu, <1 s"


def _check_plik_1380() -> tuple[bool, str]:
    """1.38.0 #20: "PLIKI: to" z rozpoznania nie robi "pominięty" dla załącznika."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1380-"))
    fake = tmp / "fake.txt"
    fake.write_text("SUROWY WYCIAG 77", encoding="utf-8")

    originals = (analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand,
                 analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks, namysl_mod.parse_plan)

    def read_document(_path):
        return {"ok": True, "text": "SUROWY WYCIAG 77", "name": "fake.txt", "kind": "txt",
                "chars": 16, "truncated": False, "why": ""}

    def describe(_doc):
        return "krótki plik tekstowy"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 3, "streszczone": 3, "doslownie": False}

    def make_ctx(local_recheck, events, seen):
        def local_chat(_system, _history, message):
            seen.append(message)
            return "ODPOWIEDZ LOKALNA"

        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="hej, przeczytaj to", history_local=[], history_cloud=[],
            files=[str(fake)], sys_local="SYS", sys_cloud="SYS", local_up=False,
            local_chat=local_chat, local_recheck=local_recheck,
            cloud_chat=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bez sieci")),
            cloud_pool=lambda: [],
            research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )

    def bogus_plan(text, message):
        plan = namysl_mod.default_plan(message)
        plan.pliki = ["to", "przeczytaj to"]
        return plan

    try:
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1, lambda _text: ["a", "b", "c"]
        namysl_mod.parse_plan = bogus_plan

        events, seen = [], []
        out = namysl_mod.run(make_ctx(lambda: True, events, seen))
        labels = [str(e.get("label") or "") for e in events]
        if out is None:
            problems.append("Namysł nie zwrócił odpowiedzi")
        if not any("Czytam plik fake.txt" in label for label in labels):
            problems.append("brak „Czytam plik fake.txt”")
        if any("pominięty" in label for label in labels):
            problems.append(f"błędna etykieta: {[l for l in labels if 'pominięty' in l][:2]}")
        if any("Plik to" in label for label in labels):
            problems.append("wpis „to” z rozpoznania trafił do plików")
        if not any("DIGEST:ODPOWIEDZ LOKALNA" in prompt for prompt in seen):
            problems.append("digest nie trafił do promptu lokalnego")

        events2, seen2 = [], []
        namysl_mod.run(make_ctx(lambda: False, events2, seen2))
        labels2 = [str(e.get("label") or "") for e in events2]
        if not any("nie mogę przeczytać" in label for label in labels2):
            problems.append("brak „nie mogę przeczytać” bez lokalnego i bez zgody")

        if namysl_mod._plausible_file_ref("to"):
            problems.append("filtr przepuścił „to”")
        if namysl_mod._plausible_file_ref("przeczytaj to"):
            problems.append("filtr przepuścił prozę „przeczytaj to”")
        if not namysl_mod._plausible_file_ref("raport.pdf"):
            problems.append("filtr odrzucił prawdziwy plik")
        # Fix #19b w Zbieraniu musi omijać 5-sekundowy cache ollama_available(),
        # inaczej stary "nie działa" nadal blokuje plik mimo działającej Ollamy.
        router_src = (ROOT / "agent" / "router.py").read_text(encoding="utf-8")
        if "ollama_available(fresh=True)" not in router_src:
            problems.append("Zbieranie nie robi świeżego sprawdzenia Ollamy")
    finally:
        (analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand,
         analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks, namysl_mod.parse_plan) = originals
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "załącznik czytany, śmieci z PLIKI odfiltrowane"


def _check_plik_upload_1381() -> tuple[bool, str]:
    """1.38.1 #23: plik z data/wgrane/<chat>/<data>-<nazwa> jest znajdowany
    po oryginalnej nazwie z wiadomości; Zbieranie czyta go z częściami 1/N."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod
    import sources as sources_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1381-"))
    chat = "test-1381"
    original = "Chronologia fabularna.txt"
    upload_dir = tmp / chat
    upload_dir.mkdir(parents=True)
    stored = upload_dir / f"2026-11-05-{original}"
    stored.write_text("STARY PLIK " * 20, encoding="utf-8")

    originals = (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
                 analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
                 namysl_mod.parse_plan)

    def read_document(path):
        p = Path(path)
        return {"ok": True, "text": "TRESC PLIKU " * 20, "name": p.name, "kind": "txt",
                "chars": len(p.name) * 20, "truncated": False, "why": ""}

    def describe(_doc):
        return "plik tekstowy z wgranych"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 3, "streszczone": 3, "doslownie": False}

    def plan_with_original(_text, message):
        plan = namysl_mod.default_plan(message)
        plan.pliki = [original]
        return plan

    def make_ctx(events, seen):
        def local_chat(_system, _history, message):
            seen.append(message)
            return "ODPOWIEDZ LOKALNA"

        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="hej, przeczytaj to", history_local=[], history_cloud=[],
            files=[], sys_local="SYS", sys_cloud="SYS", local_up=False, chat=chat,
            local_chat=local_chat, local_recheck=lambda: True,
            cloud_chat=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bez sieci")),
            cloud_pool=lambda: [],
            research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )

    try:
        sources_mod.UPLOAD_DIR = tmp
        resolved, note = namysl_mod._resolve_file(original, chat, sources_mod.chat_roots(chat))
        if resolved != stored:
            problems.append(f"nie znaleziono wgranego pliku po oryginalnej nazwie ({note})")
        found = sources_mod.find_upload_by_name(chat, original)
        if stored not in found:
            problems.append("find_upload_by_name nie widzi pliku z prefiksem daty")

        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1, lambda _text: ["a", "b", "c"]
        namysl_mod.parse_plan = plan_with_original
        events, seen = [], []
        out = namysl_mod.run(make_ctx(events, seen))
        labels = [str(e.get("label") or "") for e in events]
        if out is None:
            problems.append("Namysł nie zwrócił odpowiedzi")
        if not any(("Czytam plik" in label and "część 1/" in label) for label in labels):
            problems.append(f"brak „Czytam plik ... część 1/N”: {labels[:4]}")
        if any(("nie znaleziony" in label or "pominięty" in label) for label in labels):
            problems.append("plik z wgranych oznaczony jako nieznaleziony/pominięty")
        if not any("DIGEST:ODPOWIEDZ LOKALNA" in prompt for prompt in seen):
            problems.append("digest z wgranego pliku nie trafił do promptu lokalnego")

        missing, why = namysl_mod._resolve_file("nie-ma-takiego.txt", chat, sources_mod.chat_roots(chat))
        if missing is not None or "nie znalazłem" not in why:
            problems.append(f"brak poprawnego komunikatu dla nieistniejącego pliku: {why}")
    finally:
        (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
         analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
         namysl_mod.parse_plan) = originals
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "data/wgrane/<chat>/<data>-nazwa czytane po oryginalnej nazwie"


def _check_namysl_413_1382() -> tuple[bool, str]:
    """1.38.2 #24: plik z data/wgrane + 413 u Groqa -> szkic liczy lokalny
    model, a plik jest w jego promptcie (nie odpowiedź z notatek)."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import main as main_mod
    import namysl as namysl_mod
    import sources as sources_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1382-"))
    chat = "test-1382"
    original = "Chronologia fabularna.txt"
    upload_dir = tmp / chat
    upload_dir.mkdir(parents=True)
    stored = upload_dir / f"2026-11-05-{original}"
    stored.write_text("TRESC PLIKU O CHRONOLOGII " * 100, encoding="utf-8")

    originals = (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
                 analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks)
    calls = {"cloud": 0, "local": 0}
    local_prompts: list[str] = []
    read_paths: list[str] = []
    events: list[dict] = []

    def read_document(path):
        read_paths.append(str(path))
        return {"ok": True, "text": "TRESC PLIKU O CHRONOLOGII " * 100,
                "name": Path(path).name, "kind": "txt", "chars": 2400, "truncated": False, "why": ""}

    def describe(_doc):
        return "plik tekstowy o chronologii"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 3, "streszczone": 3, "doslownie": False}

    def cloud_fail(_s, _m, _u, **_kw):
        calls["cloud"] += 1
        raise RuntimeError('HTTP 413: Request too large for model "openai/gpt-oss-20b"')

    def local_chat(_system, _history, message):
        calls["local"] += 1
        local_prompts.append(message)
        return "ODPOWIEDZ LOKALNA NA PODSTAWIE PLIKU"

    def make_ctx(files):
        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="hej, przeczytaj to", history_local=[], history_cloud=[],
            files=files, sys_local="SYS", sys_cloud="SYS", local_up=False, chat=chat,
            local_chat=local_chat, local_recheck=lambda: True,
            cloud_chat=cloud_fail, cloud_pool=lambda: ["groq"],
            research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": True},
            progress=events.append,
        )

    try:
        sources_mod.UPLOAD_DIR = tmp
        recovered = main_mod._recent_read_attachment(chat, "hej, przeczytaj to")
        if [str(stored)] != recovered:
            problems.append(f"odzyskiwanie świeżego pliku: {recovered}")
        if main_mod._recent_read_attachment(chat, "opowiedz o pogodzie"):
            problems.append("plik odzyskany bez prośby o przeczytanie")

        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1, lambda _text: ["a", "b", "c"]
        out = namysl_mod.run(make_ctx(recovered))
        if out is None:
            problems.append("Namysł nie zwrócił odpowiedzi po 413")
        speech = (out or {}).get("speech", "")
        if speech != "ODPOWIEDZ LOKALNA NA PODSTAWIE PLIKU":
            problems.append(f"szkic nie przeszedł na lokalny: {speech!r}")
        if not calls["cloud"] or not calls["local"]:
            problems.append(f"wywołania cloud/local: {calls}")
        if not any("DIGEST:ODPOWIEDZ LOKALNA" in p for p in local_prompts):
            problems.append("plik/digest nie trafił do promptu lokalnego")
        if str(stored) not in read_paths:
            problems.append(f"nie czytano wgranego pliku: {read_paths[:2]}")
        labels = [str(e.get("label") or "") for e in events]
        if not any("Sieć nie odpowiedziała - liczę lokalnie" in label for label in labels):
            problems.append("brak komunikatu „Sieć nie odpowiedziała - liczę lokalnie”")
        zrodla = (out or {}).get("card", {}).get("zrodla") or []
        if not any("plik:" in str(z) for z in zrodla):
            problems.append(f"plik nie jest źródłem odpowiedzi: {zrodla}")
    finally:
        (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
         analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks) = originals
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "413 -> szkic lokalnie, plik w promptcie"


def _check_awaryjny_1382() -> tuple[bool, str]:
    """1.38.2 #24: po porażce wszystkich etapów sieciowych lokalny jest
    ostatnią szansą także przy KORYTO_LOKALNIE=bez_internetu."""
    import namysl as namysl_mod
    import netguard as netguard_mod
    import router as router_mod
    import juggler as juggler_mod
    import standing as standing_mod
    import trace as trace_mod

    problems: list[str] = []
    local_calls: list[str] = []
    traced: list[dict] = []
    original = (router_mod._ollama_chat, router_mod.ollama_available, router_mod.STUDENT_MODEL,
                juggler_mod.providers_pool, juggler_mod.chat, juggler_mod.rozdzielnica,
                juggler_mod.is_risky, netguard_mod.internet_allowed,
                standing_mod.pop_pending_alerts, trace_mod.record, namysl_mod.load_settings)
    old_local = os.environ.get("KORYTO_LOKALNIE")
    old_koryto = os.environ.get("KORYTO")

    def bad_chat(*_a, **_k):
        raise RuntimeError('HTTP 413: Request too large for model "openai/gpt-oss-20b"')

    try:
        os.environ["KORYTO"] = "darmowe,lokalnie"
        os.environ["KORYTO_LOKALNIE"] = "bez_internetu"
        router_mod._ollama_chat = lambda system, history, message, **kw: (local_calls.append(message)
                                                                         or "Odpowiedź lokalna po awarii sieci.")
        router_mod.ollama_available = lambda: True
        router_mod.STUDENT_MODEL = ""
        juggler_mod.providers_pool = lambda etap=None: ["groq"]
        juggler_mod.chat = bad_chat
        juggler_mod.rozdzielnica = lambda _poziom: {"etapy": ["darmowe"], "model": None}
        juggler_mod.is_risky = lambda _m: False
        netguard_mod.internet_allowed = lambda: (True, "")
        standing_mod.pop_pending_alerts = lambda: []
        trace_mod.record = lambda stage, message, **kw: traced.append({"stage": stage, **kw})
        namysl_mod.load_settings = lambda: {"tryb": "zawsze", "material_do_sieci": False}
        res = router_mod.route(type("V", (), {"notes": {}})(), "SYS", [], "ok",
                               nie_ucz=True, nie_zapisuj_sladu=True)
        speech = res.get("_speech_bez_alertu") or res.get("speech") or ""
        if speech != "Odpowiedź lokalna po awarii sieci.":
            problems.append(f"brak lokalnej odpowiedzi: {speech!r}")
        if not local_calls:
            problems.append("lokalny model nie został wywołany awaryjnie")
        extra = {}
        for row in traced:
            if isinstance(row.get("extra"), dict):
                extra.update(row["extra"])
        if "Sieć nie odpowiedziała" not in str(extra.get("lokalnie_awaryjnie", "")):
            problems.append(f"brak komunikatu awaryjnego: {extra.get('lokalnie_awaryjnie')!r}")
        note = router_mod._network_failure_note({"cloud_error": "HTTP 413", "ollama_error": "TimeoutError"})
        if "nie użyłem" in note or "też nie odpowiedział" not in note:
            problems.append(f"zły komunikat po nieudanej próbie lokalnej: {note!r}")
    finally:
        (router_mod._ollama_chat, router_mod.ollama_available, router_mod.STUDENT_MODEL,
         juggler_mod.providers_pool, juggler_mod.chat, juggler_mod.rozdzielnica,
         juggler_mod.is_risky, netguard_mod.internet_allowed,
         standing_mod.pop_pending_alerts, trace_mod.record, namysl_mod.load_settings) = original
        if old_local is None:
            os.environ.pop("KORYTO_LOKALNIE", None)
        else:
            os.environ["KORYTO_LOKALNIE"] = old_local
        if old_koryto is None:
            os.environ.pop("KORYTO", None)
        else:
            os.environ["KORYTO"] = old_koryto
    return (not problems), "; ".join(problems) if problems else "sieć 413 -> lokalny awaryjnie, uczciwy komunikat"


def _check_duplikat_1383() -> tuple[bool, str]:
    """1.38.3 #25a: ta sama ścieżka z wielu referencji = JEDEN odczyt i jedna
    narracja, bez duplikatów materiału i powtórzonego „Notatki: nic”."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod
    import sources as sources_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1383-"))
    chat = "test-1383"
    original = "Chronologia fabularna.txt"
    upload_dir = tmp / chat
    upload_dir.mkdir(parents=True)
    stored = upload_dir / f"2026-11-05-{original}"
    stored.write_text("TRESC PLIKU " * 100, encoding="utf-8")

    originals = (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
                 analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
                 namysl_mod.parse_plan)
    reads: list[str] = []

    def read_document(path):
        reads.append(str(path))
        return {"ok": True, "text": "TRESC PLIKU " * 100, "name": Path(path).name, "kind": "txt",
                "chars": 1200, "truncated": False, "why": ""}

    def describe(_doc):
        return "plik tekstowy"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 1, "streszczone": 1, "doslownie": False}

    def plan(_text, message):
        p = namysl_mod.default_plan(message)
        # Trzy różne zapisy tego samego pliku + proza z polecenia.
        p.pliki = [original, stored.name, str(stored), "przeczytaj to"]
        return p

    def make_ctx(events):
        def local_chat(_system, _history, _message):
            return "ODPOWIEDZ LOKALNA"

        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="hej, przeczytaj to", history_local=[], history_cloud=[],
            files=[str(stored)], sys_local="SYS", sys_cloud="SYS", local_up=False, local_recheck=lambda: True,
            chat=chat, local_chat=local_chat, cloud_chat=lambda *_a, **_k: ("", ""),
            cloud_pool=lambda: [], research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )

    try:
        sources_mod.UPLOAD_DIR = tmp
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1000, lambda _text: ["a"]
        namysl_mod.parse_plan = plan
        events: list[dict] = []
        out = namysl_mod.run(make_ctx(events))
        labels = [str(e.get("label") or "") for e in events]
        if len(reads) != 1:
            problems.append(f"odczytów pliku: {len(reads)}")
        if sum(1 for label in labels if "Czytam plik" in label) != 1:
            problems.append(f"narracji „Czytam plik”: {[l for l in labels if 'Czytam plik' in l]}")
        if sum(1 for label in labels if "Notatki: nic" in label) != 1:
            problems.append("„Notatki: nic” nie raz")
        zrodla = (out or {}).get("card", {}).get("zrodla") or []
        if sum(1 for z in zrodla if "plik:" in str(z)) != 1:
            problems.append(f"duplikaty źródeł: {zrodla}")
    finally:
        (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
         analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
         namysl_mod.parse_plan) = originals
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "jeden odczyt, jedna narracja, jedno źródło"


def _check_prompt_ctx_1383() -> tuple[bool, str]:
    """1.38.3 #25b, próg 12000 od 1.38.4: prompt > 12000 tokenów jest cięty,
    a pusty wynik nie ma retry."""
    import router as router_mod

    problems: list[str] = []
    router_mod._BIG_WARM_DONE.set()
    system = "Słowo " * 4800          # ok. 10,7 tys. tokenów
    user = "U" * 12000                # _build_messages i tak utnie do 2000
    reply, bodies = _fake_ollama([_reply("")],
                                 lambda: router_mod._ollama_chat(system, [], user, _allow_retry=True))
    if reply != "":
        problems.append(f"pusta odpowiedź: {reply!r}")
    if len(bodies) != 1:
        problems.append(f"pusta odpowiedź ponowiona: {len(bodies)} żądań")
    if not bodies:
        return False, "brak żądania do Ollamy"
    messages = bodies[0].get("messages") or []
    last = str(messages[-1].get("content") or "") if messages else ""
    total = router_mod._est_tokens(messages[0].get("content", "")) + router_mod._est_tokens(last)
    if "materiał ucięty - za długi dla kontekstu" not in last:
        problems.append("brak znacznika ucięcia materiału")
    if total > router_mod.LOCAL_PROMPT_SAFE_TOKENS:
        problems.append(f"system+user nadal {total} tokenów")
    if router_mod.local_last_quality().get("powod") != "prompt-ctx":
        problems.append(f"kod jakości: {router_mod.local_last_quality()}")
    # Faza Namysłu ma dostać czytelny komunikat, nie ogólne „Model nie odpowiedział”.
    try:
        _fake_ollama([_reply("")], lambda: router_mod._namysl_local_chat(system, [], user))
    except RuntimeError as e:
        if "prompt za długi" not in str(e):
            problems.append(f"komunikat: {e}")
    else:
        problems.append("brak wyjątku o za długim promptcie")
    return (not problems), "; ".join(problems) if problems else "12000 tokenów, znacznik, bez retry, jasny komunikat"


def _check_notatki_1384() -> tuple[bool, str]:
    """1.38.4 #26: nazwa załącznika rozbita na słowa nie uruchamia szukania
    w notatkach; plik jest czytany raz, bez drugiego „Czytam plik”."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod
    import sources as sources_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1384-"))
    chat = "test-1384"
    original = "2026-11-05-Chronologia fabularna.txt"
    upload_dir = tmp / chat
    upload_dir.mkdir(parents=True)
    stored = upload_dir / original
    stored.write_text("TRESC PLIKU " * 100, encoding="utf-8")

    files = [str(stored)]
    if namysl_mod._notes_query_without_attachment("Chronologia fabularna", files) != "":
        problems.append("zapytanie z samych słów nazwy pliku nie zostało wycięte")
    if namysl_mod._notes_query_without_attachment("notatki o chronologii", files) == "":
        problems.append("prawdziwe zapytanie o notatki zostało wycięte")

    originals = (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
                 analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
                 namysl_mod.parse_plan)
    reads: list[str] = []
    note_searches: list[str] = []
    events: list[dict] = []

    def read_document(path):
        reads.append(str(path))
        return {"ok": True, "text": "TRESC PLIKU " * 100, "name": Path(path).name, "kind": "txt",
                "chars": 1200, "truncated": False, "why": ""}

    def describe(_doc):
        return "plik tekstowy"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 1, "streszczone": 1, "doslownie": False}

    def plan(_text, message):
        p = namysl_mod.default_plan(message)
        p.notatki = "Chronologia fabularna"  # dokładnie to zrobiło rozpoznanie 3B
        return p

    def search_notes(_vault, query):
        note_searches.append(query)
        return []

    def make_ctx():
        def local_chat(_system, _history, _message):
            return "ODPOWIEDZ LOKALNA"

        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="hej, przeczytaj to", history_local=[], history_cloud=[],
            files=files, sys_local="SYS", sys_cloud="SYS", local_up=False, local_recheck=lambda: True,
            chat=chat, local_chat=local_chat, cloud_chat=lambda *_a, **_k: ("", ""),
            cloud_pool=lambda: [], research=None, search_notes=search_notes, research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )

    try:
        sources_mod.UPLOAD_DIR = tmp
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1, lambda _text: ["a"]
        namysl_mod.parse_plan = plan
        out = namysl_mod.run(make_ctx())
        labels = [str(e.get("label") or "") for e in events]
        if note_searches:
            problems.append(f"szukano w notatkach po nazwie pliku: {note_searches}")
        if any("Czytam notatki" in label for label in labels):
            problems.append("zbędne „Czytam notatki” dla nazwy załącznika")
        if sum(1 for label in labels if "Czytam plik" in label) != 1:
            problems.append(f"narracji „Czytam plik”: {[l for l in labels if 'Czytam plik' in l]}")
        if len(reads) != 1:
            problems.append(f"odczytów pliku: {len(reads)}")
        if out is None:
            problems.append("Namysł nie zwrócił odpowiedzi")
    finally:
        (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
         analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
         namysl_mod.parse_plan) = originals
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "nazwa pliku nie uruchamia notatek, jeden odczyt"


def _check_normalizacja_1385() -> tuple[bool, str]:
    """1.38.5 #27: prefiks daty i numer kolizji nie tworzą drugiego pliku."""
    import shutil
    import tempfile
    from pathlib import Path

    import analiza as analiza_mod
    import namysl as namysl_mod
    import sources as sources_mod

    problems: list[str] = []
    cases = {
        "2026-11-05-Chronologia fabularna.txt": "chronologia fabularna.txt",
        "2026-11-05-Chronologia fabularna-2.txt": "chronologia fabularna.txt",
        "Chronologia fabularna.txt": "chronologia fabularna.txt",
        "2026-11-05-Chronologia fabularna-3": "chronologia fabularna",
    }
    for raw, want in cases.items():
        got = namysl_mod._normalize_name(raw)
        if got != want:
            problems.append(f"{raw!r} -> {got!r}, oczekiwano {want!r}")

    tmp = Path(tempfile.mkdtemp(prefix="gregai-1385-"))
    chat = "test-1385"
    original = "Chronologia fabularna.txt"
    upload_dir = tmp / chat
    upload_dir.mkdir(parents=True)
    stored = upload_dir / f"2026-11-05-{original}"
    stored.write_text("TRESC PLIKU " * 100, encoding="utf-8")

    originals = (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
                 analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
                 namysl_mod.parse_plan, namysl_mod._resolve_file)
    reads: list[str] = []
    resolve_calls: list[str] = []

    def read_document(path):
        reads.append(str(path))
        return {"ok": True, "text": "TRESC PLIKU " * 100, "name": Path(path).name, "kind": "txt",
                "chars": 1200, "truncated": False, "why": ""}

    def describe(_doc):
        return "plik tekstowy"

    def understand(_doc, _cel, ask, progress=None, should_stop=None):
        got = ask("SYS", "PYTANIE O PLIK")
        return {"digest": "DIGEST:" + got, "pominiete": 0, "czesci": 1, "streszczone": 1, "doslownie": False}

    def plan(_text, message):
        p = namysl_mod.default_plan(message)
        p.pliki = [original, f"{Path(original).stem}-2{Path(original).suffix}"]
        return p

    def resolve_counted(ref, chat_id, roots):
        resolve_calls.append(str(ref))
        return None, "nie powinno być wołane"

    def make_ctx(events):
        def local_chat(_system, _history, _message):
            return "ODPOWIEDZ LOKALNA"

        return namysl_mod.Context(
            vault=type("V", (), {"notes": {}})(), message="hej, przeczytaj to", history_local=[], history_cloud=[],
            files=[str(stored)], sys_local="SYS", sys_cloud="SYS", local_up=False, local_recheck=lambda: True,
            chat=chat, local_chat=local_chat, cloud_chat=lambda *_a, **_k: ("", ""),
            cloud_pool=lambda: [], research=None, search_notes=lambda _v, _q: [], research_web=None,
            wiki_lookup=None, market_quote=None, market_history=None, read_page=None,
            internet_allowed=lambda: (True, ""), sanitize=lambda text: text,
            violates_style=lambda _text: [],
            settings={"tryb": "zawsze", "material_do_sieci": False},
            progress=events.append,
        )

    try:
        sources_mod.UPLOAD_DIR = tmp
        analiza_mod.read_document, analiza_mod.describe, analiza_mod.understand = read_document, describe, understand
        analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks = 1, lambda _text: ["a"]
        namysl_mod.parse_plan = plan
        namysl_mod._resolve_file = resolve_counted
        events: list[dict] = []
        out = namysl_mod.run(make_ctx(events))
        labels = [str(e.get("label") or "") for e in events]
        if resolve_calls:
            problems.append(f"plan szukał pliku mimo załącznika: {resolve_calls}")
        if len(reads) != 1:
            problems.append(f"odczytów pliku: {len(reads)}")
        if sum(1 for label in labels if "Czytam plik" in label) != 1:
            problems.append(f"narracji „Czytam plik”: {[l for l in labels if 'Czytam plik' in l]}")
        if out is None:
            problems.append("Namysł nie zwrócił odpowiedzi")
    finally:
        (sources_mod.UPLOAD_DIR, analiza_mod.read_document, analiza_mod.describe,
         analiza_mod.understand, analiza_mod.VERBATIM_CHARS, analiza_mod.split_chunks,
         namysl_mod.parse_plan, namysl_mod._resolve_file) = originals
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "data-/kolizja znormalizowane, jeden odczyt"


def _check_dedup_1386() -> tuple[bool, str]:
    """1.38.6 #29: ta sama ścieżka w ctx.files (UI race) liczona raz."""
    import shutil
    import tempfile
    from pathlib import Path

    import main as main_mod

    problems: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="gregai-1386-"))
    a = tmp / "a.txt"
    b = tmp / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    try:
        got = main_mod._dedup_upload_paths([str(a), str(a), str(a).upper(), str(b)])
        if got != [str(a), str(b)]:
            problems.append(f"dedup: {got}")
        if main_mod._dedup_upload_paths([]) != []:
            problems.append("pusta lista nie jest pusta")
        if main_mod._dedup_upload_paths([str(a), "", None]) != [str(a)]:
            problems.append("puste/nie-tekstowe wpisy nie są odsiewane")
        src = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")
        if "files = _dedup_upload_paths(files)" not in src:
            problems.append("main.py nie woła deduplikacji po odzyskaniu załącznika")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return (not problems), "; ".join(problems) if problems else "duplikaty ctx.files usuwane po resolve().lower()"


def _check_namysl_once_1387() -> tuple[bool, str]:
    """1.38.7 #30: Namysł (i Zbieranie pliku) uruchamia się RAZ na wiadomość."""
    import juggler as juggler_mod
    import namysl as namysl_mod
    import netguard as netguard_mod
    import router as router_mod
    import standing as standing_mod

    problems: list[str] = []
    run_calls: list[str] = []
    original = (namysl_mod.run, namysl_mod.load_settings, router_mod._ollama_chat,
                router_mod.ollama_available, router_mod.STUDENT_MODEL,
                juggler_mod.providers_pool, juggler_mod.rozdzielnica, juggler_mod.is_risky,
                netguard_mod.internet_allowed, standing_mod.pop_pending_alerts)
    old_local = os.environ.get("KORYTO_LOKALNIE")
    old_koryto = os.environ.get("KORYTO")

    def fake_run(_ctx):
        run_calls.append("raz")
        return None

    try:
        os.environ["KORYTO"] = "darmowe,lokalnie"
        os.environ["KORYTO_LOKALNIE"] = "bez_internetu"
        namysl_mod.run = fake_run
        namysl_mod.load_settings = lambda: {"tryb": "zawsze", "material_do_sieci": False}
        router_mod._ollama_chat = lambda *_a, **_k: "Odpowiedź lokalna"
        router_mod.ollama_available = lambda: True
        router_mod.STUDENT_MODEL = ""
        juggler_mod.providers_pool = lambda etap=None: []
        juggler_mod.rozdzielnica = lambda _p: {"etapy": ["darmowe"], "model": None}
        juggler_mod.is_risky = lambda _m: False
        netguard_mod.internet_allowed = lambda: (True, "")
        standing_mod.pop_pending_alerts = lambda: []
        res = router_mod.route(type("V", (), {"notes": {}})(), "SYS", [], "hej, przeczytaj to",
                               files=["fake.txt"], nie_ucz=True, nie_zapisuj_sladu=True)
        if len(run_calls) != 1:
            problems.append(f"Namysł uruchomiony {len(run_calls)}× zamiast 1")
        if not (res.get("speech") or res.get("_speech_bez_alertu")):
            problems.append("brak odpowiedzi po nieudanym Namysłie")
    finally:
        (namysl_mod.run, namysl_mod.load_settings, router_mod._ollama_chat,
         router_mod.ollama_available, router_mod.STUDENT_MODEL,
         juggler_mod.providers_pool, juggler_mod.rozdzielnica, juggler_mod.is_risky,
         netguard_mod.internet_allowed, standing_mod.pop_pending_alerts) = original
        if old_local is None:
            os.environ.pop("KORYTO_LOKALNIE", None)
        else:
            os.environ["KORYTO_LOKALNIE"] = old_local
        if old_koryto is None:
            os.environ.pop("KORYTO", None)
        else:
            os.environ["KORYTO"] = old_koryto
    return (not problems), "; ".join(problems) if problems else "jeden przebieg Namysłu na wiadomość"


def _check_offline(case: dict) -> tuple[bool, str]:
    typ = case["typ"]
    if typ == "izolacja":
        return _check_isolation()
    if typ == "audyt_1329":
        return _check_audyt_1329()
    if typ == "audyt_1330":
        return _check_audyt_1330()
    if typ == "audyt_1331":
        return _check_audyt_1331()
    if typ == "audyt_1332":
        return _check_audyt_1332()
    if typ == "audyt_1333":
        return _check_audyt_1333()
    if typ == "audyt_1334":
        return _check_audyt_1334()
    if typ == "audyt_1351":
        return _check_audyt_1351()
    if typ == "lokalny_timeout":
        return _check_local_timeout()
    if typ == "lokalny_cache":
        return _check_local_cache()
    if typ == "lokalny_budzet":
        return _check_local_budget()
    if typ == "lokalny_styl":
        return _check_local_style()
    if typ == "lokalny_parametry":
        return _check_local_params()
    if typ == "lokalny_walidacja":
        return _check_local_validation()
    if typ == "lokalny_kolejka":
        return _check_local_queue()
    if typ == "lokalny_retry":
        return _check_local_retry()
    if typ == "lokalny_sesja":
        return _check_local_session()
    if typ == "lokalny_warmup":
        return _check_local_warmup()
    if typ == "spoleczne_1380":
        return _check_spoleczne_1380()
    if typ == "czas_1380":
        return _check_czas_1380()
    if typ == "plik_1380":
        return _check_plik_1380()
    if typ == "plik_upload_1381":
        return _check_plik_upload_1381()
    if typ == "namysl_413_1382":
        return _check_namysl_413_1382()
    if typ == "awaryjny_1382":
        return _check_awaryjny_1382()
    if typ == "duplikat_1383":
        return _check_duplikat_1383()
    if typ == "prompt_ctx_1383":
        return _check_prompt_ctx_1383()
    if typ == "notatki_1384":
        return _check_notatki_1384()
    if typ == "normalizacja_1385":
        return _check_normalizacja_1385()
    if typ == "dedup_1386":
        return _check_dedup_1386()
    if typ == "namysl_once_1387":
        return _check_namysl_once_1387()
    if typ == "devtools":
        return _check_devtools()
    if typ == "routing":
        import capabilities as cap_mod
        hit = cap_mod.find_keyword_match(case["wiadomosc"])
        got = hit[0] if hit else None
        return got == case["oczekiwane"], f"narzędzie: {got}"
    if typ == "komenda":
        import komendy as komendy_mod
        hit = komendy_mod.parse(case["wiadomosc"])
        got = hit[0] if hit else None
        return got == case["oczekiwane"], f"komenda: {got}"
    if typ == "bramka":
        import bramka as bramka_mod
        _text, found = bramka_mod.review(case["tekst"], internet=case.get("internet", True), self_model_text="(prawda)",
                                         pisanie=bool(case.get("pisanie")))
        if not case["oczekiwane"] and _text != case["tekst"]:
            return False, "tekst zmieniony, choć nie powinien"
        got = [f["kod"] for f in found]
        return got == case["oczekiwane"], f"znaleziska: {got}"
    if typ == "spoleczne":
        import namysl as namysl_mod
        got = namysl_mod.is_social(case["wiadomosc"])
        return got == case["oczekiwane"], f"podziękowanie/reakcja: {got}"
    if typ == "slonce":
        import pogoda as pogoda_mod
        st = pogoda_mod.sun_times(date.fromisoformat(case["data"]), pogoda_mod.DEFAULT_LAT, pogoda_mod.DEFAULT_LON)
        got = (st["dzien_min"] + st["noc_min"]) if st else None
        return got == case["oczekiwane"], f"dzień + noc = {got} min"
    if typ == "straz":
        import straz as straz_mod
        got = straz_mod.clean_assessment(case["tekst"])
        return got == case["oczekiwane"], f"ocena: {got!r}"
    if typ == "pretensja":
        import router as router_mod
        got = bool(router_mod.COMPLAINT_RE.search(case["wiadomosc"]) or router_mod.CORRECTION_RE.search(case["wiadomosc"]))
        return got == case["oczekiwane"], f"pretensja/korekta: {got}"
    if typ == "nauka":
        import learning as learning_mod
        got = learning_mod.is_reaction(case["wiadomosc"])
        return got == case["oczekiwane"], f"reakcja (nie do nauki): {got}"
    return False, f"nieznany typ {typ}"


# --- Oceniacze rozmowy (tryb na żywo) ------------------------------------------------

_PL_WORDS = re.compile(r"\b(?:jest|nie|się|to|że|na|w|z|do|jak|ale|dla|czy|mam|masz|już|tak)\b", re.IGNORECASE)


def grade_answer(text: str, grader: str, internet_ok: bool) -> tuple[bool, str]:
    import bramka as bramka_mod
    text = text or ""
    if grader == "nie_puste":
        return bool(text.strip()), "pusta odpowiedź"
    if grader == "po_polsku":
        words = len(re.findall(r"\w+", text)) or 1
        pl = len(_PL_WORDS.findall(text))
        en = bramka_mod._foreign_words(text)
        ok = pl / words > 0.06 and not en
        return ok, f"polskie słowa {pl}/{words}" + (f", obce: {', '.join(en)}" if en else "")
    if grader == "bez_cudzej_tozsamosci":
        m = bramka_mod._IDENTITY_RE.search(text)
        return not m, f"cudza tożsamość: {m.group(0) if m else ''}"
    if grader == "bez_falszywego_braku_internetu":
        m = bramka_mod._NO_INTERNET_RE.search(text)
        return not (m and internet_ok), f"twierdzi, że nie ma internetu: {m.group(0) if m else ''}"
    if grader == "pelne_zakonczenie":
        tail = text.rstrip()
        last = tail.splitlines()[-1] if tail else ""
        return bool(bramka_mod._END_OK_RE.search(last)), "urwane zakończenie"
    if grader == "bez_planu_namyslu":
        return not re.search(r"pytania\s+pomocnicze", text, re.IGNORECASE), "wyciek planu Namysłu"
    if grader.startswith("zawiera:"):
        need = grader.split(":", 1)[1]
        return need.lower() in text.lower(), f"brak „{need}”"
    if grader.startswith("krotko:"):
        n = int(grader.split(":", 1)[1])
        return len(text) <= n, f"{len(text)} znaków (limit {n})"
    return False, f"nieznany oceniacz {grader}"


def _run_live_case(case: dict, k: int, internet_ok: bool) -> dict:
    import main as main_mod
    import router as router_mod
    # Router/juggler policzyły swoje ścieżki przy imporcie (po prepare_isolation
    # nie było ich jeszcze w sys.modules): przepnij je teraz na katalog eval.
    if _ISOLATION.get("dir"):
        target = Path(_ISOLATION["dir"]) / "distill_pairs.jsonl"
        router_mod.DISTILL_PAIRS_PATH = target
        import juggler as juggler_mod
        juggler_mod.DISTILL_PAIRS_PATH = target
    vault = main_mod.get_vault()
    system = main_mod.get_system_prompt()
    attempts = []
    for i in range(k):
        t0 = time.monotonic()
        try:
            res = router_mod.route(vault, system, [], case["wiadomosc"], chat=f"ewaluacja-{case['id']}-{i}",
                                   nie_ucz=True, nie_zapisuj_sladu=True)
            text = str(res.get("speech") or "")
        except Exception as e:
            text = ""
            res = {"blad": f"{type(e).__name__}: {e}"}
        fails = []
        for g in case.get("oceniacze", []):
            ok, why = grade_answer(text, g, internet_ok)
            if not ok:
                fails.append(f"{g} ({why})")
        attempts.append({"ok": not fails, "bledy": fails, "s": round(time.monotonic() - t0, 1),
                         "poczatek": text[:160]})
    return {"pass@1": attempts[0]["ok"] if attempts else False,
            f"pass@{k}": any(a["ok"] for a in attempts),
            f"pass^{k}": bool(attempts) and all(a["ok"] for a in attempts),
            "proby": attempts}


# --- Przebieg i raport -------------------------------------------------------------

def _previous(mode: str) -> dict | None:
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("tryb") == mode:
            return rec
    return None


def _save(rec: dict) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run(live: bool = False, k: int = 3, save: bool = True, cases: list[dict] | None = None) -> dict:
    cases = cases if cases is not None else load_cases()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "?"
    results: dict[str, dict] = {}
    if not live:
        for c in cases:
            if c["typ"] not in OFFLINE_TYPES:
                continue
            try:
                ok, detail = _check_offline(c)
            except Exception as e:
                ok, detail = False, f"wyjątek {type(e).__name__}: {e}"
            results[c["id"]] = {"ok": ok, "szczegoly": detail, "typ": c["typ"], "zrodlo": c.get("zrodlo", "")}
        mode = "szybki"
    else:
        # 1.32.28: wszystko, co eval --zywo mogłoby dopisać do produkcji,
        # idzie do katalogu tymczasowego; router dostaje też flagi nie_ucz
        # i nie_zapisuj_sladu (patrz _run_live_case).
        before_hashes = _production_hashes()
        prepare_isolation()
        import netguard as netguard_mod
        internet_ok = netguard_mod.internet_allowed()[0]
        for c in cases:
            if c["typ"] != "rozmowa":
                continue
            r = _run_live_case(c, k, internet_ok)
            r.update(ok=r[f"pass@{k}"], typ="rozmowa", zrodlo=c.get("zrodlo", ""))
            results[c["id"]] = r
        after_hashes = _production_hashes()
        changed = [Path(k).relative_to(ROOT).as_posix() for k, v in after_hashes.items() if before_hashes.get(k) != v]
        mode = f"zywo-k{k}"
        isolation = {"ok": not changed, "zmienione": changed}
    total = len(results)
    passed = sum(1 for r in results.values() if r["ok"])
    summary = {"przypadki": total, "zaliczone": passed}
    if live:
        summary["izolacja"] = isolation
    if live and total:
        summary["pass@1"] = round(100 * sum(1 for r in results.values() if r["pass@1"]) / total)
        summary[f"pass@{k}"] = round(100 * sum(1 for r in results.values() if r[f"pass@{k}"]) / total)
        summary[f"pass^{k}"] = round(100 * sum(1 for r in results.values() if r[f"pass^{k}"]) / total)
    prev = _previous(mode)
    regress, fixed = [], []
    if prev:
        before = prev.get("wyniki") or {}
        for cid, r in results.items():
            if cid in before and before[cid] and not r["ok"]:
                regress.append(cid)
            if cid in before and not before[cid] and r["ok"]:
                fixed.append(cid)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "wersja": version, "tryb": mode,
           "wyniki": {cid: r["ok"] for cid, r in results.items()}, "podsumowanie": summary}
    if save:
        _save(rec)
    return {"tryb": mode, "wersja": version, "wyniki": results, "podsumowanie": summary,
            "regresje": regress, "naprawione": fixed, "poprzedni": (prev or {}).get("ts")}


def report_text(rep: dict) -> str:
    s = rep["podsumowanie"]
    lines = [f"EWALUACJA GREGAI {rep['wersja']} - tryb {rep['tryb']}",
             f"Zaliczone: {s['zaliczone']}/{s['przypadki']}"]
    for key in [k for k in s if k.startswith("pass")]:
        lines.append(f"{key}: {s[key]}%")
    if "izolacja" in s:
        iso = s["izolacja"]
        lines.append("Izolacja produkcyjnych plików: " + ("OK" if iso.get("ok") else
                     "ZMIENIONE: " + ", ".join(iso.get("zmienione") or [])))
    if rep.get("poprzedni"):
        lines.append(f"Porównanie z przebiegiem z {rep['poprzedni']}: regresje {len(rep['regresje'])}, naprawione {len(rep['naprawione'])}")
    for cid in rep.get("regresje", []):
        lines.append(f"  REGRESJA: {cid}")
    for cid in rep.get("naprawione", []):
        lines.append(f"  NAPRAWIONE: {cid}")
    lines.append("")
    for cid, r in rep["wyniki"].items():
        mark = "OK  " if r["ok"] else "BŁĄD"
        detail = r.get("szczegoly", "")
        if "proby" in r:
            bad = [b for a in r["proby"] for b in a["bledy"]]
            detail = ("; ".join(dict.fromkeys(bad))[:200]) if bad else f"{len(r['proby'])} prób dobrych"
        lines.append(f"[{mark}] {cid}: {detail}")
    verdict = "GOTOWE" if s["zaliczone"] == s["przypadki"] else "DO POPRAWY"
    lines.append("")
    lines.append(f"Werdykt: {verdict}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    live = "--zywo" in argv or "--żywo" in argv
    k = 3
    if "--k" in argv:
        try:
            k = max(1, min(10, int(argv[argv.index("--k") + 1])))
        except (ValueError, IndexError):
            print("gregai eval: --k wymaga liczby 1-10")
            return 2
    case_id = None
    if "--id" in argv:
        try:
            case_id = argv[argv.index("--id") + 1]
        except IndexError:
            print("gregai eval: --id wymaga identyfikatora przypadku")
            return 2
    cases = load_cases()
    if case_id is not None:
        cases = [c for c in cases if c["id"] == case_id]
        expected_types = ("rozmowa",) if live else OFFLINE_TYPES
        if not cases or cases[0]["typ"] not in expected_types:
            mode = "na żywo" if live else "szybki"
            print(f"gregai eval: brak przypadku '{case_id}' dla trybu {mode}")
            return 2
    if live:
        print(f"Tryb na żywo: każdy przypadek rozmowy {k} razy przez prawdziwe modele (kosztuje tokeny w budżecie Koryta)...\n")
    # Pojedynczy przypadek nie zastępuje pełnego przebiegu w historii regresji.
    save = "--bez-zapisu" not in argv and case_id is None
    try:
        rep = run(live=live, k=k, save=save, cases=cases)
    finally:
        cleanup_isolation()
    print(report_text(rep))
    return 0 if rep["podsumowanie"]["zaliczone"] == rep["podsumowanie"]["przypadki"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(ROOT)
    sys.exit(main(sys.argv[1:]))
