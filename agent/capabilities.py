"""
capabilities.py

Jedno miejsce na każdy "bloczek" zdolności GREGAI. Każdy wpis w CAPABILITIES
niżej łączy w sobie trzy rzeczy dla jednego narzędzia:

1. `call`:      jak faktycznie wywołać narzędzie (None = narzędzie
                 świadomie wyłączone; model nigdy go nie wywoła, ale prompt
                 wciąż może o nim wspomnieć;
                 `user_only` = tryb uruchamiany tylko dosłownym poleceniem
                 użytkownika, np. freeram, bez udziału modelu).
2. `prompt`:    fragment promptu systemowego, który tłumaczy modelowi
                 (Ollamie), KIEDY i JAK tego narzędzia używać. Składany
                 automatycznie w jeden blok przez assemble_tools_prompt()
                 i wstrzykiwany do agent/prompt.md w main.py.
3. `keywords`:  wzorce regex do trybu zapasowego (gdy Ollama niedostępna
                 albo nie odpowiedziała). Router.py użyje ich zamiast
                 modelu, patrz keyword_fallback().

Powód, dla którego to istnieje: narzędzie dodane w tools.py i w regexach
fallbacku, ale nieopisane w prompcie, jest dla modelu niewidoczne i routing
się psuje, mimo że Ollama działa poprawnie. Dlatego DODANIE NOWEGO NARZĘDZIA
= JEDEN NOWY WPIS TUTAJ (call + prompt + keywords). Nic więcej nie trzeba
pamiętać, nie trzeba ręcznie edytować prompt.md ani router.py.
"""

from __future__ import annotations

import re

import learning as learning_mod
import persona as persona_mod
import standing as standing_mod
import symbols as symbols_mod
import sysop as sysop_mod
import tools as tools_mod
import tryby as tryby_mod


class Capability:
    __slots__ = ("key", "call", "prompt", "keywords", "clarify_context", "topic_words", "short", "user_only")

    def __init__(self, key, call, prompt, keywords=None, clarify_context=None, topic_words=None, short=None,
                 user_only=False):
        self.key = key
        # True = tryb, który uruchamia WYŁĄCZNIE dosłowne polecenie
        # użytkownika dopasowane wzorcem (freeram, fullon). Ani model routera,
        # ani planer pętli agenta nie mogą go wybrać (nie ma go w TOOL_NAMES
        # ani w katalogu planera), więc pomyłka modelu nie zatrzyma Ollamy.
        self.user_only = user_only
        # Jednolinijkowy opis dla PĘTLI AGENTA (agent/agentloop.py): planer
        # dostaje krótki katalog narzędzi, nie pełne fragmenty promptu
        # (te są dla kroku 1 routingu i dla rozmowy).
        self.short = short
        self.call = call          # callable(vault, message, arg) -> dict | None
        self.prompt = prompt      # fragment promptu systemowego (markdown)
        self.keywords = keywords or []  # lista skompilowanych regexów (fallback)
        # Jedno, krótkie, pierwszoosobowe wyjaśnienie "co bym sprawdził,
        # gdyby o TO chodziło", używane WYŁĄCZNIE przez check_ambiguity()
        # niżej, żeby dopytać, kiedy pytanie naprawdę pasuje do dwóch
        # różnych narzędzi na raz. Nieużywane = None, nie trzeba go
        # wypełniać dla każdej zdolności.
        self.clarify_context = clarify_context
        # Krótka lista luźnych, pojedynczych słów-tematów (bez wymogu
        # pełnego sformułowania, w przeciwieństwie do `keywords` wyżej),
        # używana WYŁĄCZNIE przez resolve_clarify_answer() niżej, żeby
        # rozpoznać, do której z dwóch zaproponowanych opcji odnosi się
        # krótka odpowiedź użytkownika na pytanie doprecyzowujące (np.
        # samo "notatki" albo "sieć", a nie pełne pytanie). Nieużywane =
        # None/[], nie trzeba wypełniać dla każdej zdolności.
        self.topic_words = topic_words or []


# --- Wywołania narzędzi przez jednolity interfejs (vault, message, arg) ----
# `arg` to to, co zostało po wycięciu dopasowanego słowa kluczowego z
# wiadomości (albo argument podany przez model po "TOOL: nazwa | argument").

def _call_search_brain(vault, message, arg):
    return tools_mod.search_brain(vault, arg or message)


_QUERY_NOISE_RE = re.compile(
    r"^\s*(?:(?:sprawd[zź]|poszukaj|wyszukaj|szukaj|znajd[zź]|zobacz|powiedz|podaj)\s+(?:mi\s+)?)?"
    r"(?:(?:w|na|we)\s+)?(?:(?:wikipedii|wiki|internecie|necie|sieci|encyklopedii)\b)?\s*,?\s*"
    r"(?:(?:co\s+to\s+(?:jest|s[aą])?|czym\s+(?:jest|s[aą])|kim\s+(?:by[lł]a?|jest)|co\s+to|co\s+(?:masz|wiesz|mam)\s+(?:o|na\s+temat))\s+)?", re.IGNORECASE)


def _clean_query(arg: str | None, message: str) -> str:
    """Temat zapytania bez słów polecenia: wzorzec słów kluczowych wycina tylko trafione
    słowo ("wikipedii"), a resztę ("sprawdź w ... co to") niosłoby zapytanie."""
    text = (arg or message or "").strip()
    cleaned = _QUERY_NOISE_RE.sub("", text, count=1).strip(" :,?-")
    return cleaned or text


def _call_research_web(vault, message, arg):
    return tools_mod.research_web(_clean_query(arg, message))


def _call_wiki_lookup(vault, message, arg):
    """1.30.31 (zgłoszenie Grzegorza): „długość dnia i nocy Warszawa ...” poszło do
    Wikipedii, ta nic nie miała, a na „A w internecie?” model odpowiedział „nie mam
    dostępu do internetu”. Gdy Wikipedia NIE MA hasła (a połączenie działa), od razu
    sprawdzamy to samo zapytanie w wyszukiwarce - zgoda na wysłanie tego tekstu w
    sieć już padła, a pytanie zwykle nie jest hasłem encyklopedycznym."""
    topic = _clean_query(arg, message)
    result = tools_mod.wiki_lookup(vault, topic)
    card = result.get("card") if isinstance(result, dict) else None
    if isinstance(card, dict) and card.get("type") == "wiki_lookup" and card.get("found") is False and not card.get("error"):
        web = tools_mod.research_web(card.get("query") or topic)
        if ((web.get("card") or {}).get("results")):
            web["speech"] = f"Na Wikipedii nie ma hasła o „{card.get('query') or topic}”, więc sprawdziłem w wyszukiwarce. " + web["speech"]
            return web
    return result


_MARKET_QUERY_NOISE_RE = re.compile(
    r"^\s*(?:sprawd[zź]|poka[zż]|jaki|jaka|jakie)\s+(?:mi\s+)?(?:jest\s+)?"
    r"(?:kurs|notowanie|cen[aę])\s*(?:akcji|kryptowaluty)?\s*",
    re.IGNORECASE,
)

# Ten sam, celowo wąski zestaw nazw aktywów co agent/symbols.py (jedno
# miejsce prawdy, zero duplikowania) - używany przez keywords= zdolności
# market_quote niżej. Patrz komentarz przy niej: pierwsza wersja dopuszczała
# też gołe słowa kategorii (akcje/giełda/waluta/...), co złapało "jaki kurs
# walut POLECASZ ŚLEDZIĆ" (pytanie o radę, nie o notowanie).
_MARKET_ASSET_WORDS = symbols_mod.ASSET_WORDS_PATTERN


def _call_market_quote(vault, message, arg):
    # Żywy przykład błędu: find_keyword_match() (fallback_order niżej) wycina
    # z `message` TYLKO trafione słowo ("kurs"), nie całą frazę - więc dla
    # "Jaki jest kurs aapl.us?" `arg` to "Jaki jest  aapl.us", a
    # _MARKET_QUERY_NOISE_RE (wymaga literalnego "kurs/notowanie/cenę" w
    # środku) już nic nie dopasuje, bo to słowo zniknęło wcześniej - ticker
    # nigdy nie docierał czysty do tools.market_quote. Naprawa: najpierw
    # szukaj wprost zapisanego symbolu/aliasu przez symbols.detect() (ta sama
    # definicja "ticker" co w standing.py dla zadań stałych, jedno miejsce
    # prawdy), a dopiero gdy go nie ma - starą metodą obcinania frazy.
    text = (arg or message or "").strip()
    lowered = text.lower()
    symbol = symbols_mod.detect(lowered)
    if symbol:
        return tools_mod.market_quote(symbol)
    cleaned = _MARKET_QUERY_NOISE_RE.sub("", text, count=1).strip(" :,?-")
    return tools_mod.market_quote(cleaned or text)


def _call_weather(vault, message, arg):
    import pogoda as pogoda_mod
    # 1.32.2 (przegląd poprawek): w pętli przychodzi samo miasto ("Kraków"), a
    # city_from_message rozpoznaje "w Krakowie"/"dla Krakowa" - bez tego szła Warszawa.
    if not pogoda_mod.city_from_message(message or "") and (arg or "").strip():
        message = f"pogoda w {arg.strip()}"
    return pogoda_mod.weather(message)


def _call_net_diagnose(vault, message, arg):
    import diagnoza as diagnoza_mod
    return diagnoza_mod.as_tool_result()


def _call_self_model(vault, message, arg):
    return tools_mod.self_model(message)


def _call_self_status(vault, message, arg):
    return tools_mod.self_status(vault)


def _call_brief_me(vault, message, arg):
    return tools_mod.brief_me(vault)


def _call_remember(vault, message, arg):
    # Żywy błąd, od którego to powstało: samo gołe "zapamiętaj", bez
    # żadnej treści po nim, wcześniej spadało na "arg or message", a
    # `message` to CAŁA oryginalna wiadomość, czyli dalej samo słowo
    # "zapamiętaj" (wzorzec \bzapamiętaj\b je wycina, ale `message`
    # przekazywany tutaj to wersja PRZED wycięciem). Efekt: narzędzie
    # pewnie odpowiadało "Zapisałem: zapamiętaj" i zapisywało ten sam
    # bezsensowny tekst jako fakt w memory/. Zamiast zgadywać, że puste
    # `arg` znaczy "zapamiętaj całą wiadomość", dopytaj, o co chodzi.
    fact = re.sub(r"^\s*(?:,\s*)?(?:że|iż)\s+", "", (arg or "").strip(" :,-"), count=1).strip()  # bez "ze" (przyimek)
    if not fact:
        # ok=False: dla pętli agenta (agentloop.py) to NIE jest wykonany
        # krok, tylko brak argumentu; bez tej flagi model mógłby uznać
        # "Co mam zapamiętać?" za udane zapisanie i ogłosić GOTOWE.
        return {
            "speech": "Co mam zapamiętać? Napisz np. „zapamiętaj: coś konkretnego”.",
            "card": None,
            "ok": False,
        }
    return tools_mod.remember(fact)


def _call_plan_day(vault, message, arg):
    return tools_mod.plan_day(vault)


def _call_network_status(vault, message, arg):
    return tools_mod.network_status()


def _call_graph_overview(vault, message, arg):
    return tools_mod.graph_overview(vault)


def _call_freeram(vault, message, arg):
    return tryby_mod.freeram()


def _call_fullon(vault, message, arg):
    return tryby_mod.fullon()


def _call_panicmode(vault, message, arg):
    return tryby_mod.panicmode()


def _call_standing_task_new(vault, message, arg):
    # 1.19.0: CAŁA wiadomość - argument z wzorca to reszta po wycięciu
    # trafionych słów ("Śledź kurs bitcoina i  spadnie poniżej 50000").
    return standing_mod.create_task(message or arg)


def _call_standing_task_list(vault, message, arg):
    return standing_mod.list_tasks()


def _call_standing_task_stop(vault, message, arg):
    return standing_mod.stop_task(arg or message)


# Tryby mocy (freeram, fullon) zatrzymują albo uruchamiają Ollamę, więc łapie je
# tylko wiadomość będąca WYŁĄCZNIE tym poleceniem ("freeram", "tryb fullon!"),
# nigdy zdanie, które zaczyna się od tego słowa ("freeram czemu tak wolno?").
_MODE_RE = r"\A\s*(?:tryb\s+)?{name}\s*[.!]*\s*\Z"

# --- Rejestr: tu wpisuje się każdy nowy "bloczek" ---------------------------
# Kolejność tutaj = kolejność w prompt systemowym (czysto kosmetyczna).
# O kolejności sprawdzania w fallbacku decyduje _FALLBACK_ORDER poniżej.

CAPABILITIES = {
    "freeram": Capability(
        key="freeram",
        call=_call_freeram,
        short="tryb Freeram: zwolnij RAM (wyładuj model, zatrzymaj Ollamę), oddaj moc maszynie",
        user_only=True,
        prompt=(
            "- **freeram**: tryb mocy, który użytkownik uruchamia sam, wpisując "
            "'freeram' (wyładowuje duży model i zatrzymuje Ollamę, zabezpieczeń "
            "WARP i zapory nie rusza). Obsługuje go serwer: nie wywołujesz go "
            "sam i nie opisujesz jego działania z głowy."
        ),
        keywords=[re.compile(_MODE_RE.format(name=r"free[\s-]?ram"), re.IGNORECASE)],
    ),
    "fullon": Capability(
        key="fullon",
        call=_call_fullon,
        short="tryb Fullon: pełna moc dla lokalnego AI (wczytaj i przypnij model w RAM)",
        user_only=True,
        prompt=(
            "- **fullon**: tryb mocy, który użytkownik uruchamia sam, wpisując "
            "'fullon' (startuje Ollamę, wczytuje i przypina duży model w RAM, "
            "rozgrzewa). Obsługuje go serwer: nie wywołujesz go sam i nie "
            "opisujesz jego działania z głowy."
        ),
        keywords=[re.compile(_MODE_RE.format(name=r"full[\s-]?on"), re.IGNORECASE)],
    ),
    "gregaipanicmode": Capability(
        key="gregaipanicmode",
        call=_call_panicmode,
        short="panic mode: zablokuj dostęp z sieci (zapora + LAN) i wyłącz cały komputer",
        user_only=True,
        prompt=(
            f"- **gregaipanicmode**: awaryjna blokada, którą {persona_mod.USER_NAME} uruchamia sam, wpisując "
            "dosłownie 'gregaipanicmode' (najpierw cofa dostęp z sieci - zapora i tryb LAN, "
            "potem wyłącza CAŁY komputer, nie tylko GREGAI). Obsługuje go serwer: nie "
            "wywołujesz go sam, nie podsuwasz go jako sugestii (nawet żartem) i nie opisujesz "
            "jego działania z głowy."
        ),
        keywords=[re.compile(_MODE_RE.format(name=r"gregai[\s-]?panic[\s-]?mode"), re.IGNORECASE)],
    ),
    "search_brain": Capability(
        key="search_brain",
        call=_call_search_brain,
        short="szukaj faktu w notatkach użytkownika (argument: czego szukać)",
        # Wprost "w notatkach"/"pokaż notatki o": bez wytrenowanego routera (świeża instalacja)
        # takie pytanie szłoby do modelu rozmowy, który notatek nie widzi.
        keywords=[re.compile(
            r"\b(?:co|czy)\s+mam\s+(?:w\s+)?(?:moich\s+)?notatk\w*\s+(?:o|na\s+temat)\b"
            r"|\bpoka[zż]\s+(?:mi\s+)?(?:moje\s+)?notatk\w*\s+(?:o|z|na\s+temat)\b"
            r"|\b(?:znajd[zź]|wyszukaj|poszukaj|szukaj|sprawd[zź])\s+(?:mi\s+)?(?:w|we)\s+(?:moich\s+)?notatk\w*\b"
            # Tylko od początku wiadomości i nie o zaimek ("co mam o tym myśleć?" to rozmowa).
            r"|\A\s*(?:czy\s+mam\s+co[sś]|co\s+mam)\s+(?:o|na\s+temat)\s+(?!(?:tym|tej|tego|nim|niej|nich|sobie)\b)"
            r"|\bw\s+(?:której|jakiej)\s+notatce\b",
            re.IGNORECASE,
        )],
        prompt=(
            "- **search_brain**: konkretny fakt Z TREŚCI plików użytkownika "
            "(notatki, projekty, koncepcje, \"neuronki\"). Podaj nazwę "
            "pliku źródłowego (wszystkie, jeśli było kilka). Narzędzie "
            "domyślne: nazwa własna z plików użytkownika, nic innego nie "
            "pasuje -> to. Pytanie o sam GRAF (ile węzłów, typy, huby) -> "
            "graph_overview, nie to. Pytanie o wiedzę ZE ŚWIATA (nie z "
            "plików użytkownika) -> wiki_lookup, nie to."
        ),
    ),
    "graph_overview": Capability(
        key="graph_overview",
        call=_call_graph_overview,
        short="przegląd grafu notatek: liczby, typy, huby",
        prompt=(
            "- **graph_overview**: przegląd CAŁEGO grafu notatek: ile "
            "węzłów, podział na typy (panel \"Filtry\" na "
            "http://localhost:7777) i najbardziej połączone węzły (panel "
            "\"Top huby\"). Pasuje do pytań O SAM GRAF/STRUKTURĘ, nie o "
            "pojedynczy fakt, np. \"ile masz notatek?\", \"jakie są "
            "najbardziej połączone węzły?\". To te same dane, co w "
            "przeglądarce - nie masz dostępu do niczego więcej."
        ),
        keywords=[
            re.compile(
                r"\A(?=.*\bw[eę]z[lł]\w*\b)(?=.*\b(?:wyczyta\w*|czyta\w*|widzisz|masz|jest|poka\w*)\b)",
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(r"\bile\s+(mam|masz|jest|macie)\s+(notatek|w[eę]z[lł]\w*)\b", re.IGNORECASE),
            re.compile(r"\A(?=.*\b(notatk\w*|w[eę]z[lł]\w*)\b)(?=.*\b(bez|nie\s+maj[aą]|nie\s+ma)\s+(żadnych\s+)?po[lł][aą]cze[nń]\b)|\bsamotn\w*\s+(w[eę]z[lł]\w*|notatk\w*)\b", re.IGNORECASE | re.DOTALL),
            # Żywy przykład błędu (runda 2 audytu, 2026-10-19): gołe "jakie
            # typy" bez wymogu współwystępowania łapało "jakie typy psów są
            # najlepsze dla dzieci?"/"jakie typy kawy pijasz rano?" - teraz
            # wymaga też słowa o notatkach/węzłach/grafie gdziekolwiek w
            # wiadomości, tak jak pierwsza alternatywa tej samej zdolności.
            re.compile(
                r"\A(?=.*\bjakie\s+typy\b)(?=.*\b(?:notatk\w*|w[eę]z[lł]\w*|graf\w*)\b)",
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(r"\btop\s*hub\w*\b|\bnajbardziej\s+po[lł][aą]czon\w*\b", re.IGNORECASE),
            re.compile(r"\bco\s+(widzisz|masz)\s+w\s+(moim\s+)?grafie\b", re.IGNORECASE),
            re.compile(r"\bopowiedz\s+o\s+(moich\s+)?w[eę]z[lł]ach\b", re.IGNORECASE),
        ],
        clarify_context=(
            "O grafie notatek: jak Twoje węzły (projekty, notatki, kontakty) "
            "są połączone ze sobą, ile ich jest i które są hubami."
        ),
        topic_words=[
            "graf", "grafie", "grafu", "grafem", "grafy",
            "notatk", "węzł", "wezl", "hub",
            "projekty", "kontakty", "klienci",
        ],
    ),
    "research_web": Capability(
        key="research_web",
        call=_call_research_web,
        short="szukaj w internecie (argument: zapytanie)",
        prompt=(
            "- **research_web**: sprawdź coś w internecie i odnieś wynik "
            "do konkretnych liczb/celów/sytuacji użytkownika, nie tylko "
            "surowy fakt."
        ),
        # "wyszukaj w plikach / notatkach / logach ..." to szukanie LOKALNE, nie w internecie.
        keywords=[re.compile(
            r"\bsprawd[zź]\w*\b.*\bw\s+(?:internecie|necie)\b"
            r"|\bsprawd[zź]\w*\s+(?:mi\s+)?w\s+sieci\b"
            r"|\bwyszukaj\b(?!\s+(?:mi\s+)?(?:w|we|po|na)\s+(?:moich\s+|mojej\s+|moim\s+|tych\s+|naszych\s+)?"
            r"(?:plik\w*|notatk\w*|katalog\w*|folder\w*|dysk\w*|log\w*|pami[eę]ci|graf\w*|w[eę]z[lł]\w*|wiedz\w*|neuronk\w*))",
            re.IGNORECASE,
        )],
    ),
    "market_quote": Capability(
        key="market_quote",
        call=_call_market_quote,
        short="bieżący kurs jednego symbolu/tickera (argument: ticker, np. aapl.us)",
        prompt=(
            "- **market_quote**: BIEŻĄCY kurs jednego tickera (np. "
            "aapl.us, ^spx, btcusd). \"jaki jest kurs X\". Metal, krypto albo indeks "
            "po nazwie (złoto, srebro, bitcoin) -> market_quote z tickerem (xauusd, xagusd, btcusd); "
            "research_web tylko, gdy nie da się wskazać instrumentu."
        ),
        # Żywy przykład błędu (runda 1 audytu): samo "kurs" jest wieloznaczne po
        # polsku (notowanie, ALE też "kurs programowania", "kurs prawa jazdy",
        # "zmienić kurs firmy") - bez dodatkowego warunku "Zapisałem się na kurs
        # programowania" trafiało tu zamiast zostać zwykłą rozmową.
        # Żywy przykład błędu (runda 2 audytu): PIERWSZA naprawa dopuszczała też
        # gołe słowa kategorii (akcje/giełda/waluta/kryptowaluta/spółka/indeks),
        # a to złapało "jaki kurs walut POLECASZ ŚLEDZIĆ" - pytanie o RADĘ, nie o
        # notowanie - i próbowało (nieudanie) znaleźć w nim tickera. Wymagamy
        # więc teraz dokładnie tego, co standing._detect_symbol uznaje za
        # prawdziwy ticker: wprost zapisany symbol (aapl.us, ^spx) albo jedną z
        # tych samych, celowo wąskich nazw aktywów (_MARKET_ASSET_WORDS, patrz
        # standing._SYMBOL_ALIASES) - nic szerszego, żadnych gołych kategorii.
        keywords=[re.compile(
            # 1.19.0 (przegląd): "daj znać/informuj mnie, gdy kurs ... spadnie"
            # to prośba o PILNOWANIE (zadanie stałe), nie o jedno notowanie teraz.
            r"\A(?!.*\b(?:daj\s+zna[cć]|informuj\s+mnie|powiadom\s+mnie|ostrze[zż]\s+mnie)\b)"
            r"(?=.*\b(?:kurs\w*|notowan\w*|cen[aąeęy]|kosztuj\w*)\b)"
            r"(?=.*(?:\b[a-z]{1,6}\.[a-z]{2,3}\b|\^[a-z]{2,6}\b"
            r"|\b(?:" + _MARKET_ASSET_WORDS + r")\b))",
            re.IGNORECASE | re.DOTALL,
        )],
    ),
    "wiki_lookup": Capability(
        key="wiki_lookup",
        call=_call_wiki_lookup,
        short="hasło z Wikipedii do banku wiedzy (argument: temat)",
        prompt=(
            "- **wiki_lookup**: ENCYKLOPEDYCZNA wiedza o świecie (osoby, "
            "miejsca, pojęcia, wydarzenia), NIE z plików użytkownika. "
            "Pasuje do \"co to jest X\", \"kim był X\", \"sprawdź na "
            "Wikipedii X\". Różnica od search_brain: wiedza ZE ŚWIATA, nie "
            "z notatek użytkownika. Różnica od research_web: stabilne "
            "fakty encyklopedyczne, nie aktualności/ceny/\"co się teraz "
            "dzieje\" (to research_web). Znalezisko trafia do lokalnego "
            "banku wiedzy - następne pytanie o ten temat nie potrzebuje "
            "już internetu."
        ),
        # Wąski, celowo: tylko wyraźne "Wikipedia"/"encyklopedia". Ogólne
        # "co to jest X"/"kim był X" bez tego słowa jest ZA szerokie na
        # szybką ścieżkę (kolidowałoby z pytaniami o WŁASNE pojęcia
        # użytkownika z search_brain) i zostaje dla Ollamy do rozpoznania
        # przez prompt wyżej; gdy się jej to uda, learning.py (patrz
        # router.py, krok 0.75) sam zapamięta tę konkretną frazę jako
        # nowy szybki wzorzec, dokładnie tak samo jak dla innych narzędzi.
        keywords=[re.compile(
            r"\bwikipedi\w*\b|\bencyklopedi\w*\b",
            re.IGNORECASE,
        )],
    ),
    "weather": Capability(
        key="weather",
        call=_call_weather,
        short="pogoda i prognoza na dziś/jutro (argument: miasto, domyślnie z .env)",
        prompt=(
            "- **weather**: aktualna pogoda i prognoza na dziś i jutro (temperatura, opady, wiatr, "
            "wschód i zachód słońca) z Open-Meteo. Dotyczy \"jaka jest pogoda\", \"czy będzie "
            "padać\", \"prognoza na jutro w Krakowie\". Nie zgaduj pogody z pamięci ani z linków."
        ),
        # Słowo "pogoda" na POCZĄTKU wiadomości (40 znaków) albo wyraźne pytanie o deszcz:
        # "zła pogoda zepsuła mi plany" w środku dłuższego zdania to rozmowa, nie prośba o prognozę.
        keywords=[re.compile(
            # Audyt 1.32.1: tylko odmiana słowa "pogoda" - "pogodziłem się z bratem" i
            # "jestem pogodny" to nie pytania o prognozę.
            r"\A[^.?!\n]{0,40}\bpogod(?:a|y|[eę]|zie|[aą]|owe\w*)\b|\A[^.?!\n]{0,40}\bprognoz\w*\s+(?:pogody|na\s+(?:dzi[sś]|jutro|weekend))\b"
            r"|\A\s*(?:czy|a\s+czy)\s+(?:dzi[sś]\s+|jutro\s+|dzisiaj\s+)?(?:b[eę]dzie\s+)?pada(?:[cć]|\s+deszcz|\s+[sś]nieg)?\b"
            # 1.32.2 (audyt tura 7): "będzie dziś padać?" - czas także po "będzie", bez "czy".
            r"|\A\s*(?:(?:czy|a\s+czy)\s+)?(?:(?:dzi[sś]|dzisiaj|jutro)\s+)?b[eę]dzie\s+(?:(?:dzi[sś]|dzisiaj|jutro)\s+)?pada(?:[cć]|\s+deszcz|\s+[sś]nieg)?\b"
            r"|\A\s*(?:ile\s+(?:jest\s+)?stopni|jaka\s+(?:jest\s+)?temperatura)\s+(?:na\s+dworze|za\s+oknem|w\s+\w+)",
            re.IGNORECASE,
        )],
    ),
    "net_diagnose": Capability(
        key="net_diagnose",
        call=_call_net_diagnose,
        short="diagnoza dostępu GREGAI do internetu, warstwa po warstwie",
        prompt=(
            "- **net_diagnose**: sprawdza, czy i dlaczego GREGAI ma albo nie ma internetu (WARP, tunel, DNS, "
            "wyszukiwarki, dostawcy AI) i mówi, co naprawić. Dotyczy \"czemu nie masz internetu?\", "
            "\"zdiagnozuj internet\", \"sprawdź połączenie z internetem\". To NIE jest stan sieci domowej "
            "(urządzenia, router) - to network_status."
        ),
        keywords=[re.compile(
            r"\bdiagnoz\w*\s+(?:dost[eę]pu\s+do\s+)?(?:internet\w*|po[lł][aą]czeni\w*|warp)\b"
            r"|\bzdiagnozuj\b"
            r"|\b(?:czemu|dlaczego)\s+(?:nie\s+masz|nie\s+dzia[lł]a\s+ci|nie\s+dzia[lł]a|tracisz)\s+(?:dost[eę]pu\s+do\s+)?internet\w*"
            r"|\A\W*sprawd[zź]\s+(?:mi\s+|swoje\s+)?(?:po[lł][aą]czenie\s+z\s+internetem|dost[eę]p\s+do\s+internetu|internet)\W*\Z"
            r"|\bczy\s+masz\s+(?:teraz\s+)?(?:dost[eę]p\s+do\s+)?internet\w*\b"
            # pretensja z rozmowy z 23.10: „Jak to nie masz dostępu do internetu” - odpowiedzią jest diagnoza
            r"|\A\W*(?:jak\s+to|przecie[zż])\s+nie\s+masz\s+(?:dost[eę]pu\s+do\s+)?internet\w*",
            re.IGNORECASE,
        )],
    ),
    "self_model": Capability(
        key="self_model",
        call=_call_self_model,
        short="kim jest GREGAI i z jakich modeli korzysta",
        prompt=(
            "- **self_model**: kim jest GREGAI, kto go stworzył i z jakich modeli korzysta. "
            "Dotyczy \"z jakiego modelu korzystasz?\", \"na jakim modelu działasz?\", \"czym "
            "jesteś?\", \"kto cię napisał?\"."
        ),
        keywords=[re.compile(
            # Audyt 1.32.1: pytanie o model musi dotyczyć GREGAI (druga osoba) - "Jaki model
            # iPhone'a kupić do flipa?" odpowiadało "Jestem GREGAI...".
            r"\A(?=.*\b(?:jeste[sś]|ty|ci[eę]|ciebie|tob\w*|tw[oó]j\w*|u[zż]ywasz|korzystasz|dzia[lł]asz|nap[eę]dza\w*)\b)"
            r"(?=.*(?:\b(?:z\s+jakiego|jakiego|na\s+jakim|jakim|kt[oó]rego|kt[oó]rym)\s+(?:modelu|modelem|llm\w*|ai)\b"
            r"|\bjaki(?:m)?\s+(?:jeste[sś]\s+)?model(?:em)?\b))"
            r"|\b(?:czym|kim)\s+(?:ty\s+)?jeste[sś]\b"
            r"|\bkto\s+(?:ci[eę]|tobie)\s+(?:stworzy|napisa|zrobi|zaprogramowa|wytrenowa|zbudowa)\w*"
            r"|\bkto\s+(?:jest\s+)?tw(?:oim|[oó]j)\s+(?:tw[oó]rc|autor)\w*",
            re.IGNORECASE,
        )],
    ),
    "self_status": Capability(
        key="self_status",
        call=_call_self_status,
        short="czego GREGAI się nauczył",
        prompt=(
            "- **self_status**: co GREGAI SAM się do tej pory nauczył (nowe "
            "komendy, słowa do dopytań, bank wiedzy z Wikipedii) i jaka "
            "część rozmów nie potrzebowała już modelu. Dotyczy \"czego się "
            "nauczyłeś?\", \"jak Ci idzie samouczenie?\" (o Twoim "
            "rozwoju/nauce, nie sieci domowej czy projektach użytkownika)."
        ),
        keywords=[re.compile(
            r"\b(czego|co)\s+si[eę]\s+nauczy[lł]e?ś\b"
            r"|\A\s*(?:jak\s+si[eę]\s+(?:czujesz|masz)|jaki\s+(?:jest\s+)?tw[oó]j\s+stan|co\s+(?:ostatnio\s+)?robi[lł]e?ś)\s*[?!.]*\s*\Z"
            r"|\bco\s+(teraz\s+)?umiesz(\s*,?\s*czego\s+nie\s+umia[lł]e?ś)?\b"
            r"|\bco\s+nowego\s+(umiesz|potrafisz)\b"
            r"|\bjak\s+ci\s+idzie\s+samoucz\w*\b"
            r"|\bile\s+si[eę]\s+(już\s+)?nauczy[lł]e?ś\b"
            r"|\bczy\s+się\s+(czegoś\s+)?nauczy[lł]e?ś\b",
            re.IGNORECASE,
        )],
    ),
    "brief_me": Capability(
        key="brief_me",
        call=_call_brief_me,
        short="brief: najważniejsze węzły notatek i alerty sieci domowej",
        prompt=(
            "- **brief_me**: krótkie podsumowanie: najważniejsze węzły w "
            "notatkach i alerty sieci domowej. Kalendarza ani poczty NIE "
            "czyta. Dotyczy KAŻDEGO pytania o to, co nowego/ważnego się "
            "dzieje, np. \"co nowego?\", \"zrób mi brief\"."
        ),
        keywords=[re.compile(
            # Żywy przykład błędu, od którego to powstało: "co się
            # zmieniło ważnego?" (naturalna parafraza "co nowego?"/"co
            # ważnego?", inny szyk słów) trafiało w search_brain, bo
            # brief_me miał te same dwa problemy co plan_day wyżej:
            # prompt bez przykładów parafraz i wzorzec za wąski na
            # inny szyk słów.
            # 1.19.0 (audyt rdzenia): "co nowego"/"co się zmieniło" tylko jako
            # krótkie pytanie samo w sobie (ew. "u mnie", "dziś", "ważnego") -
            # "Co nowego w Pythonie 3.14?" i "Co się zmieniło w iOS 26?" to
            # pytania o świat, nie o moje notatki.
            r"\bbrief\b|\A\s*(?:no\s+(?:to\s+)?|i\s+)?co\s+(?:nowego|wa[zż]nego|si[eę]\s+zmieni[lł]o)"
            r"(?:\s+(?:u\s+mnie|dzi[sś]|dzisiaj|wa[zż]nego|ostatnio|w\s+(?:moich\s+)?notatkach))*\s*[?!.]*\s*\Z"
            r"|\A\s*co\s+(?:mam|jest)\s+(?:dzi[sś]|dzisiaj|jutro)?\s*w\s+kalendarzu\s*[?!.]*\s*\Z"
            r"|\A\s*(?:jakie|czy)\s+mam\s+nieprzeczytan\w*\s+(?:wiadomo[sś]ci|maile?)\s*[?!.]*\s*\Z"
            r"|\bwymaga\w*\s+(mojej\s+)?uwagi\b",
            re.IGNORECASE,
        )],
    ),
    "remember": Capability(
        key="remember",
        call=_call_remember,
        short="zapisz jeden fakt do pamięci (argument: treść faktu)",
        prompt=(
            "- **remember**: jeden fakt, jeden opatrzony datą plik w "
            "memory/. Zawsze powiedz na głos dokładnie to, co zapisałeś. "
            "Pasuje do \"zapamiętaj: ...\", \"zapisz sobie, "
            "że ...\", \"nie zapomnij, że ...\"."
        ),
        keywords=[re.compile(
            # "zapisz sobie"/"nie zapomnij", NIE gołe "zapisz": to
            # ostatnie jest zbyt ogólne po polsku (zapisz PLIK, zapisz
            # MNIE na wizytę...), złapałoby dużo niezwiązanych próśb i
            # pisało bezsensowne "fakty" do memory/. "zapisz sobie" i
            # "nie zapomnij" to już jednoznacznie prośba o zapamiętanie.
            # Żywy przykład błędu, od którego to powstało: "zapisz
            # sobie, że testuję teraz GREGAI" trafiało w search_brain.
            r"\bzapami[eę]taj\b|\bzapisz\s+sobie\b|\bnie\s+zapomnij\b",
            re.IGNORECASE,
        )],
    ),
    "plan_day": Capability(
        key="plan_day",
        call=_call_plan_day,
        short="plan dnia z notatek użytkownika",
        prompt=(
            "- **plan_day**: maksymalnie pięć elementów bazy, "
            "uporządkowanych wg tego, co najważniejsze strategicznie i "
            "finansowo. WYŁĄCZNIE z notatek użytkownika i z tego, co sam "
            "powiedział w rozmowie, nigdy nie zmyślaj punktów planu. "
            "Dotyczy KAŻDEGO pytania o to, co dziś/dzisiaj robić, np. "
            "\"plan na dziś?\", \"co mam dzisiaj do zrobienia?\"."
        ),
        keywords=[re.compile(
            # Poprzedni wzorzec ("dzi[eę]\b") łapał "dzień" ale NIE "dziś"
            # (najnaturalniejsze "plan na dziś" przechodziło w ogóle
            # niezauważone), znalezione testem przy okazji innej zmiany.
            r"\bplan\s+na\s+dzi[sś]\b|\bplan\s+na\s+dzie[nń]\b|\bplan\s+dnia\b|\bzaplanuj\s+(mi\s+)?dzie[nń]\b"
            # Dwa niezależne lookaheady (jak przy "podłączył" w
            # network_status niżej): "dziś/dzisiaj" GDZIEKOLWIEK w
            # wiadomości ORAZ słowo o robieniu/priorytetach/ważności
            # GDZIEKOLWIEK. Żywy przykład błędu, od którego to powstało:
            # "co mam dzisiaj do zrobienia?" (naturalna parafraza "planu
            # na dziś", bez słowa "plan" wcale) trafiało w search_brain,
            # bo plan_day miał jeden, sztywny wzorzec i prompt bez
            # żadnych przykładów parafraz, w przeciwieństwie do
            # network_status/graph_overview.
            # 1.19.0: "najważniejsze" tylko z "mam/moje/mój/zrobić" - "Jakie są
            # najważniejsze wiadomości dziś?" to pytanie o świat, nie o plan.
            # Audyt 1.32.1: "zrobić" tylko z "mam/muszę/trzeba" - "Co mogę dziś zrobić na
            # obiad?" to nie pytanie o plan dnia.
            r"|\A(?=.*\bdzi[sś](?:iaj)?\b)(?=.*\b(?:zrobieni\w*|priorytet\w*)\b)"
            r"|\A(?=.*\bdzi[sś](?:iaj)?\b)(?=.*\bzrobi[cć]\w*\b)(?=.*\b(?:mam|musz[eę]|trzeba|powinien\w*|powinnam)\b)"
            r"|\A(?=.*\bdzi[sś](?:iaj)?\b)(?=.*\b(?:naj)?wa[zż]niejsz\w*\b)(?=.*\b(?:mam|moje|m[oó]j|moim|dla\s+mnie)\b)"
            r"(?!.*\b(?:wiadomo[sś]\w*|news\w*|informacj\w*\s+ze\s+[sś]wiata)\b)",
            re.IGNORECASE | re.DOTALL,
        )],
    ),
    "network_status": Capability(
        key="network_status",
        call=_call_network_status,
        short="stan sieci domowej: urządzenia, router, sygnał, dane",
        prompt=(
            "- **network_status**: PEŁNY stan sieci domowej: (1) urządzenia "
            "TERAZ podłączone vs. znane-ale-offline (IP/MAC/nazwa/"
            "producent); (2) alerty: nowe urządzenie albo powrót po "
            "nieobecności; (3) router: sygnał, operator, typ (LTE/5G), "
            "dane w TYM MIESIĄCU, SSID, model, bateria. Dotyczy KAŻDEGO "
            "pytania o sieć/Wi-Fi/router/urządzenia, np. \"stan sieci?\". "
            "To NIE search_brain: sieć to nie notatka w plikach. \"Sieć\" "
            "może też znaczyć GRAF notatek (np. \"co się z czym łączy\") - "
            "dwuznaczność z graph_overview, dopytaj."
        ),
        keywords=[re.compile(
            # 1.19.0 (audyt rdzenia): "jakie urządzenia" tylko z "w sieci/podłączone/
            # mam w domu" - "Jakie urządzenia Apple polecasz?" to zakupy.
            r"\bjakie\s+urz[aą]dzenia\b(?=.*\b(?:sieci|wifi|wi[- ]?fi|pod[lł][aą]czon\w*|router\w*|w\s+domu)\b)"
            r"|\bkto jest w sieci\b|\b(stan|status)\s+siec\w*\b"
            # \bsie[cć]\w*\s+domow\w*\b (nie tylko sztywne "sieć
            # domowa"/"domową"). Żywy przykład błędu, od którego to
            # powstało: "ile mam połączeń W SIECI DOMOWEJ" (dopełniacz,
            # po "w") nie łapało się na starym, sztywnym wzorcu, model
            # nie skojarzył tego z network_status i pytanie trafiło
            # błędnie do search_brain ("nie znalazłem nic w plikach").
            r"|\bsie[cć]\w*\s+domow\w*\b|\bco (siedzi|wisi) w sieci\b"
            # "internetu" dopisane obok "danych": przykład z prompta
            # tego narzędzia to literalnie "ile mam danych/internetu w
            # tym miesiącu", a stary wzorzec łapał tylko wariant z
            # "danych", nie z "internetu".
            # 1.19.0: "ile danych/internetu" tylko z "mam/zostało/zużyłem/w tym
            # miesiącu" - "Ile kosztuje abonament internetu w Orange?" i "Ile
            # danych potrzeba do treningu modelu?" to nie pytania o mój router.
            r"|\A(?=.*\b(?:ile|zu[zż]ycie|zu[zż]y[lł]\w*)\b)(?=.*\b(?:danych|internetu|transferu|gb)\b)"
            r"(?=.*\b(?:mam|mi|zosta[lł]o|zu[zż]y[lł]\w*|zu[zż]ycie|w\s+tym\s+miesi[aą]cu|pakiet\w*)\b)"
            r"(?!.*\b(?:kosztuj\w*|cena|cen[yaę]|abonament\w*|potrzeba|potrzebuj\w*)\b)"
            r"|\blimit\s+danych\b"
            # "sygnał"/"zasięg" same w sobie są wieloznaczne (zasięg w
            # sensie social media/YouTube, sygnał w sensie "znak,
            # wskazówka") - żywy przykład błędu (runda 2 audytu,
            # 2026-10-19), zgłoszony jako realne ryzyko WŁAŚNIE dla tego
            # użytkownika (YouTube/streaming): "jaki mam teraz zasięg na
            # ostatnim filmie na YouTube?" i "to był mocny sygnał, że
            # powinienem zmienić pracę" fałszywie trafiały tutaj. Wymóg:
            # ALBO krótkie pytanie dokładnie z prompta tego narzędzia
            # ("jaki mam zasięg/sygnał?", bez niczego więcej), ALBO
            # współwystępowanie ze słowem sieciowym gdziekolwiek w
            # wiadomości.
            r"|\A\s*jaki\s+(?:mam\s+)?(?:teraz\s+)?(?:zasi[eę]g|sygna[lł]\w*)\s*[?!.]*\s*\Z"
            r"|\A(?=.*\b(?:zasi[eę]g\w*|sygna[lł]\w*)\b)"
            r"(?=.*\b(?:rout\w*|sie[cć]\w*|wifi|wi[- ]?fi|telefon\w*|operator\w*|4g|5g|lte|internet\w*)\b)"
            r"|\bnazwa\s+(mojego\s+)?wi[- ]?fi\b|\bssid\b"
            # 1.19.0: 4G/5G/LTE tylko o MOIM łączu ("mam", "router", "sygnał",
            # "jaki zasięg") - "Czy iPhone 13 ma 5G?" to pytanie o telefon na sprzedaż.
            r"|\A(?=.*\b(?:4g|5g|lte)\b)(?=.*\b(?:mam|m[oó]j|moim|router\w*|sygna[lł]\w*|zasi[eę]g\w*|[lł][aą]czy\s+si[eę]|po[lł][aą]czeni\w*)\b)"
            r"(?!.*\b(?:iphone\w*|samsung\w*|galaxy|xiaomi|pixel|telefon\s+ma|obs[lł]uguje|ma\s+(?:4g|5g|lte))\b)"
            r"|\bjaki\s+mam\s+internet\b"
            r"|\bbateria\w*\s+(w\s+)?router\w*\b|\bstatus\s+routera\b"
            # Dwa niezależne lookaheady (kolejność słów nie ma
            # znaczenia), ten sam wzorzec co w AMBIGUITY_GROUPS niżej:
            # "podłączył/podłączyła/podłączyło się" GDZIEKOLWIEK w
            # wiadomości ORAZ słowo sieć/wifi/router GDZIEKOLWIEK.
            # Żywy przykład błędu, od którego to powstało: "czy ktoś
            # nowy się podłączył do mojego wifi" (dokładnie przykład
            # z prompta tego narzędzia) trafiało w search_brain, bo
            # żaden wzorzec fallbacku tego nie łapał, a model (3b,
            # lokalnie) nie trzymał się instrukcji z prompt.md.
            r"|\A(?=.*\bpod[łl][aą]czy\w*\b)(?=.*\b(?:sieci?|wifi|wi[- ]?fi|rout\w*)\b)",
            re.IGNORECASE | re.DOTALL,
        )],
        clarify_context=(
            "O sieci domowej: jakie urządzenia (telefon, router, laptop) są "
            "teraz podłączone, i stan samego routera (sygnał, dane, Wi-Fi)."
        ),
        topic_words=[
            "sieć", "sieci", "siecią", "wifi", "wi-fi", "router", "routera",
            "routerze", "internet", "internetu", "urządzeni", "telefon",
            "laptop", "4g", "5g", "lte", "sygnał", "sygnal",
        ],
    ),
    "standing_task_new": Capability(
        key="standing_task_new",
        call=_call_standing_task_new,
        short="nowe zadanie stałe: pilnuj czegoś w tle i daj znać, gdy się wydarzy (argument: całe polecenie)",
        prompt=(
            "- **standing_task_new**: NOWE zadanie W TLE (nie jednorazowe "
            "pytanie) - czasowniki śledź/pilnuj/monitoruj/informuj mnie w "
            "sensie CIĄGŁYM (\"cały czas\", \"i daj znać, gdy...\"), nie "
            "\"sprawdź teraz\". Argument: CAŁA treść polecenia, dosłownie, "
            "nigdy skrócona. Pasuje do: \"śledź giełdę i daj znać kiedy "
            "wchodzić\"."
        ),
        # Żywy przykład błędu (runda 2 audytu, 2026-10-19): gołe "pilnuj"/
        # "śledź" bez wymogu współwystępowania z czymś wskazującym na
        # CIĄGŁOŚĆ łapało zwykłą rozmowę - i w przeciwieństwie do innych
        # narzędzi tutaj, skutek jest TRWAŁY: powstaje prawdziwe zadanie
        # stałe, które dalej działa w tle, nie tylko błędna odpowiedź.
        # "Lubię śledź w oleju, a Ty?" (śledź-ryba), "Pilnuj się, jest
        # ślisko", "Pilnuj dzieci, ja wychodzę na chwilę" - wszystkie
        # trafiały. Wymóg współwystępowania (lookahead niżej) już i tak
        # pokrywał prawdziwy przypadek, od którego to narzędzie powstało.
        keywords=[re.compile(
            # Dwa niezależne lookaheady (kolejność słów bez znaczenia):
            # czasownik śledzenia GDZIEKOLWIEK w wiadomości ORAZ wyraźny
            # znacznik ciągłości GDZIEKOLWIEK. Żywy przykład, od którego
            # to powstało: "potrzebuje, żebyś mi śledził giełde cały czas
            # i dawał znac kiedy wchodzić" (2026-10-19).
            # Audyt 1.32.1: tylko prośba do GREGAI (śledź, śledzić, śledził(byś), pilnuj,
            # pilnujcie...), nie pierwsza osoba: "Ciągle śledzę wiadomości i mnie to
            # dobija" zakładało trwałe zadanie w tle.
            r"\A(?=.*\b(?:[sś]led(?:[zź]|[zź]cie|zi[cć]|zi[lł]\w*)|(?:pilnuj|monitoruj|informuj)(?:cie|esz)?)\b)"
            r"(?=.*\b(?:ca[lł]y\s+czas|na\s+bie[zż][aą]co|ci[aą]gle|stale)\b)"
            # 1.19.0 (audyt rdzenia): gołe "daj znać kiedy" tworzyło TRWAŁE zadanie
            # w tle ("Daj znać kiedy skończysz"). Teraz tylko z czasownikiem
            # śledzenia albo warunkiem na liczbie/kursie/cenie.
            r"|\A(?=.*\b(?:daj\s+zna[cć]|informuj\s+mnie|powiadom\s+mnie|ostrze[zż]\s+mnie)\s*,?\s*(?:gdy|kiedy|jak|je[sś]li|je[zż]eli)\b)(?=.*\b(?:[sś]led[zź]\w*|pilnuj\w*|monitoruj\w*|kurs\w*|cen[aęy]\w*|spadnie|wzro[sś]nie|przekroczy|poni[zż]ej|powy[zż]ej|pojawi\s+si[eę]|zmieni\s+si[eę])\b)"
            r"|\binformuj\s+mnie\s+(?:na\s+bie[zż][aą]co\s+)?o\b",
            re.IGNORECASE | re.DOTALL,
        )],
    ),
    "standing_task_list": Capability(
        key="standing_task_list",
        call=_call_standing_task_list,
        short="lista zadań stałych, które GREGAI teraz pilnuje w tle",
        prompt=(
            "- **standing_task_list**: jakie zadania stałe teraz "
            "pilnujesz. \"co teraz śledzisz?\", \"co pilnujesz w tle?\"."
        ),
        keywords=[re.compile(
            r"\bco\s+(?:teraz\s+)?[sś]ledzisz\b|\bco\s+(?:teraz\s+)?pilnujesz\b"
            r"|\bjakie\s+(?:masz\s+)?zadania\s+sta[lł]e\b",
            re.IGNORECASE,
        )],
    ),
    "standing_task_stop": Capability(
        key="standing_task_stop",
        call=_call_standing_task_stop,
        short="zatrzymaj zadanie stałe (argument: którego dotyczyło, jeśli jest ich kilka)",
        prompt=(
            "- **standing_task_stop**: zatrzymanie zadania stałego. "
            "Argument: czego dotyczyło (do dopasowania, gdy jest ich "
            "kilka). \"przestań śledzić giełdę\"."
        ),
        keywords=[re.compile(
            r"\bprzesta[nń]\s+(?:[sś]ledzi[cć]|pilnowa[cć]|monitorowa[cć])\b"
            r"|\bzatrzymaj\s+(?:to\s+)?zadanie\b|\bkoniec\s+z\s+pilnowaniem\b"
            r"|\bwy[lł][aą]cz\s+zadanie\s+sta[lł]e\b",
            re.IGNORECASE,
        )],
    ),
}

# --- Narzędzia systemowe (agent/sysop.py), TYLKO gdy SYSOP_ENABLED=1 -------
# Na tym laptopie (patrz INSTALACJA_UBUNTU_26_04.md, Krok 12) GREGAI dostaje stałe, nazwane narzędzia
# systemowe z poziomami: odczyt od razu, zmiana po potwierdzeniu w rozmowie
# (agentloop.confirm_or_execute), destrukcyjne zablokowane - a w trybie pełnym
# (1.17.0, sysop.py "Tryb PEŁNY") wg SYSOP_PYTAJ. Rejestracja
# tutaj = te same trzy rzeczy co dla każdej zdolności (wywołanie, prompt,
# wzorce szybkiej ścieżki), więc router, szybka ścieżka i pętla agenta
# widzą je tak samo. Gdy SYSOP jest wyłączony, nie istnieją
# wcale: zestaw narzędzi się nie zmienia, wytrenowany router zostaje ważny.

_SERVICE_VERBS = {
    "zrestartuj": "restart", "restartuj": "restart", "zresetuj": "restart",
    "uruchom": "start", "wystartuj": "start", "odpal": "start",
    "zatrzymaj": "stop", "wyłącz": "stop", "wylacz": "stop", "rozłącz": "stop", "rozlacz": "stop", "zabij": "stop", "ubij": "stop",
    "włącz": "start", "wlacz": "start",
    "przeładuj": "reload", "przeladuj": "reload",
}
# "Wyłącz/włącz" bez dopowiedzenia znaczy zatrzymaj/uruchom teraz; `disable` i `enable`
# (start systemu, nie bieżący stan usługi) tylko gdy użytkownik mówi o starcie systemu.
_BOOT_WORDS = re.compile(r"ze startu|przy starcie|po starcie|na start|na stałe|na stale|autostart|z systemem|po restarcie komputera|"
                         r"przy uruchomieniu|przy bootowaniu|przy rozruchu")


_SERVICE_ACTIONS = {"start", "stop", "restart", "reload", "enable", "disable"}
# Odmiana nazwy usługi -> nazwa jednostki ("zrestartuj ollamę" -> ollama). Inne
# nazwy zostają jak napisał użytkownik; sysop (MANAGED_UNITS) i sudoers
# dopuszczają tylko gregai i ollama.
_UNIT_STEMS = (("ollam", "ollama"), ("gregai", "gregai"), ("warp", "warp-svc"), ("tunel", "warp-svc"), ("zapor", "ufw"), ("firewall", "ufw"),
               ("ufw", "ufw"), ("apparmor", "apparmor"), ("sshd", "sshd"), ("ssh", "ssh"))


def _canonical_unit(word: str) -> str:
    word = word.lower().strip(".,;:!?\"'")
    for stem, unit in _UNIT_STEMS:
        if word.startswith(stem):
            return unit
    return word


def _service_action_arg(message: str, arg: str | None) -> str | None:
    """'zrestartuj usługę gregai' -> 'restart gregai'; 'zrestartuj ollamę' ->
    'restart ollama'. Gdy model podał już argument w formie 'akcja nazwa',
    zostaje. None = nie wiadomo, o którą usługę chodzi (wtedy pytamy, zamiast
    po cichu restartować gregai)."""
    parts = (arg or "").split()
    if len(parts) >= 2 and parts[0].lower() in _SERVICE_ACTIONS:
        return f"{parts[0].lower()} {_canonical_unit(parts[1])}"
    text = (message or "").lower()
    if re.search(r"\bponownie\b", text):
        action = "restart"
    else:
        verb, action = next(((v, a) for v, a in _SERVICE_VERBS.items() if re.search(rf"(?<!\w){v}\w*", text)), ("", "restart"))
        if verb in ("wyłącz", "wylacz", "włącz", "wlacz") and _BOOT_WORDS.search(text):
            action = "disable" if action == "stop" else "enable"
    m = (re.search(r"us[lł]ug\w*\s+([\w.-]+)", text)
         or re.search(r"(?<!\w)(gregai\w*|ollam\w*|sshd?|nginx|cron|docker|warp\w*|tunel|zapor\w*|firewall\w*|ufw|apparmor\w*)(?!\w)", text))
    unit = _canonical_unit(m.group(1)) if m else ""
    return f"{action} {unit}" if unit else None


def _path_arg(arg: str | None) -> str | None:
    """Ścieżka z reszty zdania ("README.md i powiedz, co w nim jest" -> "README.md"): pierwsze
    słowo wyglądające na plik/folder (z "/" albo "." albo istniejące w dozwolonych katalogach);
    None = nic takiego, pytamy o ścieżkę."""
    words = (arg or "").strip(" :,?!").split()
    for w in words:
        w = w.strip("„”\"',;:")
        if not w:
            continue
        if "/" in w or "." in w or sysop_mod.resolve_in_roots(w) is not None and sysop_mod.resolve_in_roots(w).exists():
            return w
    return None


def _make_sysop_call(tool_name: str):
    def _call(vault, message, arg):
        import agentloop  # leniwie: agentloop importuje capabilities
        if tool_name == "sys_service_action":
            arg = _service_action_arg(message, arg)
            if arg is None:
                return {"speech": "Którą usługę? Mogę zarządzać tylko dwiema: gregai i ollama. "
                                  "Napisz np. „zrestartuj usługę ollama”.", "card": None, "ok": False}
        elif tool_name in ("fs_read", "fs_list"):
            arg = _path_arg(arg)
            if arg is None:
                return {"speech": "Którą ścieżkę? Podaj nazwę pliku albo folderu, np. „pokaż plik README.md”.", "card": None, "ok": False}
        elif tool_name == "sys_services":
            # Z rozmowy: tylko prawdziwa nazwa jednostki, inaczej lista ("Czy usługi działają?").
            arg = sysop_mod.pick_unit(message, arg)
        elif tool_name == "sys_logs":
            first = ((arg or "").split() or [""])[0]
            if "/" not in first and not first.endswith((".log", ".txt", ".json")):
                # Jednostka z rozmowy ("pokaż logi ollamy" -> arg bywa całym zdaniem) plus ewentualna liczba linii.
                nums = [w for w in (arg or "").split() if w.isascii() and w.isdigit()][:1]
                arg = " ".join([sysop_mod.pick_unit(message, arg) or "gregai"] + nums)
        return agentloop.confirm_or_execute(vault, tool_name, (arg or "").strip(), origin="rozmowa")
    return _call


_SYSOP_KEYWORDS = {
    "sys_status": [re.compile(r"\b(stan|status|obci[aą][zż]enie)\s+(serwera|systemu|komputera|maszyny)\b|\bile\s+(mam\s+)?(wolnego\s+)?(miejsca|wolnego)\s+(mam\s+)?na\s+dysku\b|\bile\s+(mam\s+)?(?:(wolnej\s+)?ram\b|wolne(?:go|j)\s+ramu\b)|\btemperatur\w*\s+(cpu|procesora|serwera)\b", re.IGNORECASE)],
    "sys_services": [re.compile(r"\bjakie\s+us[lł]ugi\b|\bstatus\s+us[lł]ugi\b|\bczy\s+us[lł]uga\s+\S+\s+(dzia[lł]a|chodzi)\b|\bus[lł]ugi\s+(systemowe|systemd)\b", re.IGNORECASE)],
    # Żywy przykład błędu (runda 2 audytu, 2026-10-19): gołe "journal" łapało
    # "Czytałem dziś artykuł w Wall Street Journal"/"Prowadzę journal swoich
    # transakcji" - teraz wymaga też czasownika sprawdzania/pokazywania,
    # tak jak pierwsza alternatywa tej samej zdolności.
    "sys_logs": [re.compile(
        r"\b(poka[zż]|wy[sś]wietl|sprawd[zź])\s+logi\b|\blogi\s+(us[lł]ugi|serwera|systemu|gregai|ollam\w*)\b"
        r"|\A(?=.*\bjournal\w*\b)(?=.*\b(?:poka[zż]\w*|wy[sś]wietl\w*|sprawd[zź]\w*)\b)",
        re.IGNORECASE | re.DOTALL,
    )],
    "sys_updates": [re.compile(r"\b(s[aą]|jakie|ile)\s+(jakie[sś]\s+)?aktualizacj\w*\b|\bdo\s+aktualizacji\b|\bczy\s+system\s+jest\s+aktualny\b", re.IGNORECASE)],
    "sys_network": [re.compile(r"\b(otwarte|nas[lł]uchuj[aą]ce)\s+porty\b|\binterfejsy\s+sieciowe\b|\bjakie\s+ip\s+ma\s+serwer\b", re.IGNORECASE)],
    "fs_read": [re.compile(r"\b(poka[zż]|przeczytaj|otw[oó]rz|wy[sś]wietl)\s+(mi\s+)?(zawarto[sś][cć]\s+)?plik\w*\s+", re.IGNORECASE)],
    "fs_search": [re.compile(r"\b(wyszukaj|znajd[zź]|szukaj|poszukaj|grep\w*)\s+(mi\s+)?(w|we)\s+plikach\s+(s[lł]ow[oa]\s+|fraz[eę]\s+|tekst\s+)?", re.IGNORECASE)],
    "fs_list": [re.compile(r"\b(wylistuj|wypisz|poka[zż]|wy[sś]wietl)\s+(mi\s+)?(zawarto[sś][cć]\s+)?(folder\w*|katalog\w*)\s+|\bco\s+jest\s+w\s+(folderze|katalogu)\s+|\blista\s+plik[oó]w\s+w\s+", re.IGNORECASE)],
    # Żywy przykład błędu (runda 2 audytu, 2026-10-19): gołe "jakie procesy"
    # łapało "Jakie procesy sądowe mogą mi grozić po tej transakcji?" -
    # teraz wymaga współwystępowania ze słowem komputerowym/systemowym.
    "sys_processes": [re.compile(
        r"\A(?=.*\b(?:jakie|kt[oó]re)\s+procesy\b)"
        r"(?=.*\b(?:cpu|procesor\w*|pami[eę][cć]\w*|ram|system\w*|serwer\w*|komputer\w*|maszyn\w*)\b)"
        r"|\bco\s+(zjada|zu[zż]ywa|obci[aą][zż]a)\s+(cpu|procesor|pami[eę][cć]|ram)\b",
        re.IGNORECASE | re.DOTALL,
    )],
    # Żywy przykład błędu (runda 2 audytu, 2026-10-19): gołe "timery" łapało
    # "Mam już odliczanie timery w kuchni na jajka." - teraz albo krótkie
    # pytanie dokładnie w stylu prompta tej zdolności, albo współwystępowanie
    # ze słowem system/systemd/cron.
    "sys_timers": [re.compile(
        r"\A\s*(?:jakie\s+(?:masz\s+)?timery|poka[zż]\s+(?:mi\s+)?timery)\s*[?!.]*\s*\Z"
        r"|\A(?=.*\btimery\b)(?=.*\b(?:system\w*|systemd|cron|harmonogram\w*|zaplanowan\w*)\b)"
        r"|\bzaplanowane\s+zadania\s+(systemu|systemd|cron)\b|\bcron\b",
        re.IGNORECASE | re.DOTALL,
    )],
    "sys_service_action": [re.compile(r"\b(zrestartuj|restartuj|zresetuj|uruchom|wystartuj|zatrzymaj|prze[lł]aduj|wy[lł][aą]cz|w[lł][aą]cz)\s+(us[lł]ug\w*|gregai|ollam\w*|serwer\s+gregai)\b|\b(wy[lł][aą]cz|rozł[aą]cz|rozlacz|zatrzymaj|zabij|ubij)\s+(mi\s+)?(zapor[eę]|firewall\w*|ufw|warp\w*|apparmor\w*|tunel)\b", re.IGNORECASE)],
    # "(zrób kopię zapasową...)(?!...papierze...)" - żywy przykład błędu
    # (runda 2 audytu, 2026-10-19): "Zrób kopię zapasową tego planu na
    # papierze, zanim go zgubisz" łapało to narzędzie. Niższe ryzyko niż
    # inne znaleziska tej rundy (wymaga Twojego potwierdzenia przed
    # wykonaniem), ale wykluczenie fizycznej kopii jest proste i darmowe.
    # 1.18.0: także bez zewnętrznego celu - "zrób backup na pendrive/dysk/usb/
    # telefon", "w chmurze" to kopia GDZIE INDZIEJ, a sys_backup robi kopię danych
    # GREGAI do backups/ na tym komputerze; karta pytałaby o inną akcję niż ta, o
    # którą chodzi (wtedy wiadomość idzie zwykłą drogą: router/planer).
    "sys_backup": [re.compile(r"^(?!.*\b(?:na\s+papierze|na\s+(?:pendrive\w*|pendrajw\w*|dysk|dysk\s+zewn\w*|zewn\w*|usb|telefon\w*|kart[eęy]\w*|serwer\w*|chmur[eę])"
                              r"|w\s+chmurze|do\s+chmury)\b)"
                              r".*?(?:\b(zr[oó]b|wykonaj|przygotuj)\s+(kopi[eę]\s+zapasow\w*|backup)\b|\bbackup\s+(danych|notatek|gregai)\b)",
                              re.IGNORECASE | re.DOTALL)],
    "sys_update_apply": [re.compile(r"\b(zaktualizuj|zainstaluj\s+aktualizacje)\s+(system\w*|serwer\w*|pakiety)\b", re.IGNORECASE)],
}

if sysop_mod.enabled():
    for _name, (_tier, _desc, _fn, _verify) in sysop_mod.active_tools().items():
        # Tryb pełny SYSOP (1.17.0): zmiana nie zawsze czeka na "tak" - prompt ma
        # mówić modelowi prawdę o tym, co kod faktycznie zrobi (sysop.needs_confirmation).
        _level = ("odczyt, wykonywane od razu" if _tier == sysop_mod.READ
                  else "zmiana, wymaga potwierdzenia użytkownika" if sysop_mod.needs_confirmation(_tier)
                  else "zmiana, wykonywana od razu (tryb pełny)")
        CAPABILITIES[_name] = Capability(
            key=_name,
            call=_make_sysop_call(_name),
            prompt=f"- **{_name}**: {_desc} (poziom: {_level}).",
            keywords=_SYSOP_KEYWORDS.get(_name, []),
            short=_desc,
        )

# Kolejność sprawdzania wzorców w trybie zapasowym (bez Ollamy). Pierwsze
# trafienie wygrywa. Nowe narzędzie z własnym wzorcem dopisz tu w miejscu,
# które ma sens względem istniejących (np. bardziej specyficzne wzorce
# wcześniej niż ogólne), domyślny fallback poza tą listą to search_brain.
# Narzędzia systemowe (gdy włączone) PRZED resztą: "zrestartuj usługę" ma
# trafić w sys_service_action, nie w search_brain.
_FALLBACK_ORDER = ([name for name in sysop_mod.active_tools() if name in CAPABILITIES] if sysop_mod.enabled() else []) + [
    "gregaipanicmode", "freeram", "fullon",
    "remember", "plan_day", "standing_task_new", "standing_task_list", "standing_task_stop",
    "network_status", "graph_overview",
    "net_diagnose", "self_model", "weather",
    "market_quote", "research_web", "wiki_lookup", "search_brain", "self_status", "brief_me",
]

TOOL_NAMES = {key for key, cap in CAPABILITIES.items() if cap.call is not None and not cap.user_only}


def assemble_tools_prompt() -> str:
    """Składa fragmenty promptu wszystkich zdolności w jeden blok markdown,
    w kolejności, w jakiej są zdefiniowane w CAPABILITIES powyżej."""
    return "\n".join(cap.prompt for cap in CAPABILITIES.values())


# Ile początkowych znaków wiadomości sprawdzają wzorce szybkiej ścieżki. Polecenie
# jest na początku zdania; długi wklejony tekst nie ma wywoływać narzędzia
# jednym słowem z głębi (np. "podłączył" w środku artykułu).
KEYWORD_SCAN_CHARS = 1500

# Prośba o zapisanie notatki na początku wiadomości ("zapamiętaj: ...", "zapisz sobie
# ...", "nie zapomnij ...") to zawsze remember, nawet gdy sama treść notatki brzmi jak
# polecenie systemowe ("zapisz sobie: zrestartuj usługę gregai w piątek").
NOTE_HEAD_RE = re.compile(r"\A\s*(zapami[eę]taj|zapisz\s+sobie|nie\s+zapomnij)\b", re.IGNORECASE)

# Pytanie definicyjne albo "jak to zrobić" ("co to jest LTE?", "czym jest journalctl?",
# "jak działa cron?", "jak sprawdzić miejsce na dysku?", "jak przetłumaczyć
# 'zapamiętaj ...'?") prosi o wyjaśnienie, nie o polecenie. Słowo tematu (LTE,
# journalctl, timery, dysk, zapamiętaj) nie może wtedy uruchamiać narzędzia: do
# szybkiej ścieżki zostaje tylko wyraźne "Wikipedia" / "sprawdź w internecie".
DEFINITION_HEAD_RE = re.compile(
    r"\A\s*(co\s+to\s+(jest|są|znaczy)|czym\s+(jest|są)|co\s+(oznacza|znaczy)|na\s+czym\s+polega"
    r"|jak\s+dzia[łl]a(j[ąa])?|do\s+czego\s+s[łl]u[żz]y(ą)?|po\s+co\s+(jest|są)"
    r"|jak\s+(?:(?:mo[żz]na|mog[eę]|da\s+si[eę]|nale[żz]y|powinienem|powinnam)\s+)?\w+ć)\b",
    re.IGNORECASE,
)
_DEFINITION_TOOLS = ("wiki_lookup", "research_web")

# Szybka ścieżka wysyła tekst do internetu tylko z KRÓTKIEJ wiadomości: polecenie typu
# "wyszukaj kurs euro" ma kilkadziesiąt znaków. Długi wklejony tekst (log, notatka,
# artykuł) ze słowem "wyszukaj" albo "Wikipedia" w środku nie może iść do wyszukiwarki.
_OUTBOUND_KEYS = ("research_web", "wiki_lookup", "market_quote")
MAX_OUTBOUND_CMD_CHARS = 300

# Narzędzia, które coś zapisują albo wysyłają: słowo-polecenie musi stać na POCZĄTKU
# wiadomości (pierwsze zdanie), nie w środku wklejonego tekstu ("przeczytaj to: ...
# nie zapomnij ... wyszukaj ..."). Wklejona treść to dane, nie polecenie.
_COMMAND_HEAD_CHARS = 160
_HEAD_ONLY_KEYS = ("remember", "research_web", "wiki_lookup", "market_quote")
# 1.20.0: narzędzia ZMIENIAJĄCE system łapią się tylko na początku wiadomości (40 znaków):
# "restartuj" w środku wklejonego logu albo cytatu nie może uruchomić zmiany.
_HEAD_STRICT_KEYS = ("sys_service_action", "sys_update_apply", "sys_backup")
_COMMAND_HEAD_STRICT_CHARS = 40


def find_keyword_match(message: str) -> tuple[str, str | None] | None:
    """Sprawdza wzorce `keywords` wszystkich zdolności w kolejności
    _FALLBACK_ORDER i zwraca (klucz_narzędzia, argument) dla pierwszego
    trafienia, albo None gdy żaden precyzyjny wzorzec nie pasuje.

    Używane w DWÓCH miejscach: (1) tutaj niżej w keyword_fallback(), gdy
    Ollama jest niedostępna, (2) w router.py jako SZYBKA ŚCIEŻKA dla
    jednoznacznych komend, NIEZALEŻNIE od tego, czy Ollama akurat
    odpowiada. Powód (2): "Plan na dziś?" czy "zapamiętaj X" są już
    jednoznaczne same z siebie (ten sam precyzyjny wzorzec, który i tak
    by finalnie trafił), więc czekanie 30-40s na model lokalny tylko po
    to, żeby on sam zawołał to samo narzędzie, jest czystą stratą czasu.
    Ta sama filozofia co check_ambiguity/resolve_clarify_answer wyżej:
    mechaniczna gwarancja tam, gdzie regex już wystarczy, model
    zarezerwowany dla reszty (rozmowa, niejednoznaczne sformułowania)."""
    scan = message[:KEYWORD_SCAN_CHARS]
    order = (["remember"] if NOTE_HEAD_RE.match(scan) else []) + list(_FALLBACK_ORDER)
    if DEFINITION_HEAD_RE.match(scan):
        order = [key for key in order if key in _DEFINITION_TOOLS]
    for key in order:
        if key in _OUTBOUND_KEYS and len(message) > MAX_OUTBOUND_CMD_CHARS:
            continue
        # Notatka zaczyna się od "zapamiętaj" (NOTE_HEAD_RE) i może być długa; "zapamiętaj" gdzieś
        # indziej liczy się tylko w krótkiej wiadomości, nie w wklejonym tekście "do podsumowania".
        if key == "remember" and not NOTE_HEAD_RE.match(scan) and len(message) > MAX_OUTBOUND_CMD_CHARS:
            continue
        cap = CAPABILITIES[key]
        # Audyt 1.8.20 runda 2: narzędzie świadomie wyłączone (call=None, patrz
        # komentarz Capability wyżej) nie ma TU czego wołać - dispatch() ma tę
        # samą osłonę, ale keyword_fallback() niżej woła cap.call(...) wprost,
        # bez niej. Obecnie żadna zdolność nie ma call=None razem z keywords,
        # więc to się jeszcze nie zdarzyło, ale jedno miejsce prawdy jest
        # bezpieczniejsze niż liczenie na to, że się nie zdarzy.
        if cap.call is None:
            continue
        for pattern in cap.keywords:
            hit = pattern.search(scan)
            if hit is None or (key in _HEAD_ONLY_KEYS and hit.start() >= _COMMAND_HEAD_CHARS) or (key in _HEAD_STRICT_KEYS and hit.start() >= _COMMAND_HEAD_STRICT_CHARS):
                continue
            arg = pattern.sub("", message, count=1).strip(" :,-?!.") or None
            return key, arg
    return None


def keyword_fallback(vault, message: str) -> dict:
    """Tryb zapasowy, gdy Ollama niedostępna. Sprawdza wzorce przez
    find_keyword_match(); brak trafienia = potraktuj jako pytanie o pliki."""
    match = find_keyword_match(message)
    if match is not None:
        key, arg = match
        return CAPABILITIES[key].call(vault, message, arg)
    return CAPABILITIES["search_brain"].call(vault, message, message)


def dispatch(tool_name: str, vault, message: str, arg: str) -> dict | None:
    """Wywołanie narzędzia, które model wybrał przez konwencję
    'TOOL: nazwa | argument'. None = nieznane/wyłączone narzędzie."""
    cap = CAPABILITIES.get(tool_name)
    if cap is None or cap.call is None or cap.user_only:
        return None
    return cap.call(vault, message, arg)


# --- Dwuznaczność: "o co Ci chodzi?" zamiast zgadywania ---------------------
# Powód, dla którego to istnieje: słowo "sieć" w tej aplikacji ma DWA
# zupełnie różne znaczenia: sieć domowa/Wi-Fi (network_status) i graf
# notatek, który też jest "siecią" połączeń (graph_overview). Pytanie typu
# "co odpowiada za co w sieci" jest naprawdę dwuznaczne: zgadnięcie
# jednego narzędzia na pewno czasem da złą odpowiedź. Rozwiązanie: ZAMIAST
# zgadywać, zapytaj użytkownika, który kontekst miał na myśli, i poczekaj
# na odpowiedź w następnej wiadomości (ona już naturalnie trafi do
# właściwego narzędzia, bo będzie jednoznaczna).
#
# Sprawdzane deterministycznie w router.py PRZED wywołaniem Ollamy, więc
# działa identycznie niezależnie od tego, czy model jest akurat dostępny
# (ta sama filozofia co capabilities.py w ogóle: mechaniczna gwarancja,
# nie liczenie na to, że model się tego "domyśli"). System prompt (patrz
# prompt.md) dodatkowo uczy model tej samej zasady jako uzupełnienie, dla
# dwuznacznych sformułowań, których nie przewidział żaden wzorzec tutaj.
#
# Dodanie nowej dwuznaczności = jeden nowy wpis tutaj + clarify_context
# na obu zdolnościach, których dotyczy (patrz CAPABILITIES wyżej).
AMBIGUITY_GROUPS = [
    {
        "trigger": re.compile(r"\A\s*(poka[zż]|wy[sś]wietl)\s+(mi\s+)?(moj[aą]\s+)?sie[cć]\s*[?.!]*\s*\Z", re.IGNORECASE),
        "options": ["network_status", "graph_overview"],
    },
    {
        # "Co odpowiada za co w sieci", "co w sieci odpowiada za co",
        # "w sieci co jest za co odpowiedzialne", dokładny przykład, od
        # którego to powstało, w dowolnym szyku słów (dwa niezależne
        # lookaheady: fraza "co ... odpowiada za co" gdziekolwiek w
        # wiadomości, i słowo "sieć/sieci" gdziekolwiek w wiadomości,
        # żeby kolejność nie miała znaczenia).
        "trigger": re.compile(
            r"\A(?=.*\bco\b.{0,25}\b(odpowiada|jest\s+odpowiedzialne)\s+za\s+co\b)"
            r"(?=.*\bsieci?\b)",
            re.IGNORECASE | re.DOTALL,
        ),
        "options": ["network_status", "graph_overview"],
    },
    {
        # "co się z czym łączy", "co jest połączone z czym", bez słowa
        # "sieć" wcale: to samo pytanie równie dobrze o urządzenia w
        # sieci domowej, jak o węzły w grafie notatek.
        "trigger": re.compile(
            r"\bco\s+(si[eę]\s+)?(jest\s+)?po[lł][aą]czon\w*\s+z\s+czym\b"
            r"|\bco\s+si[eę]\s+z\s+czym\s+[lł][aą]czy\b",
            re.IGNORECASE,
        ),
        "options": ["network_status", "graph_overview"],
    },
    {
        # Samo gołe "Połączenia?" (albo "jakie połączenia", "moje
        # połączenia") i NIC więcej, żywy przykład: użytkownik napisał
        # tylko to jedno słowo i trafił w search_brain ("nie znalazłem
        # nic o tym w plikach"), bo nic w tym pytaniu nie wskazywało na
        # żadne konkretne narzędzie. Zakotwiczone na CAŁEJ wiadomości
        # (^...$), dłuższe, już jednoznaczne pytanie z tym słowem w
        # środku (np. "ile mam aktywnych połączeń w sieci domowej") tego
        # NIE złapie, bo tam kontekst już rozstrzyga.
        "trigger": re.compile(
            r"^\s*(jakie\s+|moje\s+)?po[lł][aą]czeni\w*\s*\??\s*$",
            re.IGNORECASE,
        ),
        "options": ["network_status", "graph_overview"],
    },
]


def check_ambiguity(message: str) -> dict | None:
    """None = pytanie jednoznaczne, idź dalej normalnie (model/fallback).
    Dict = pytanie dopasowało znaną dwuznaczność, zwróć od razu pytanie
    doprecyzowujące z dwoma kontekstami, NIE wywołuj żadnego narzędzia."""
    for group in AMBIGUITY_GROUPS:
        if not group["trigger"].search(message):
            continue
        lines = []
        for i, key in enumerate(group["options"], start=1):
            cap = CAPABILITIES.get(key)
            context = (cap.clarify_context if cap and cap.clarify_context else key)
            lines.append(f"{i}) {context}")
        speech = "To może znaczyć dwie różne rzeczy:\n" + "\n".join(lines) + "\nO które z nich Ci chodzi?"
        return {
            "speech": speech,
            "card": {
                "type": "clarify",
                "options": [
                    {
                        "key": key,
                        "context": (CAPABILITIES[key].clarify_context if CAPABILITIES[key].clarify_context else key),
                    }
                    for key in group["options"]
                ],
            },
            # Echo wraca z frontendu w NASTĘPNYM żądaniu (pole
            # pending_clarify) i mówi resolve_clarify_answer() niżej, do
            # których dwóch narzędzi próbować dopasować odpowiedź
            # użytkownika. Bez tego każda kolejna wiadomość byłaby
            # traktowana jako całkiem nowe, niezależne pytanie i odpowiedź
            # w stylu "notatki" albo "o grafie notatek" nigdy nie trafiłaby
            # do właściwego narzędzia (żywy przykład błędu, od którego to
            # powstało).
            "pending_clarify": list(group["options"]),
        }
    return None


# Numer/słowo porządkowe -> indeks opcji (0 = pierwsza, 1 = druga). Działa
# niezależnie od treści opcji, więc zawsze jest sprawdzane jako pierwsze.
_ORDINAL_TO_INDEX = {
    "1": 0, "jeden": 0, "jedna": 0, "jedno": 0,
    "pierwsza": 0, "pierwszy": 0, "pierwsze": 0,
    "2": 1, "dwa": 1, "druga": 1, "drugi": 1, "drugie": 1,
}


MAX_CLARIFY_WORDS = 6


def resolve_clarify_answer(message: str, option_keys: list[str]) -> str | None:
    """Próbuje dopasować odpowiedź na pytanie doprecyzowujące (patrz
    check_ambiguity wyżej) do jednej z `option_keys` zaproponowanych w
    tym pytaniu. Dwa niezależne sposoby, sprawdzane w tej kolejności:

    1. Numer/słowo porządkowe ("1", "druga"): jednoznaczne, nie wymaga
       żadnej wiedzy o temacie.
    2. `topic_words` każdej z dwóch zdolności z option_keys, RĘCZNE
       (patrz CAPABILITIES wyżej) PLUS WYUCZONE (learning_mod.
       learned_topic_words: patrz agent/learning.py, sekcja "Druga
       warstwa samouczenia"): luźne, pojedyncze słowa-tematy (np.
       "notatki", "sieć"), rozpoznawane nawet gdy odpowiedź nie pasuje do
       żadnego z precyzyjnych wzorców `keywords` tej zdolności (te są
       pisane pod pełne pytania, nie pod krótkie odpowiedzi typu jedno
       słowo). Wyuczone słowa rosną same z użycia: gdy ręczna lista tu
       nie wystarczy i odpowiedź rozpozna się normalną ścieżką routingu
       niżej w router.py, ta konkretna fraza zostaje dopisana tutaj, żeby
       następne takie samo dopytanie złapało ją już od razu.

    None = nie udało się jednoznacznie rozpoznać (obie zdolności trafione
    naraz albo żadna). Nie zgaduj, potraktuj wiadomość normalnie, jak
    każdą inną (może to zupełnie nowy temat, nie odpowiedź na dopytanie)."""
    text = message.strip().lower().rstrip(".!?) ")
    # Odpowiedź na dopytanie jest krótka. Długa wiadomość to nowe pytanie, nawet
    # jeśli zawiera słowo-temat ("sieć").
    if len(text.split()) > MAX_CLARIFY_WORDS:
        return None

    ordinal = _ORDINAL_TO_INDEX.get(text)
    if ordinal is not None and ordinal < len(option_keys):
        return option_keys[ordinal]

    matches = []
    for key in option_keys:
        cap = CAPABILITIES.get(key)
        if not cap:
            continue
        words = list(cap.topic_words) + learning_mod.learned_topic_words(key)
        if any(re.search(r"(?<!\w)" + re.escape(word), text) for word in words if word):
            matches.append(key)

    if len(matches) == 1:
        return matches[0]
    return None
