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

import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "training" / "ewaluacja" / "regresja.jsonl"
HISTORY_PATH = ROOT / "data" / "ewaluacja" / "historia.jsonl"
OFFLINE_TYPES = ("routing", "komenda", "bramka", "spoleczne", "slonce", "straz", "nauka", "pretensja")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(json.loads(line))
    return out


# --- Oceniacze szybkie (bez sieci) --------------------------------------------------

def _check_offline(case: dict) -> tuple[bool, str]:
    typ = case["typ"]
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
    vault = main_mod.get_vault()
    system = main_mod.get_system_prompt()
    attempts = []
    for i in range(k):
        t0 = time.monotonic()
        try:
            res = router_mod.route(vault, system, [], case["wiadomosc"], chat=f"ewaluacja-{case['id']}-{i}")
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
        import netguard as netguard_mod
        internet_ok = netguard_mod.internet_allowed()[0]
        for c in cases:
            if c["typ"] != "rozmowa":
                continue
            r = _run_live_case(c, k, internet_ok)
            r.update(ok=r[f"pass@{k}"], typ="rozmowa", zrodlo=c.get("zrodlo", ""))
            results[c["id"]] = r
        mode = f"zywo-k{k}"
    total = len(results)
    passed = sum(1 for r in results.values() if r["ok"])
    summary = {"przypadki": total, "zaliczone": passed}
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
    if live:
        print(f"Tryb na żywo: każdy przypadek rozmowy {k} razy przez prawdziwe modele (kosztuje tokeny w budżecie Koryta)...\n")
    rep = run(live=live, k=k, save="--bez-zapisu" not in argv)
    print(report_text(rep))
    return 0 if rep["podsumowanie"]["zaliczone"] == rep["podsumowanie"]["przypadki"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(ROOT)
    sys.exit(main(sys.argv[1:]))
