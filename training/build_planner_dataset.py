"""
training/build_planner_dataset.py

Zbiór do treningu PLANERA pętli agenta (agent/agentloop.py): małego modelu,
który na podstawie CELU i WYKONANYCH KROKÓW odpowiada jedną linią
KROK: narzędzie | argument / GOTOWE: ... / PYTANIE: ... Czysty stdlib.

Dlaczego osobny model: dzisiejszy planer to model rozmowy (OLLAMA_MODEL,
dziś qwen2.5:3b; poniższy pomiar był na gemma2:2b) z pełną instrukcją i przykładami, ~1000 tokenów promptu na KAŻDY krok
zadania. Zmierzone 2026-10-07: dwukrokowe zadanie 125 s, pięć iteracji
poprawek promptu, zanim model przestał ogłaszać GOTOWE bez wykonania
kroku. Wytrenowany 0.5B z chudym promptem (agentloop.PLANNER_INSTRUCTION_SHORT)
ma format w wagach: powinien być wyraźnie szybszy na krok (szacunek, bez pomiaru) i mniej zabezpieczeń w akcji.

Źródła:
1. training/planner_seed.jsonl: epizody WZORCOWE napisane przez Claude'a
   (decyzja użytkownika z 2026-10-08: "Ty go trenuj"): {"goal", "steps":
   [{"tool", "arg", "ok", "observation"}], "final": "GOTOWE: ..." |
   "PYTANIE: ..."}. Obejmują zdolności GREGAI i narzędzia systemowe
   (SYSOP), ścieżki warunkowe ("jeśli są błędy"), odzyskiwanie po błędzie
   (pusty argument, nieznane narzędzie, ZABLOKOWANE, błąd formatu,
   (kontrola)) i zatrzymanie pytaniem, gdy brakuje danych.
2. data/training/episodes.jsonl: epizody Z UŻYCIA (agentloop._episode),
   tylko outcome == "gotowe" i z polem "final" (starsze wpisy bez final
   dostarczają same kroki). Epizody "gotowe_niepelne", "limit", "petla",
   "pytanie" itd. nie wchodzą: to zapis porażki planera, nie wzorzec.

Punkty decyzyjne: epizod o n krokach daje n+1 przykładów: stan przed
krokiem k -> "KROK: tool | arg", stan po wszystkich -> final. Stan jest
renderowany DOKŁADNIE funkcją agentloop._render_state (ta sama, co w
produkcji), a prompt systemowy to agentloop.planner_system_prompt(trained=True).

Cel treningu NIE może być błędem modelu: pseudo-kroki "(format)" i
"(kontrola)", nieznane narzędzie, pusty argument tam, gdzie wymagany,
i krok ZABLOKOWANY zostają w STANIE (uczą odzyskiwania po takiej
obserwacji), ale nigdy nie są CELEM (model nie ma się uczyć popełniać
błędu, który sam potem naprawił).

Filtr narzędzi: epizod używający narzędzia spoza bieżącego katalogu
(np. sys_* na laptopie bez SYSOP) jest pomijany w całości, bo planer
widzi w prompcie tylko bieżący katalog; manifest planera zapisuje
zestaw narzędzi, więc po włączeniu SYSOP trening trzeba powtórzyć.

Wyjście (data/training/): planner_train.jsonl, planner_eval.jsonl (15%
EPIZODÓW, nie przykładów, żeby stany jednego zadania nie trafiały do obu
zbiorów), planner_stats.json.
"""

from __future__ import annotations

import hashlib
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
import agentloop  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent / "planner_seed.jsonl"
EPISODES_PATH = ROOT / "data" / "training" / "episodes.jsonl"
OUT_DIR = ROOT / "data" / "training"

EVAL_FRACTION = 0.15
RANDOM_SEED = 20261008
PSEUDO_TOOLS = {"(format)", "(kontrola)"}
_MISTAKE_RE = re.compile(r"^(Nieznane narzędzie|Narzędzie \w+ wymaga argumentu|ZABLOKOWANE|ODMOWA)")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def is_mistake(step: dict) -> bool:
    """Krok, który był błędem planera (nie wolno go uczyć jako celu)."""
    if step.get("tool") in PSEUDO_TOOLS:
        return True
    return not step.get("ok") and bool(_MISTAKE_RE.match(step.get("observation") or ""))


def step_line(step: dict) -> str:
    return f"KROK: {step['tool']} | {step.get('arg') or ''}".rstrip()


# Narzędzia, których wynik składa GREGAI sam, z własnych pomiarów i stałych tekstów (liczniki,
# stan usług, adresy interfejsów, własne komunikaty). Do nauki planera idą epizody z użycia,
# w których występują WYŁĄCZNIE takie narzędzia. Cała reszta zwraca cudzy tekst (strony,
# nazwy urządzeń, linie logów i procesów, zawartość plików i notatek, wyjście apt): podsunięta
# nim instrukcja mogłaby trafić do wag planera. Lista dozwolonych, nie zakazanych: nowe
# narzędzie jest domyślnie nieufne, dopóki ktoś świadomie go tu nie dopisze. Epizody wzorcowe
# (planner_seed.jsonl) są pisane ręcznie i tego ograniczenia nie mają.
LOCAL_OUTPUT_TOOLS = frozenset({
    "self_status", "graph_overview", "remember",
    "sys_status", "sys_services", "sys_timers", "sys_network",
    "sys_service_action", "sys_backup",
})


def uses_external_text(episode: dict) -> bool:
    for s in episode.get("steps") or []:
        if s.get("tool") in PSEUDO_TOOLS or s.get("tool") in LOCAL_OUTPUT_TOOLS or is_mistake(s):
            continue
        return True
    return False


def expand(episode: dict, system: str, source: str, known: set[str]) -> tuple[list[dict], str | None]:
    """Epizod -> lista przykładów; albo ([], powód) gdy pominięty."""
    goal = (episode.get("goal") or "").strip()
    steps = episode.get("steps") or []
    final = (episode.get("final") or "").strip()
    if not goal:
        return [], "bez celu"
    unknown = set()
    # Narzędzie wyłączone ustawieniem (sys_shell przy SYSOP_SHELL=0) w ogóle
    # nie istnieje dla planera: epizod z jego użyciem (także zablokowanym)
    # uczyłby go obserwacji, której w tym trybie nie zobaczy ("ZABLOKOWANE"
    # zamiast "Nieznane narzędzie").
    gated = set(agentloop.sysop.TOOLS) - set(agentloop.sysop.active_tools())
    for s in steps:
        tool = s.get("tool")
        if tool in gated:
            unknown.add(tool)
            continue
        if tool in PSEUDO_TOOLS or tool in known:
            continue
        if is_mistake(s):
            # "Nieznane narzędzie 'pogoda'": błąd modelu zostaje w stanie
            # jako obserwacja, nie świadczy o brakującym narzędziu.
            continue
        unknown.add(tool)
    if unknown:
        return [], f"narzędzia spoza katalogu: {', '.join(sorted(unknown))}"
    if final:
        parsed = agentloop.parse_action(final)
        if parsed is None or parsed[0] == "KROK":
            return [], "final nie jest GOTOWE/PYTANIE"
    out = []
    state_steps: list[dict] = []
    for step in steps:
        if not is_mistake(step):
            state = {"goal": goal, "steps": [{k: s.get(k) for k in ("tool", "arg", "ok", "observation")} for s in state_steps]}
            out.append({"system": system, "user": agentloop._render_state(state), "assistant": step_line(step),
                        "source": source, "goal": goal, "kind": "KROK", "tool": step["tool"]})
        state_steps.append({"tool": step.get("tool"), "arg": step.get("arg") or "", "ok": bool(step.get("ok")),
                            "observation": (step.get("observation") or "")[:agentloop.OBSERVATION_LIMIT + 3]})  # +3: znacznik "..." z _observation
    if final:
        state = {"goal": goal, "steps": state_steps}
        out.append({"system": system, "user": agentloop._render_state(state), "assistant": final,
                    "source": source, "goal": goal, "kind": final.split(":")[0].upper(), "tool": None})
    if not out:
        return [], "bez przykładów"
    return out, None


def main() -> int:
    rng = random.Random(RANDOM_SEED)
    system = agentloop.planner_system_prompt(trained=True)
    known = {name for name, _, _ in agentloop.tool_catalog()}

    seed = read_jsonl(SEED_PATH)
    live_all = read_jsonl(EPISODES_PATH)
    skipped = Counter()
    live = []
    for e in live_all:
        if e.get("outcome") != "gotowe":
            continue
        if e.get("trained"):
            # Odpowiedzi wytrenowanego planera nie są materiałem do jego nauki
            # (jak w routerze: model nie uczy się z własnych decyzji).
            skipped["episodes: epizod wytrenowanego planera"] += 1
            continue
        if uses_external_text(e):
            skipped["episodes: wynik narzędzia z cudzym tekstem (internet, sieć, logi, pliki, notatki)"] += 1
            continue
        if any(len(s.get("observation") or "") == 200 for s in e.get("steps") or []):
            # Stary format zapisywał obserwacje ucięte do 200 znaków, a planer
            # widział do 700: cel cytowałby fakty nieobecne w stanie.
            skipped["episodes: obserwacja ucięta do 200 znaków (stary format)"] += 1
            continue
        live.append(e)
    episodes: list[tuple[str, list[dict]]] = []
    for source, rows in (("seed", seed), ("episodes", live)):
        for ep in rows:
            examples, why = expand(ep, system, source, known)
            if why:
                skipped[f"{source}: {why}"] += 1
                continue
            episodes.append((source, examples))

    # Podział po EPIZODACH, potem deduplikacja stanów (identyczny stan ->
    # pierwszy cel wygrywa; stany początkowe par warunkowych są takie same
    # i mają ten sam cel, więc nic nie ginie).
    # Do oceny (bramka eksportu) trafiają wyłącznie epizody WZORCOWE, pisane ręcznie: epizod z
    # użycia, choćby podsunięty, nie może zdawać egzaminu, który sam współtworzy.
    rng.shuffle(episodes)
    seed_eps = [e for e in episodes if e[0] == "seed"]
    live_eps = [e for e in episodes if e[0] != "seed"]
    if not seed_eps:  # plik wzorcowy jest w paczce; bez niego ocena idzie po tym, co jest
        seed_eps, live_eps = live_eps, []
    n_eval = max(3, round(len(seed_eps) * EVAL_FRACTION)) if len(seed_eps) >= 8 else max(1, len(seed_eps) // 4)
    eval_eps = seed_eps[:n_eval]
    train_eps = seed_eps[n_eval:] + live_eps

    def flatten(eps: list[tuple[str, list[dict]]], taken: set[str]) -> list[dict]:
        out = []
        for _, examples in eps:
            for ex in examples:
                if ex["user"] in taken:
                    skipped["duplikat stanu"] += 1
                    continue
                taken.add(ex["user"])
                out.append(ex)
        return out

    taken: set[str] = set()
    train = flatten(train_eps, taken)
    eval_set = flatten(eval_eps, taken)
    rng.shuffle(train)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write_text(OUT_DIR / "planner_train.jsonl", "".join(fsutil.json_line(r) + "\n" for r in train), mode=fsutil.PRIVATE_MODE)
    fsutil.atomic_write_text(OUT_DIR / "planner_eval.jsonl", "".join(fsutil.json_line(r) + "\n" for r in eval_set), mode=fsutil.PRIVATE_MODE)

    stats = {
        "system_prompt_chars": len(system),
        "system_prompt_sha1": hashlib.sha1(system.encode("utf-8")).hexdigest(),
        "tools": sorted(known),
        "seed_episodes": len(seed),
        "live_episodes_total": len(live_all),
        "live_episodes_gotowe": len(live),
        "episodes_used": len(episodes),
        "skipped": dict(skipped),
        "train": len(train),
        "eval": len(eval_set),
        "per_kind_train": dict(Counter(r["kind"] for r in train)),
        "per_tool_train": dict(Counter(r["tool"] for r in train if r["tool"])),
        "per_source_train": dict(Counter(r["source"] for r in train)),
        "max_user_chars": max((len(r["user"]) for r in train + eval_set), default=0),
    }
    fsutil.atomic_write_text(OUT_DIR / "planner_stats.json", json.dumps(stats, ensure_ascii=False, indent=2), mode=fsutil.PRIVATE_MODE)

    print(f"Prompt planera ({len(system)} znaków), katalog: {', '.join(sorted(known))}")
    print(f"Epizody: seed {len(seed)}, z użycia {len(live)}/{len(live_all)} (gotowe), użyte {len(episodes)}, "
          f"pominięte: {dict(skipped) or 'nic'}")
    print(f"Przykłady: trening {len(train)}, eval {len(eval_set)}; rodzaje: {stats['per_kind_train']}")
    for tool, n in sorted(stats["per_tool_train"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {tool}")
    print(f"Zapisano do {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
