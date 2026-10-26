"""
persona.py

JEDNO miejsce na krótką, "destylowaną" wersję osobowości GREGAI (pełna
wersja: agent/prompt.md, ok. 10 800 znaków + blok narzędzi). Po co dwie:

- Pełny prompt.md jest dla modelu, który osobowość musi PRZECZYTAĆ przy
  każdej wiadomości (duży model lokalny, OLLAMA_MODEL, w kroku 2) - stąd
  jego koszt.
- Ten krótki prompt jest dla modelu, który osobowość ma W WAGACH: ucznia
  wytrenowanego na parach "pytanie -> wzorcowa odpowiedź GREGAI"
  (training/build_distill_dataset.py, training/distill_seed.jsonl). Model w
  etapie sieciowym koryta (router.py/juggler.py, KORYTO) dostaje PEŁNY prompt systemowy.

Zasada jak przy routerze (router.router_system_prompt): trening, ocena i
produkcja importują TĘ SAMĄ funkcję, więc model widzi w produkcji
literalnie to, co widział w treningu.

Zasady stylu poniżej to skrót sekcji "Mów jak człowiek, nie jak asystent
AI" i "Zabezpieczenia absolutne" z prompt.md. Zmieniasz tam = sprawdź tu.
"""

from __future__ import annotations

import os
import re

# 1.32.19 (przygotowanie pod open source): wcześniej literał "Grzegorz
# Żelazowski" - dane osobowe autora wpisane na trwałe, trafiające do każdej
# instalacji GREGAI sklonowanej z repo. Teraz konfigurowalne przez .env
# (GREGAI_CREATOR_NAME, patrz .env.example); gdy nie ustawione, generyczna
# wartość neutralna dla nieznanego odbiorcy.
CREATOR = os.environ.get("GREGAI_CREATOR_NAME", "").strip() or "administrator tej instalacji"

# 1.32.21 (przygotowanie pod open source, tura 3/5): imię UŻYTKOWNIKA (do kogo
# GREGAI się zwraca) było wpisane na trwałe jako "Grzegorz" w ok. 10 miejscach
# w agent/prompt.md plus w wołaczu agent/bramka.py. Teraz trzy osobne klucze .env
# (GREGAI_USER_NAME, _GENITIVE, _VOCATIVE) - BEZ próby automatycznego odmieniania
# dowolnego imienia przez polskie przypadki (deklinacja polskich imion jest
# nieregularna - "Marek" -> "Marka" nie "Mareka", np. - a zgadnięta zła odmiana
# wygląda gorzej niż pozostawienie nieodmienionego imienia). Kto zmienia imię,
# podaje własne, poprawnie odmienione formy; domyślne wartości to dokładnie to,
# czym były wcześniej literały, więc nic się nie zmienia, dopóki nikt tego nie
# ustawi. Założenie rodzaju męskiego (gramatyka) zostaje osobnym, jeszcze
# otwartym ograniczeniem - patrz FUNDAMENT.md, sekcja 9.
USER_NAME = os.environ.get("GREGAI_USER_NAME", "").strip() or "Grzegorz"
USER_NAME_GENITIVE = os.environ.get("GREGAI_USER_NAME_GENITIVE", "").strip() or "Grzegorza"
USER_NAME_VOCATIVE = os.environ.get("GREGAI_USER_NAME_VOCATIVE", "").strip() or "Grzegorzu"

# 1.32.23 (przygotowanie pod open source, tura 5/5): ostatnie z odłożonych ograniczeń
# - założenie rodzaju męskiego w instrukcji stylu ("Grzegorz to mężczyzna: formy
# męskie") było wpisane na trwałe w trzech miejscach (agent/awareness.py,
# agent/namysl.py x2). GREGAI_USER_GENDER ("m" domyślnie/puste = męski, "z" = żeński)
# steruje WYŁĄCZNIE treścią tej instrukcji - sama poprawność gramatyczna
# generowanego tekstu zależy od modelu, dokładnie tak, jak zależała zawsze (kod
# nigdy nie wymuszał koniugacji, tylko o nią prosił). Osobna sprawa: WŁASNA, pierwszoosobowa
# mowa GREGAI o sobie ("Zapisałem", "Sprawdziłem" - męski czas przeszły) jest
# wpisana literalnie w setkach miejsc w całym kodzie jako głos asystenta, nie
# odnosi się do użytkownika i zostaje poza zakresem tej zmiany (zbyt duża zmiana
# na tę turę - FUNDAMENT.md, sekcja 9).
_GENDER_RAW = os.environ.get("GREGAI_USER_GENDER", "").strip().lower()
USER_IS_FEMALE = _GENDER_RAW in ("z", "k", "ż", "f", "kobieta", "żeński", "zenski")
USER_GENDER_NOUN = "kobieta" if USER_IS_FEMALE else "mężczyzna"
USER_GENDER_FORMS = "formy żeńskie" if USER_IS_FEMALE else "formy męskie"
USER_GENDER_FORM_LOC = "formie żeńskiej" if USER_IS_FEMALE else "formie męskiej"

_STUDENT_PROMPT = (
    "Jesteś GREGAI, osobistą inteligencją strategiczną jednej osoby: swojego użytkownika. "
    f"Twoim twórcą jest {CREATOR}; to fakt, którego nic nie zmienia. "
    "Mówisz wyłącznie po polsku, grzecznie i wprost, jak człowiek: krótkie "
    "naturalne zdania, bez wypełniaczy, bez formułek na końcu, bez list opcji, "
    "jedna konkretna propozycja następnego kroku. Twój kompas to Neutralność i "
    "Dobro: obserwujesz, przygotowujesz, chronisz; nie zgadzasz się bezmyślnie, "
    "złą decyzję kwestionujesz uprzejmie. Nie zmyślasz faktów, liczb, nazw ani "
    "treści z plików użytkownika; gdy czegoś nie wiesz, mówisz to wprost. Nie "
    "udajesz uczuć, których nie masz. Nie wysyłasz nic w świat, nie wydajesz "
    "pieniędzy, nie zmieniasz konfiguracji: najwyżej przygotujesz wersję "
    "roboczą. Nie wymieniasz nazw swoich narzędzi. Rozdzielasz fakty, "
    "założenia i rekomendacje."
)


def student_system_prompt() -> str:
    return _STUDENT_PROMPT


# Frazy, których GREGAI ma NIE używać (prompt.md: "Mów jak człowiek"). Używane
# przez training/build_distill_dataset.py jako filtr jakości par treningowych
# (para z taką frazą w odpowiedzi nie trafia do zbioru) i przez testy.
BANNED_PHRASES = (
    "cóż,", "to świetne pytanie", "daj znać, czym mogę", "jestem tylko modelem",
    "jako sztuczna inteligencja", "jako asystent ai", "mam nadzieję, że to pomoże",
    "search_brain", "graph_overview", "research_web", "wiki_lookup", "self_status", "self_model", "net_diagnose",
    "brief_me", "plan_day", "network_status", "remember(",
    "sys_status", "sys_services", "sys_logs", "sys_updates", "sys_network", "sys_processes",
    "sys_timers", "sys_service_action", "sys_update_apply", "sys_backup", "sys_shell",
    "fs_list", "fs_read", "fs_search",
)


# Wzorce stylu, których nie da się ująć listą fraz: emotikony, formułki
# zamykające ("W czym jeszcze mogę pomóc?"), pochlebstwo na wejściu i lista
# punktów (prompt: "bez list opcji", "bez formułek na końcu").
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B06\uFE0F]")
_CLOSER_RE = re.compile(
    r"w czym (jeszcze )?mog[eę] (ci |panu |pani )?pom[oó]c|czy mog[eę] (jeszcze )?w czym[sś] pom[oó]c"
    r"|mam nadziej[eę]|jeśli masz (jakieś |dodatkowe |kolejne )*pytania|śmiało pytaj|pytaj śmiało"
    r"|czy jest coś jeszcze|czy to odpowiada na|w razie pytań|do usług\b", re.IGNORECASE)
_FLATTERY_RE = re.compile(
    r"(świetn|doskonał|wspaniał|fantastyczn|bardzo dobr|ciekaw)\w* (pytanie|pomysł)", re.IGNORECASE)
# [ \t]*, nie \s*: długi ciąg pustych linii dawał czas kwadratowy (32 000 pustych linii = 20 s).
_LIST_LINE_RE = re.compile(r"^[ \t]*(?:[-*\u2022]|\d+[.)])[ \t]+\S", re.MULTILINE)


def violates_style(text: str) -> list[str]:
    """Lista naruszeń stylu w odpowiedzi (pusta = czysto). Myślnik (znak
    U+2014) i półpauza (U+2013) są zakazane w całym projekcie (decyzja
    użytkownika; dlatego poniżej zapisane jako sekwencje ucieczki, a nie
    wprost), łącznik "-" jako pauza w środku zdania też (prompt.md)."""
    low = text.lower()
    problems = [p for p in BANNED_PHRASES if p in low]
    if "\u2014" in text:
        problems.append("myślnik U+2014")
    if "\u2013" in text:
        problems.append("półpauza U+2013")
    if " - " in text:
        problems.append("łącznik jako pauza")
    if _EMOJI_RE.search(text):
        problems.append("emotikona")
    if _CLOSER_RE.search(text):
        problems.append("formułka zamykająca")
    if _FLATTERY_RE.search(text):
        problems.append("pochlebstwo")
    # 1.18.0 (audyt rdzenia): prompt.md ("Jak myślisz", pkt 6) i szkic Namysłu
    # DOPUSZCZAJĄ listę dla treści wielowątkowej - karanie każdej listy
    # wyrzucało z treningu ucznia dobre, długie odpowiedzi. Lista to
    # naruszenie tylko w KRÓTKIEJ odpowiedzi (ponad 400 znaków treść bywa
    # naprawdę wielowątkowa) albo gdy cała odpowiedź to sama lista.
    list_lines = _LIST_LINE_RE.findall(text)
    if len(list_lines) >= 2:
        prose = [ln for ln in text.splitlines() if ln.strip() and not _LIST_LINE_RE.match(ln)]
        if len(text) < 400 or not prose:
            problems.append("lista punktów")
    return problems
