"""
vault.py

Zamienia foldery z notatkami na przeszukiwalny graf. Wyłącznie do odczytu:
ten moduł nigdy nie zapisuje do indeksowanych folderów.

Obsługiwane formaty: .md, .txt, .pdf (podstawowa ekstrakcja tekstu, bez
zewnętrznych bibliotek).

Pomijane: node_modules, .git, wszystkie katalogi ukryte (zaczynające się od
kropki), pliki > 2 MB.

[[wikilinks]] pomiędzy notatkami są traktowane jako krawędzie grafu.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

import slowa as slowa_mod

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
SKIP_DIRS = {"node_modules", ".git"}
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}

# Konwencja "projektu": notatka z `type: Project` (patrz TYPE_LABELS_ORDER w
# ui/app.js - ten sam angielski napis steruje kolorem i filtrem, UI tłumaczy go
# na "Projekt"). Rozmowa w interfejsie może być PRZYPISANA do takiego węzła
# (agent/main.py: payload["project"]): wtedy widzi tylko jego własny podgraf
# (patrz project_scope) + wspólną pulę nieprzypisanych notatek (shared_pool_slugs),
# nigdy podgraf innego projektu - "projekty nie mają wspólnej wiedzy" (prośba
# użytkownika, 2026-10-18).
PROJECT_TYPE = "Project"
# Ekstrakcja PDF bez zewnętrznych bibliotek ma twarde limity: mały plik PDF
# potrafi rozpakować się do gigabajtów ("bomba dekompresji").
PDF_MAX_STREAM_BYTES = 4 * 1024 * 1024
PDF_MAX_TOTAL_BYTES = 16 * 1024 * 1024

# [[Tytuł]], [[Tytuł|alias]], [[Tytuł#sekcja]], [[Tytuł#sekcja|alias]]. Długości
# są ograniczone, a "[" jest wykluczone ze wszystkich klas znaków: bez tego
# każde "[[" w pliku pełnym "[[" zjadało do 200 znaków, zanim się wycofało
# (czas ~200x liniowy: plik 2 MB = ponad 30 s z zamrożonym serwerem), a
# niedomknięte "[[" połykało następny prawdziwy link.
WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]{1,200})(?:#[^\[\]|]{0,200})?(?:\|[^\[\]]{0,200})?\]\]")
# Spacje i tabulatory, nigdy znak nowej linii: "type:\n\nTreść" nie ma typu
# "Treść", a samotne "# " nie bierze następnej linii za tytuł.
FRONTMATTER_TYPE_RE = re.compile(r"^type:[ \t]*[\"']?([^\s\"']+)", re.MULTILINE | re.IGNORECASE)
TITLE_RE = re.compile(r"^#[ \t]+(\S.*)$", re.MULTILINE)
_TYPE_LINE_RE = re.compile(r"^type:[ \t]*\S.*$", re.MULTILINE | re.IGNORECASE)
_KEY_LINE_RE = re.compile(r"[ \t]*[A-Za-z_][\w-]*:.*|[ \t]*- .*")


def _header_end(masked: str) -> int:
    """Koniec nagłówka notatki: frontmatter `---...---`, H1 i linie `klucz: wartość`
    do pierwszej pustej linii po nich. `type:` liczy się tylko tu, nie w treści
    ("type: ext4" we wpisie fstab to nie typ notatki)."""
    lines = masked.split("\n")
    pos, i, seen_key = 0, 0, False
    while i < len(lines) and not lines[i].strip():
        pos += len(lines[i]) + 1; i += 1
    if i < len(lines) and lines[i].strip() == "---":
        j = i + 1
        while j < len(lines) and lines[j].strip() != "---":
            j += 1
        if j < len(lines):
            for k in range(i, j + 1):
                pos += len(lines[k]) + 1
            i = j + 1
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            if seen_key:
                break
        elif TITLE_RE.fullmatch(ln) or _KEY_LINE_RE.fullmatch(ln):
            seen_key = seen_key or not ln.startswith("#")
        else:
            break
        pos += len(ln) + 1; i += 1
    return pos
# Kod w notatce (blok ``` albo ~~~, `inline`) to nie linki, tytuł ani typ:
# `# komentarz` w bloku basha nie jest nagłówkiem, `[[ -f x ]]` nie jest linkiem.
# Ogrodzenie ma 3 lub więcej znaków (cztery pozwalają pokazać trzy w środku), zamyka je linia
# z co najmniej tyloma samymi znakami; w ogrodzeniu z ` opis po otwarciu nie ma ` (inaczej
# linia "```kod``` tekst" byłaby otwarciem bloku, który połknąłby resztę notatki).
_FENCE_RE = re.compile(
    r"^[ \t]{0,3}(?:(`{3,})[^`\n]*\n.*?(?:^[ \t]{0,3}\1`*[ \t]*$|\Z)"
    r"|(~{3,})[^\n]*\n.*?(?:^[ \t]{0,3}\2~*[ \t]*$|\Z))", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def mask_code(text: str) -> str:
    """Ten sam tekst (ta sama długość, te same końce linii), w którym kod jest
    zastąpiony spacjami. Wyszukujemy na wersji zamaskowanej, a fragmenty
    wycinamy z oryginału po pozycjach dopasowania."""
    def _blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return _INLINE_CODE_RE.sub(_blank, _FENCE_RE.sub(_blank, text))


def _title_match(text: str, masked: str):
    """Dopasowanie pierwszego nagłówka `# Tytuł` poza kodem. Odstęp po "#" musi być w
    ORYGINALE: "#`x` Tytuł" (kod zaraz po kratce) to nie nagłówek, choć po zamaskowaniu
    kodu wygląda jak "#   Tytuł"."""
    for m in TITLE_RE.finditer(masked):
        if text[m.start() + 1] in " \t":
            return m
    return None


def find_title(text: str, masked: str | None = None) -> str | None:
    """Pierwszy nagłówek `# Tytuł` poza kodem albo None. `masked` = mask_code(text),
    gdy wołający już je policzył (build_vault liczy je raz na notatkę)."""
    m = _title_match(text, mask_code(text) if masked is None else masked)
    if not m:
        return None
    # Linia z ORYGINAŁU: w zamaskowanym tekście `kod` na początku tytułu jest spacjami,
    # więc grupa 1 zaczynałaby się dopiero po nim ("`kubectl` podstawy" -> "podstawy").
    return re.sub(r"^#[ \t]+", "", text[m.start():m.end()]).strip() or None


def find_type(text: str, masked: str | None = None) -> str | None:
    masked = mask_code(text) if masked is None else masked
    m = FRONTMATTER_TYPE_RE.search(masked, 0, _header_end(masked))
    if not m:
        return None
    t = text[m.start(1):m.end(1)]
    # 1.32.10: interfejs pokazuje "Projekt", więc i tak wpisany ręcznie typ jest projektem.
    if t.lower() in ("projekt", "project"):
        return PROJECT_TYPE
    return t[:1].upper() + t[1:]


def find_wikilinks(text: str, masked: str | None = None) -> Set[str]:
    if masked is None:
        masked = mask_code(text)
    return {text[m.start(1):m.end(1)].strip() for m in WIKILINK_RE.finditer(masked)}


def _printable(text: str) -> str:
    """Nazwa pliku bywa niepoprawnym UTF-8 (Windows-1250 w wypakowanym archiwum):
    w komunikatach i JSON-ie zostają tylko znaki, które da się zakodować."""
    return text.encode("utf-8", "replace").decode("utf-8")


@dataclass
class Note:
    slug: str
    path: str
    title: str
    ntype: str
    text: str
    links: Set[str] = field(default_factory=set)  # target slugs (resolved)
    raw_links: Set[str] = field(default_factory=set)  # unresolved [[names]]
    # True: plik nie jest w UTF-8, więc tekst w pamięci jest przybliżeniem.
    # Taka notatka jest tylko do odczytu (zapis zgubiłby polskie znaki).
    lossy: bool = False


@dataclass
class Vault:
    notes: Dict[str, Note] = field(default_factory=dict)  # slug -> Note
    by_title: Dict[str, str] = field(default_factory=dict)  # normalized title -> slug
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def degrees(self) -> Dict[str, int]:
        """Stopień każdej notatki (linki wychodzące + przychodzące) w jednym przebiegu."""
        # Różni sąsiedzi (link w obie strony to jedno połączenie), tak jak panel "Top huby"
        # w interfejsie liczy krawędzie; wcześniej wzajemny link liczył się podwójnie.
        neigh = {slug: set(note.links) for slug, note in self.notes.items()}
        for slug, note in self.notes.items():
            for target in note.links:
                if target in neigh:
                    neigh[target].add(slug)
        return {slug: len(s - {slug}) for slug, s in neigh.items()}

    def top_hubs(self, n: int = 10):
        deg = self.degrees()
        ranked = sorted(self.notes.values(), key=lambda note: deg[note.slug], reverse=True)
        return [(note, deg[note.slug]) for note in ranked[:n]]

    def related(self, slug: str) -> List[Note]:
        """Notatki BEZPOŚREDNIO połączone z `slug`: linki wychodzące z
        tej notatki plus inne notatki, które linkują DO niej
        (przychodzące), tak jak degree() liczy oba kierunki, tylko
        tutaj zwracane są same węzły, nie tylko ich liczba. Używane
        tam, gdzie samo dopasowanie tekstowe nie wystarcza i wartościowe
        jest pokazać kontekst z grafu (patrz tools.py:search_brain):
        np. że dany Projekt ma przypisanego Klienta i otwartą Fakturę,
        czego żadne wyszukiwanie słów kluczowych samo nie znajdzie."""
        note = self.notes.get(slug)
        if not note:
            return []
        related_slugs = set(note.links)
        for other in self.notes.values():
            if other.slug != slug and slug in other.links:
                related_slugs.add(other.slug)
        related_slugs.discard(slug)
        # 1.18.0: stała kolejność (najbardziej połączone pierwsze, potem tytuł) -
        # zbiór dawał co uruchomienie inną kolejność, a odpowiedź pokazuje [:4].
        deg = self.degrees()
        found = [self.notes[s] for s in related_slugs if s in self.notes]
        return sorted(found, key=lambda n: (-deg.get(n.slug, 0), n.title.lower()))

    def counts_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for note in self.notes.values():
            counts[note.ntype] = counts.get(note.ntype, 0) + 1
        return counts

    def projects(self) -> List[Note]:
        """Notatki typu Project (patrz PROJECT_TYPE), po tytule - lista, z której
        interfejs buduje szynę "Projekty" w Rozmowie."""
        return sorted((n for n in self.notes.values() if n.ntype == PROJECT_TYPE), key=lambda n: n.title.lower())

    def _adjacent(self, slug: str) -> Set[str]:
        """Sąsiedzi JEDNEGO węzła w obie strony (jak related(), tu same slugi, bez
        samego siebie): pomocnicze dla project_scope poniżej."""
        note = self.notes.get(slug)
        if not note:
            return set()
        out = set(note.links)
        for other in self.notes.values():
            if slug in other.links:
                out.add(other.slug)
        out.discard(slug)
        return out

    def _project_owners(self) -> Dict[str, Set[str]]:
        """slug -> projekty, do których notatka NALEŻY (1.26.0, audyt prywatności).

        Dawniej każdy projekt zbierał wszystko osiągalne linkami, więc wspólny
        węzeł (np. notatka "Grzegorz" połączona z klientem A i fakturą B) sklejał
        podgrafy: na losowym grafie 2000 notatek projekt A "widział" 1981.
        Teraz jedno przeszukanie wszerz ze WSZYSTKICH projektów naraz: notatka
        należy tylko do projektów NAJBLIŻSZYCH (najmniej kroków; remis = do
        każdego z nich). Notatka połączona wprost z dwoma projektami nadal
        należy do obu; faktura B (1 krok od B, 3 od A) - tylko do B. Inny węzeł
        typu Project jest granicą, nie przejściem. Wynik w pamięci obiektu
        (jedno liczenie na wersję grafu zamiast N przeszukań na wiadomość)."""
        sig = (len(self.notes), sum(len(n.links) for n in self.notes.values()))
        cached = self.__dict__.get("_owners_cache")
        if cached and cached[0] == sig:
            return cached[1]
        adj: Dict[str, Set[str]] = {s: set() for s in self.notes}
        for n in self.notes.values():
            for t in n.links:
                if t in adj and t != n.slug:
                    adj[n.slug].add(t)
                    adj[t].add(n.slug)
        projects = [n.slug for n in self.notes.values() if n.ntype == PROJECT_TYPE]
        pset = set(projects)
        dist: Dict[str, int] = {}
        owners: Dict[str, Set[str]] = {}
        frontier = []
        for p in projects:
            dist[p], owners[p] = 0, {p}
            frontier.append(p)
        d = 0
        while frontier:
            nxt_frontier = []
            for cur in frontier:
                for nb in adj.get(cur, ()):
                    if nb in pset:
                        continue
                    if nb not in dist:
                        dist[nb] = d + 1
                        owners[nb] = set(owners[cur])
                        nxt_frontier.append(nb)
                    elif dist[nb] == d + 1 and not owners[nb]:
                        # 1.32.11 (audyt tura 15): remis odległości NIE łączy właścicieli - notatka
                        # z projektu A z linkiem do notatki B wciągała cały podgraf B do zakresu A.
                        owners[nb] = set(owners[cur])
            frontier = nxt_frontier
            d += 1
        self.__dict__["_owners_cache"] = (sig, owners)
        return owners

    def project_scope(self, project_slug: str) -> Set[str]:
        """Slugi "należące" do projektu `project_slug` (patrz _project_owners):
        on sam plus notatki, dla których jest najbliższym projektem. Pusty zbiór,
        gdy `project_slug` nie jest notatką w tym vault."""
        if project_slug not in self.notes:
            return set()
        return {s for s, own in self._project_owners().items() if project_slug in own} | {project_slug}

    def shared_pool_slugs(self) -> Set[str]:
        """Notatki, które nie "należą" do ŻADNEGO projektu (patrz project_scope):
        ogólna, wspólna wiedza widoczna z każdej rozmowy przypisanej do projektu,
        niezależnie od tego, do którego. Brak projektów w vault = wszystko jest
        wspólne (nic jeszcze nie jest wyodrębnione)."""
        if not any(n.ntype == PROJECT_TYPE for n in self.notes.values()):
            return set(self.notes.keys())
        return set(self.notes.keys()) - set(self._project_owners().keys())

    def filtered(self, slugs: Set[str]) -> "Vault":
        """Widok TEGO vault ograniczony do `slugs` (np. podgraf projektu + pula
        wspólna): te samo obiekty Note (nic nie jest kopiowane ani ponownie
        parsowane), więc search()/degrees()/related() policzone na tym widoku
        liczą się tylko w jego granicach - rozmowa przypisana do projektu dostaje
        go jako swój `vault`, zamiast przeglądać cały graf."""
        kept = {s: n for s, n in self.notes.items() if s in slugs}
        by_title = {t: s for t, s in self.by_title.items() if s in kept}
        return Vault(notes=kept, by_title=by_title, skipped=list(self.skipped), errors=list(self.errors))

    def search(self, query: str, limit: int = 5) -> List[Note]:
        """Notatki pasujące do zapytania, najlepsze pierwsze (patrz search_hits)."""
        return [hit.note for hit in self.search_hits(query, limit)]

    def search_hits(self, query: str, limit: int = 5) -> List["SearchHit"]:
        """Ranking (1.19.0). Słowa zapytania i notatki porównywane jako CAŁE
        rdzenie (slowa.stem, z obocznościami: "kawie" -> "Kawa", "ręce" ->
        "Ręka", "Żelazowskiego" -> "Żelazowski"), po złożeniu znaków
        (slowa.fold). Dokładne słowo waży więcej niż ten sam rdzeń, a ten więcej
        niż sam początek słowa (tylko dla słów od 6 liter: "prompt" ->
        "promptowanie"). Dwuliterowe skróty ("AI", "UI") tylko jako całe słowa.

        Kolejność: najpierw notatki, których TYTUŁ ma wszystkie słowa zapytania,
        potem z największą liczbą różnych trafionych słów, potem siła trafień
        w tytule, dokładne trafienia, na końcu liczba wystąpień w treści (po
        najwyżej 5 na słowo). Treść bez H1 i linii `type:`.

        Próg trafności: notatka wchodzi, gdy pasuje co najmniej połowa słów
        zapytania, albo (dla zapytań z 1-2 słowami) gdy pasuje tytuł. Dotąd
        wystarczało jedno słowo z długiego pytania ("prac" z "pracy" ->
        "Kalendarz prac"), więc Namysł i zadania stałe dostawały szum."""
        terms = _query_terms(query)
        if not terms:
            return []
        hits = []
        for note in self.notes.values():
            idx = _note_index(note)
            title_lv, body_lv, counts = [], [], []
            for term in terms:
                title_lv.append(_term_level(term, idx.title_words, idx.title_stems))
                b_level = _term_level(term, idx.body_words, idx.body_stems)
                body_lv.append(b_level)
                counts.append(min(_term_count(term, idx), 5) if b_level else 0)
            matched = sum(1 for t, b in zip(title_lv, body_lv) if t or b)
            if not matched:
                continue
            title_hits = sum(1 for t in title_lv if t)
            if not (matched * 2 >= len(terms) or (title_hits and len(terms) <= 2)):
                continue
            exact = sum(1 for t, b in zip(title_lv, body_lv) if t == 3 or b == 3)
            hit = SearchHit(note=note, matched=matched, total=len(terms), title_hits=title_hits,
                            exact=exact, strong=matched == len(terms) or title_hits == len(terms))
            key = (title_hits == len(terms), matched, sum(title_lv), exact, sum(counts))
            hits.append((tuple(-v for v in key), note.title.lower(), hit))
        # Tytuł jako ostatni klucz: przy remisie kolejność stała między wywołaniami.
        hits.sort(key=lambda x: (x[0], x[1]))
        return [h for _, _, h in hits[:limit]]


@dataclass
class SearchHit:
    """Jedno trafienie wyszukiwania (1.19.0). `strong`: pasują WSZYSTKIE słowa
    zapytania (w treści albo w tytule) - dla wywołujących, którzy chcą brać
    notatkę jako materiał tylko przy pewnym trafieniu (Namysł, zadania stałe)."""
    note: "Note"
    matched: int
    total: int
    title_hits: int
    exact: int
    strong: bool


@dataclass
class _NoteIndex:
    title_words: frozenset
    title_stems: frozenset
    body_words: Dict[str, int]
    body_stems: Dict[str, int]


_WORD_RE = re.compile(r"\w+")


def _index_words(text: str) -> tuple[Dict[str, int], Dict[str, int]]:
    words: Dict[str, int] = {}
    stems: Dict[str, int] = {}
    for w in _WORD_RE.findall(text[:MAX_FILE_BYTES]):
        words[w] = words.get(w, 0) + 1
        st = slowa_mod.stem(w)
        stems[st] = stems.get(st, 0) + 1
    return words, stems


def _note_index(note: "Note") -> _NoteIndex:
    """Słowa i rdzenie notatki, z pamięcią podręczną na notatkę. Klucz to id
    obiektu, ważność sprawdzana tożsamością tekstu i tytułu: przeładowanie
    notatki tworzy nowe obiekty, więc stary wpis nigdy nie posłuży nowej treści."""
    # 1.20.0: indeks żyje NA obiekcie notatki (znika razem z nią). Wcześniejszy słownik
    # po id() trzymał indeksy starych notatek po każdej przebudowie vaultu.
    hit = note.__dict__.get("_idx")
    if hit is not None and hit[0] is note.text and hit[1] is note.title:
        return hit[2]
    title = slowa_mod.fold(note.title)
    body = slowa_mod.fold(strip_title_and_type(note.text))
    t_words, t_stems = _index_words(title)
    b_words, b_stems = _index_words(body)
    idx = _NoteIndex(frozenset(t_words), frozenset(t_stems), b_words, b_stems)
    note.__dict__["_idx"] = (note.text, note.title, idx)
    return idx


@dataclass(frozen=True)
class _Term:
    word: str            # złożone słowo zapytania
    variants: frozenset  # rdzeń i jego oboczności (puste dla skrótów 2-literowych)


def _term_level(term: "_Term", words, stems) -> int:
    """3 = to samo słowo, 2 = ten sam rdzeń, 1 = słowo notatki zaczyna się od
    słowa zapytania (od 6 liter), 0 = brak."""
    if term.word in words:
        return 3
    if not term.variants:
        return 0
    if any(v in stems or v in words for v in term.variants) or term.word in stems:
        return 2
    if len(term.word) >= 6 and any(w.startswith(term.word) for w in words):
        return 1
    return 0


def _term_count(term: "_Term", idx: _NoteIndex) -> int:
    count = idx.body_words.get(term.word, 0)
    if term.variants:
        count = max(count, sum(idx.body_stems.get(v, 0) for v in term.variants))
    return count


def _query_terms(query: str) -> list:
    out, seen = [], set()
    for word in search_terms(query):
        if word in seen:
            continue
        seen.add(word)
        out.append(_Term(word, frozenset() if len(word) <= 2 else slowa_mod.stem_variants(word)))
    return out


def term_matches(word: str, query: str) -> bool:
    """Czy słowo z tekstu (dowolna forma) pasuje do któregoś słowa zapytania -
    ta sama miara co search_hits (dla wycinków i podświetleń)."""
    folded = slowa_mod.fold(word)
    stems = {slowa_mod.stem(folded)}
    return any(_term_level(t, {folded}, stems) for t in _query_terms(query))


def excerpt(note: "Note", query: str, limit: int = 1200) -> str:
    """Wycinek treści notatki (bez H1 i `type:`) najwyżej `limit` znaków, wokół
    miejsc, gdzie występują słowa zapytania (1.19.0). Dotąd brany był początek
    notatki, więc pasujący akapit dalej w długiej notatce nie docierał do
    modelu. Krótka notatka wraca w całości; bez trafień - jej początek.
    Wycięte fragmenty zaznaczone "(...)"."""
    body = strip_title_and_type(note.text if hasattr(note, "text") else str(note))
    if len(body) <= limit:
        return body
    terms = _query_terms(query or "")
    positions = []
    if terms:
        for m in _WORD_RE.finditer(body):
            folded = slowa_mod.fold(m.group(0))
            if any(_term_level(t, {folded}, {slowa_mod.stem(folded)}) for t in terms):
                positions.append(m.start())
    if not positions:
        return body[:limit].rstrip() + " (...)"
    # Okno, które obejmuje najwięcej trafień (lewy brzeg na trafieniu, z zapasem
    # na kontekst przed nim).
    span = int(limit * 0.8)
    best_i, best_n, j = 0, 0, 0
    for i, pos in enumerate(positions):
        while j < len(positions) and positions[j] < pos + span:
            j += 1
        if j - i > best_n:
            best_i, best_n = i, j - i
    start = max(0, positions[best_i] - limit // 5)
    # Początek na granicy linii albo zdania, jeśli jest blisko.
    cut = max(body.rfind("\n", 0, start + 1), body.rfind(". ", 0, start + 1))
    if cut >= 0 and start - cut < 200:
        start = cut + 1
    start = min(start, max(0, len(body) - limit))
    end = min(len(body), start + limit)
    text = body[start:end].strip()
    return ("(...) " if start > 0 else "") + text + (" (...)" if end < len(body) else "")


# Słowa, które w zapytaniu do notatek niczego nie wyróżniają ("co to jest X", "jak działa Y",
# "pokaż notatki o Z"): gdyby liczyły się jak słowa kluczowe, "jest" pasowałoby prawie do
# każdej notatki i zapytanie o nieistniejący temat zwracało przypadkowe wyniki.
_SEARCH_STOP = frozenset(slowa_mod.fold(w) for w in slowa_mod.WSPOLNE | set("""
    wiem wiesz myślisz myslisz sądzisz sadzisz oceniasz uważasz uwazasz
    powiedz opowiedz wyjaśnij wyjasnij wytłumacz wytlumacz opisz działa dziala działają dzialaja znaczy oznacza
    znajdź znajdz pokaż pokaz szukaj wyszukaj poszukaj sprawdź sprawdz
    notatki notatkach notatka notatkę notatek notatce notatkami
    """.split()) | slowa_mod.KROTKIE_POMIJANE)


def search_terms(query: str) -> list[str]:
    """Słowa zapytania do `Vault.search`: po złożeniu znaków (slowa.fold), bez
    słów pytających i "kleju" (_SEARCH_STOP), różne, najwyżej 12 (wklejony długi
    tekst dawałby tysiące porównań w KAŻDEJ notatce). Od 1.19.0 zostają też
    dwuliterowe skróty ("AI", "UI"); rdzenie liczy dopiero _query_terms."""
    words = [slowa_mod.fold(t) for t in re.findall(r"\w+", query[:2000]) if len(t) >= 2]
    kept = [w for w in words if w not in _SEARCH_STOP]
    return list(dict.fromkeys(kept))[:12]


def strip_title_and_type(text: str) -> str:
    """Treść notatki bez PIERWSZEGO nagłówka H1 i linii `type:`. Wzorce są te
    same co przy wczytywaniu (TITLE_RE, FRONTMATTER_TYPE_RE): luźniejsze `^#.*$`
    wycinałoby też pierwszą linię `## Sekcja` albo `#tag` z notatki bez H1."""
    masked = mask_code(text)
    m = _title_match(text, masked)
    if m:
        text, masked = text[:m.start()] + text[m.end():], masked[:m.start()] + masked[m.end():]
    m = _TYPE_LINE_RE.search(masked, 0, _header_end(masked))
    if m:
        text = text[:m.start()] + text[m.end():]
    return text.strip()


def normalize_title(title: str) -> str:
    # Scal ciągi białych znaków (spacje, tabulatory, a zwłaszcza znak nowej
    # linii) do pojedynczej spacji: [[wikilink]], który w pliku zawinął się
    # na dwie linie, znaczy ten sam tytuł co jednoliniowy. Tytuł z `# ...`
    # jest jednoliniowy, więc to go nie zmienia.
    # NFC: "ó" zapisane jako o + akcent (macOS, niektóre edytory) to ten sam tytuł.
    return " ".join(unicodedata.normalize("NFC", title).split()).lower()


_PL_EXTRA = str.maketrans({"ł": "l", "Ł": "L"})  # ł nie rozkłada się w NFKD na l + znak


def slugify(title: str, max_len: int = 50, default: str = "notatka") -> str:
    """Zamienia tytuł na bezpieczną nazwę pliku, używane przy tworzeniu
    nowej notatki z poziomu interfejsu grafu."""
    normalized = unicodedata.normalize("NFKD", title.translate(_PL_EXTRA)).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:max_len].strip("-") or default


# Jeden przebieg po znakach znaczących: wyrażenie regularne z "{0,1000}" na strumieniu
# pełnym "\(" (każdy nawias to kandydat na początek łańcucha) liczyło się minutami.
_PDF_TOKEN = re.compile(rb"\\.|\(|\)|\[|\]|Tj|TJ")
_PDF_MAX_STRING = 1000
_PDF_MAX_ARRAY = 500


def _pdf_text_strings(stream: bytes) -> list:
    """Łańcuchy z operatorów Tj ((tekst) Tj) i TJ ([ (tekst) liczba (tekst) ] TJ),
    w kolejności wystąpienia. Nawiasy w łańcuchu mogą być zagnieżdżone albo
    uciekane ("\\("); nawias domknięty = koniec łańcucha. Liniowe względem
    długości strumienia."""
    out = []
    depth = 0
    start = 0
    last = None       # (łańcuch, pozycja za ")") ostatniego domkniętego łańcucha
    array = None      # łańcuchy od ostatniego "[" (None = poza tablicą)
    closed_array = None
    for m in _PDF_TOKEN.finditer(stream):
        tok = m.group(0)
        if tok[:1] == b"\\":
            continue
        if tok == b"(":
            if depth == 0:
                start = m.end()
            depth += 1
            continue
        if tok == b")":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0:
                s = stream[start:m.start()]
                last = (s, m.end()) if len(s) <= _PDF_MAX_STRING else None
                if array is not None and last is not None and len(array) < _PDF_MAX_ARRAY:
                    array.append(s)
            continue
        if depth > 0:
            continue  # "[", "Tj" wewnątrz łańcucha to zwykły tekst
        if tok == b"[":
            array = []
        elif tok == b"]":
            closed_array = (array, m.end()) if array is not None else None
            array = None
        elif tok == b"Tj":
            # Łańcuch zużyty albo odrzucony: bez zerowania każde kolejne "Tj" wycinało
            # strumień od ostatniego ")" (4 KB pliku = kwadratowy czas, serwer stał).
            if last is not None and _pdf_adjacent(stream, last[1], m.start()):
                out.append(last[0])
            last = None
        elif tok == b"TJ":
            if closed_array is not None and _pdf_adjacent(stream, closed_array[1], m.start()):
                out.append(b"".join(closed_array[0]))  # jedna tablica = jeden kawałek tekstu
            closed_array = None
    return out


def _pdf_adjacent(stream: bytes, a: int, b: int) -> bool:
    """Między ")" / "]" a operatorem tylko białe znaki (i niewiele: w prawdziwym PDF
    to spacja albo nowa linia; długa przerwa to nie ten sam łańcuch)."""
    return 0 <= b - a <= 64 and not stream[a:b].strip()


def _pdf_unescape(raw: bytes) -> str:
    return re.sub(rb"\\([()\\])", rb"\1", raw).decode("latin-1", errors="ignore")


def _extract_pdf_text(data: bytes) -> str:
    """
    Minimalna ekstrakcja tekstu z PDF bez zewnętrznych bibliotek.
    Działa dla prostych, nieszyfrowanych PDF-ów ze strumieniami Flate.
    Może nie odczytać wszystkiego: to świadomy kompromis (brak zależności).
    Wszystko liniowe i z limitami: strumienie znajdujemy przez split (nie
    regex z leniwym .*?), rozpakowanie jest ucięte (bomba dekompresji), a
    operator Tj ma ograniczoną długość łańcucha.
    """
    text_chunks = []
    total = 0
    for part in data.split(b"endstream"):
        idx = part.find(b"stream")
        if idx < 0:
            continue
        chunk = part[idx + len(b"stream"):]
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        try:
            decompressed = zlib.decompressobj().decompress(chunk, PDF_MAX_STREAM_BYTES)
        except Exception:
            continue
        total += len(decompressed)
        if total > PDF_MAX_TOTAL_BYTES:
            break
        # Tekst z operatorów Tj (jeden łańcuch) i TJ (tablica łańcuchów); łańcuch
        # to (...) z dozwolonym \\ -ucieczką, więc "(a\\\\)" kończy się poprawnie.
        if b"Tj" not in decompressed and b"TJ" not in decompressed:
            continue  # strumień bez operatorów tekstu (obraz, czcionka): nie ma czego szukać
        for s in _pdf_text_strings(decompressed):
            text_chunks.append(_pdf_unescape(s))
    return "\n".join(text_chunks)


def _read_file(path: Path) -> tuple[str, bool]:
    """-> (tekst, lossy). UTF-8 (z BOM lub bez) czytamy wiernie; plik w innym
    kodowaniu (zwykle Windows-1250) dekodujemy jako cp1250 tylko do podglądu i
    wyszukiwania, i oznaczamy jako lossy (tylko do odczytu). Końce linii
    CRLF/CR zamieniamy na LF, jak robił to tryb tekstowy."""
    data = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_text(data), False
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        # UTF-16 z BOM (Notatnik Windows "Unicode"): jako cp1250 dawałoby NUL między literami.
        text, lossy = data.decode("utf-16", errors="replace"), True
    else:
        try:
            text, lossy = data.decode("utf-8-sig"), False
        except UnicodeDecodeError:
            text, lossy = data.decode("cp1250", errors="replace"), True
    return text.replace("\r\n", "\n").replace("\r", "\n"), lossy


def file_style(path: Path) -> tuple[bool, bool]:
    """(BOM, czyste CRLF) pliku na dysku. _read_file zamienia je na LF bez BOM, więc
    zapis musi je przywrócić (restyle): inaczej jedna zmiana tytułu przepisuje cudze
    pliki w innym kodowaniu końców linii i zaśmieca różnice w git albo synchronizacji."""
    try:
        data = path.read_bytes()
    except OSError:
        return False, False
    newlines = data.count(b"\n")
    return data.startswith(b"\xef\xbb\xbf"), newlines > 0 and data.count(b"\r\n") == newlines


def restyle(text: str, bom: bool, crlf: bool) -> str:
    """Tekst (z końcami linii LF) w stylu pliku, który nadpisujemy."""
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return "\ufeff" + text if bom else text


def _slug_for(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return str(rel).replace("\\", "/")


def _candidate_files(root: Path, vault: "Vault") -> List[Path]:
    """Pliki pod `root` w stałej kolejności, bez schodzenia do katalogów ukrytych (.git,
    .obsidian, .trash) i node_modules: katalog notatek będący repozytorium git miał tam
    dziesiątki tysięcy plików, przeglądanych przy KAŻDEJ budowie indeksu. Ukryte katalogi
    liczymy względem KORZENIA: projekt leżący pod katalogiem o takiej nazwie nie może przez
    to nie zaindeksować niczego. Dowiązania do katalogów są pomijane (z adnotacją)."""
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS or d.startswith("."):
                continue
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                vault.skipped.append(f"{_printable(full)} (dowiązanie do katalogu)")
                continue
            keep.append(d)
        dirnames[:] = keep
        found.extend(Path(dirpath, f) for f in filenames)
    found.sort(key=lambda q: (q.with_suffix("").as_posix(), q.suffix))
    return found


def disk_signature(roots: List[str]) -> int:
    """Tani odcisk stanu plików, które indeksuje build_vault (ścieżka, rozmiar,
    czas zmiany): gdy się zmienił, notatki zmieniono poza interfejsem (edytor,
    menedżer plików) i trzeba zbudować vault od nowa. Nie czyta zawartości."""
    entries = []
    for root_str in roots:
        for dirpath, dirnames, filenames in os.walk(root_str):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                if os.path.splitext(name)[1].lower() not in SUPPORTED_SUFFIXES:
                    continue
                try:
                    st = os.stat(os.path.join(dirpath, name))
                except OSError:
                    continue
                entries.append((dirpath, name, st.st_size, st.st_mtime_ns))
    return hash(tuple(sorted(entries)))


def text_version(text: str) -> str:
    """Znacznik wersji treści notatki: edytor odsyła go przy zapisie, a serwer
    odmawia, gdy plik na dysku jest już inny (ktoś zmienił go w międzyczasie)."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


# Wyciągnięty tekst z PDF-ów, kluczem (ścieżka, rozmiar, czas zmiany): odbudowa grafu po
# zmianie JEDNEJ notatki nie rozpakowuje ponownie wszystkich PDF-ów (to najdroższy krok).
_PDF_CACHE: Dict[tuple, str] = {}


def build_vault(roots: List[str]) -> Vault:
    vault = Vault()
    pdf_seen: Set[tuple] = set()

    # Pierwszy przebieg: wczytaj wszystkie notatki
    for root_str in roots:
        root = Path(root_str)
        if not root.exists():
            vault.errors.append(f"Folder nie istnieje: {root_str}")
            continue

        try:
            root.resolve(strict=True)  # korzeń musi być osiągalny (zepsute dowiązanie = błąd, nie pusty graf)
        except OSError as e:
            vault.errors.append(f"{root_str}: {e}")
            continue

        # sorted(): kolejność przeglądania nie zależy od systemu plików, więc
        # dwie notatki o tym samym tytule zawsze rozstrzygają się tak samo.
        # Klucz bez rozszerzenia: "alfa.md" przed "alfa-2.md" (inaczej "-" < "."
        # oddawałoby linki nowszej kopii), czyli pierwsza utworzona notatka wygrywa.
        for path in _candidate_files(root, vault):
            try:
                if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                try:
                    str(path).encode("utf-8")
                except UnicodeEncodeError:
                    # Nazwa nie jest w UTF-8: slug z takiej nazwy zepsułby JSON całego grafu.
                    vault.skipped.append(f"{_printable(str(path))} (nazwa pliku nie jest w UTF-8)")
                    continue
                if path.is_symlink():
                    # Poza folderem: cudzy plik; wewnątrz: ta sama notatka pod drugą nazwą (link
                    # wskazywałby dowiązanie, a zapis jednej dawał konflikt wersji w drugiej).
                    vault.skipped.append(f"{_printable(str(path))} (dowiązanie do pliku)")
                    continue
                st = path.stat()
                if not stat.S_ISREG(st.st_mode):
                    # FIFO, gniazdo, urządzenie: otwarcie do odczytu zawiesiłoby budowę całego grafu.
                    vault.skipped.append(f"{_printable(str(path))} (nie jest zwykłym plikiem)")
                    continue
                if st.st_size > MAX_FILE_BYTES:
                    vault.skipped.append(f"{path} (> 2 MB)")
                    continue
            except (OSError, RuntimeError, ValueError) as e:  # RuntimeError: pętla dowiązań (starszy Python)
                vault.errors.append(_printable(f"{path}: {e}"))
                continue

            is_pdf = path.suffix.lower() == ".pdf"
            pdf_key = (str(path), st.st_size, st.st_mtime_ns)
            try:
                if is_pdf and pdf_key in _PDF_CACHE:
                    text, lossy = _PDF_CACHE[pdf_key], False
                else:
                    text, lossy = _read_file(path)
                    if is_pdf:
                        _PDF_CACHE[pdf_key] = text
                if is_pdf:
                    pdf_seen.add(pdf_key)
            except Exception as e:
                vault.errors.append(_printable(f"{path}: {e}"))
                continue

            masked = mask_code(text)  # raz na notatkę: to większość czasu budowy indeksu
            ntype = find_type(text, masked) or "Note"
            title = find_title(text, masked) or path.stem

            slug = _slug_for(path, root)
            # Ta sama względna nazwa w dwóch korzeniach (np. python.md w notatki/
            # i w wiki_cache/) nie może się nawzajem nadpisać: kolejny korzeń
            # dostaje przedrostek z nazwą swojego folderu. Pierwszy korzeń
            # (notatki użytkownika) zawsze zachowuje zwykły slug.
            if slug in vault.notes:
                base, counter = f"{root.name}/{slug}", 2
                slug = base
                while slug in vault.notes:
                    slug = f"{base}#{counter}"
                    counter += 1
            raw_links = find_wikilinks(text, masked)

            note = Note(
                slug=slug,
                path=str(path),
                title=title,
                ntype=ntype,
                text=text,
                raw_links=raw_links,
                lossy=lossy,
            )
            vault.notes[slug] = note
            vault.by_title.setdefault(normalize_title(title), slug)

    for stale in [k for k in _PDF_CACHE if k not in pdf_seen]:
        _PDF_CACHE.pop(stale, None)  # PDF usunięty albo zmieniony

    # Drugi przebieg: rozwiąż [[wikilinks]] na slugi. Dokładny tytuł pierwszy; potem
    # tytuł bez ogonków ([[Kanal YouTube]]) i nazwa/ścieżka pliku ([[iphone-flip-sop]]).
    by_fold: Dict[str, str] = {}
    by_file: Dict[str, str] = {}
    for s, n in vault.notes.items():
        by_fold.setdefault(slowa_mod.fold(normalize_title(n.title)), s)
        base = normalize_title(re.sub(r"\.(md|txt|pdf)$", "", s, flags=re.I))
        by_file.setdefault(base, s)
        by_file.setdefault(base.rsplit("/", 1)[-1], s)
    for note in vault.notes.values():
        for raw in note.raw_links:
            key = normalize_title(raw)
            target_slug = (vault.by_title.get(key) or by_fold.get(slowa_mod.fold(key))
                           or by_file.get(re.sub(r"\.(md|txt|pdf)$", "", key)))
            if target_slug and target_slug != note.slug:
                note.links.add(target_slug)

    return vault
