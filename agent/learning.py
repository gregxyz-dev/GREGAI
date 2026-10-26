"""
learning.py

Samoucząca się warstwa routingu. Cel: każda fraza, dla której Ollama
POPRAWNIE rozpoznała narzędzie, a której nie złapał żaden RĘCZNY wzorzec
z capabilities.py, zostaje zapamiętana jako nowy, taki sam deterministyczny
wzorzec na przyszłość. Efekt: im więcej użytkownik rozmawia z GREGAI, tym
więcej ścieżek omija Ollamę całkowicie i trafia od razu. To nie jest
dotrenowanie modelu (to robi training/), tylko dopisywanie nowych skrótów z
prawdziwego użycia do wzorców z capabilities.py, bez restartu usługi i bez
udziału człowieka.

Filozofia całego projektu (deterministyczne > probabilistyczne) stosuje
się tu W DWÓJNASÓB, bo tym razem wzorzec nie jest pisany przez człowieka,
który może ocenić, czy jest bezpieczny: jest generowany automatycznie.
Stąd twarde zasady bezpieczeństwa niżej:

1. Uczymy się WYŁĄCZNIE z udanych rozpoznań Ollamy (model sam zawołał
   konkretne narzędzie), NIGDY z samej treści rozmowy czy zgadywania.
2. Uczymy się na słowach z FRAZY-WYZWALACZA, nie z TREŚCI argumentu
   (patrz _strip_arg): inaczej np. "zapamiętaj, że kupić mleko" nauczyłoby
   wzorzec na słowach "kupić"/"mleko", który następnym razem błędnie
   zapisałby jako fakt zupełnie inne pytanie, które przypadkiem też
   wspomina mleko (żywy przykład ryzyka, od którego to zabezpieczenie
   powstało, zanim jeszcze się zdarzyło, bo tu nie ma czasu czekać na
   błąd na produkcji).
3. Minimum 2 znaczące słowa: jedno słowo to zbyt słaby, zbyt ogólny
   sygnał, żeby bezpiecznie automatycznie generalizować.
4. Każdy nowy wzorzec jest sprawdzany pod kątem konfliktu z wzorcami
   JUŻ wyuczonymi dla INNYCH narzędzi (patrz learn_from_resolution):
   te same słowa nie mogą wskazywać na dwa różne narzędzia naraz. Gdy
   wykryty, nowy wzorzec NIE jest zapisywany (wolimy nie nauczyć się
   niczego, niż nauczyć się źle).
5. Zapisane deterministycznie jako zwykłe wzorce (?=.*\\bsłowo\\b), ten
   sam mechanizm co capabilities_mod.find_keyword_match, sprawdzane w
   router.py w tym samym miejscu, PRZED Ollamą: jednoznaczna, wyuczona
   komenda nie czeka już na model.

Plik danych: data/learned_routes.json (ten sam katalog i styl co
data/network_inventory.json w siec.py: zwykły json.dumps/loads, bez
blokad, bo to jedna osoba na jednym komputerze w sieci domowej).

Trzeci mechanizm w tym pliku (forget_route/forget_topic_words, niżej):
nauka w drugą stronę. Samouczenie się bez możliwości ODUCZENIA jest
jednostronne, czyli niebezpieczne na dłuższą metę: błędnie wyuczony
wzorzec zostałby na zawsze, mylące się w ten sam sposób w kółko.
router.py wykrywa, kiedy użytkownik explicite poprawia poprzednią
odpowiedź (CORRECTION_RE) i jeśli ta odpowiedź wynikała z czegoś, co
GREGAI wyuczył się SAM (nie z ręcznego wzorca w capabilities.py, tego
nie da się automatycznie wycofać), usuwa to konkretne nauczenie od
razu, zamiast czekać, aż pomyli się tak drugi raz.
"""

from __future__ import annotations

import functools
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import fsutil
import slowa as slowa_mod
import trace as trace_mod

DATA_DIR = Path(__file__).parent.parent / "data"
LEARNED_PATH = DATA_DIR / "learned_routes.json"

# Słowa-"kleje" (zaimki, spójniki, czasowniki pomocnicze): wspólny rdzeń z
# agent/slowa.py (1.18.0 - jedno źródło z wyszukiwaniem w notatkach, wcześniej
# dwie listy się rozjeżdżały) plus czasowniki-polecenia, które w odpowiedzi na
# dopytanie nie mówią, O CZYM mowa ("pokaż"). Długość >= 4 znaki (patrz
# significant_words) i tak odsiewa większość krótkich słówek.
STOPWORDS = slowa_mod.WSPOLNE | {
    "pokaż", "pokaz", "sprawdź", "sprawdz", "podaj", "powiedz", "wyświetl", "wyswietl", "zobacz", "daj",
    # 1.32.2 (audyt tura 7): słowa czasu nie niosą tematu - wyuczone ['dzis', 'pada'] z
    # "bedzie dzis padac?" łapało potem "dzis padam z nog po dowozach".
    "dzis", "dziś", "dzisiaj", "jutro", "teraz",
    "możecie", "musicie", "żebyście", "żebyśmy",  # były tu przed slowa.py (1.17.x)
}

# Tylko litery (żadnych cyfr: "4g"/"5g" i tak są już pokryte ręcznym
# wzorcem w capabilities.py, nie trzeba tego uczyć automatycznie).
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

MIN_SIGNIFICANT_WORDS = 2
MAX_SIGNIFICANT_WORDS = 4
# 1.32.16 (audyt tura 18): czasowniki/przysłówki tak częste w KAŻDYM poleceniu o
# obserwowaniu/informowaniu (niezależnie od tematu), że same, bez żadnego innego,
# konkretnego słowa w wyzwalaczu, nie są wystarczającym sygnałem - `_GENERIC_TRIGGER_STEMS`
# niżej, zaraz po definicji `_stem()` (potrzebuje jej, żeby dopasować dokładnie to, co
# widzi `significant_words`).
_GENERIC_TRIGGER_WORDS = (
    "sprawdzaj", "sprawdzac", "sprawdz", "codziennie", "regularnie", "stale", "ciagle",
    "zawsze", "czasami", "zmieni", "zmienia", "zmienilo", "zmienil",
    "informuj", "powiedz", "napisz", "przypomnij", "obserwuj", "monitoruj", "pilnuj",
    "sledz", "daj", "dawaj", "znac", "wiedziec",
)
MAX_LEARNED_ROUTES = 150
# Uczymy się tylko z krótkich poleceń. Z długiego wklejonego tekstu pierwsze
# cztery słowa to przypadkowe słowa, nie fraza-wyzwalacz.
MAX_LEARN_CHARS = 200
# Wyuczony wzorzec szuka słów w początku wiadomości (jak szybka ścieżka).
SCAN_CHARS = 1500

_CACHE: list[dict] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_READ_FAILED: set = set()


def _read_json(path: Path, default, valid):
    """JSON z pliku albo `default`. Plik nieczytelny lub o złym kształcie nie jest
    po cichu nadpisywany: trafia do `<nazwa>.corrupt-<data>`, żeby dało się go obejrzeć."""
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if valid(data):
            return data
    except OSError:
        # 1.29.0 (kontrola): chwilowy błąd odczytu (np. za dużo otwartych plików) to nie
        # uszkodzony plik: nie odsuwamy go, a zapis w tym przebiegu jest wstrzymany.
        _READ_FAILED.add(str(path))
        return default
    except Exception:
        pass
    fsutil.quarantine(path)
    return default


def _valid_routes(data) -> bool:
    return isinstance(data, list) and all(
        isinstance(r, dict) and isinstance(r.get("tool"), str)
        and isinstance(r.get("words"), list) and r["words"] and all(isinstance(w, str) and w for w in r["words"])
        for r in data)


# 1.30.31 (zgłoszenie Grzegorza: „Jak to nie masz dostepu do internetu” zostało
# zapamiętane jako komenda network_status ze słowami „dostęp, internet”): reakcja,
# pretensja albo pytanie retoryczne nie jest poleceniem. Model dobrze zgadł, że to o
# sieci, ale wzorzec z takiej frazy łapałby potem zwykłe zdania o internecie. Tych
# wiadomości nie uczymy się wcale, a już zapisane wzorce z takim przykładem znikają
# przy wczytaniu pliku.
_REACTION_RE = re.compile(
    r"\A\s*(?:jak\s+to|co\s+(?:ty|jest|ty\s+gadasz)|czemu|dlaczego|serio|naprawd[eę]|przecie[zż]|omg\w*|wtf|hmm+|ej+)\b"
    r"|\b(?:nie|bez|nigdy|zamiast|żadn\w*)\b",
    re.IGNORECASE,
)


def is_reaction(message: str) -> bool:
    return bool(_REACTION_RE.search((message or "")[:SCAN_CHARS]))


def _normalize_routes(routes: list[dict]) -> list[dict]:
    """Pola poza słowami-wyzwalaczami o złym typie (plik edytowany ręcznie) naprawiamy
    na miejscu: licznik trafień czy znacznik czasu nie mogą przewracać dopasowania ani sortowania."""
    routes[:] = [r for r in routes if not is_reaction(r.get("example") if isinstance(r.get("example"), str) else "")]
    for r in routes:
        if "hits" in r and (not isinstance(r["hits"], int) or isinstance(r["hits"], bool)):
            r["hits"] = 0
        for field in ("last_used", "created"):
            if field in r and not isinstance(r[field], str):
                r[field] = None
        if "example" in r and not isinstance(r["example"], str):
            r["example"] = ""
        if "by" in r and not isinstance(r["by"], str):
            del r["by"]
    return routes


def _load() -> list[dict]:
    global _CACHE
    if _CACHE is None or str(LEARNED_PATH) in _READ_FAILED:
        _READ_FAILED.discard(str(LEARNED_PATH))  # ponowna próba po chwilowym błędzie
        _CACHE = _normalize_routes(_read_json(LEARNED_PATH, [], _valid_routes))
    return _CACHE


def _save() -> None:
    """Nauka jest dodatkiem: brak miejsca na dysku nie może psuć rozmowy."""
    try:
        if str(LEARNED_PATH) in _READ_FAILED:
            return  # nie nadpisujemy pliku, którego nie udało się przeczytać
        fsutil.atomic_write_text(LEARNED_PATH, json.dumps(_CACHE, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as e:  # ValueError: tekst, którego nie da się zapisać w UTF-8
        print(f"UWAGA: nie zapisano {LEARNED_PATH.name}: {e}")


def _stem(word: str) -> str:
    """Bardzo prosta heurystyka na polską odmianę: obcina 1-2 znaki z
    końca (nigdy poniżej 4 znaków), żeby "router"/"routera"/"routerze"
    albo "zapamiętał"/"zapamiętała"/"zapamiętali" dały ten sam rdzeń.
    Zero pretensji do lingwistycznej poprawności, dokładnie w duchu
    ręcznych wzorców w capabilities.py (np. "rout\\w*", "sygna[lł]\\w*"):
    nie trzeba złapać WSZYSTKICH form danego słowa, trzeba złapać
    wystarczająco, żeby wzorzec przeżył naturalną odmianę w kolejnej
    rozmowie, a nie tylko wrócił dla identycznie napisanej frazy."""
    if len(word) >= 7:
        return word[:-2]
    if len(word) >= 5:
        return word[:-1]
    return word


_GENERIC_TRIGGER_STEMS = frozenset(_stem(w) for w in _GENERIC_TRIGGER_WORDS)


def significant_words(text: str) -> list[str]:
    """Rdzenie słów-kandydatów na wzorzec-wyzwalacz: małe litery, bez
    cyfr, bez najczęstszych "kleju" (STOPWORDS, sprawdzane PRZED
    ucięciem końcówki, bo to tam są wypisane konkretne formy odmiany),
    bez duplikatów po ucięciu (patrz _stem), w kolejności pierwszego
    wystąpienia. Krótkie (< 4 znaki) odpadają z góry: po polsku to w
    większości zaimki/spójniki/partykuły ("co", "czy", "ma", "się",
    "jak"), prawie nigdy nic, co niesie temat rozmowy."""
    seen: list[str] = []
    for w in WORD_RE.findall(text.lower()):
        if len(w) < 4 or w in STOPWORDS:
            continue
        stem = _stem(w)
        if stem not in seen:
            seen.append(stem)
    return seen


def _strip_arg(message: str, model_arg: str) -> str:
    """Wycina z wiadomości fragment, który Ollama podała jako argument
    (po "TOOL: nazwa | argument"), żeby uczyć się na FRAZIE-WYZWALACZU
    ("zapisz to gdzieś, żeby nie zapomnieć: X"), nigdy na TREŚCI samego
    argumentu ("X"). Patrz punkt 2 w docstringu modułu wyżej: to
    najważniejsze zabezpieczenie w tym pliku."""
    if not model_arg or model_arg.strip() == message.strip():
        return message
    idx = message.lower().find(model_arg.strip().lower())
    if idx == -1:
        return message
    return message[:idx] + message[idx + len(model_arg.strip()):]


@functools.lru_cache(maxsize=512)
def _compiled(words: tuple) -> re.Pattern:
    # \A + DOTALL: lookaheady liczą się raz od początku wiadomości (liniowo),
    # a wiadomość wielowierszowa działa jak jednowierszowa.
    parts = [rf"(?=.*\b{re.escape(w)}\w*\b)" for w in words]
    return re.compile(r"\A" + "".join(parts), re.IGNORECASE | re.DOTALL)


def _pattern_for(words: list[str]) -> re.Pattern:
    """Sam format co w capabilities.py (lookaheady (?=.*\\bsłowo\\b)
    połączone razem): każdy RDZEŃ musi się znaleźć GDZIEKOLWIEK w
    wiadomości, niezależnie od szyku. Kolejność słów w prawdziwej mowie
    jest zbyt zmienna, żeby wymagać konkretnego porządku.

    \\w* po rdzeniu (a nie goły \\b{rdzeń}\\b) jest tu konieczne: `words`
    to już OKROJONE rdzenie z _stem (np. "siec" z "sieci", "włama" z
    "włamał"), nie całe słowa. Bez \\w* rdzeń "siec" wymagałby, żeby w
    wiadomości było DOSŁOWNIE samo "siec", a nigdy "sieci"/"siecią",
    czyli niemal nic, co ktoś naprawdę napisze. Żywy błąd, od którego
    to powstało: wyuczony wzorzec z "...mojej sieci..." nie złapał
    kolejnej wiadomości z "...bezprzewodowej sieci..." tylko dlatego, że
    tej jednej literki \\w* tu brakowało."""
    return _compiled(tuple(words))


# 1.32.11: wzorzec bez ani jednego trafienia przez 30 dni wygasa (sam z siebie nic nie udowodnił).
ROUTE_UNUSED_DAYS = 30


def _expired(r: dict) -> bool:
    if r.get("hits"):
        return False
    try:
        import datetime as _dt
        created = _dt.datetime.fromisoformat(str(r.get("created") or "").replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=_dt.timezone.utc)
        return (_dt.datetime.now(_dt.timezone.utc) - created).days > ROUTE_UNUSED_DAYS
    except (ValueError, TypeError):
        return False


def prune_expired() -> int:
    routes = _load()
    before = len(routes)
    routes[:] = [r for r in routes if not _expired(r)]
    if len(routes) != before:
        _save()
    return before - len(routes)


def find_learned_record(message: str) -> dict | None:
    """Jak find_learned_match niżej, ale zwraca cały zapisany rekord
    (narzędzie + DOKŁADNY zestaw słów), nie tylko (narzędzie, argument).
    Czysty odczyt, bez efektów ubocznych (nie podnosi hits/last_used):
    używane w router.py przy wykrywaniu korekty (patrz CORRECTION_RE),
    żeby wiedzieć DOKŁADNIE, który wpis wycofać przez forget_route,
    zamiast zgadywać na podstawie samego klucza narzędzia."""
    routes = _load()
    if not routes:
        return None
    scan = message[:SCAN_CHARS]
    low = scan.lower()
    for record in sorted(routes, key=lambda r: -len(r["words"])):
        if _expired(record):
            continue
        # Tanie wstępne sito: rdzeń słowa musi w ogóle wystąpić w tekście.
        if not all(w in low for w in record["words"]):
            continue
        if _pattern_for(record["words"]).search(scan):
            return record
    return None


# Wiadomość z przeczeniem ("nie pokazuj ..., tylko ...") znaczy co innego niż
# jej słowa-wyzwalacze: wyuczony wzorzec nie rozstrzyga jej sam, decyduje model.
_NEGATION_RE = re.compile(r"\b(nie|bez|nigdy|zamiast|żadn\w*)\b", re.IGNORECASE)


def _strip_triggers(message: str, words: list[str]) -> str:
    """Wiadomość bez słów-wyzwalaczy wzorca (pierwsze wystąpienie każdego rdzenia):
    to, co zostaje, jest argumentem narzędzia. Sam wzorzec to zero-szerokie
    lookaheady, więc `pattern.sub("", ...)` niczego nie wycinało i argumentem
    była cała wiadomość."""
    out = message
    for w in words:
        out = re.sub(rf"\b{re.escape(w)}\w*\b", " ", out, count=1, flags=re.IGNORECASE)
    return " ".join(out.split()).strip(" :,-")


def peek_learned_match(message: str) -> tuple[str, str | None] | None:
    """To samo co find_learned_match, ale TYLKO ODCZYT: nie zwiększa licznika
    trafień, nie zmienia last_used i niczego nie zapisuje. Dla skryptów
    treningowych (training/build_dataset.py), które mają być bezpieczne do
    uruchomienia w każdej chwili, także gdy serwer działa."""
    if _NEGATION_RE.search(message[:SCAN_CHARS]):
        return None
    record = find_learned_record(message)
    if record is None:
        return None
    return record["tool"], (_strip_triggers(message, record["words"]) or None)


def find_learned_match(message: str) -> tuple[str, str | None] | None:
    """Sprawdza wyuczone wzorce, najbardziej precyzyjne (najwięcej
    wymaganych słów) najpierw, i zwraca (klucz_narzędzia, argument) dla
    pierwszego trafienia, tak jak capabilities_mod.find_keyword_match.
    Wołane w router.py PO ręcznych wzorcach, PRZED Ollamą: jednoznaczna
    wyuczona komenda ma takie samo prawo do natychmiastowej odpowiedzi,
    jak komenda opisana ręcznie w capabilities.py."""
    if _NEGATION_RE.search(message[:SCAN_CHARS]):
        return None
    record = find_learned_record(message)
    if record is None:
        return None
    arg = _strip_triggers(message, record["words"]) or None
    record["hits"] = record.get("hits", 0) + 1
    record["last_used"] = _now_iso()
    _save()
    return record["tool"], arg


def forget_route(tool: str, words: list[str]) -> bool:
    """Usuwa KONKRETNY wyuczony wzorzec (dopasowany po narzędziu i
    dokładnym zestawie słów). Wywoływane WYŁĄCZNIE z router.py, gdy
    użytkownik explicite poprawia GREGAI od razu po tym, jak ten wzorzec
    zadziałał (patrz router.py: CORRECTION_RE/_undo_prior_learning). Ta
    sama filozofia co nauka wzorców wyżej, w drugą stronę: "wolimy nie
    nauczyć się niczego, niż nauczyć się źle", tutaj: wolimy ZAPOMNIEĆ
    coś źle wyuczonego, niż pozwolić mu dalej mylić się w ten sam
    sposób. Zwraca True, jeśli faktycznie coś usunięto."""
    routes = _load()
    word_set = set(words)
    before = len(routes)
    routes[:] = [r for r in routes if not (r["tool"] == tool and set(r["words"]) == word_set)]
    if len(routes) != before:
        _save()
        return True
    return False


def learn_from_resolution(message: str, tool: str, model_arg: str, by: str | None = None,
                          kontekst: bool = False) -> dict | None:
    """Wywoływane z router.py WYŁĄCZNIE gdy Ollama sama, bez pomocy
    żadnego wzorca (ani ręcznego, ani wcześniej wyuczonego), poprawnie
    rozpoznała narzędzie dla tej wiadomości. Taki moment jest żywym
    dowodem, że dana fraza (a konkretnie jej słowa-wyzwalacze) naprawdę
    oznacza to narzędzie, więc zapisujemy ją jako nowy wzorzec na
    przyszłość. Patrz docstring modułu wyżej dla pełnych zasad
    bezpieczeństwa (punkty 1-4).

    Zwraca nowo zapisany wpis (dict) albo None, gdy nic nie zostało
    zapisane (za słaby sygnał albo konflikt z innym narzędziem).
    Router.py przekazuje to dalej do trace.py, żeby na stronie /debug
    było widać DOKŁADNIE ten moment, w którym GREGAI się czegoś
    nauczył, nie tylko końcowy stan pliku."""
    if len(message) > MAX_LEARN_CHARS:
        return None
    if is_reaction(message):
        return None
    # 1.18.0: decyzja podjęta z kontekstem poprzednich wiadomości (router
    # sieciowy koryta widzi dwie ostatnie) nie wynika z SAMEJ tej wiadomości -
    # wzorzec z niej skracałby następnym razem drogę dla frazy, która bez tamtego
    # kontekstu znaczy co innego ("sprawdź w notatkach tego gościa").
    if kontekst:
        return None
    # Sekret z .env wpisany w wiadomość nie może trafić ani do słów wzorca, ani do
    # przykładu (plik jest materiałem treningowym routera).
    message = trace_mod.mask(message)
    model_arg = trace_mod.mask(model_arg) if model_arg else model_arg
    trigger_text = _strip_arg(message, model_arg)
    # 1.32.11 (audyt tura 15): argument sparafrazowany przez model ("Kraków" dla "Krakowie",
    # "AAPL" dla "apple") nie da się wyciąć z wiadomości, więc słowa TREŚCI ("krakow", "appl")
    # weszłyby do wyzwalaczy i łapały potem "temperatura procesora ... Krakowie". Nie uczymy się.
    if model_arg and model_arg.strip() and trigger_text == message and model_arg.strip() != message.strip():
        return None
    # Decyzja darmowej puli (koryto:groq...) nie jest wzorcem do nauki: bywa błędna, a wpis
    # wracałby potem jako etykieta treningowa routera (pętla dryfu).
    if by and by.startswith("koryto:") and by != "koryto:anthropic":
        return None
    words = significant_words(trigger_text)
    if len(words) < MIN_SIGNIFICANT_WORDS:
        return None
    words = words[:MAX_SIGNIFICANT_WORDS]
    word_set = set(words)
    # 1.32.16 (audyt tura 18): wszystkie słowa wyzwalacza są z zamkniętej listy czasowników/
    # przysłówków tak częstych w KAŻDYM poleceniu o obserwowaniu/informowaniu, że bez żadnego
    # innego, bardziej konkretnego słowa nie są wystarczającym sygnałem - inaczej "Sprawdzaj
    # codziennie X, powiedz mi jak się zmieni" uczy się na {"sprawdz","codzienn","zmien"} i
    # ten wzorzec potem łapie każdą niezwiązaną wiadomość z tymi samymi, pospolitymi słowami.
    if word_set <= _GENERIC_TRIGGER_STEMS:
        return None

    routes = _load()
    for existing in routes:
        existing_set = set(existing["words"])
        if existing["tool"] == tool:
            if existing_set <= word_set:
                # Istniejący wzorzec jest taki sam albo ogólniejszy
                # (wymaga tych samych słów albo ich podzbioru): już
                # łapie wszystko, co złapałby ten nowy. Nic do dodania.
                return None
        else:
            if word_set <= existing_set or existing_set <= word_set:
                # Te same słowa wskazywałyby na DWA różne narzędzia
                # naraz: dokładnie ten sam problem co AMBIGUITY_GROUPS w
                # capabilities.py, tylko wykryty automatycznie. Zamiast
                # zgadywać, który wygra przy sprawdzaniu, nie ucz się
                # tego wzorca wcale (patrz punkt 4 w docstringu modułu).
                return None

    # Nowy wzorzec jest OGÓLNIEJSZY (podzbiór słów) od któregoś z już
    # wyuczonych dla TEGO SAMEGO narzędzia: nowy i tak złapie wszystko,
    # co złapałby stary, plus więcej, więc stary wpis staje się
    # martwym balastem w pliku i można go usunąć.
    routes[:] = [
        r for r in routes
        if not (r["tool"] == tool and word_set < set(r["words"]))
    ]

    new_record = {
        "tool": tool,
        "words": sorted(word_set),
        "example": message[:200],
        "created": _now_iso(),
        "hits": 0,
        "last_used": None,
    }
    # Kto podjął decyzję. "router" = wytrenowany router: taki wzorzec skraca
    # drogę na żywo, ale nie jest materiałem treningowym (router nie uczy się
    # z własnych odpowiedzi, training/build_dataset.py go pomija).
    if by:
        new_record["by"] = by
    routes.append(new_record)

    if len(routes) > MAX_LEARNED_ROUTES:
        # 1.18.0: najpierw odpadają wzorce, które ani razu się nie przydały
        # (hits=0, najstarsze pierwsze), dopiero potem najdawniej używane -
        # dotąd sam wiek wyrzucał też często trafiające wzorce sprzed tygodni,
        # a zostawiał świeże, które nigdy nie zadziałały. Nowo dodany wpis
        # chroniony (inaczej przy pełnym pliku od razu by wypadł).
        def _keep_key(r: dict) -> tuple:
            return (r is new_record, (r.get("hits") or 0) > 0, r.get("last_used") or r.get("created") or "")
        routes.sort(key=_keep_key)
        del routes[: len(routes) - MAX_LEARNED_ROUTES]

    _save()
    return new_record


def all_routes() -> list[dict]:
    """Wszystkie wyuczone wzorce, najpierw ostatnio użyte/dodane:
    widok na to, czego się GREGAI do tej pory nauczył, pod stronę
    /debug (patrz ui/debug.html i /api/debug/learned w main.py)."""
    routes = _load()
    return sorted(routes, key=lambda r: r.get("last_used") or r.get("created") or "", reverse=True)


# --- Druga warstwa samouczenia: słowa-tematy dla DOPYTAŃ --------------------
# Osobny mechanizm od wzorców-wyzwalaczy wyżej, inny problem: capabilities.py
# (check_ambiguity/resolve_clarify_answer) dopytuje, kiedy pytanie pasuje do
# DWÓCH narzędzi naraz (np. "sieć" = sieć domowa ALBO graf notatek), a potem
# rozpoznaje, do którego z dwóch chodziło, przez RĘCZNIE wpisaną listę
# `topic_words` (np. "wifi", "router" dla network_status). Ta lista jest
# siłą rzeczy niekompletna: użytkownik na krótkie dopytanie odpowiada
# dowolnym słowem, którego akurat nie przewidziałem.
#
# Ten moduł to zamykał już raz dla CAŁYCH komend (wyżej), teraz zamyka to
# samo dla SKRÓTÓW odpowiedzi na dopytanie: kiedy odpowiedź na dopytanie
# NIE złapała się na żaden znany topic_word (ani ręczny, ani wcześniej
# wyuczony), więc poszła normalną ścieżką routingu (szybki wzorzec/wyuczony
# wzorzec/Ollama) i TA ścieżka rozpoznała jedno z dwóch narzędzi
# zaproponowanych w dopytaniu, to jest żywy dowód, że te słowa oznaczają
# WŁAŚNIE TO narzędzie w kontekście tej dwuznaczności. Zapisujemy je, żeby
# następne dopytanie tego samego typu rozpoznało krótką odpowiedź od razu,
# mechanicznie, bez Ollamy.
#
# Bezpieczeństwo: ten mechanizm działa WYŁĄCZNIE w jednym, wąskim oknie
# (jedna odpowiedź na jedno konkretne dopytanie router.py właśnie zadał),
# nie globalnie na każdą wiadomość, więc nawet nadmiernie ogólne słowo jest
# dużo mniej ryzykowne niż w wzorcach-wyzwalaczach wyżej. Mimo to: te same
# zasady konfliktu (punkt 4 w module docstring) obowiązują identycznie,
# sprawdzane przez wołającego (router.py), bo stąd nie widać, jakie słowa
# ma RĘCZNIE przypisane druga zdolność (capabilities.py importowałby ten
# plik, nie odwrotnie: żadnego importu w drugą stronę).
TOPIC_WORDS_PATH = DATA_DIR / "learned_topic_words.json"
MAX_LEARNED_TOPIC_WORDS_PER_TOOL = 30
# Krótka odpowiedź na dopytanie ("o grafie notatek") ma kilka znaczących słów;
# dłuższa wypowiedź to nowe pytanie i nie uczy słów-tematów.
MAX_TOPIC_WORDS_PER_LEARN = 6

_TOPIC_CACHE: dict | None = None


def _valid_topic_words(data) -> bool:
    return isinstance(data, dict) and all(
        isinstance(k, str) and isinstance(v, list) and all(isinstance(w, str) for w in v) for k, v in data.items())


def _load_topic_words() -> dict:
    global _TOPIC_CACHE
    if _TOPIC_CACHE is None or str(TOPIC_WORDS_PATH) in _READ_FAILED:
        _READ_FAILED.discard(str(TOPIC_WORDS_PATH))
        _TOPIC_CACHE = _read_json(TOPIC_WORDS_PATH, {}, _valid_topic_words)
    return _TOPIC_CACHE


def _save_topic_words() -> None:
    try:
        if str(TOPIC_WORDS_PATH) in _READ_FAILED:
            return
        fsutil.atomic_write_text(TOPIC_WORDS_PATH, json.dumps(_TOPIC_CACHE, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as e:
        print(f"UWAGA: nie zapisano {TOPIC_WORDS_PATH.name}: {e}")


def learned_topic_words(key: str) -> list[str]:
    """Wyuczone słowa-tematy dla zdolności `key`, puste gdy nic jeszcze.
    Wołane z capabilities.py:resolve_clarify_answer (dopisywane OBOK
    ręcznej listy `topic_words`, nigdy jej nie zastępując) i z router.py
    przy sprawdzaniu konfliktu przed nauką nowego słowa niżej."""
    return list(_load_topic_words().get(key, []))


def learn_topic_words(message: str, resolved_key: str, own_words: set, other_words: set) -> list[str] | None:
    """Wywoływane z router.py WYŁĄCZNIE gdy: (1) było aktywne dopytanie
    (pending_clarify) między dwoma narzędziami, (2) ta odpowiedź NIE
    rozpoznała się przez istniejące topic_words (inaczej wróciłaby od
    razu jako "doprecyzowanie_rozwiazane", nic nowego do nauczenia), (3)
    normalna ścieżka routingu (szybki/wyuczony wzorzec albo Ollama) i tak
    rozpoznała jedno z DWÓCH narzędzi zaproponowanych w tym dopytaniu
    (`resolved_key`). `own_words`/`other_words` to już POŁĄCZONE zbiory
    (ręczne topic_words + to, co już wyuczone) dla, odpowiednio, narzędzia
    rozpoznanego i tego drugiego z dopytania: liczy je wołający
    (router.py), bo tylko on ma dostęp i do capabilities.py, i do tego
    modułu naraz.

    Zwraca listę NOWO dodanych słów (do trace.py, widoczne na /debug) albo
    None, gdy nic nowego nie dodano (brak sygnału albo kolizja)."""
    candidates = set(significant_words(message))
    if not candidates or len(candidates) > MAX_TOPIC_WORDS_PER_LEARN:
        return None

    # Punkt 4 z module docstring, zastosowany tutaj: słowo, które już
    # oznacza TO SAMO narzędzie, nic nowego nie wnosi; słowo, które
    # oznacza DRUGIE narzędzie z tego samego dopytania, jest właśnie tym
    # konfliktem, którego nie chcemy nauczyć (ta sama krótka odpowiedź
    # wskazywałaby na dwie różne rzeczy naraz, czyli dokładnie ta
    # dwuznaczność, od której to dopytanie w ogóle się zaczęło).
    # Porównanie po wspólnym początku, nie po równości: kandydaci są rdzeniami
    # ("siec" z "sieci"), a listy ręczne pełnymi formami ("sieci", "siecią");
    # resolve_clarify_answer dopasowuje słowa jako początki, więc rdzeń cudzego
    # słowa nauczony dla tego narzędzia sprawiłby, że ta sama odpowiedź pasowałaby
    # do obu naraz i dopytanie nigdy by się nie rozstrzygnęło.
    known = {w.lower() for w in own_words | other_words if w}
    new_words = {c for c in candidates
                 if not any(k.startswith(c) or c.startswith(k) for k in known)}
    if not new_words:
        return None

    store = _load_topic_words()
    existing = store.setdefault(resolved_key, [])
    existing_set = set(existing)
    added = sorted(w for w in new_words if w not in existing_set)
    if not added:
        return None

    existing.extend(added)
    if len(existing) > MAX_LEARNED_TOPIC_WORDS_PER_TOOL:
        del existing[: len(existing) - MAX_LEARNED_TOPIC_WORDS_PER_TOOL]

    _save_topic_words()
    return added


def forget_topic_words(tool: str, words: list[str]) -> bool:
    """Jak forget_route wyżej, dla drugiej warstwy (słowa-tematy do
    dopytań): usuwa konkretne słowa z listy wyuczonej dla `tool`.
    Zwraca True, jeśli faktycznie coś usunięto."""
    store = _load_topic_words()
    existing = store.get(tool)
    if not existing:
        return False
    to_remove = set(words)
    new_list = [w for w in existing if w not in to_remove]
    if len(new_list) == len(existing):
        return False
    store[tool] = new_list
    _save_topic_words()
    return True


def all_learned_topic_words() -> dict:
    """Cały zapisany słownik {narzędzie: [słowa]}, pod stronę /debug
    (patrz /api/debug/topic_words w main.py), żeby ta druga warstwa
    samouczenia była tak samo widoczna jak wzorce-wyzwalacze wyżej, nie
    cichym, niewidocznym mechanizmem."""
    return dict(_load_topic_words())
