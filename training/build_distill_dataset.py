"""
training/build_distill_dataset.py

Zbiór do DESTYLACJI osobowości GREGAI: pary "pytanie -> wzorcowa odpowiedź"
dla ucznia, czyli małego modelu, który ma prowadzić zwykłą rozmowę (krok
2 routingu) w charakterze GREGAI bez czytania ponad 10 000-znakowego prompt.md
przy każdej wiadomości. Czysty stdlib.

Trzy źródła:
1. training/distill_seed.jsonl: ręczny rozruch (napisany przez Claude'a
   w personie GREGAI, patrz agent/prompt.md): powitania, pytania o samego
   GREGAI, decyzje w domenach użytkownika, strategia, wsparcie, zadania
   językowe, wiedza ogólna, granice (odmowy), wiadomości niejasne, Trzy
   siły, literówki. Format: {"category", "user", "assistant"}.
1b. training/teacher/*.jsonl: ZBIÓR NAUCZYCIELA (decyzja użytkownika z
   2026-10-08: "w tym tygodniu Ty go trenuj"): wiedza Claude'a spisana w
   personie GREGAI, po jednym pliku na domenę (tożsamość i działanie
   GREGAI, Linux/Ubuntu Server, sieć domowa, programowanie, AI/LLM,
   bezpieczeństwo, wiedza ogólna, matematyka, biznes/strategia, język,
   granice, wiadomości niejasne, dialogi). To wiedza CLAUDE'A (nie
   lokalnego dużego modelu!) spisana z góry do plików, więc w czasie treningu nie
   potrzebuje klucza API ani chmury. Ten sam format co seed, plus opcjonalne
   pole "history": [{"role": "user"|"assistant", "content": ...}, ...]
   (poprzednie tury rozmowy; uczeń w produkcji dostaje historię, więc
   musi umieć z niej korzystać: "A dlaczego?", "Zrób mi to").
2. data/training/distill_pairs.jsonl: pary ZEBRANE Z UŻYCIA przez
   router.py, z każdego etapu sieciowego koryta (KORYTO, 1.17.0): każda odpowiedź
   Z CHMURY (Claude, nie lokalny duży model) na prawdziwe pytanie użytkownika
   ląduje tu jako przykład do nauki. Format: {"ts", "user", "assistant", "model"}.
   Pary, które użytkownik skorygował ("nie o to") w następnej turze, są
   pomijane (patrz router.py: extra.cloud + CORRECTION_RE).

Filtr jakości (agent/persona.py: violates_style): odpowiedź z zakazaną
frazą, myślnikiem (U+2014), łącznikiem jako pauzą albo nazwą narzędzia NIE
trafia do zbioru - uczymy stylu, więc zły styl w danych to zły styl w
modelu. Odpowiedzi dłuższe niż MAX_ANSWER_CHARS też odpadają (GREGAI mówi
krótko; uczeń ma generować na CPU, każdy token kosztuje).

Prompt systemowy ucznia = persona.student_system_prompt(): JEDNA funkcja
dla treningu, oceny i produkcji (jak router.router_system_prompt()).

Wyjście (data/training/): student_train.jsonl, student_eval.jsonl
(10%, bez par z seed "powitanie", bo te są zbyt podobne do siebie, żeby
coś mierzyć), student_probe.jsonl (same pytania do ręcznego obejrzenia
odpowiedzi ucznia), student_stats.json.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from env_loader import load_env  # noqa: E402

load_env()

import fsutil  # noqa: E402
import persona  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent / "distill_seed.jsonl"
TEACHER_DIR = Path(__file__).resolve().parent / "teacher"
COLLECTED_PATH = ROOT / "data" / "training" / "distill_pairs.jsonl"
OUT_DIR = ROOT / "data" / "training"

EVAL_FRACTION = 0.10
MAX_ANSWER_CHARS = 900
# 1.32.11: tylko odpowiedzi tych dostawców uczą ucznia (darmowa pula bywa słaba albo zmanipulowana).
TRUSTED_PROVIDERS = frozenset({"anthropic"})
RANDOM_SEED = 20261007


def read_jsonl(path: Path, *, strict: bool = True) -> list[dict]:
    """Pliki ręczne (seed, teacher) czytane ściśle: błąd w nich to błąd
    autora, ma przerwać z numerem linii. Plik zbierany w trakcie pracy
    (distill_pairs.jsonl) może mieć urwaną ostatnią linię po awarii prądu:
    uszkodzone linie są pomijane z komunikatem."""
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            if strict:
                raise SystemExit(f"{path}: linia {n} nie jest poprawnym JSON-em ({e.msg})") from e
            print(f"  (pominięto uszkodzoną linię {n} w {path.name})")
            continue
        if isinstance(rec, dict):
            out.append(rec)
        elif strict:
            raise SystemExit(f"{path}: linia {n} nie jest obiektem JSON")
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).strip(" ?.!,")


def _clean_history(raw) -> list[dict]:
    """Historia -> lista tur {"role", "content"} w kolejności, bez pustych.
    Para z historią, w której ODPOWIEDŹ asystenta łamie styl, odpada w
    całości (patrz filtr niżej), bo uczeń uczy się też z poprzednich tur."""
    out = []
    for turn in raw or []:
        if not isinstance(turn, dict):
            continue
        role, content = turn.get("role"), turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content.strip()})
    return out


def _key(user: str, history: list[dict]) -> str:
    # Klucz deduplikacji: samo pytanie, a przy dialogu także historia, bo
    # "A dlaczego?" po różnych tematach to RÓŻNE przykłady.
    base = _norm(user)
    if history:
        base += " || " + " | ".join(_norm(t["content"])[:60] for t in history)
    return base


# 1.18.0: Claude jest od 1.17.0 głównym źródłem par i formatuje odpowiedzi
# Markdownem - nagłówki "###", linie "---" i nazwy wewnętrznych narzędzi w
# treści to rzeczy, których uczeń ma NIE naśladować (dymek ich nie chce, prompt
# zabrania nazw narzędzi). violates_style łapie już myślniki i formułki; tu
# dokładamy znaczniki i nazwy narzędzi, każde liczone osobno w raporcie.
_HEADING_RE = re.compile(r"^\s*#{1,6}\s", re.MULTILINE)
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.MULTILINE)
_TOOL_NAME_RE = re.compile(r"\b(?:sys_[a-z_]+|fs_(?:read|list|search)|search_brain|wiki_lookup|research_web|market_quote)\b")


def _markup_problems(text: str) -> list[str]:
    out = []
    if _HEADING_RE.search(text):
        out.append("nagłówek Markdown")
    if _RULE_RE.search(text):
        out.append("linia ---")
    if _TOOL_NAME_RE.search(text):
        out.append("nazwa narzędzia")
    return out


def main() -> int:
    rng = random.Random(RANDOM_SEED)
    system = persona.student_system_prompt()

    seed = [{**r, "source": "seed"} for r in read_jsonl(SEED_PATH)]
    teacher = []
    for path in sorted(TEACHER_DIR.glob("*.jsonl")) if TEACHER_DIR.exists() else []:
        teacher.extend({**r, "source": "teacher", "file": path.stem} for r in read_jsonl(path))
    collected = []
    rejected = Counter()
    raw_collected = read_jsonl(COLLECTED_PATH, strict=False)
    # 1.29.0: korekta "nie o to" dopisuje znacznik {"pomin_user": ...} zamiast przepisywać
    # plik; oznaczamy OSTATNIĄ wcześniejszą parę z tym pytaniem (ten sam skrót, co w routerze).
    try:
        import trace as _trace
        _preview = _trace.preview
    except Exception:
        _preview = lambda s: " ".join(str(s).split())[:200]
    for i, r in enumerate(raw_collected):
        if "pomin_user" in r:
            for prev in reversed(raw_collected[:i]):
                if "pomin_user" not in prev and not prev.get("skip") and _preview(str(prev.get("user") or "")) == r["pomin_user"]:
                    prev["skip"] = True
                    break
    for r in raw_collected:
        if r.get("skip") or "pomin_user" in r:
            continue
        hlen = r.get("history_len")
        if "history" not in r and isinstance(hlen, int) and hlen > 0:
            # Stary zapis: kontynuacja rozmowy bez zapisanej historii. Bez pytania poprzedzającego
            # taka odpowiedź ("A dlaczego?") uczyłaby ucznia zmyślać kontekst.
            rejected["chmura: ciąg dalszy rozmowy bez zapisanej historii"] += 1
            continue
        collected.append({"category": "chmura", "user": r.get("user", ""), "assistant": r.get("assistant", ""),
                          "history": r.get("history"), "source": "cloud", "provider": r.get("provider")})

    kept: dict[str, dict] = {}
    for r in seed + teacher + collected:
        user, answer = r.get("user"), r.get("assistant")
        if not isinstance(user, str) or not isinstance(answer, str):
            rejected["puste"] += 1
            continue
        user, answer = user.strip(), answer.strip()
        if not user or not answer:
            rejected["puste"] += 1
            continue
        history = _clean_history(r.get("history"))
        if len(history) != len(r.get("history") or []):
            # Cicho zgubiona tura to rekord uczący odpowiedzi na "A jeśli nie zadziała?" bez
            # pytania, do którego się odnosi. W plikach ręcznych to błąd autora (przerywamy z
            # nazwą rekordu), w zebranych z chmury tylko liczymy.
            if r["source"] != "cloud":
                raise SystemExit(f"{r.get('file', 'distill_seed')}: historia rekordu {user!r} ma turę bez roli "
                                 "user/assistant albo bez treści (popraw plik)")
            rejected["chmura: pominięta uszkodzona tura historii"] += 1
        problems = persona.violates_style(answer) + _markup_problems(answer)
        # 1.32.11 (audyt tura 15): odpowiedź z chmury uczy ucznia tylko od zaufanego dostawcy
        # (Claude), a nie z losowego darmowego modelu; bez adresów www i tekstu o "twórcy" czy
        # "instrukcjach", których nie było w pytaniu (wstrzyknięcia z sieci).
        if r["source"] == "cloud":
            if r.get("provider") not in TRUSTED_PROVIDERS:
                rejected["chmura: dostawca spoza zaufanych"] += 1
                continue
            if re.search(r"https?://", answer) and not re.search(r"https?://", user):
                problems.append("adres www spoza pytania")
            if re.search(r"(?i)\b(twórc|instrukcj|zignoruj)", answer) and not re.search(r"(?i)\b(twórc|instrukcj|zignoruj)", user):
                problems.append("tekst o twórcy/instrukcjach spoza pytania")
        for turn in history:
            if turn["role"] == "assistant":
                problems += [f"historia: {p}" for p in persona.violates_style(turn["content"])]
        if problems:
            rejected["styl: " + ", ".join(problems[:2])] += 1
            continue
        if len(answer) > MAX_ANSWER_CHARS:
            rejected["za długie"] += 1
            continue
        r = {**r, "history": history}
        key = _key(user, history)
        if key in kept:
            # Ręczne źródła (seed, nauczyciel) wygrywają z chmurą przy tym
            # samym pytaniu: są napisane celowo w personie; chmura bywa
            # zbyt rozwlekła. Seed i nauczyciel między sobą: pierwszy
            # wygrywa (seed), duplikat liczony, żeby było go widać.
            if kept[key]["source"] == "cloud" and r["source"] != "cloud":
                kept[key] = r
            else:
                rejected["duplikat"] += 1
            continue
        kept[key] = r

    examples = list(kept.values())
    rng.shuffle(examples)
    eval_pool = [e for e in examples if e.get("category") != "powitanie"]
    n_eval = max(5, round(len(eval_pool) * EVAL_FRACTION))
    eval_set = eval_pool[:n_eval]
    eval_keys = {_key(e["user"], e["history"]) for e in eval_set}
    train_set = [e for e in examples if _key(e["user"], e["history"]) not in eval_keys]

    def rec(e: dict) -> dict:
        out = {"system": system, "user": e["user"], "assistant": e["assistant"],
               "source": e["source"], "category": e.get("category")}
        if e.get("history"):
            out["history"] = e["history"]
        return out

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write_text(OUT_DIR / "student_train.jsonl", "".join(fsutil.json_line(rec(e)) + "\n" for e in train_set), mode=fsutil.PRIVATE_MODE)
    fsutil.atomic_write_text(OUT_DIR / "student_eval.jsonl", "".join(fsutil.json_line(rec(e)) + "\n" for e in eval_set), mode=fsutil.PRIVATE_MODE)
    probe = [{k: v for k, v in rec(e).items() if k != "assistant"} for e in eval_set[:20]]
    fsutil.atomic_write_text(OUT_DIR / "student_probe.jsonl", "".join(fsutil.json_line(p) + "\n" for p in probe), mode=fsutil.PRIVATE_MODE)

    stats = {
        "system_prompt": system,
        "system_prompt_chars": len(system),
        "seed_pairs": len(seed),
        "teacher_pairs": len(teacher),
        "teacher_files": dict(Counter(r["file"] for r in teacher)),
        "collected_pairs": len(collected),
        "with_history_train": sum(1 for e in train_set if e.get("history")),
        "rejected": dict(rejected),
        "train": len(train_set),
        "eval": len(eval_set),
        "per_category_train": dict(Counter(e.get("category") for e in train_set)),
        "avg_answer_chars": round(sum(len(e["assistant"]) for e in train_set) / max(1, len(train_set))),
    }
    fsutil.atomic_write_text(OUT_DIR / "student_stats.json", json.dumps(stats, ensure_ascii=False, indent=2), mode=fsutil.PRIVATE_MODE)

    print(f"Prompt ucznia ({len(system)} znaków): {system[:90]}...")
    print(f"Seed: {len(seed)}, nauczyciel: {len(teacher)} ({len(stats['teacher_files'])} plików), z chmury: {len(collected)}, "
          f"odrzucone: {dict(rejected) or 'nic'}")
    print(f"Trening: {len(train_set)} (z historią {stats['with_history_train']}), eval: {len(eval_set)}, "
          f"śr. długość odpowiedzi {stats['avg_answer_chars']} znaków")
    for cat, n in sorted(stats["per_category_train"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {cat}")
    print(f"Zapisano do {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
