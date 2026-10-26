"""
bramka.py (1.32.0)

Bramka odpowiedzi: ostatnia kontrola tekstu MODELU, zanim trafi do Grzegorza.
Wzorowana na hakach "Stop" i "code-based graders" z everything-claude-code
(skills/eval-harness: "deterministyczne > probabilistyczne"), ale zamiast
ostrzegać programistę - naprawia albo zapisuje w śladzie (Nadzorca).

Każdy oceniacz to czysta funkcja tekst -> znalezisko; bez modelu, bez sieci,
w milisekundach. Narodziły się z prawdziwych wpadek (rozmowa z 23.10.2026):

  brak_internetu      "Nie mam dostępu do internetu" - gdy internet DZIAŁA.
                      Zdanie usuwane, w jego miejsce prawda: mogę sprawdzić.
  tozsamosc           "Jestem LFM od Liquid AI", "trenowany przez badaczy z
                      NVIDIA" - model z puli mówi o sobie, nie o GREGAI.
                      Zdania usuwane; gdy zostałoby niewiele - odpowiedź z
                      tools.self_model (prawda z konfiguracji).
  pytania_pomocnicze  wewnętrzny plan Namysłu w odpowiedzi ("Odpowiedzi na
                      pytania pomocnicze") - linia usuwana.
  markdown            niedomknięte ** (gwiazdki na ekranie) - domykane/usuwane.
  obcy_jezyk          angielskie słówka w polskim zdaniu ("trają po 12
                      godzin each") - tylko odnotowane (poprawa wymagałaby
                      modelu, a ryzyko zepsucia cytatu jest większe niż zysk).
  urwane              długa odpowiedź kończąca się w pół zdania - odnotowane.

Zasada: bramka NIGDY nie dopisuje faktów. Usuwa nieprawdę o samym GREGAI i
dokłada tylko zdania o jego własnych możliwościach (które zna kod).
"""

from __future__ import annotations

import re

# --- Wzorce --------------------------------------------------------------------

_NO_INTERNET_RE = re.compile(
    r"\bnie\s+mam\s+(?:teraz\s+|obecnie\s+|bezpośredniego\s+)?(?:dostępu|dostepu|połączenia|polaczenia)\s+(?:do|z)\s+"
    r"(?:internetu|sieci|aktualnych\s+danych\s+z\s+(?:internetu|sieci))"
    # 1.32.2: tylko "brak MI dostępu" - "NetworkManager pokazuje brak dostępu do internetu"
    # to poprawna diagnoza (audyt tura 7, rozmowa o karcie LTE).
    r"|\bbrak\s+mi\s+(?:dostępu|dostepu)\s+do\s+internetu"
    r"|\bnie\s+(?:mogę|moge|potrafię|potrafie)\s+(?:przeglądać|przegladac|przeszukiwać|przeszukiwac)\s+(?:internetu|sieci)"
    r"|\bnie\s+(?:mogę|moge)\s+(?:pobrać|pobrac|sprawdzić|sprawdzic)\s+(?:aktualnych\s+)?(?:danych|informacji)?\s*(?:z|w)\s+(?:internetu|internecie|sieci)"
    r"|\bnie\s+mam\s+możliwości\s+(?:przeglądania|sprawdzenia)\s+(?:internetu|sieci)",
    re.IGNORECASE,
)
# Przegląd 1.32.0 (H3): sama nazwa po "jestem" NIE wystarcza ("Jestem Gemini z urodzenia"
# w tekście na profil); potrzebny kontekst modelu/asystenta w tym samym zdaniu. Reguła
# "moja architektura" usunięta ("Moja architektura domu to dwa piętra").
_MODEL_NAMES = r"(?:LFM\w*|GPT[\w\-.]*|ChatGPT|Llam\w*|Gemm\w*|Gemini|Qwen\w*|Mistral\w*|Claude|DeepSeek\w*|Phi[\w\-]*)"
_IDENTITY_RE = re.compile(
    r"\bjestem\s+(?:modelem\s+(?:językowym\s+|jezykowym\s+)?|asystentem\s+)?" + _MODEL_NAMES +
    r"\b[^.!?\n]{0,80}?\b(?:model\w*|asystent\w*|LLM|sztuczn\w+\s+inteligencj\w+|AI\b|stworzon\w*|wytrenowan\w*|"
    r"opracowan\w*|firmy|od\s+(?:Liquid|OpenAI|Google|Meta|Anthropic|Alibab\w*|Mistral|NVIDIA|Microsoft))"
    r"|\bjestem\s+(?:modelem\s+(?:językowym\s+|jezykowym\s+)?)" + _MODEL_NAMES + r"\b"
    r"|\b(?:jestem|zostałem|zostalem|zostałam)\s+(?:\w+\s+){0,3}?(?:stworzon\w*|wytrenowan\w*|trenowan\w*|opracowan\w*|"
    r"zaprojektowan\w*|zbudowan\w*)\s+(?:\w+\s+){0,2}?(?:przez|w)\s+(?:zespół\s+|firm\w+\s+|badaczy\s+(?:z\s+)?)?"
    r"(?:Liquid\s*AI|NVIDIA|OpenAI|Meta\b|Google|Mistral|Alibab\w*|Anthropic|DeepSeek|Microsoft|MIT)",
    re.IGNORECASE,
)
# Fragmenty nietykalne: bloki i wstawki kodu, adresy, cytaty („…”, "…"). Bramka ich nie
# ocenia i nie zmienia (przegląd 1.32.0, H3: `2 ** 10`, cytat błędnego zdania w recenzji).
_PROTECT_RE = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+|„[^”\n]{0,400}”|\"[^\"\n]{0,400}\"", re.DOTALL)
_HELPER_HEAD_RE = re.compile(r"^\W*(?:odpowiedzi\s+na\s+)?pytania\s+pomocnicze\W*$", re.IGNORECASE)
_EN_WORDS = frozenset({"each", "however", "therefore", "which", "although", "because", "without", "whereas",
                       "largest", "truly", "needed", "visibility", "learnings", "overall", "key", "update", "insights",
                       "meanwhile", "furthermore", "moreover", "basically", "actually", "anyway",
                       # 1.32.16 (audyt tura 18): anglicyzmy z codziennej, biznesowo-technicznej polszczyzny
                       # (projekty Grzegorza: flipowanie iPhone'ów, strony internetowe, GREGAI) - "feedback",
                       # "deadline", "workflow", "framework", "issue" nie były nawet odnotowywane.
                       "feedback", "deadline", "workflow", "framework", "issue"})
_POLISH_CHARS_RE = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_WORD_RE = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+")
_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+", re.DOTALL)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9„\"(])")
_END_OK_RE = re.compile(r"[.!?…)\]\"”':;>`*]\s*$|^\s*[-*•]|\d\s*$")

# 1.32.3 (audyt tura 8): jedna propozycja, nie trzy (zasada "jedna konkretna propozycja").
INTERNET_NOTE = "Mogę to sprawdzić w internecie: napisz „sprawdź w internecie” i temat."


# 1.32.5: cena rynkowa z pamięci modelu. W rozmowie GREGAI podał "srebro $24,90 za uncję",
# choć narzędzie notowań dwa razy nie odpowiedziało - liczba była zmyślona (stara, z treningu).
# Cena przy temacie rynkowym, której cyfr nie ma ani w wiadomości, ani w ostatnich turach
# (tam trafiają wyniki narzędzi), nie dociera do Grzegorza.
# Przegląd 1.32.6: temat w TYM SAMYM zdaniu co cena i tylko instrumenty (nie "złotych" jako
# waluta, nie "kurs angielskiego"); liczby porównywane wartością (+-0,5%), nie podciągiem cyfr;
# wolno też liczbę wyliczoną z dwóch liczb ze źródeł (przeliczenie kursem, gram z uncji).
_MARKET_TOPIC_RE = re.compile(
    r"(?i)(?<!\w)(?:złoto|złota|zloto|zlota|srebr\w*|platyn\w*|pallad\w*|uncj\w*|bitcoin\w*|btc|ethereum|eth|"
    r"solan[aąy]|xau\w*|xag\w*|ropy|ropa|baryłk\w*|akcj[aeiy]\w*|notowani\w*|"
    r"kurs\w*\s+(?:dolar\w*|euro|frank\w*|funt\w*|usd|eur|chf|gbp|złota|zlota|srebra|bitcoin\w*|btc|akcji))(?!\w)")
_PRICE_RE = re.compile(r"(?i)(?:[$€£]\s?\d[\d\s.,]*\d|[$€£]\s?\d|\d[\d\s.,]*\s?(?:\$|€|£|usd|pln|zł|zl|eur|dolar\w*|euro|złot(?:y|ych|e)\b))")
_NUM_RE = re.compile(r"\d[\d\s]*(?:[.,]\d+)?")
_SENT_RE = re.compile(r"(?<!\bok\.)(?<!\bnp\.)(?<!\bca\.)(?<!\btj\.)(?<!\bgodz\.)(?<=[.!?…])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9„\"(])")
UNVERIFIED_PRICE_NOTE = ("Nie podam ceny z pamięci, bo byłaby zgadywana i pewnie nieaktualna. Napisz na przykład "
                         "„sprawdź kurs srebra”, a pobiorę notowanie z sieci; jeśli serwis nie odpowie, powiem to wprost.")


def _num(s: str):
    s = re.sub(r"\s", "", s or "")
    if s.count(",") == 1 and s.count(".") <= 1 and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(text or ""):
        v = _num(m.group(0))
        if v is not None and v > 0:
            out.append(v)
    return out[:60]


def _covered(v: float, src: list[float]) -> bool:
    close = lambda a, b: abs(a - b) <= max(0.005 * max(abs(a), abs(b)), 0.006)
    if any(close(v, x) for x in src):
        return True
    for a in src:
        for b in src + [31.1035]:
            if close(v, a * b) or (b and close(v, a / b)):
                return True
    return False


def _unverified_prices(text: str, sources: str) -> list[str]:
    """Zdania z ceną instrumentu bez pokrycia w źródłach; [] = wszystko w porządku."""
    src = _numbers(sources)
    bad = []
    for sent in _SENT_RE.split(text or ""):
        if not _MARKET_TOPIC_RE.search(sent):
            continue
        for m in _PRICE_RE.finditer(sent):
            v = _num(_NUM_RE.search(m.group(0)).group(0)) if _NUM_RE.search(m.group(0)) else None
            if v is not None and not _covered(v, src):
                bad.append(sent)
                break
    return bad


def _finding(kod: str, opis: str, waga: str, poprawione: bool) -> dict:
    return {"kod": kod, "opis": opis, "waga": waga, "poprawione": poprawione}


def _drop_sentences(text: str, rx: re.Pattern) -> tuple[str, int, int]:
    """Usuwa zdania pasujące do `rx` (linia po linii, zdanie po zdaniu). Zwraca
    (nowy tekst, liczba usuniętych zdań, liczba usuniętych znaków)."""
    out_lines, n, chars = [], 0, 0
    for line in text.split("\n"):
        if not rx.search(line):
            out_lines.append(line)
            continue
        parts = _SENT_SPLIT_RE.split(line)
        keep = []
        for p in parts:
            if rx.search(p):
                n += 1
                chars += len(p)
            else:
                keep.append(p)
        joined = " ".join(keep).strip()
        if joined or not line.strip():
            out_lines.append(joined)
    new = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    return new, n, chars


def _foreign_words(text: str) -> list[str]:
    plain = _CODE_RE.sub(" ", text)
    plain = re.sub(r"„[^”]{0,200}”|\"[^\"]{0,200}\"", " ", plain)  # cytaty zostawiamy
    if not _POLISH_CHARS_RE.search(plain):
        return []  # tekst nie po polsku (np. kod, angielski cytat) - nie oceniamy
    found = []
    for line in plain.split("\n"):
        words = _WORD_RE.findall(line)
        if len(words) < 4:
            continue
        en = [w for w in words if w.lower() in _EN_WORDS]
        if en and _POLISH_CHARS_RE.search(line):
            found.extend(en)
    return list(dict.fromkeys(found))[:5]


def _value(x):
    return x() if callable(x) else x


def _protect(text: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def sub(m: "re.Match") -> str:
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    return _PROTECT_RE.sub(sub, text), kept


def _restore(text: str, kept: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))] if int(m.group(1)) < len(kept) else "", text)


def review(text: str, internet=True, self_model_text=None, pisanie: bool = False,
           zrodla=None) -> tuple[str, list[dict]]:
    """(poprawiony tekst, znaleziska). `internet` = czy bramka WARP jest otwarta
    (fałszywe "nie mam internetu" poprawiamy tylko, gdy to naprawdę nieprawda).
    `self_model_text` = prawdziwa odpowiedź o tożsamości (tools.self_model), gdy
    po usunięciu cudzej tożsamości zostałoby za mało treści. Oba mogą być
    funkcjami: liczone dopiero, gdy wzorzec coś znajdzie (zwykła odpowiedź nie
    płaci za sprawdzenie WARP ani za składanie tekstu o modelach)."""
    if not text or not text.strip():
        return text, []
    findings: list[dict] = []
    original = text
    text, kept = _protect(text)

    # 1. Fałszywe "nie mam dostępu do internetu". Nie w tekście pisanym DLA Grzegorza
    #    (SMS, mail, post: "dziś nie mam dostępu do internetu" to jego zdanie, nie GREGAI).
    if not pisanie and _NO_INTERNET_RE.search(text) and _value(internet):
        new, n, _c = _drop_sentences(text, _NO_INTERNET_RE)
        text = (new + ("\n\n" if new else "") + INTERNET_NOTE).strip()
        findings.append(_finding("brak_internetu", f"odpowiedź twierdziła, że nie ma internetu ({n} zd.), a bramka WARP jest otwarta",
                                 "krytyczna", True))

    # 2. Cudza tożsamość (też nie w tekście pisanym dla Grzegorza)
    if not pisanie and _IDENTITY_RE.search(text):
        self_model_text = _value(self_model_text)
        before = len(text)
        new, n, chars = _drop_sentences(text, _IDENTITY_RE)
        if self_model_text and (not new.strip() or chars > 0.4 * before):
            text, kept = _protect(self_model_text)
        else:
            text = new or (self_model_text or "")
        findings.append(_finding("tozsamosc", f"model przedstawił się jako ktoś inny niż GREGAI ({n} zd.)", "krytyczna", True))

    # 3. Pytania pomocnicze Namysłu
    lines = text.split("\n")
    kept_lines = [ln for ln in lines if not _HELPER_HEAD_RE.match(ln.strip())]
    if len(kept_lines) != len(lines):
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
        findings.append(_finding("pytania_pomocnicze", "w odpowiedzi był nagłówek wewnętrznego planu Namysłu", "poprawialna", True))

    # 3b. Cena rynkowa bez źródła (zrodla = wiadomość + ostatnie tury; None = nie sprawdzamy)
    _bad = _unverified_prices(text, _value(zrodla) or "") if (not pisanie and zrodla is not None) else []
    if _bad:
        new = " ".join(x for x in _SENT_RE.split(text) if x not in _bad).strip()
        n = len(_bad)
        text = (new + ("\n\n" if new else "") + UNVERIFIED_PRICE_NOTE).strip()
        findings.append(_finding("cena_bez_zrodla", f"cena rynkowa bez wyniku narzędzia ({n} zd.)", "krytyczna", True))

    # 4. Niedomknięte pogrubienie - w KAŻDEJ linii osobno (1.32.14: dwie niedomknięte w różnych
    #    liniach dawały parzystą liczbę gwiazdek i obie zostawały widoczne).
    _lines = text.split("\n")
    _fixed_bold = 0
    for _i, _ln in enumerate(_lines):
        if _ln.count("**") % 2 == 1:
            _j = _ln.rfind("**")
            _lines[_i] = _ln[:_j] + _ln[_j + 2:]
            _fixed_bold += 1
    if _fixed_bold:
        text = "\n".join(_lines)
        findings.append(_finding("markdown", f"niedomknięte ** w {_fixed_bold} lin. (gwiazdki byłyby widoczne)", "poprawialna", True))
    # 4b. Wołacz: "Grzegorz" jako zwrot do Ciebie -> "Grzegorzu"; nazwisko zostaje bez zmian
    # ("Grzegorz Żelazowski" - stąd blokada, gdy po imieniu idzie kolejne słowo z wielkiej litery).
    # 1.32.16 (audyt tura 18): dawniej tylko konkretne słowo grzecznościowe PRZED imieniem
    # ("Cześć Grzegorz", "Dzięki Grzegorz") - a "Grzegorz, zrobiłem to", "Powiem wprost,
    # Grzegorz:", "Słuchaj Grzegorz," zostawały bez poprawki, mimo że to ten sam zwrot wprost
    # do Ciebie, tylko gdzie indziej w zdaniu. Teraz: samo imię "Grzegorz" (nie dłuższe słowo),
    # niepoprzedzone bezpośrednio literą/myślnikiem (więc nie środek innego słowa) i
    # nieposzone od razu kolejnym słowem z wielkiej litery (nazwisko) - to zawsze zwrot do
    # Ciebie w tej jednoosobowej rozmowie.
    # 1.32.18 (audyt tura 20/20): to jednak myliło zwrot wprost do Ciebie z "Grzegorz" jako
    # PODMIOTEM zdania w trzeciej osobie ("Grzegorz zdecydował się...", "...: Grzegorz prosił
    # o pomoc") - częste, gdy model odtwarza Twoją własną wcześniejszą decyzję z notatek albo
    # streszczenia rozmowy. Czasownik czasu przeszłego trzeciej osoby w rodzaju męskim
    # zawsze kończy się na gołe "ł" (zdecydował, prosił, chciał, mógł) - inaczej niż w zwrocie
    # wprost do Ciebie, gdzie po imieniu idzie przecinek/dwukropek albo inne słowo. Gdy
    # kolejne słowo jest takim czasownikiem, to podmiot, nie wołacz - zostaje bez zmian.
    # 1.32.21 (przygotowanie pod open source, tura 3/5): dawniej literał "Grzegorz" ->
    # "Grzegorzu" na trwałe. Teraz persona.USER_NAME/USER_NAME_VOCATIVE (domyślnie
    # dokładnie te same wartości - zero zmiany zachowania, dopóki nikt nie ustawi
    # .env). Gdy ktoś poda inne imię, wołacz działa poprawnie TYLKO jeśli sam poda
    # też poprawną formę wołacza (patrz persona.py) - nie próbujemy zgadywać
    # polskiej deklinacji automatycznie.
    # 1.32.23 (przygotowanie pod open source, tura 5/5): blokada podmiotu była tylko dla
    # czasownika w rodzaju męskim (gołe "ł" - "zdecydował", "prosił"). Gdy GREGAI_USER_GENDER
    # ustawiony na żeński, model odtwarzający trzecioosobowy opis Ciebie użyje żeńskiej/
    # neutralnej formy ("zdecydowała", "chciało") - bez tej poprawki takie zdanie błędnie
    # trafiałoby w wołacz. Teraz blokada łapie też "-ła"/"-ło" na końcu słowa.
    import persona as persona_mod
    _own_name = re.escape(persona_mod.USER_NAME)
    _voc = re.subn(
        rf"(?<![\w-]){_own_name}(?![a-ząćęłńóśźż])(?!\s+[A-ZĄĆĘŁŃÓŚŹŻ])(?!\s+\w{{2,}}(?:ł|ła|ło)\b)",
        persona_mod.USER_NAME_VOCATIVE, text)
    if _voc[1]:
        text = _voc[0]
        findings.append(_finding("wolacz", f"„{persona_mod.USER_NAME}” zamiast wołacza „{persona_mod.USER_NAME_VOCATIVE}”", "poprawialna", True))
    # 4c. Formułka na końcu ("Cieszę się, że mogłem pomóc", "...daj znać.") - bez niej, gdy coś zostaje.
    _paras = text.rstrip().split("\n")
    while len(_paras) > 1 and re.match(r"(?i)^\W*(cieszę się, że mogłem pomóc|jeśli (?:chcesz|potrzebujesz|będziesz potrzebowa[łl])[^.?!]{0,120}daj znać|daj znać[,.!]?\s*$|możemy też sprawdzić|smacznego!?\s*$|w razie pytań[^.]{0,80}daj znać)", _paras[-1].strip()):
        _paras.pop()
        while _paras and not _paras[-1].strip():
            _paras.pop()
        findings.append(_finding("formulka", "formułka asystenta na końcu odpowiedzi", "poprawialna", True))
    if findings and findings[-1]["kod"] == "formulka":
        text = "\n".join(_paras)

    # 4d. Podwójne/wielokrotne spacje w środku linii (wcięcie na początku linii - listy,
    # cytaty - zostaje bez zmian). 1.32.16 (audyt tura 18): nic wcześniej tego nie łapało.
    _sp_lines = text.split("\n")
    _fixed_spaces = 0
    for _i, _ln in enumerate(_sp_lines):
        _m = re.match(r"^(\s*)(.*)$", _ln, re.DOTALL)
        _lead, _rest = _m.group(1), _m.group(2)
        _new_rest = re.sub(r" {2,}", " ", _rest)
        if _new_rest != _rest:
            _sp_lines[_i] = _lead + _new_rest
            _fixed_spaces += 1
    if _fixed_spaces:
        text = "\n".join(_sp_lines)
        findings.append(_finding("spacje", f"wielokrotne spacje w {_fixed_spaces} lin.", "poprawialna", True))

    # 5. Obce słowa (tylko odnotowane)
    en = _foreign_words(text)
    if en:
        findings.append(_finding("obcy_jezyk", "angielskie słowa w polskiej odpowiedzi: " + ", ".join(en), "informacja", False))

    text = _restore(text, kept)

    # 6. Urwane zakończenie (tylko odnotowane; na tekście po przywróceniu kodu i cytatów)
    tail = text.rstrip()
    if len(tail) > 200 and not tail.endswith("```") and not _END_OK_RE.search(tail.splitlines()[-1] if tail.splitlines() else tail):
        findings.append(_finding("urwane", "odpowiedź kończy się w pół zdania", "informacja", False))
    if not text.strip():
        text = original  # bramka nigdy nie zostawia pustej odpowiedzi
    return text, findings


def summary(findings: list[dict]) -> str:
    return "; ".join(f"{f['kod']}{'' if f['poprawione'] else ' (odnotowane)'}" for f in findings)
