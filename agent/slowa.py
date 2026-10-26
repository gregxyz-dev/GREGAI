"""
slowa.py

Jedno źródło polskich słów-"kleju" i składania znaków diakrytycznych
(1.18.0). Do 1.17.x były DWIE osobne listy słów pomijanych: w learning.py
(wzorce wyuczone) i w vault.py (wyszukiwanie w notatkach) - rozjeżdżały się
(np. "kim", "sądzisz" były tylko w jednej albo w żadnej), więc ta sama
wiadomość inaczej "ważyła" słowa w dwóch miejscach. Wspólny rdzeń jest tu;
każdy moduł dokłada TYLKO swoje, specyficzne słowa (np. wyszukiwanie pomija
"notatki", bo w nim nic nie wyróżnia, a uczenie wzorców NIE, bo dla niego to
właśnie słowo-wyzwalacz).

fold(): małe litery, bez polskich znaków ("Żelazowski" -> "zelazowski",
"ogród" -> "ogrod"). Ł nie rozkłada się w NFKD na L + znak, stąd osobna
podmiana. Używane po obu stronach porównania (zapytanie i notatka), więc
pytanie pisane bez ogonków znajduje notatkę pisaną z ogonkami i odwrotnie.
"""

from __future__ import annotations

import unicodedata

_PL_EXTRA = str.maketrans({"ł": "l", "Ł": "L"})


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_PL_EXTRA))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


# Zaimki, spójniki, partykuły, czasowniki posiłkowe i pytające - po polsku
# prawie nigdy nie niosą tematu. Formy z ogonkami i bez (ludzie piszą różnie).
WSPOLNE = frozenset("""
    jak jest czy kto kim gdzie kiedy dlaczego czemu ile ilu tak nie się sie siebie sobie
    jakie jaki jaka jaką jaka jakiej jakim jakich jakimi
    które który która którą której którego których którym którymi
    ktore ktory ktora ktora ktorej ktorego ktorych ktorym ktorymi
    mój moje moja moją mojej mojego moi moich moim moimi
    moj moja mojej
    twoje twoja twój twoją twojej twojego twoich twoim twoj
    nasze nasza nasz naszych naszym jego jej ich nim niej nimi
    tego temu tym tych tymi tej ten tamto tamten
    są był była było były będzie będą będziesz sa byl byla bylo byly bedzie beda
    masz macie mają maja mam
    chcę chce chcesz chcemy chcecie chcą
    może możesz możemy mogą moze mozesz mozemy moga można mozna trzeba
    musisz musi musimy muszą musza
    żeby żebyś żebym zeby zebys zebym aby gdy jeśli jesli
    oraz albo lub ale ponieważ poniewaz dlatego jednak też tez także takze już juz jeszcze tylko
    bardzo trochę troche zawsze nigdy wszystko
    coś cos czegoś czegos czymś czyms
    potem wtedy wcześniej wczesniej później pozniej
    proszę prosze poproszę poprosze
    mnie mną mna tobie nam nas wam
    dla przez przy nad pod bez
    """.split())


# --- Rdzenie wyrazów (1.19.0) ------------------------------------------------
# Do 1.18.0 wyszukiwanie brało PIERWSZE 4-5 liter słowa: "kawie" nie trafiało w
# "Kawa" (za krótkie, porównywane w całości), "psach" nie w "Psy", a "prompt"
# trafiało w "Promocje" (wspólny początek "prom"). Teraz odcinamy typowe polskie
# końcówki odmiany (na tekście już po fold(), więc bez ogonków) i porównujemy
# CAŁE rdzenie słowo do słowa, a nie początki.
#
# Najdłuższe końcówki najpierw: "zelazowskiego" traci "ego", nie samo "o".
_KONCOWKI = tuple(sorted("""
    iego iemu owie owi ami ach ego emu iej ich imi ych ymi iem iom iow
    om ow em ie ia iu io ej ym im ii
    a e i o u y
""".split(), key=len, reverse=True))

# Oboczności na końcu rdzenia: ta sama końcówka przypadka zmienia ostatnią
# spółgłoskę ("ręka" -> "ręce", "noga" -> "nodze", "mucha" -> "musze",
# "kot" -> "kocie", "Wrocław" -> "Wrocławiu" bez zmiany). Rdzeń z lewej strony
# może odpowiadać każdemu z rdzeni po prawej - stem_variants() zwraca wszystkie.
_OBOCZNOSCI = {
    "c": ("k", "t"),
    "dz": ("g", "d"),
    "sz": ("ch", "s"),
    "rz": ("r",),
    "z": ("g", "z"),
    "s": ("ch",),
}

# Najkrótszy rdzeń po odcięciu końcówki. 2 litery, bo "psy"/"psach"/"psie" mają
# rdzeń "ps"; porównujemy CAŁE rdzenie, więc krótki rdzeń nie łapie przypadkowych
# słów (inaczej niż dawne porównanie po początku słowa).
MIN_RDZEN = 2


def stem(word: str) -> str:
    """Rdzeń słowa JUŻ złożonego przez fold() ("kawie" -> "kaw", "zelazowskiemu"
    -> "zelazowsk"). Słowa krótsze niż 3 litery i liczby zostają bez zmian."""
    if len(word) < 3 or not word.isalpha():
        return word
    for end in _KONCOWKI:
        if word.endswith(end) and len(word) - len(end) >= MIN_RDZEN:
            word = word[:-len(end)]
            break
    # Ruchome "e" przed ostatnią spółgłoską: "notatek" / "notatka", "Marek" /
    # "Marka" - po odcięciu końcówki oba mają mieć ten sam rdzeń.
    if len(word) > 4 and word.endswith("ek") and word[-3] not in "aeiouy":
        word = word[:-2] + "k"
    return word


def stem_variants(word: str) -> frozenset:
    """Rdzeń słowa i jego warianty z oboczności ("rec" -> {"rec", "rek", "ret"}).
    Dla strony ZAPYTANIA: notatka ma zapisany jeden rdzeń na słowo, a zapytanie
    w innym przypadku może mieć na końcu oboczną spółgłoskę."""
    base = stem(word)
    out = {base}
    # Oboczność "w przód" (rec -> rek) tylko gdy stem odciął końcówkę przypadka:
    # "łódź" -> "lodz" bez końcówki to mianownik, a nie "nodze" (-> "log" trafiało "log").
    inflected = base != word
    for tail, swaps in _OBOCZNOSCI.items():
        if inflected and base.endswith(tail) and len(base) > len(tail):
            for swap in swaps:
                out.add(base[:-len(tail)] + swap)
    # Odwrotnie też: zapytanie w mianowniku ("ręka" -> "rek"), notatka w miejscowniku ("ręce" -> "rec").
    for tail, swaps in _OBOCZNOSCI.items():
        for swap in swaps:
            if base.endswith(swap) and len(base) > len(swap):
                out.add(base[:-len(swap)] + tail)
    return frozenset(out)


# Dwuliterowe słowa, które NIE są tematem (przyimki, zaimki, partykuły). Inne
# dwuliterowe ("AI", "UI", "PC", "OS") są skrótami - zostają jako słowa kluczowe.
KROTKIE_POMIJANE = frozenset("""
    co to ja ty on my wy mi ci mu go je ze na za do od po we ma ni no tu az im bo by
    al ok oh ah aa ee ta te tz np itd ze ku of in is it the an or and
""".split())
