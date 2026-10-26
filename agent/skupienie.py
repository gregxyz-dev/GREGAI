"""
skupienie.py - warstwa UWAGI GREGAI.

Pomysł Grzegorza (2026-10-22): u człowieka jest odbiór oczami -> interpretacja
-> SKUPIENIE -> analiza. GREGAI dotąd podejmował decyzję "ile się napracować"
ukryto i rozsypanie (raz szybka ścieżka, raz task_kind, raz Namysł). Ten moduł
wyciąga ten jeden etap na wierzch: zanim cokolwiek policzymy, nadajemy
wiadomości WAGĘ 1-4, i dopiero ta waga mówi, ile maszynerii uruchomić.

Poziomy:
  1 szum      - odruch; krótkie potwierdzenie / small talk, nic nie trzeba liczyć.
  2 rutyna    - zwykłe pytanie albo jedno polecenie (jedno narzędzie / prosta odpowiedź).
  3 ważne     - analiza / decyzja / research / wyjaśnienie -> pełny Namysł.
  4 krytyczne - pieniądze, zdrowie albo nieodwracalna akcja -> Namysł + wzmożone
                sprawdzenie (każda liczba i twierdzenie wobec materiału) i ostrożność.

Reguły są DETERMINISTYCZNE (żadnego modelu): to samo zdanie zawsze dostaje tę
samą wagę, a `ocena` zwraca też POWODY - krótkie, jawne etykiety, żeby dało się
pokazać użytkownikowi i przetestować, dlaczego akurat tyle. To jest ta sama
zasada, o którą prosił Grzegorz przy planerze: "zaprogramuj regułami, nie ufaj
modelowi", rozciągnięta na uwagę.

To wersja 1: ocena W PRZÓD (forward). Pełne bramkowanie wysiłku na każdym
poziomie i "re-skupienie" (analiza podnosi wagę i wracamy) dokładamy w kolejnym
kroku - tu waga jest już liczona, widoczna i wpływa na rygor sprawdzania przy 4.
"""

from __future__ import annotations

import re

# --- 4: KRYTYCZNE (sprawdzane najpierw - wygrywa z resztą) -------------------
# Nieodwracalne operacje: usunięcie/nadpisanie/reset. Lepiej raz za dużo uwagi.
_KRYT_NIEODWRACALNE = re.compile(
    r"\b(usu[nń]\w*|skasuj\w*|wykasuj\w*|kasuj\w*|nadpis\w*|sformatuj\w*|formatuj\w*|"
    r"wyczy[sś][cć]\w*|zresetuj\w*|resetuj\w*|przywr[óo][cć]\s+fabryczn\w*)\b",
    re.IGNORECASE,
)
# Pieniądze realnie przesuwane / inwestycja - tylko formy ROZKAZUJĄCE/decyzyjne
# ("przelej", "kup", "sprzedaj", "zainwestuj"), nie codzienne wzmianki. 1.30.29
# (audyt tura 3): dawne kup\w*/inwestuj\w* łapały "kupę roboty", "kupon", "kupiłem
# mleko", "inwestuję w rozwój" i fałszywie podnosiły je do wagi 4 (kosztowna
# eskalacja + ostrzeżenie). Teraz kup/kupuj/kupię i sprzedaj/sprzedam, z granicą
# słowa, więc "kupiłem"/"kupa"/"kupon" już nie trafiają.
_KRYT_PIENIADZE = re.compile(
    # Audyt 1.32.1: zapłać/wypłać/wpłać tylko w trybie rozkazującym albo bezokoliczniku -
    # "Ile zapłaciłem za prąd?" to pytanie o przeszłość, nie przesuwanie pieniędzy.
    r"\b(?:przelej\w*|przele[wj]\w*|(?:za|wy|w)p[łl]a(?:[cć]|[cć]my|[cć]cie|ci[cć])|"
    # 1.32.2 (audyt tura 7): "kupującemu", "jutro kupię", "za ile sprzedam" to nie polecenia.
    r"zainwestuj\w*|kup|kupuj(?:cie|my)?|sprzedaj|sprzedajcie|sprzedajmy|"
    r"all[\s-]?in|ca[łl][eay]\s+oszcz[eę]dno\w*|"
    r"wszystkie\s+(?:pieni[aą]dz\w*|oszcz[eę]dno\w*))\b",
    re.IGNORECASE,
)
# Zdrowie: dawki, leki, objawy. Tu błąd potrafi zaszkodzić.
_KRYT_ZDROWIE = re.compile(
    r"\b(dawk\w*|dawkowani\w*|lek[iuaów]?\b|leki\w*|leku\b|tabletk\w*|objaw\w*|"
    r"zatruci\w*|przedawk\w*|alergi\w*|duszno\w*|krwawi\w*|zawa[łl]\w*)\b",
    re.IGNORECASE,
)

# --- 1: SZUM (tylko gdy CAŁA wiadomość to potwierdzenie / grzeczność) --------
# Jeden "żeton" grzecznościowy; wiadomość to szum, gdy składa się WYŁĄCZNIE z
# takich żetonów (np. "to wszystko, dziękuję" = "to wszystko" + "dziękuję").
_SZUM_TOKEN = (
    r"(?:dzi[eę]k\w*|dzi[eę]kuj\w*|thx|thanks|ok|oki|okej|okey|spoko|git|"
    r"jasne|no\s+ba|pa|nara|cze[sś][cć]|hej|hejka|siema|elo|yo|no|aha|mhm|"
    r"super|wporz[aą]dku|w\s+porz[aą]dku|to\s+wszystko|to\s+tyle|dobra)"
)
_SZUM = re.compile(
    rf"^\s*{_SZUM_TOKEN}(?:[\s.!,…]+{_SZUM_TOKEN})*[\s.!,…]*$",
    re.IGNORECASE,
)

# --- 3: WAŻNE (analiza / decyzja / research / wyjaśnienie) -------------------
_WAZNE = re.compile(
    r"\b(przeanaliz\w*|analiz\w*|por[óo]wn\w*|zdecyd\w*|decyzj\w*|rozwa[żz]\w*|"
    r"oce[nń]\w*|zbadaj\w*|zbada[cć]\w*|research\w*|dlaczego|czemu\b|"
    r"wyja[sś]nij\w*|wyt[łl]umacz\w*|jak\s+najlepiej|czy\s+warto|op[łl]aca\w*|"
    r"strategi\w*|plan\s+na\s+|zaplanuj\w*|co\s+lepsze|co\s+wybra[cć])\b",
    re.IGNORECASE,
)

# 1.32.2 (audyt tura 7): edycja tekstu ("usuń myślniki z tego tekstu", "sformatuj opis w
# punkty") to nie nieodwracalna operacja - chyba że w zdaniu jest też prawdziwy obiekt.
_TEKST_RE = re.compile(r"\b(?:tekst\w*|opis\w*|zdani\w*|akapit\w*|my[sś]lnik\w*|ogłoszeni\w*|ogloszeni\w*)\b", re.IGNORECASE)
_OBIEKT_RE = re.compile(r"\b(?:plik\w*|folder\w*|katalog\w*|dysk\w*|partycj\w*|pendrive\w*|kont[oa]\b|notat\w*|zadani\w*|baz[aęy]\w*|router\w*|telefon\w*|iphon\w*|system\w*|list\w*|kontakt\w*|klient\w*|mail\w*|kana[łl]\w*|film\w*|repozytor\w*|wszystk\w*|zdj[eę]\w*|wiadomo\w*)\b", re.IGNORECASE)
# Objawy baterii albo dawka nawozu to nie zdrowie człowieka - chyba że mowa o człowieku.
_NIE_ZDROWIE_RE = re.compile(r"\b(?:bateri\w*|ekran\w*|iphon\w*|telefon\w*|laptop\w*|p[łl]yt\w*|naw[oó]z\w*|nawoz\w*|saletr\w*|oprysk\w*|pomidor\w*|ro[śs]lin\w*|gleb\w*|modem\w*)\b", re.IGNORECASE)
_ZDROWIE_TWARDE_RE = re.compile(r"\b(?:alergi\w*|zatru\w*|duszn\w*|krwaw\w*|zawa[łl]\w*|lek[iuaów]?\b|leki\w*|leku\b|tabletk\w*|przedawk\w*)", re.IGNORECASE)
_LUDZKIE_RE = re.compile(r"\b(?:mnie|mi|mam|miałem|dziec\w*|b[oó]l\w*|g[łl]ow\w*|brzuch\w*|zjad\w*|wypi\w*)\b", re.IGNORECASE)
# /plan, /badaj, /recenzja i "przemyśl:" to jawna prośba o staranność: co najmniej waga 3.
_STARANNIE_RE = re.compile(r"^\s*(?:/(?:plan|badaj|zbadaj|recenzja|research|review)\b|(?:przemy[sś]l(?:\s+to)?|zastan[oó]w\s+si[eę]|namys[łl]|dok[łl]adnie|g[łl][eę]boko)\s*[:,\-])", re.IGNORECASE)
_DLUGIE_ZNAKI = 300   # długa, złożona wiadomość to zwykle nie "rutyna"

POZIOM_NAZWY = {1: "szum", 2: "rutyna", 3: "ważne", 4: "krytyczne"}

# Powody poziomu 4, które są AKCJĄ (coś się nieodwracalnie wydarzy), a nie samym
# pytaniem. Tu należy się "przystanek": potwierdź i sprawdź sam, zanim zrobisz.
# "Zdrowie" tu NIE wchodzi - to zwykle pytanie, dostaje rygor sprawdzania, nie
# bramkę potwierdzenia (pomysł z architektury Claude Code: jeden checkpoint
# uprawnień dla rzeczy nieodwracalnych, tu sterowany wagą uwagi).
POWODY_AKCJA = frozenset({"nieodwracalna operacja", "realny ruch pieniędzy / inwestycja"})


_PYTANIE_RE = re.compile(
    r"^\W*(?:ile|jak|jaki\w*|czy|co|kiedy|gdzie|dlaczego|czemu|po\s+co|kt[oó]r\w*|w\s+jaki\s+spos[oó]b)\b")
_GRZECZNA_PROSBA_RE = re.compile(
    r"^\W*(?:czy\s+)?(?:mo[zż]esz|m[oó]g[lł]by[sś]|mog[lł]aby[sś]|prosz[eę]|dasz\s+rad[eę]|zr[oó]b)\b")
_ROZKAZ_RE = re.compile(
    r"\b(?:usu[nń]|skasuj|wykasuj|sformatuj|wyczy[sś][cć]|zresetuj|nadpisz|przelej|"
    r"(?:za|wy|w)p[łl]a[cć]|zainwestuj|kup|sprzedaj)\b")
_NOTATKA_RE = re.compile(r"^\W*(?:zapami[eę]taj|zanotuj|zapisz\s+(?:sobie|w\s+notatk)|przypomnij(?:\s+mi)?|notatka)\b")


def czy_akcja_nieodwracalna(powody: list[str]) -> bool:
    """Czy powody wagi 4 to nieodwracalna AKCJA (wymaga przystanku na
    potwierdzenie), a nie samo pytanie (np. o zdrowie)."""
    return any(p in POWODY_AKCJA for p in (powody or []))


def ocena(message: str, history: list | None = None) -> tuple[int, list[str]]:
    """Waga uwagi 1-4 dla wiadomości + powody (jawne etykiety). Deterministyczne.
    `history` przyjmowane dla zgodności z kolejnymi wersjami (re-skupienie z
    kontekstu); wersja 1 liczy wagę z samej wiadomości."""
    msg = (message or "").strip()
    low = msg.lower()
    if not msg:
        return 2, ["pusta wiadomość"]

    # 4 - krytyczne: sprawdzane najpierw, bo przebija wszystko inne.
    # Audyt 1.32.1: pytanie ("Jak usunąć konto?") albo notatka ("zapamiętaj: kup mleko")
    # nie jest akcją do wykonania - bez ostrzeżenia "nie da się cofnąć" i bez wagi 4.
    # Przegląd poprawek 1.32.1: sam "?" na końcu ("usuń folder, dobrze?") i grzeczna prośba
    # ("czy możesz usunąć...") to nadal polecenie; tryb rozkazujący gdziekolwiek też.
    pytanie = (bool(_PYTANIE_RE.match(low)) and not _GRZECZNA_PROSBA_RE.match(low)
               and not _ROZKAZ_RE.search(low))
    notatka = bool(_NOTATKA_RE.match(low))
    powody4 = []
    tekst_tylko = bool(_TEKST_RE.search(low)) and not _OBIEKT_RE.search(low)
    if _KRYT_NIEODWRACALNE.search(low) and not (pytanie or notatka or tekst_tylko):
        powody4.append("nieodwracalna operacja")
    if _KRYT_PIENIADZE.search(low) and not (pytanie or notatka):
        powody4.append("realny ruch pieniędzy / inwestycja")
    # Wyjątek "to bateria/roślina, nie człowiek" tylko dla samych objawów albo dawki - alergia,
    # zatrucie, duszność, krwawienie, zawał i leki zostają zdrowiem (przegląd poprawek 1.32.2).
    _tylko_urzadzenie = (_NIE_ZDROWIE_RE.search(low) and not _LUDZKIE_RE.search(low)
                         and not _ZDROWIE_TWARDE_RE.search(low))
    if _KRYT_ZDROWIE.search(low) and not _tylko_urzadzenie:
        powody4.append("zdrowie")
    if powody4:
        return 4, powody4
    if pytanie and (_KRYT_NIEODWRACALNE.search(low) or _KRYT_PIENIADZE.search(low)):
        # Pytanie o pieniądze albo nieodwracalną operację: rzetelna odpowiedź (waga 3),
        # ale bez przystanku "nie da się cofnąć" - nic tu nie jest wykonywane.
        return 3, ["pytanie o pieniądze / nieodwracalną operację"]

    if _STARANNIE_RE.match(low):
        return 3, ["prośba o staranne przemyślenie"]

    # 1 - szum: tylko gdy CAŁA wiadomość to potwierdzenie/grzeczność i nie pyta.
    if len(msg) <= 30 and "?" not in msg and _SZUM.match(low):
        return 1, ["krótkie potwierdzenie / small talk"]

    # 3 - ważne: analiza/decyzja/research/wyjaśnienie, albo długa, złożona treść.
    if _WAZNE.search(low):
        return 3, ["analiza / decyzja / research"]
    if len(msg) >= _DLUGIE_ZNAKI:
        return 3, ["długa, złożona wiadomość"]

    # 2 - rutyna: domyślnie.
    return 2, ["rutynowe pytanie / polecenie"]
