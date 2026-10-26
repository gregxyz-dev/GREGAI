"""
symbols.py

Jedno miejsce prawdy dla rozpoznawania tickerów/symboli giełdowych i
kryptowalutowych w dowolnym tekście w naturalnym języku.

Wydzielone z standing.py w 1.16.2 (czytelność): ta logika nie ma nic
wspólnego z zadaniami stałymi - to standing.py pożyczał ją, a capabilities.py
(_call_market_quote, _MARKET_ASSET_WORDS) sięgał PO NIĄ dalej, wprost do
prywatnych atrybutów modułu standing (standing_mod._SYMBOL_ALIASES,
standing_mod._EXPLICIT_SYMBOL_RE) - czyli moduł o zadaniach stałych pełnił
rolę biblioteki współdzielonej, nigdy tak nie pomyślanej. Teraz obie strony
(standing.py dla zadań stałych, capabilities.py dla bezpośrednich pytań o
kurs) importują ten sam, jawnie publiczny moduł, zamiast sięgać do cudzych
szczegółów implementacji jednym poziomem za głęboko.

Walidację KSZTAŁTU pojedynczego, już wyciągniętego tickera (do samego
zapytania o notowanie) zostawiamy w tools.py (_SYMBOL_RE, tuż przy market_quote) -
to inna odpowiedzialność: tu wyszukujemy ticker GDZIEŚ w zdaniu, tam
sprawdzamy, czy to, co mamy, w ogóle wygląda jak bezpieczny ticker.
"""

from __future__ import annotations

import re

# Kilka najpopularniejszych, potocznie wpisywanych nazw -> ticker/symbol
# (krypto idzie potem do Coinbase, reszta do Yahoo Finance - patrz tools.py).
# Celowo małe i ostrożne: nie zgadujemy tickera z nazwy firmy (zbyt
# niejednoznaczne), ale zdanie może od razu podać literalny ticker (np.
# "śledź kurs aapl.us") - wtedy ten słownik nie jest nawet potrzebny.
SYMBOL_ALIASES = {
    "bitcoin": "btcusd", "bitcoina": "btcusd", "bitcoinem": "btcusd", "btc": "btcusd",
    "ethereum": "ethusd", "eth": "ethusd",
    # 1.30.16: więcej głównych kryptowalut (notowania przez Coinbase, patrz tools._CRYPTO_PAIRS).
    "solana": "solusd", "solany": "solusd", "solaną": "solusd", "sol": "solusd",
    "ripple": "xrpusd", "xrp": "xrpusd",
    "cardano": "adausd", "ada": "adausd",
    "dogecoin": "dogeusd", "doge": "dogeusd",
    "polkadot": "dotusd", "dot": "dotusd",
    "litecoin": "ltcusd", "ltc": "ltcusd",
    "chainlink": "linkusd", "link": "linkusd",
    "avalanche": "avaxusd", "avax": "avaxusd",
    "bonk": "bonkusd", "bonka": "bonkusd",
    "złoto": "xauusd", "zloto": "xauusd",
    # Audyt 1.32.1: dopełniacz ("cena złota") - tylko z sygnałem finansowym, jak "złoto".
    "złota": "xauusd", "zlota": "xauusd",
    # 1.32.6 (rozmowa 25.10): srebro nie było rozpoznawane, więc każde pytanie dawało kartę.
    "srebro": "xagusd", "srebra": "xagusd", "srebrem": "xagusd",
}
# "złoto"/"zloto" i "eth" są wieloznaczne poza finansami (złoty medal, złota
# zasada, złota rybka; "eth" jako inicjały/nazwa projektu/ETH Zurich) - żywy
# przykład błędu z audytu 2026-10-19: "śledź czy wygram złoto na zawodach
# pływackich" i "śledź mój projekt o nazwie eth" fałszywie wykrywały ticker.
# "bitcoin"/"btc"/"ethereum" nie mają w praktyce tego problemu, zostają bez
# dodatkowego wymogu. Dla słów z tej listy wymagamy więc, żeby w tekście był
# też wyraźny sygnał finansowy - inaczej to nie ten "kurs".
# Krótkie, kolizyjne tickery (poza finansami znaczą co innego: sól, imię Ada,
# kropka, link, skrót ltc) wymagają finansowego sygnału w tekście - jak "eth".
# Pełne nazwy (solana, cardano, dogecoin...) są jednoznaczne, zostają bez wymogu.
AMBIGUOUS_ALIASES = frozenset({"złoto", "zloto", "złota", "zlota", "srebro", "srebra", "srebrem", "eth", "sol", "ada", "dot", "link", "ltc"})
FINANCE_QUALIFIER_RE = re.compile(
    r"\b(?:kurs\w*|notowan\w*|cen[aąeęy]|kosztuj\w*|gie[łl]d\w*|rynk\w*|inwestyc\w*|invest\w*|surowc\w*|uncj\w*|krypto\w*)\b",
    re.IGNORECASE,
)
# Wprost napisany ticker w tekście: "aapl.us", "^spx" itp. - ten sam kształt,
# co tools._SYMBOL_RE, tylko szukany GDZIEKOLWIEK w tekście, nie jako cała
# wiadomość (bo tekst to zwykle pełne zdanie/polecenie, np. "śledź kurs
# aapl.us i daj znać przy spadku", albo "Jaki jest kurs aapl.us?").
# Audyt 1.32.1: tylko prawdziwe sufiksy giełd (Stooq/Yahoo), nie dowolne ".xx" -
# "notes.md", "app.js" czy "money.pl" szły jako ticker do Yahoo. Przed nim nie może
# stać kropka, ukośnik ani @, a po nim litera, ukośnik albo kropka z literą (ścieżka,
# domena); kropka kończąca zdanie jest w porządku.
EXPLICIT_SYMBOL_RE = re.compile(
    r"(?<![\w./@])[a-z]{1,6}\.(?:us|uk|de|jp|hk|wa|pa|as|mi|sw|to|ax|he|st|ns|bo|sa|mx|ol|ks|ss|sz|tw|si|vi)(?![\w/]|\.\w)|\^[a-z]{2,6}\b")

# Gotowy do użycia w regexach fallbacku (np. capabilities.py: keywords=
# zdolności market_quote) - wszystkie znane aliasy jako jedna alternatywa,
# posortowana dla stabilnego, powtarzalnego wyniku.
ASSET_WORDS_PATTERN = "|".join(sorted({re.escape(w) for w in SYMBOL_ALIASES}))


# Ticker -> potoczna, krótka nazwa do pokazania człowiekowi (np. w
# podpowiedziach "Co dalej?"). Gdy nie znamy, pokazujemy sam ticker wielkimi
# literami. Celowo wąskie: lepiej pokazać "BTCUSD" niż zgadnąć źle.
_DISPLAY_NAMES = {
    "btcusd": "BTC", "ethusd": "ETH", "xauusd": "złota", "xagusd": "srebra",
}


def display_name(symbol: str) -> str:
    """Krótka, czytelna nazwa instrumentu do pokazania w interfejsie
    (nie do zapytania o notowanie). Dla znanych aliasów oddaje potoczną nazwę
    (btcusd -> BTC), dla reszty sam ticker wielkimi literami."""
    s = (symbol or "").strip().lower()
    if s in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[s]
    return (symbol or "").strip().upper()


def detect_all(text: str) -> list[str]:
    """Wszystkie instrumenty wykryte w tekście, bez duplikatów, w kolejności
    pojawiania się - do pytań o kilka naraz ("przeanalizuj BTC i SOL"). Te same
    reguły co detect(): wprost zapisane tickery + aliasy (wieloznaczne tylko przy
    finansowym sygnale)."""
    lowered = (text or "").lower()
    found: list[str] = []
    for m in EXPLICIT_SYMBOL_RE.finditer(lowered):
        if m.group(0) not in found:
            found.append(m.group(0))
    has_fin = bool(FINANCE_QUALIFIER_RE.search(lowered))
    for word, symbol in SYMBOL_ALIASES.items():
        if symbol in found:
            continue
        if not re.search(rf"\b{re.escape(word)}\b", lowered):
            continue
        if word in AMBIGUOUS_ALIASES and not has_fin:
            continue
        found.append(symbol)
    return found


def detect(text: str) -> str | None:
    """Najlepsza próba wychwycenia tickera z dowolnego tekstu (zlecenie
    zadania stałego, wiadomość czatu, już znormalizowane do małych liter albo
    nie - funkcja sama robi .lower()). Brak trafienia = None: nic nie jest
    zgadywane na siłę, dokładnie tak samo ściśle jak w tools.market_quote."""
    lowered = (text or "").lower()
    m = EXPLICIT_SYMBOL_RE.search(lowered)
    if m:
        return m.group(0)
    for word, symbol in SYMBOL_ALIASES.items():
        if not re.search(rf"\b{re.escape(word)}\b", lowered):
            continue
        if word in AMBIGUOUS_ALIASES and not FINANCE_QUALIFIER_RE.search(lowered):
            continue
        return symbol
    return None
