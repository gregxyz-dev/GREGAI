"""
memory.py

Zapisuje WYŁĄCZNIE do folderu ./memory, jeden plik markdown na każdy
zapamiętany fakt, z datą w nazwie pliku. Nigdzie indziej nie zapisuje.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import data as data_mod
import fsutil
import vault as vault_mod

MEMORY_DIR = Path(data_mod.MEMORY_ROOT)
MAX_FACT_CHARS = 2000
MAX_TITLE_CHARS = 120


def _find_same_fact(title: str, body: str) -> str | None:
    """Plik w memory/ z tym samym tytułem I tą samą treścią (tytuł bywa obcięty do 120
    znaków, więc sam tytuł nie odróżnia "faktura ... 1200 zł" od "... 1500 zł")."""
    # 1.32.3 (audyt tura 8): porównanie bez wielkości liter, zbędnych spacji i kropki na końcu -
    # "lubię kawę", "Lubię kawę" i "lubię kawę." to ten sam fakt, nie trzy pliki.
    # Słowa z cyframi (kody, numery, hasła: "Ab12" i "AB12" to dwa różne kody) porównujemy
    # z wielkością liter, resztę bez ("Lubię kawę" i "lubię kawę." to ten sam fakt).
    def norm(s: str, fold_case: bool = True) -> str:
        words = (s or "").split()
        if words:
            words[-1] = words[-1].rstrip(".!")
        return " ".join(w if any(c.isdigit() for c in w) else w.casefold() for w in words)
    want, want_body = norm(title), norm(body)
    try:
        for p in sorted(MEMORY_DIR.glob("*.md")):
            try:
                with open(p, encoding="utf-8-sig", errors="replace") as fh:  # 1.32.10: BOM z edytora
                    first = fh.readline().rstrip("\r\n")
                    if not first.startswith("# ") or norm(first[2:]) != want:
                        continue
                    rest = fh.read()
            except OSError:
                continue
            if norm(rest.split("\n\n", 1)[-1]) == want_body:
                return p.name
    except OSError:
        pass
    return None


def remember(fact: str) -> tuple[str, bool]:
    """Zapisuje jeden fakt jako nowy plik w memory/. Zwraca (nazwa pliku, czy nowy).

    Tytuł (linia `# ...`) jest jedną linią, żeby wielolinijkowy fakt nie
    rozbił nagłówka ani nie podrobił linii `type:`; pełna treść idzie niżej.
    Nowy plik powstaje wyłącznie (O_EXCL), więc dwa fakty o tej samej nazwie
    nigdy się nie nadpiszą."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    # Samotny surogat z JSON-a (kod U+D800) nie da się zapisać jako UTF-8: zamieniamy go
    # na "?" przed zapisem, zamiast pokazać użytkownikowi surowy wyjątek.
    # 1.28.0 (audyt): końce linii ujednolicone (CRLF nigdy nie pasował przy porównaniu
    # duplikatów, więc każdy zapis dawał nowy plik).
    body = fact.encode("utf-8", "replace").decode("utf-8").replace("\x00", "")
    body = body.replace("\r\n", "\n").replace("\r", "\n").strip()[:MAX_FACT_CHARS]
    try:  # wartości sekretów z .env (hasło routera, klucze) nie mają leżeć jawnie w notatce i grafie
        import sysop
        body = sysop.mask_secrets(body)
    except ImportError:
        pass
    title = " ".join(body.split())
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS].rstrip() + "…"
    slug = vault_mod.slugify(body, 40, default="fakt")
    content = f"# {title}\ntype: Memory\ndata: {date_str}\n\n{body}\n"
    # Ten sam fakt zapisany drugi raz (powtórzone polecenie, drugie "tak") nie tworzy
    # drugiego węzła o tym samym tytule: wraca istniejący plik.
    existing = _find_same_fact(title, body)
    if existing:
        return existing, False

    filename = f"{date_str}-{slug}.md"
    counter = 2
    while not fsutil.create_new_text(MEMORY_DIR / filename, content, mode=0o644):
        filename = f"{date_str}-{slug}-{counter}.md"
        counter += 1
    return filename, True
