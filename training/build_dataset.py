"""
training/build_dataset.py

Składa zbiór treningowy dla WYTRENOWANEGO routera (patrz
agent/router.py: ROUTER_MODEL i training/README.md) z WŁASNYCH danych
GREGAI. Czysty stdlib, zero zależności: można go odpalić w każdej chwili,
także bez środowiska treningowego, żeby zobaczyć, czego GREGAI by się
teraz nauczył.

Cztery źródła, od najbardziej "własnego" do najbardziej "ręcznego":

1. data/decision_log.json: PRAWDZIWE wiadomości użytkownika i to, które
   narzędzie faktycznie odpowiedziało (szybka_sciezka, wyuczona_sciezka,
   ollama_narzedzie). Wiadomości, które skończyły jako zwykła rozmowa, NIE
   dają etykiety BRAK: bez routera i bez BIG_MODEL_ROUTING trafiają tam
   także prośby, których żaden wzorzec nie złapał, a nikt nie podjął decyzji
   "to rozmowa" (BRAK pochodzi z seed_examples.json). Pomijane: decyzje podjęte przez SAM wytrenowany router
   (extra.router_model) - model nie może uczyć się z własnych odpowiedzi,
   bo utrwalałby własne błędy; odpowiedzi na dopytania
   (doprecyzowanie_rozwiazane: "notatki", "2" nie znaczą nic bez
   kontekstu); korekty ("nie o to"); wpisy, które DZIŚ zderzają się z
   wzorcem ręcznym/wyuczonym (sprzeczność = wtedy model/wzorzec się
   pomylił, nie uczymy się z tego).
2. data/learned_routes.json: frazy, które GREGAI sam zapamiętał
   (learning.py) - każda ma `example` (oryginalną wiadomość) i `tool`.
3. agent/capabilities.py: frazy-przykłady w cudzysłowach z promptów
   narzędzi ("plan na dziś?", "co to jest X" itd.). Wyciągane
   automatycznie: DODANIE narzędzia z przykładami w capabilities.py =
   automatycznie nowe przykłady treningowe, bez dotykania tego pliku.
   Frazy, które check_ambiguity() uznaje za dwuznaczne, są pomijane
   (produkcja i tak rozstrzyga je deterministycznie PRZED modelem).
4. training/seed_examples.json: ręczny rozruch (parafrazy + zwykła
   rozmowa) i osobny zestaw kontrolny `golden`, który NIGDY nie trafia do
   treningu - na nim training/eval_router.py mierzy, czy model
   generalizuje, nie tylko pamięta.

Format etykiety = DOKŁADNIE to, co parsuje router.py (parse_routing_reply):
"TOOL: nazwa | argument", "TOOL: nazwa" (narzędzia ignorujące argument,
router.py podstawi wtedy całą wiadomość) albo "BRAK". Prompt systemowy =
router_mod.router_system_prompt(), ta sama funkcja co w produkcji.

Wyjście (data/training/):
  router_train.jsonl  - trening (z augmentacją)
  router_eval.jsonl   - 15% odłożone z tych samych źródeł (bez augmentacji)
  router_golden.jsonl - zestaw kontrolny z seed_examples.json
  dataset_stats.json  - ile skąd, ile na narzędzie, konflikty

Każda linia: {"system": ..., "user": ..., "assistant": ..., "source": ...}
"""

from __future__ import annotations

import difflib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from env_loader import load_env  # noqa: E402

load_env()

import fsutil  # noqa: E402
import trace as trace_mod  # noqa: E402
import capabilities as cap_mod  # noqa: E402
import learning as learning_mod  # noqa: E402
import router as router_mod  # noqa: E402
import sysop as sysop_mod  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent / "seed_examples.json"
OUT_DIR = ROOT / "data" / "training"
DECISION_LOG = ROOT / "data" / "decision_log.json"
LEARNED_ROUTES = ROOT / "data" / "learned_routes.json"

EVAL_FRACTION = 0.15
RANDOM_SEED = 20261007

# Narzędzia, których wywołanie IGNORUJE argument (patrz capabilities.py:
# _call_graph_overview itd.): etykieta to samo "TOOL: nazwa", krótsza do
# wygenerowania i bez ryzyka, że model zmyśli argument, którego nikt nie
# czyta. plan_day dostaje w produkcji całą wiadomość (arg or message), co
# jest dokładnie tym, co robi router.py przy braku argumentu.
NO_ARG_TOOLS = {"graph_overview", "self_status", "brief_me", "network_status", "plan_day"}

# Etapy śladu decyzji, które niosą WIARYGODNĄ etykietę narzędzia.
TOOL_STAGES = {"szybka_sciezka", "wyuczona_sciezka", "ollama_narzedzie"}
# Rozmowa (żaden wzorzec nie złapał) kończy się u dużego modelu, ucznia albo w chmurze. To NIE jest
# etykieta: nikt nie zdecydował, że to rozmowa, wiadomość po prostu nie została rozpoznana (może być
# prośbą o narzędzie, której nie znamy). Licznik w raporcie, bez przykładów.
BRAK_STAGES = {"ollama_rozmowa", "uczen_rozmowa", "chmura_rozmowa", "zongler_rozmowa", "zongler_senior_juniorzy", "namysl"}

# Wypełniacze dla fraz-szablonów z capabilities.py ("co to jest X",
# "kim był X", "zapamiętaj: ..."). Osoby osobno od pojęć, żeby nie
# produkować "kim był fotosynteza".
PLACEHOLDER_THINGS = ["fotosynteza", "blockchain", "czarna dziura", "inflacja"]
PLACEHOLDER_PERSONS = ["Napoleon", "Mikołaj Kopernik", "Albert Einstein"]  # tylko mężczyźni: szablon to "kim był X"
PLACEHOLDER_FACTS = ["mleko się kończy", "spotkanie jest w piątek o 10", "faktura ma termin 15-go"]


# --- Wyprowadzanie argumentu z wiadomości (ta sama logika dla każdego źródła) ---

_WIKI_PREFIX = re.compile(
    r"^(?:(?:sprawd[zź]|poszukaj|znajd[zź]|zobacz)\s+(?:mi\s+)?(?:na|w)\s+(?:wikipedii|wiki|encyklopedii)\s*,?\s*)?"
    r"(?:(?:co|czym)\s+(?:to\s+)?(?:jest|s[aą])\s+|kim\s+(?:by[lł]a?|jest)\s+|kto\s+to\s+(?:by[lł]a?|jest)\s+"
    r"|wyja[sś]nij(?:\s+mi)?(?:\s+prosz[eę])?\s*,?\s*(?:(?:co|czym)\s+(?:to\s+)?(?:jest\s+)?|poj[eę]cie\s+)?"
    r"|opowiedz(?:\s+mi)?\s+o\s+)?",
    re.IGNORECASE,
)
_RESEARCH_PREFIX = re.compile(
    r"^(?:sprawd[zź]|wyszukaj|poszukaj|znajd[zź]|zobacz|wyguglaj)\s+(?:mi\s+)?"
    r"(?:(?:w\s+|na\s+)?(?:internecie|necie|sieci|google|online)\s*,?\s*)?",
    re.IGNORECASE,
)
_RESEARCH_INFIX = re.compile(r"\s+(?:w\s+)?(?:internecie|necie|sieci|google|online)\b", re.IGNORECASE)
_REMEMBER_PREFIX = re.compile(
    r"^(?:zapami[eę]taj|zapisz\s+sobie|nie\s+zapomnij|zanotuj(?:\s+sobie)?|zapisz)"
    r"(?:\s+prosz[eę])?\s*[:,]?\s*(?:[zż]e\s+)?",
    re.IGNORECASE,
)


def _tidy(text: str) -> str:
    return text.strip().strip(" ,.;:!?-").strip()


def derive_arg(tool: str, message: str) -> str | None:
    """Argument dla etykiety, gdy przykład go nie podaje wprost."""
    if tool in NO_ARG_TOOLS:
        return None
    if tool == "wiki_lookup":
        return _tidy(_WIKI_PREFIX.sub("", message, count=1)) or _tidy(message)
    if tool == "research_web":
        text = _RESEARCH_PREFIX.sub("", message, count=1)
        text = _RESEARCH_INFIX.sub("", text, count=1)
        return _tidy(text) or _tidy(message)
    if tool == "remember":
        return _tidy(_REMEMBER_PREFIX.sub("", message, count=1)) or None
    if tool == "search_brain":
        # Pełna wiadomość = dokładnie to, co robi router.py bez argumentu.
        return None
    return None


def make_label(tool: str, arg: str | None) -> str:
    if tool == "BRAK":
        return "BRAK"
    # Etykieta to jedna linia: nowa linia w argumencie rozbiłaby format TOOL: x | arg.
    arg = " ".join(arg.split()) if arg else arg
    if arg:
        return f"TOOL: {tool} | {arg}"
    return f"TOOL: {tool}"


# --- Źródła ------------------------------------------------------------------

def _norm(message: str) -> str:
    return re.sub(r"\s+", " ", message.strip().lower()).strip(" ?.!,")


# Narzędzia z seedu, których bieżący katalog nie zna (np. sys_* bez SYSOP_ENABLED=1).
# Wynik: router uczony na mniejszym zestawie, więc main() ostrzega GŁOŚNO.
# sys_shell przy SYSOP_SHELL=0 to stan zamierzony (wersja stabilna), nie ostrzeżenie.
DROPPED_TOOLS: dict[str, int] = defaultdict(int)


def _drop_unknown_tool(kind: str, tool: str, count: int) -> None:
    """Zapisuje pominięte narzędzie; głośno tylko wtedy, gdy to nie jest zamierzone."""
    DROPPED_TOOLS[tool] += count
    if tool == "sys_shell" and not sysop_mod.shell_enabled():
        return
    print(f"  [{kind}] pomijam nieznane narzędzie {tool!r}")


def from_seeds(seed: dict) -> list[dict]:
    out = []
    for tool, items in seed.get("tools", {}).items():
        if tool not in router_mod.TOOL_NAMES:
            _drop_unknown_tool("seed", tool, len(items))
            continue
        for item in items:
            msg, arg = (item, None) if isinstance(item, str) else (item["msg"], item.get("arg"))
            out.append({"user": msg, "tool": tool, "arg": arg if arg is not None else derive_arg(tool, msg), "source": "seed"})
    for msg in seed.get("brak", []):
        out.append({"user": msg, "tool": "BRAK", "arg": None, "source": "seed"})
    return out


_QUOTED = re.compile(r"\"([^\"]{4,120})\"")
# Cudzysłów w prompcie narzędzia to nie zawsze przykład wypowiedzi
# użytkownika: bywa nazwą panelu ("Top huby") albo opisem pojęcia ("co
# się teraz dzieje" w wiki_lookup opisuje, co zostaje przy research_web).
# Wypowiedź użytkownika poznajemy po tym, że kończy się pytajnikiem, ma
# miejsce na wypełnienie (X / ...) albo zaczyna się od polecenia.
_IMPERATIVES = (
    "zrób", "sprawdź", "zapamiętaj", "zapisz", "nie zapomnij", "wyjaśnij",
    "opowiedz", "daj", "pokaż", "status", "plan", "ile", "jaki", "jaka",
    "jakie", "co ", "czy ", "kim ", "czym ",
)


def _looks_like_user_phrase(phrase: str) -> bool:
    low = phrase.lower()
    if len(phrase.split()) < 2:
        return False  # "neuronki", "Filtry": nazwy, nie pytania
    if phrase.endswith("?") or re.search(r"\bX\b", phrase) or "..." in phrase:
        return True
    return low.startswith(_IMPERATIVES)


def from_capabilities() -> list[dict]:
    """Frazy-przykłady w cudzysłowach z promptów narzędzi. Zostają tylko
    te, które wyglądają jak wypowiedź użytkownika (_looks_like_user_phrase)
    i NIE są znaną dwuznacznością. Szablony z X / "..." dostają
    wypełniacze, "danych/internetu" -> pierwszy wariant."""
    out = []
    skipped_negative = []
    for key, cap in cap_mod.CAPABILITIES.items():
        if cap.call is None or key not in router_mod.TOOL_NAMES:
            continue
        prompt = cap.prompt or ""
        prev_end = 0
        for m in _QUOTED.finditer(prompt):
            # Tekst MIĘDZY poprzednim cytatem a tym (nie ostatnie N znaków:
            # poprzedni cytat sam może zawierać "nie", jak "czego nie
            # umiałeś wcześniej?", i nie o to "nie" chodzi).
            gap = prompt[prev_end:m.start()].lower()
            prev_end = m.end()
            phrase = re.sub(r"\b(\w+)/(\w+)\b", r"\1", m.group(1).strip())
            if not _looks_like_user_phrase(phrase):
                continue
            if cap_mod.check_ambiguity(phrase) is not None:
                continue
            # Przykład NEGATYWNY ("..., nie aktualności, ceny czy "co się
            # teraz dzieje" (to zostaje przy research_web)"): w prompcie
            # narzędzia A cytowana jest fraza, która należy do narzędzia
            # B. Poznajemy to po "nie" w tekście tuż przed cytatem, bez
            # "np."/"typu"/"dla", które zapowiadają prawdziwe przykłady.
            if re.search(r"\bnie\b", gap[-60:]) and not re.search(r"\bnp\.|\btypu\b|\bdla\b", gap[-60:]):
                skipped_negative.append((key, phrase))
                continue
            variants: list[str]
            if re.search(r"\bX\b", phrase):
                topics = PLACEHOLDER_PERSONS if phrase.lower().startswith(("kim", "kto")) else PLACEHOLDER_THINGS
                variants = [re.sub(r"\bX\b", topic, phrase) for topic in topics]
            elif "..." in phrase:
                variants = [phrase.replace("...", fact) for fact in PLACEHOLDER_FACTS]
            else:
                variants = [phrase]
            for v in variants:
                v = v[0].upper() + v[1:] if v else v
                out.append({"user": v, "tool": key, "arg": derive_arg(key, v), "source": "capabilities"})
    for key, phrase in skipped_negative:
        print(f"  [capabilities] pominięto przykład negatywny w prompcie {key}: {phrase!r}")
    return out


def from_learned_routes() -> list[dict]:
    if not LEARNED_ROUTES.exists():
        return []
    try:
        routes = json.loads(LEARNED_ROUTES.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for r in routes:
        # Wpisy zapisane przed maskowaniem mogą zawierać sekret: maskujemy też tutaj.
        msg, tool = trace_mod.mask((r.get("example") or "").strip()), r.get("tool")
        if not msg or tool not in router_mod.TOOL_NAMES:
            continue
        if r.get("by") == "router":
            continue  # decyzja wytrenowanego routera: nie uczymy go jego własnych odpowiedzi
        # 1.32.11 (audyt tura 15): decyzja darmowej puli bez ani jednego potwierdzonego trafienia
        # nie jest etykietą (pętla dryfu: zły wzorzec -> zła etykieta -> zły router).
        if str(r.get("by") or "").startswith("koryto:") and r.get("by") != "koryto:anthropic" and not r.get("hits"):
            continue
        match = learning_mod.peek_learned_match(msg)
        # derive_arg przed argumentem ze wzorca: wzorzec wycina tylko
        # słowo-wyzwalacz ("wyszukaj" -> "w internecie najlepsze ..."),
        # derive_arg czyści całą frazę wprowadzającą. Spójnie dla
        # wszystkich źródeł, żeby model uczył się JEDNEJ konwencji.
        arg = None if tool in NO_ARG_TOOLS else (derive_arg(tool, msg) or (match[1] if match and match[0] == tool else None))
        out.append({"user": msg, "tool": tool, "arg": arg, "source": "learned_routes"})
    return out


def from_decision_log() -> tuple[list[dict], dict]:
    skipped = Counter()
    if not DECISION_LOG.exists():
        return [], dict(skipped)
    try:
        entries = json.loads(DECISION_LOG.read_text(encoding="utf-8"))
    except Exception:
        return [], dict(skipped)
    out = []
    for e in entries:
        msg = (e.get("message") or "").strip()
        stage, tool = e.get("stage"), e.get("tool")
        extra = e.get("extra") or {}
        if not msg:
            continue
        router_model = str(extra.get("router_model") or "")
        # 1.18.0: decyzja routera SIECIOWEGO koryta ("koryto:anthropic" itd.,
        # pełne opisy narzędzi, mocny model) to dobra etykieta nauczyciela dla
        # małego routera - ale tylko gdy patrzył na SAMĄ wiadomość. Z kontekstem
        # poprzednich wiadomości (extra.routing_kontekst) etykieta nie wynika z
        # samego tekstu, którego uczy się router - pomijamy. Decyzje
        # wytrenowanego routera jak dotąd: nie uczymy go na jego własnych.
        if router_model and not (router_model.startswith("koryto:") and not extra.get("routing_kontekst")):
            skipped["decyzja_routera" if not router_model.startswith("koryto:") else "koryto_z_kontekstem"] += 1
            continue
        if extra.get("skorygowane"):
            skipped["poprawiona_przez_uzytkownika"] += 1
            continue
        if router_mod.CORRECTION_RE.search(msg):
            skipped["korekta"] += 1
            continue
        if stage in TOOL_STAGES and tool in router_mod.TOOL_NAMES:
            if stage == "wyuczona_sciezka":
                learned = learning_mod.find_learned_record(msg)
                # by="router" = wzorzec z decyzji wytrenowanego routera (pomijamy, jak
                # wyżej). Wzorców z kontekstu poprzednich wiadomości learning w ogóle
                # nie zapisuje (learn_from_resolution, kontekst=True).
                if learned and learned.get("by") == "router":
                    skipped["wyuczone_z_odpowiedzi_routera"] += 1  # to samo co extra.router_model, dalej w łańcuchu
                    continue
            match = cap_mod.find_keyword_match(msg) or learning_mod.peek_learned_match(msg)
            if match and match[0] != tool:
                skipped["sprzeczny_ze_wzorcem"] += 1
                continue
            arg = None if tool in NO_ARG_TOOLS else (derive_arg(tool, msg) or (match[1] if match else None))
            out.append({"user": msg, "tool": tool, "arg": arg, "source": "decision_log"})
        elif stage in BRAK_STAGES:
            skipped["rozmowa_bez_decyzji"] += 1
        else:
            skipped[f"etap_{stage}"] += 1
    return out, dict(skipped)


# --- Scalanie, konflikty, augmentacja, podział -------------------------------

def dedupe(examples: list[dict]) -> tuple[list[dict], list[dict]]:
    """Jedna wiadomość = jedna etykieta. Ta sama wiadomość z DWIEMA
    różnymi etykietami to konflikt: wyrzucamy obie (uczenie modelu
    sprzeczności to najgorsze, co można zrobić) i raportujemy."""
    by_key: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        by_key[_norm(ex["user"])].append(ex)
    kept, conflicts = [], []
    for key, group in by_key.items():
        tools = {g["tool"] for g in group}
        if len(tools) > 1:
            conflicts.append({"message": group[0]["user"], "labels": sorted(tools), "sources": sorted({g["source"] for g in group})})
            continue
        # Preferuj źródło "najbardziej własne" przy duplikatach.
        order = {"decision_log": 0, "learned_routes": 1, "capabilities": 2, "seed": 3}
        kept.append(min(group, key=lambda g: order.get(g["source"], 9)))
    return kept, conflicts


NEAR_DUPLICATE = 0.9


def _near(a: str, b: str) -> bool:
    """Prawie to samo zdanie (po normalizacji). Same szybkie górne ograniczenia
    przed pełnym ratio(), bo porównań jest kilkadziesiąt tysięcy."""
    if a == b:
        return True
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sm.real_quick_ratio() >= NEAR_DUPLICATE and sm.quick_ratio() >= NEAR_DUPLICATE and sm.ratio() >= NEAR_DUPLICATE


def drop_near_duplicates(candidates: list[dict], references: list[str]) -> tuple[list[dict], int]:
    """Przykłady z `candidates` prawie identyczne z którymkolwiek tekstem z
    `references` (golden albo eval) wypadają. Samo usuwanie DOKŁADNYCH powtórzeń
    nie wystarcza: "zapisz sobie, że spotkanie jest w piątek" w eval i "...w piątek
    o 10" w treningu to ta sama wypowiedź, a ocena by się zawyżała."""
    refs = [_norm(r) for r in references]
    keep, dropped = [], 0
    for ex in candidates:
        n = _norm(ex["user"])
        if any(_near(n, r) for r in refs):
            dropped += 1
        else:
            keep.append(ex)
    return keep, dropped


def augment(ex: dict, rng: random.Random) -> list[dict]:
    """Lekkie warianty TEJ SAMEJ wiadomości: wielkość pierwszej litery,
    znak na końcu, grzeczny przedrostek. Celowo mało (max 3 na przykład):
    chodzi o odporność na drobiazgi formy, nie o sztuczne pompowanie
    liczby przykładów."""
    msg = ex["user"]
    variants = {msg}
    if msg and msg[0].isupper():
        variants.add(msg[0].lower() + msg[1:])
    stripped = msg.rstrip("?.!")
    if stripped != msg:
        variants.add(stripped)
    elif not msg.endswith("?") and rng.random() < 0.3 and ex["tool"] != "remember":
        variants.add(msg + "?")
    if rng.random() < 0.25 and ex["tool"] != "remember":
        prefix = rng.choice(["Hej, ", "Proszę, ", "GREGAI, ", "Słuchaj, "])
        variants.add(prefix + msg[0].lower() + msg[1:])
    out = []
    for v in sorted(variants):
        arg = ex["arg"]
        if arg and arg not in v and ex["tool"] != "search_brain":
            arg = derive_arg(ex["tool"], v) or ex["arg"]
        out.append({**ex, "user": v, "arg": arg})
    return out


def to_record(ex: dict, system: str) -> dict:
    return {
        "system": system,
        "user": ex["user"],
        "assistant": make_label(ex["tool"], ex["arg"]),
        "source": ex["source"],
    }


def split_eval(examples: list[dict], rng: random.Random) -> tuple[list[dict], list[dict]]:
    by_tool: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        by_tool[ex["tool"]].append(ex)
    train, evals = [], []
    for tool, group in by_tool.items():
        rng.shuffle(group)
        n_eval = max(1, round(len(group) * EVAL_FRACTION)) if len(group) >= 4 else 0
        evals.extend(group[:n_eval])
        train.extend(group[n_eval:])
    return train, evals


def write_jsonl(path: Path, records: list[dict]) -> None:
    fsutil.atomic_write_text(path, "".join(fsutil.json_line(r) + "\n" for r in records), mode=fsutil.PRIVATE_MODE)


def main() -> int:
    rng = random.Random(RANDOM_SEED)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    system = router_mod.router_system_prompt()

    sources = {
        "decision_log": None,
        "learned_routes": from_learned_routes(),
        "capabilities": from_capabilities(),
        "seed": from_seeds(seed),
    }
    sources["decision_log"], log_skipped = from_decision_log()

    # Zestaw kontrolny (bramka jakości) powstaje PRZED podziałem i nigdy nie trafia do
    # treningu ani do eval: te same frazy z decision_log/learned_routes są z niego usuwane.
    golden = []
    for tool, items in seed.get("golden", {}).get("tools", {}).items():
        if tool not in router_mod.TOOL_NAMES:
            _drop_unknown_tool("golden", tool, len(items))
            continue
        for item in items:
            msg, arg = (item, None) if isinstance(item, str) else (item["msg"], item.get("arg"))
            golden.append(to_record({"user": msg, "tool": tool, "arg": arg if arg is not None else derive_arg(tool, msg), "source": "golden"}, system))
    for msg in seed.get("golden", {}).get("brak", []):
        golden.append(to_record({"user": msg, "tool": "BRAK", "arg": None, "source": "golden"}, system))
    golden_users = {_norm(rec["user"]) for rec in golden}

    all_examples = [ex for group in sources.values() for ex in group]
    leaked = [ex for ex in all_examples if _norm(ex["user"]) in golden_users]
    if leaked:
        print(f"  [golden] usunięto z treningu {len(leaked)} przykładów powtarzających zestaw kontrolny")
    all_examples = [ex for ex in all_examples if _norm(ex["user"]) not in golden_users]
    kept, conflicts = dedupe(all_examples)
    # Prawie-duplikaty golden i eval odpadają z treningu (nie z golden/eval).
    kept, near_golden = drop_near_duplicates(kept, [rec["user"] for rec in golden])
    train_raw, eval_raw = split_eval(kept, rng)
    train_raw, near_eval = drop_near_duplicates(train_raw, [ex["user"] for ex in eval_raw])

    train = []
    for ex in train_raw:
        train.extend(augment(ex, rng))
    rng.shuffle(train)
    train_records = [to_record(ex, system) for ex in train]
    eval_records = [to_record(ex, system) for ex in eval_raw]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "router_train.jsonl", train_records)
    write_jsonl(OUT_DIR / "router_eval.jsonl", eval_records)
    write_jsonl(OUT_DIR / "router_golden.jsonl", golden)

    stats = {
        "system_prompt": system,
        "tools": sorted(router_mod.TOOL_NAMES),
        "per_source_raw": {k: len(v) for k, v in sources.items()},
        "decision_log_skipped": log_skipped,
        "conflicts": conflicts,
        "near_duplicates_dropped": {"golden": near_golden, "eval": near_eval},
        "dropped_tools": dict(DROPPED_TOOLS),
        "unique_examples": len(kept),
        "train_after_augmentation": len(train_records),
        "eval": len(eval_records),
        "golden": len(golden),
        "per_label_train": dict(Counter(r["assistant"].split(" | ")[0] for r in train_records)),
        "per_label_eval": dict(Counter(r["assistant"].split(" | ")[0] for r in eval_records)),
    }
    fsutil.atomic_write_text(OUT_DIR / "dataset_stats.json", json.dumps(stats, ensure_ascii=False, indent=2), mode=fsutil.PRIVATE_MODE)

    print(f"Prompt systemowy routera ({len(system)} znaków): {system}")
    print("Źródła (surowo):", stats["per_source_raw"])
    if log_skipped:
        print("Pominięte z decision_log:", log_skipped)
    if conflicts:
        print(f"KONFLIKTY etykiet (wyrzucone, {len(conflicts)}):")
        for c in conflicts:
            print(f"  - {c['message']!r}: {c['labels']} z {c['sources']}")
    if near_golden or near_eval:
        print(f"Prawie-duplikaty usunięte z treningu: {near_golden} względem golden, {near_eval} względem eval")
    unexpected = {t: n for t, n in DROPPED_TOOLS.items() if not (t == "sys_shell" and not sysop_mod.shell_enabled())}
    if unexpected:
        print("UWAGA: seed zawiera narzędzia, których bieżący katalog nie zna, więc router uczy się na MNIEJSZYM zestawie:")
        for t, n in sorted(unexpected.items()):
            print(f"  - {t}: pominięto {n} przykładów")
        print("  Sprawdź SYSOP_ENABLED=1 w .env (bez niego model nie nauczy się żadnego sys_* ani fs_*).")
    print(f"Unikalnych przykładów: {len(kept)} -> trening {len(train_records)} (po augmentacji), eval {len(eval_records)}, golden {len(golden)}")
    print("Na etykietę (trening):")
    for label, n in sorted(stats["per_label_train"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {label}")
    print(f"Zapisano do {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
