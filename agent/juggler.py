"""
juggler.py

Żongler: WSZYSCY zewnętrzni dostawcy AI w jednym łańcuchu - od 1.17.0 także
Claude (Anthropic). Do 1.16.x Claude był osobną, zahardkodowaną "chmurą" w
router.py (CLOUD_FALLBACK/_cloud_chat), próbowaną dopiero PO darmowej puli;
decyzją Grzegorza (2026-10-21: "głównym dostawcą ma być Anthropic, reszta
darmowe API jako fallback, ostatecznym fallbackiem lokalna maszyna") jest
teraz zwykłym wkładem w tym module, a o KOLEJNOŚCI etapów (anthropic ->
darmowe -> lokalnie, konfigurowalnej w .env: KORYTO=...) decyduje
agent/koryto.py - ten moduł wykonuje etapy SIECIOWE w tej kolejności, etap
lokalny wykonuje router.py.

Metafora Grzegorza (2026-10-19): GREGAI + żongler to długopis - rdzeń,
który się nie zmienia. Dostawcy to WKŁADY: wymienne, podpinane pod jeden
złącz (ten moduł), bez zmian w samym GREGAI. Dodanie/wymiana dostawcy =
nowa funkcja `_X_chat` + wpis w _FREE/_KEY_ENV/_MODEL/_DAILY_LIMIT
niżej, reszta systemu (router.py, main.py, /debug) nic o tym nie wie.

Dlaczego pula, nie jeden dostawca (powód Grzegorza): żeby żadna POJEDYNCZA
sztuczna inteligencja nie "false-flagowała" wzorca zapytań GREGAI - requesty
rozkładają się między kilkoma niezależnymi serwerami, więc jeden dostawca
widzi tylko część ruchu i nigdy całej historii.

Dwa tryby pracy, obie decyzje podejmuje router.py (ten moduł tylko wykonuje):

1. ŁAŃCUCH (pytania rutynowe): router.route() woła chat() - idzie etapami
   koryta (koryto.network_order()): etap "anthropic" to jeden dostawca
   (Claude, stała pozycja - domyślnie pierwszy), etap "darmowe" to darmowa
   pula w LOSOWEJ kolejności (losowanej od nowa przy KAŻDYM wywołaniu chat(),
   patrz random.shuffle tam). Pierwszy sukces wygrywa. _FREE niżej to tylko
   pula/kolejność wyświetlania darmowych (status, providers_pool, research) -
   NIE kolejność prób w ich etapie, inaczej dostawca pierwszy na liście (Groq,
   najwyższy dzienny limit) wygrywałby niemal zawsze i reszta puli nigdy by
   nie była realnie używana, co wprost zaprzecza powodowi istnienia puli
   (patrz akapit wyżej - żaden pojedynczy DARMOWY dostawca nie powinien
   widzieć większości ruchu; Claude jako świadomie wybrany główny dostawca
   jest z tej zasady wyłączony). Błąd/wyczerpany dzienny limit = cicho
   następny w kolejności, a po ostatnim sieciowym - router.py idzie etapem
   lokalnym (uczeń -> model lokalny).

2. SENIOR + DWÓCH JUNIORÓW (pytania RYZYKOWNE, patrz is_risky niżej):
   router.route() woła research() - DWÓCH różnych dostawców dostaje
   zapytanie RÓWNOLEGLE, ale bez historii rozmowy i bez osobowości/kontekstu
   GREGAI (_RESEARCH_SYSTEM_PROMPT - neutralny, bezosobowy prompt badawczy).
   Żaden z nich nie widzi, że pytanie dotyczy akurat Grzegorza, ani całej
   rozmowy - dostaje tylko samo pytanie. Dopiero LOKALNY model (ten sam,
   który i tak odpowiada w rozmowie - etap lokalny w router.py), z PEŁNYM
   promptem osobowości, składa z ich surowego researchu finalną odpowiedź
   w głosie GREGAI. Żaden zewnętrzny dostawca nie widzi ani persony, ani
   treści, która trafi do użytkownika - stąd "senior" (lokalny, kompiluje)
   i "juniorzy" (zewnętrzni, tylko research). Ten etap NIE jest zapisywany
   jako para destylacji (patrz router.py: _record_distill_pair) - finalna
   treść jest autorstwa lokalnego modelu, nie "nauczyciela", więc uczyłaby
   ucznia naśladować coś, co już umie, zamiast realnie podnosić poziom.

Bezpieczeństwo - te same zasady co dotychczasowa chmura, bez wyjątków:
  - netguard.urlopen(): WYŁĄCZNIE przez Cloudflare WARP, fail-closed (patrz
    agent/netguard.py). Żadnego requestu z tego modułu z pominięciem tej
    funkcji.
  - trace.mask(): sekrety (hasła, klucze, karty, PIN) wpisane w rozmowie są
    maskowane PRZED wysyłką do KAŻDEGO dostawcy, tak samo jak przy chmurze.
  - Klucze dostawców (*_API_KEY) nigdy nie trafiają do logu/śladu: nazwy
    kończące się na "_KEY" są już automatycznie maskowane przez
    agent/sysop.py (_SECRET_NAME) - bez potrzeby dodawania ich tam ręcznie.
  - Limit dzienny PER DOSTAWCA, nie jeden wspólny licznik (patrz _calls_today):
    każdy dostawca ma własny, bo każdy ma inny, darmowy limit API.

Historia widziana przez dostawców w trybie łańcuchowym jest już oczyszczona
przez router.py (ten sam kształt, co dotąd dla chmury - patrz
router._cloud_history): ten moduł dostaje gotową listę {"role","content"}.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as _FutureTimeout
from pathlib import Path

import koryto as koryto_mod
import netguard as netguard_mod
import trace as trace_mod
from env_loader import env_float, env_int

# Ten sam plik par destylacji co chmura (router.DISTILL_PAIRS_PATH) - osobna
# stała, nie import z router.py, żeby uniknąć importu kołowego (router.py
# importuje TEN moduł). Rekordy teraz noszą pole "provider" (anthropic dla
# starych wpisów chmury, nazwa dostawcy dla nowych z żonglera).
DISTILL_PAIRS_PATH = Path(__file__).parent.parent / "data" / "training" / "distill_pairs.jsonl"

# Budżet odpowiedzi i czas: te same wartości co dotychczasowa chmura
# (router.CLOUD_MAX_TOKENS), bo cel (pełna, rzeczowa odpowiedź, nie ucięta w
# połowie słowa) jest ten sam. 400 -> 900, 2026-10-19 (zgłoszenie Grzegorza:
# wyjaśnienie fizyki w kilku podpunktach urywało się w środku zdania, zanim
# model zdążył dokończyć) - dostawcy w puli są darmowe per ZAPYTANIE, nie per
# token, więc wyższy limit nie kosztuje nic więcej z dziennego budżetu.
# 900 -> 1600 (1.17.15, transkrypt Grzegorza: odpowiedź urwana w pół zdania
# "Chcesz, żebym oceniał Cię na pod"): polski tokenizuje się drogo, a odpowiedź
# z Namysłu/z notatek bywa dłuższa niż zwykła tura. Dostawcy darmowi liczą
# per zapytanie, nie per token. Do tego dokończenie po ucięciu (_continued).
JUGGLER_MAX_TOKENS = env_int("JUGGLER_MAX_TOKENS", 1600, 16, 8192)
# Budżet czasu CAŁEGO łańcucha chat() (1.17.1, patrz komentarz w chat()).
_CHAIN_BUDGET_S = float(env_int("KORYTO_BUDZET_S", 120, 10, 3600))
# Budżet CAŁEJ wiadomości (1.18.0, audyt rdzenia): jedna wiadomość to dziś
# kilka łańcuchów (krok 1 routera, fazy Namysłu, rozmowa) - każdy z własnymi
# 120 s, a dostawca martwy w pierwszym był próbowany od nowa w każdym kolejnym.
# Najgorszy przypadek przy padniętej sieci: 5-8 minut zanim padło "sieć nie
# odpowiedziała". Teraz router otwiera zakres wiadomości (request_scope): jeden
# budżet CZASU SIECI dla wszystkich łańcuchów (liczy się tylko czekanie na
# dostawców, nie praca narzędzi - apt czy kopia zapasowa nie zjadają budżetu)
# i licznik porażek: dostawca, który w TEJ wiadomości zawiódł DWA razy, jest
# pomijany do jej końca (jedna porażka to często chwilowe 529/przeciążenie,
# a przy samym kluczu Claude jedno potknięcie nie może zabić całego zadania).
# 1.30.5 (zgłoszenie Grzegorza: "4 minuty a dalej nie mam odpowiedzi"): domyślny
# budżet ścięty z 600 s (10 min!) do 210 s. To asystent do rozmowy - nikt nie
# czeka 10 minut. Gdy fast-dostawca (Claude) się zacina, każda faza Namysłu
# cyklowała wolną darmową pulę i czekanie się sumowało. 210 s wystarcza, gdy
# sieć działa, a gdy nie - Namysł oddaje szkic albo wraca do szybkiej ścieżki,
# zamiast wisieć. Kto chce dłużej, podnosi KORYTO_BUDZET_WIADOMOSC_S.
_REQUEST_BUDGET_S = float(env_int("KORYTO_BUDZET_WIADOMOSC_S", 210, 30, 7200))
_DEAD_AFTER_FAILURES = 2
_REQ = threading.local()


class request_scope:
    """`with juggler.request_scope():` wokół obsługi jednej wiadomości
    (router.route). Poza zakresem chat() działa jak dotąd (sam budżet łańcucha)."""

    def __init__(self, budget_s: float | None = None):
        self.budget = float(budget_s if budget_s is not None else _REQUEST_BUDGET_S)

    def __enter__(self):
        self._prev = getattr(_REQ, "scope", None)
        # spent: sekundy czekania na dostawców; fails: nazwa -> [liczba porażek, pierwszy powód]
        _REQ.scope = {"budget": self.budget, "spent": 0.0, "fails": {}, "lock": threading.Lock()}
        return _REQ.scope

    def __exit__(self, *exc):
        _REQ.scope = self._prev
        return False


def _scope() -> dict | None:
    return getattr(_REQ, "scope", None)


def _scope_failed(scope: dict | None, name: str, e: BaseException) -> None:
    if scope is None:
        return
    with scope["lock"]:
        entry = scope["fails"].setdefault(name, [0, (f"{type(e).__name__}: {e}" if str(e) else type(e).__name__)[:120]])
        entry[0] += 1


def _scope_dead(scope: dict | None, name: str) -> str | None:
    """Pierwotny powód, gdy dostawca zawiódł w tej wiadomości już _DEAD_AFTER_FAILURES razy."""
    if scope is None:
        return None
    entry = scope["fails"].get(name)
    return entry[1] if entry and entry[0] >= _DEAD_AFTER_FAILURES else None


def _scope_left(scope: dict | None) -> float | None:
    return None if scope is None else scope["budget"] - scope["spent"]


def _scope_spend(scope: dict | None, seconds: float) -> None:
    if scope is not None:
        with scope["lock"]:
            scope["spent"] += max(0.0, seconds)


# 1.19.0 (audyt rdzenia): ustawienia JEDNEGO wywołania dostawcy, przekazywane
# wątkiem, nie argumentem - funkcje dostawców (i ich zamienniki w testach)
# mają stały podpis (system, messages, timeout).
#   guard_ok:   chat()/research() właśnie sprawdziły WARP świeżo, więc
#               zapytania dostawcy mogą się na to powołać (netguard.recently_verified)
#   max_tokens: limit odpowiedzi dla tego wywołania (chat(max_tokens=...))
#   deadline:   chwila (monotonic), po której dostawca nie zaczyna już
#               dokończenia uciętej odpowiedzi
class _call_flags:
    def __init__(self, max_tokens: int | None = None, timeout: float | None = None, model: str | None = None):
        self.values = {"guard_ok": True, "max_tokens": max_tokens,
                       "deadline": (time.monotonic() + timeout) if timeout else None,
                       "model": model}  # 1.30.17: nadpisanie modelu Claude dla TEGO wywołania (Namysł -> Sonnet)

    def __enter__(self):
        self._prev = {k: getattr(_REQ, k, None) for k in self.values}
        for k, v in self.values.items():
            setattr(_REQ, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self._prev.items():
            setattr(_REQ, k, v)
        return False


def _guard_reuse() -> float:
    """reuse_s dla netguard.urlopen: okno ponownego użycia świeżego sprawdzenia
    tylko wewnątrz chat()/research() (które same sprawdziły WARP na starcie);
    funkcja dostawcy wołana bezpośrednio sprawdza świeżo jak dotąd."""
    return netguard_mod.FRESH_REUSE_MAX_S if getattr(_REQ, "guard_ok", None) else 0.0


# Darmowe modele z rozumowaniem (np. gpt-oss na Groq/HF/Cloudflare) zużywają
# część limitu na myślenie: przy limicie 80 tokenów treść wracała pusta. Limit
# z wywołania (chat(max_tokens=...)) nie schodzi u nich poniżej tej wartości.
_REASONING_FLOOR_TOKENS = 600


def _max_tokens(default: int, floor: int = 0) -> int:
    override = getattr(_REQ, "max_tokens", None)
    return max(16, floor, min(int(override), 8192)) if override else default


def _time_left() -> float | None:
    deadline = getattr(_REQ, "deadline", None)
    return None if deadline is None else deadline - time.monotonic()


def _guard_check() -> None:
    """Jedno świeże sprawdzenie WARP na początku łańcucha (1.19.0). Blokada =
    od razu wyjątek, bez pytania kolejnych dostawców: przy padniętym WARP
    zawiedliby wszyscy, a każdy z osobnym warp-cli i stroną Cloudflare.
    Każdy błąd samego sprawdzenia też blokuje (fail-closed)."""
    if netguard_mod.recently_verified(netguard_mod.FRESH_REUSE_MAX_S):
        return
    try:
        ok, reason = netguard_mod.internet_allowed(fresh=True)
    except Exception as e:
        ok, reason = False, f"nie da się sprawdzić WARP ({type(e).__name__})"
    if not ok:
        raise netguard_mod.NetGuardBlocked(f"internet dla sieciowych AI zablokowany: {reason}")

# --- Dostawcy: klucz w .env, model domyślny, dzienny limit darmowy --------
# Priorytet łańcucha: Groq pierwszy (najmocniejszy darmowy limit, ok. 1000
# zapytań/dzień na modelach typu gpt-oss - stan na 2026-10), potem Gemini
# (limit darmowy Google NIE jest już publikowany w jednej tabeli - 100/dzień
# to ostrożny domyślny, sprawdź własny limit na stronie Google AI Studio i
# dopisz GEMINI_DAILY_LIMIT w .env, jeśli jest wyższy), na końcu OpenRouter
# (limit POTWIERDZONY: 50/dzień, 20/min dla modelu "openrouter/free" -
# darmowy auto-router, który sam wybiera wśród aktualnie darmowych modeli,
# więc nie psuje się, gdy jeden konkretny darmowy model zniknie z oferty).
# UWAGA: od 1.8.10 kolejność prób w chat() jest losowana przy każdym
# wywołaniu (patrz chat() niżej) - _PRIORITY to już tylko pula i kolejność
# wyświetlania w /debug, nie kolejność prób.
#
# Dwaj kolejni dostawcy, dorzuceni na prośbę Grzegorza (2026-10-19):
#
# - Hugging Face (router.huggingface.co) - WYJĄTEK wśród wszystkich
#   dostawców: darmowy limit to nie liczba zapytań dziennie, tylko "0,10 USD
#   kredytu MIESIĘCZNIE" na CAŁY router (stan sprawdzony w sieci 2026-10-19,
#   może się zmienić - sprawdź huggingface.co/docs/inference-providers).
#   HUGGINGFACE_DAILY_LIMIT=20 to ostrożne, PRZYBLIŻONE przełożenie tego na
#   dzień (0,10 USD / 30 dni = ułamek centa/dzień - przy tanim, małym modelu
#   to zwykle kilkanaście-kilkadziesiąt krótkich zapytań, ale realny koszt
#   zależy od modelu i długości odpowiedzi) - jeśli HF zacznie odrzucać
#   zapytania przed wyczerpaniem tego licznika, obniż ręcznie w .env.
# - Cloudflare Workers AI - jedyny dostawca z DWOMA wymaganymi sekretami
#   (CLOUDFLARE_API_KEY I CLOUDFLARE_ACCOUNT_ID, patrz _EXTRA_ENV niżej):
#   account_id wchodzi wprost w ścieżkę URL (Cloudflare traktuje go jak
#   identyfikator konta, nie jak hasło - widoczny też w panelu Cloudflare,
#   stąd NIE jest maskowany jak *_API_KEY). Darmowy limit: 10 000
#   "neuronów"/dzień (reset o 00:00 UTC) - dla małego modelu to szacunkowo
#   ok. 1000-1300+ odpowiedzi/dzień, ale koszt w neuronach zależy od modelu,
#   więc CLOUDFLARE_DAILY_LIMIT=500 to ostrożny domyślny margines poniżej
#   tego szacunku, podnieś w .env, jeśli panel Cloudflare pokazuje spory
#   zapas.
#
# Oba modele domyślne to ta sama rodzina co Groq (openai/gpt-oss-20b) -
# otwarty model dostępny u wielu dostawców naraz (więc niski ryzyko, że
# zniknie z oferty akurat jednego z nich), mały wariant (tańszy w kredytach/
# neuronach, dłużej starcza na darmowym limicie).
_FREE = ("groq", "gemini", "openrouter", "huggingface", "cloudflare")
# Etap koryta (agent/koryto.py) dla każdego dostawcy: Claude ma własny,
# stały etap "anthropic"; cała darmowa pula to jeden etap "darmowe".
_ETAP = {"anthropic": "anthropic", **{name: "darmowe" for name in _FREE}}
# Kolejność wyświetlania (status, /debug) - Claude pierwszy, bo domyślnie
# pierwszy w korycie; to NIE jest kolejność prób (patrz chat()).
_PRIORITY = ("anthropic",) + _FREE

_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY", "cloudflare": "CLOUDFLARE_API_KEY",
}

# Dostawcy wymagający DODATKOWYCH zmiennych w .env poza samym kluczem API
# (na razie tylko Cloudflare: account_id w ścieżce URL) - _configured()
# niżej sprawdza, że WSZYSTKIE są ustawione, zanim provider liczy się jako
# "gotowy" w providers_pool()/status()/_allowed(). Bez tego Cloudflare z
# samym CLOUDFLARE_API_KEY, ale bez CLOUDFLARE_ACCOUNT_ID, wyglądałby w
# panelu na skonfigurowanego, a każda próba i tak kończyłaby się błędem.
_EXTRA_ENV: dict[str, tuple[str, ...]] = {"cloudflare": ("CLOUDFLARE_ACCOUNT_ID",)}

_MODEL = {
    # Claude: ANTHROPIC_MODEL (1.17.0) albo starsza nazwa CLOUD_MODEL z .env
    # sprzed koryta - obie działają, żeby .env ze starego laptopa nie
    # zmieniał cicho modelu. Domyślnie Haiku 5.5 (claude-haiku-5-5): prośba
    # Grzegorza 2026-10-21 ("claude haiku"), najtańszy i najszybszy model z
    # aktualnej rodziny - jako GŁÓWNY dostawca każdej rozmowy liczy się
    # właśnie to. Mocniejszy model (claude-sonnet-5-5) wpisujesz w .env.
    "anthropic": (os.environ.get("ANTHROPIC_MODEL", "").strip()
                  or os.environ.get("CLOUD_MODEL", "").strip() or "claude-haiku-5-5"),
    "groq": os.environ.get("GROQ_MODEL", "").strip() or "openai/gpt-oss-20b",
    # gemini-3.8-flash: zweryfikowane 2026-10-21 wobec oficjalnej listy modeli
    # (ai.google.dev/gemini-api/docs/models) - obecny, stabilny, zalecany dla
    # nowych projektów domyślny model Flash (poprzedni domyślny tu,
    # gemini-3.5-flash z 1.8.x, nadal działa, Google sam przekierowuje go na
    # 3.6, ale 3.8 jest świeższy i to on jest teraz zalecany). GEMINI_MODEL w
    # .env zawsze nadpisuje tę wartość - podnieś ją tam, gdy Google wyda kolejny.
    "gemini": os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.8-flash",
    "openrouter": os.environ.get("OPENROUTER_MODEL", "").strip() or "openrouter/free",
    "huggingface": os.environ.get("HUGGINGFACE_MODEL", "").strip() or "openai/gpt-oss-20b",
    "cloudflare": os.environ.get("CLOUDFLARE_MODEL", "").strip() or "@cf/openai/gpt-oss-20b",
}

# 1.30.17 (prośba Grzegorza: "coś grubego, żeby umiał od ręki"): MOCNIEJSZY Claude
# TYLKO do myślenia Namysłu (plan, szkic, krytyka, poprawa analiz), gdy jest klucz
# anthropic. Routing i zwykła rozmowa zostają na tanim modelu (_MODEL["anthropic"],
# domyślnie Haiku). Dzienny/miesięczny budżet (KORYTO_BUDZET_*) i tak ogranicza koszt;
# po jego wyczerpaniu Namysł spada na darmową pulę. NAMYSL_MODEL="" = bez dopłaty
# (to samo, co zwykła rozmowa); NAMYSL_MODEL=claude-haiku-5-5 wraca do taniego.
NAMYSL_MODEL = os.environ.get("NAMYSL_MODEL", "").strip()
if NAMYSL_MODEL == "":
    NAMYSL_MODEL = "claude-sonnet-5-5"
elif NAMYSL_MODEL.lower() in ("0", "off", "nie", "wylaczony", "brak"):
    NAMYSL_MODEL = ""  # jawnie wyłączone -> używaj zwykłego modelu

_DAILY_LIMIT = {
    # Claude jest PŁATNY per token, więc dzienny limit to jedyny bezpiecznik
    # kosztów. 50 -> 300 (1.17.0): jako główny dostawca KAŻDEJ rozmowy (plus
    # krok 1 routera i planer, patrz koryto.py) 50 wyczerpywałoby się w
    # godzinę i reszta dnia szłaby darmową pulą wbrew decyzji o "głównym
    # dostawcy". 300 krótkich zapytań Haiku dziennie to rząd kilkudziesięciu
    # groszy - własny próg wpisujesz w .env (CLOUD_DAILY_LIMIT).
    "anthropic": env_int("CLOUD_DAILY_LIMIT", 300, 0, 1000000),
    "groq": env_int("GROQ_DAILY_LIMIT", 1000, 0, 1000000),
    "gemini": env_int("GEMINI_DAILY_LIMIT", 100, 0, 1000000),
    "openrouter": env_int("OPENROUTER_DAILY_LIMIT", 50, 0, 1000000),
    "huggingface": env_int("HUGGINGFACE_DAILY_LIMIT", 20, 0, 1000000),
    "cloudflare": env_int("CLOUDFLARE_DAILY_LIMIT", 500, 0, 1000000),
}

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
# Budżet odpowiedzi Claude: osobna stała (nazwa CLOUD_MAX_TOKENS z .env
# zachowana ze starej "chmury" w router.py, ta sama wartość i ten sam powód:
# 900 tokenów = pełna, wielopunktowa odpowiedź po polsku bez ucięcia; Anthropic
# liczy realne tokeny, nie sam limit). CLOUD_TIMEOUT - jak dotąd 60 s.
_ANTHROPIC_MAX_TOKENS = env_int("CLOUD_MAX_TOKENS", 1600, 16, 8192)  # 900 -> 1600, 1.17.15 (patrz JUGGLER_MAX_TOKENS)
_ANTHROPIC_TIMEOUT = env_int("CLOUD_TIMEOUT", 60, 1, 3600)
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_GEMINI_URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_HUGGINGFACE_URL = "https://router.huggingface.co/v1/chat/completions"
# Brak stałej _CLOUDFLARE_URL: adres zawiera account_id z .env (zmienny per
# instalacja), więc budowany jest dopiero w _cloudflare_chat() niżej.

# Prompt dla trybu "junior" (research()): celowo BEZ osobowości GREGAI i BEZ
# historii rozmowy - dostawca ma odpowiedzieć na SAMO pytanie, neutralnie,
# nie zgadując, czyje to pytanie ani w jakim kontekście. To właściwa
# "konstrukcja" pytania z instrukcji Grzegorza: nie przeróbka treści pytania,
# a usunięcie identyfikującego kontekstu, który najczęściej odpowiada za
# false-flag (nie samo pytanie, ale to, Z CZYM jest podane).
_RESEARCH_SYSTEM_PROMPT = (
    "Jesteś neutralnym, ogólnym asystentem badawczym. Odpowiadaj rzeczowo i "
    "pomocnie na pytanie poniżej. Nie zgaduj, kto je zadał ani w jakim "
    "kontekście - potraktuj je jako samodzielne pytanie ogólne. Nie odmawiaj, "
    "chyba że pytanie jest wprost i poważnie szkodliwe. Odpowiedź ma być "
    "krótkim, praktycznym materiałem badawczym (kilka punktów albo krótki "
    "akapit) - kto inny złoży z niego później finalną odpowiedź, więc nie "
    "musisz być kompletny ani ostateczny."
)

# Heurystyka "ryzykowne" = pytanie, które pojedynczy dostawca może
# zinterpretować jako sygnał do odmowy albo (gorzej) do nieproszonej reakcji
# kryzysowej, zamiast zwykłej odpowiedzi: finanse w kryzysie, zdrowie
# psychiczne, bezpieczeństwo/systemy, przemoc, polityka. Celowo prosty
# wzorzec (regex, nie model) - Grzegorz może go pominąć, bo w trybie
# łańcuchowym pytanie i tak dostanie odpowiedź, tylko bez dodatkowej
# warstwy ochronnej.
# 1.19.0 (audyt rdzenia): zawężone formy - dawne "d[lł]ug\w+", "zabi[jć]",
# "bro[nń]" i "polityk" łapały "Jak długo gotować jajko?", "Jak zabić czas w
# pociągu?", "Jak bronić się w dyskusji?", "Jaka jest polityka zwrotów?".
_RISKY_RE = re.compile(
    r"\b(samobój\w*|skrzywdz\w*|przemoc\w*|wybuchow\w*|narkotyk\w*"
    r"|zabi(?:ć|c|j\w*)\s+(?:si[ęe]|go|j[ąa]|ich|kogo[śs]|cz[lł]owieka|siebie)|si[ęe]\s+zabi(?:j[ęe]|jesz|ć|c)\b"
    r"|bro[nń]|bro[nń]\s+paln\w*|broni\s+palnej|pistolet\w*|karabin\w*"
    r"|haker\w*|w[lł]am\w*|zhack\w*|exploit\w*|nielegaln\w*|oszust\w*"
    r"|bankrut\w*|zadłuż\w*|zadluz\w*|d[lł]ug(?:ów|ow|ach|ami|iem|om|u)\b|egzekuc\w*|komornik\w*"
    r"|depresj\w*|kryzys\w*|nie dam rady|poddaj[ęe] si[ęe]|rozpacz\w*"
    r"|polityczn\w*|na kogo g[lł]osowa\w*|wybor\w*\s+(?:prezydenck|parlamentarn)\w*)\b",
    re.IGNORECASE,
)
# "dług"/"długi" to też "długi spacer": ryzykowne tylko przy słowie o pieniądzach obok.
_DEBT_RE = re.compile(
    r"\b(?:d[lł]ugi?|d[lł]ug)\b(?=.{0,40}\b(?:sp[lł]a[ct]\w*|kredyt\w*|po[zż]yczk\w*|bank\w*|z[lł]\b|z[lł]otych|odsetk\w*|rat\w*))"
    r"|\b(?:sp[lł]a[ct]\w*|kredyt\w*|po[zż]yczk\w*|mam|narobi\w*|wpad\w*\s+w)\s+(?:\w+\s+){0,3}d[lł]ugi?\b",
    re.IGNORECASE,
)


def is_risky(message: str) -> bool:
    """Pytanie, przy którym warto zebrać opinie kilku modeli (finanse, prawo,
    zdrowie psychiczne, przemoc, polityka) - patrz router, krok "ryzykowne"."""
    return _RISKY_RE.search(message) is not None or _DEBT_RE.search(message) is not None


def _configured(name: str) -> bool:
    """Czy dostawca ma WSZYSTKO, czego potrzebuje do próby: główny klucz
    (_KEY_ENV) i - dla tych, którzy tego wymagają (_EXTRA_ENV) - każdą
    dodatkową zmienną też ustawioną. Jedno miejsce, z którego korzystają
    providers_pool()/_allowed()/status(), żeby te trzy nigdy się nie
    rozjechały w tym, co liczą za "gotowego" dostawcę."""
    if not os.environ.get(_KEY_ENV[name], "").strip():
        return False
    return all(os.environ.get(extra, "").strip() for extra in _EXTRA_ENV.get(name, ()))


def _etap_providers(etap: str) -> list[str]:
    """Dostawcy należący do etapu koryta (w kolejności wyświetlania)."""
    return [name for name in _PRIORITY if _ETAP[name] == etap]


def providers_pool(etap: str | None = None) -> list[str]:
    """Dostawcy gotowi do próby (klucz + ew. dodatkowe zmienne, patrz
    _configured), w kolejności etapów koryta (agent/koryto.py) - samo "czy
    jest co próbować", bez sprawdzania dziennego limitu (to robi _allowed
    przy faktycznej próbie). Etap pominięty w KORYTO nie wchodzi do puli
    wcale. `etap` zawęża do jednego etapu ("anthropic" albo "darmowe")."""
    etapy = [etap] if etap else koryto_mod.network_order()
    return [name for e in etapy for name in _etap_providers(e) if _configured(name)]


# --- Rozdzielnica (1.30.23): "prąd" = płatny Claude. Waga uwagi (skupienie 1-4)
# decyduje, którą SZYNĄ puścić zapytanie, żeby najdroższego modelu używać jak
# najmniej przy jak najlepszym wyniku. Polityka B (domyślna, prośba Grzegorza):
# darmowa pula ZAWSZE pierwsza, Claude tylko jako ESKALACJA przy wadze 3-4, gdy
# pula zawiedzie; przy wadze 1-2 płatny etap jest w ogóle wykluczony. Respektuje
# KORYTO (nie wskrzesza etapu, który użytkownik wyłączył). ROZDZIELNICA=0 wyłącza
# (zachowanie jak dawniej: kolejność i model wg KORYTO/NAMYSL_MODEL).
_PLATNY_ETAP = "anthropic"
_ROZDZ_LICZNIK = {"bez_claude": 0, "z_claude": 0, "blokady_platnego": 0}


def _stopped() -> bool:
    """Stop z przeglądarki (router._CANCEL w tym samym wątku), bez importu routera."""
    router = sys.modules.get("router")
    try:
        return bool(router and router._cancelled())
    except Exception:
        return False


def _read_deadline(call_timeout) -> float:
    """Ile wolno czytać treść odpowiedzi: tyle, ile wynosi limit wywołania (najmniej
    5 s, najwyżej 60 s jak dawniej). Serwer sączący bajty nie zatrzyma już wiadomości
    na minutę przy limicie 10 s (audyt 1.32.1)."""
    try:
        t = float(call_timeout or 60.0)
    except (TypeError, ValueError):
        t = 60.0
    return max(5.0, min(60.0, t))


def rozdzielnica_policy() -> str:
    p = os.environ.get("ROZDZIELNICA", "B").strip().upper()
    if p in ("0", "OFF", "NIE", "WYLACZONA", "WYLACZONE"):
        return "off"
    return "A" if p == "A" else "B"


def rozdzielnica(poziom: int) -> dict:
    """Dla wagi uwagi `poziom` (1-4) zwraca, którymi etapami sieciowymi i jakim
    modelem puścić to wywołanie. {"etapy": [...], "model": str|None, "platny": bool}.
    Etapy w KOLEJNOŚCI prób (pierwszy = próbowany najpierw)."""
    net = koryto_mod.network_order()                      # dozwolone etapy wg KORYTO
    has_free = "darmowe" in net
    has_platny = _PLATNY_ETAP in net
    policy = rozdzielnica_policy()
    if policy == "off":
        return {"etapy": net, "model": (NAMYSL_MODEL or None), "platny": has_platny, "policy": "off"}
    # Polityka A: płatny dopiero od wagi 4. Polityka B: płatny jako eskalacja od 3.
    prog_platny = 4 if policy == "A" else 3
    pusc_platny = has_platny and poziom >= prog_platny
    etapy = (["darmowe"] if has_free else []) + ([_PLATNY_ETAP] if pusc_platny else [])
    # Gdy KORYTO nie ma darmowej puli, a płatny jest wykluczony przez wagę -
    # zostaje pusto (zapytanie pójdzie lokalnie); to świadomy wybór polityki.
    if has_platny and not pusc_platny:
        _ROZDZ_LICZNIK["blokady_platnego"] += 1
    model = (NAMYSL_MODEL or None) if (pusc_platny and poziom >= 4) else None
    return {"etapy": etapy, "model": model, "platny": pusc_platny, "policy": policy}


def samodopasowanie() -> list | None:
    """1.32.4 (decyzja Grzegorza: "niech dostawca sam się dopasowuje"): wywołania bez
    wskazanej kolejności (wybór narzędzia, straż, zadania stałe, streszczenia) idą najpierw
    darmową pulą, a płatny Claude wchodzi dopiero, gdy pula zawiedzie. Rozmowa i Namysł mają
    własną kolejność z rozdzielnicy (waga uwagi). ROZDZIELNICA=0 wraca do kolejności KORYTO."""
    if rozdzielnica_policy() == "off":
        return None
    net = koryto_mod.network_order()
    order = [e for e in ("darmowe", _PLATNY_ETAP) if e in net] + [e for e in net if e not in ("darmowe", _PLATNY_ETAP)]
    return order or None


def rozdzielnica_licznik() -> dict:
    """Ile odpowiedzi sieciowych obsłużyła darmowa pula vs płatny Claude i ile
    razy rozdzielnica w ogóle zablokowała płatny etap (oszczędność). Do /debug."""
    return dict(_ROZDZ_LICZNIK)


# --- Licznik dzienny PER DOSTAWCA (ten sam wzorzec co router._cloud_calls_today,
# tylko rozbity na dostawcę: jeden wspólny limit nie miałby sensu, bo każdy
# dostawca ma inny, darmowy budżet) ------------------------------------------
_CALLS_MEM: dict[str, dict] = {}
_COUNT_CACHE: dict = {"key": None, "counts": {}}
# Audyt 2026-10-19: _CALLS_MEM/_COUNT_CACHE były czytane/zapisywane bez
# blokady, mimo że main.py odpala ThreadingHTTPServer (więc kilka żądań
# naraz = kilka wątków) - ten sam powód, dla którego trace.py ma _LOCK
# (patrz jego docstring: "jedyna blokada chroni pamięć podręczną przed
# wyścigiem wątków serwera"). Bez niej dwa równoległe zapytania mogły
# zgubić jeden z dwóch przyrostów licznika (read-modify-write bez ochrony).
# Ten sam problem i ta sama łata w router.py (_CLOUD_CALLS_MEM/_CLOUD_COUNT_CACHE).
_LOCK = threading.Lock()

# --- Bezpiecznik dostawcy (1.10.0, wzorzec z puli poświadczeń OpenClaude:
# cooldown po porażce, trwałe wyłączenie po błędzie autoryzacji, sukces zeruje).
# Dotąd dostawca, który właśnie padł (sieć, 5xx, limit minutowy 429), był
# losowany od nowa przy KAŻDEJ wiadomości i kosztował pełny timeout (do 60 s),
# zanim łańcuch przeszedł dalej - przy jednym martwym dostawcy każda odpowiedź
# była o minutę wolniejsza. Teraz: 429/5xx/sieć -> cooldown (Retry-After
# dostawcy, inaczej 60 s podwajane przy kolejnych porażkach, do 15 min);
# 401/403 -> wyłączony do restartu (zły klucz sam się nie naprawi); 400/404
# (zła nazwa modelu, format) -> cooldown jak wyżej, bo bywa chwilowe. Gdy
# WSZYSCY są w cooldownie, próbujemy tego, który padł najdawniej (nigdy
# "nikt"). Stan w pamięci procesu, widoczny w status()/narracji Namysłu.
_BREAKER: dict[str, dict] = {}
# 60 -> 15 s (1.17.1, zgłoszenie Grzegorza 2026-10-21: "skoro raz można było,
# to drugi raz też powinno móc"): po JEDNEJ porażce dostawca odpoczywał
# minutę (i dwie, cztery... przy kolejnych), a odpoczywający idzie na KONIEC
# kolejki - więc jedna chwilowa czkawka Claude odsyłała kolejne wiadomości do
# darmowej puli wbrew kolejności koryta. 15 s wystarcza, żeby nie dobijać
# dostawcy w trakcie jednej odpowiedzi, a zdrowy wraca na swoje miejsce przy
# następnej wiadomości. Podwajanie przy kolejnych porażkach i 15 min sufitu
# zostają - trwale martwy dostawca nadal nie jest próbowany przy każdym pytaniu.
COOLDOWN_BASE_S = 15.0
COOLDOWN_MAX_S = 15 * 60.0
FORBIDDEN_COOLDOWN_S = 900  # 1.27.0: HTTP 403 = 15 min przerwy
RETRY_AFTER_INLINE_S = 10.0  # krótszy Retry-After: poczekaj i powtórz u TEGO SAMEGO dostawcy
DAILY_QUOTA_COOLDOWN_S = 4 * 60 * 60  # 1.32.15: 429 "limit dzienny" = 4 godz., nie minuty dostawcy
_DAILY_QUOTA_RE = re.compile(
    r"(?i)(per-day|per_day|daily (free )?allocation|exceeded your current quota|quota exceeded|"
    r"free-models-per-day)")


def _breaker(name: str) -> dict:
    return _BREAKER.setdefault(name, {"cooldown_do": 0.0, "porazki": 0, "wylaczony": "", "ostatnia_porazka": 0.0,
                                      "twardy": False})


def _retry_after_seconds(e: Exception) -> float | None:
    headers = getattr(e, "headers", None)
    raw = None
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        # 1.32.12: Retry-After jako data HTTP ("Wed, 21 Oct 2026 07:28:00 GMT")
        try:
            from email.utils import parsedate_to_datetime
            v = parsedate_to_datetime(str(raw)).timestamp() - time.time()
        except Exception:
            return None
    # 1.27.0 (audyt): "inf"/"1e999"/NaN wywracały int() i cały łańcuch dostawców do restartu.
    if not math.isfinite(v):
        return float(COOLDOWN_MAX_S)
    return min(max(0.0, v), float(COOLDOWN_MAX_S))


def note_failure(name: str, e: Exception) -> str:
    """Zapis porażki dostawcy; zwraca krótki opis decyzji (do błędu/śladu)."""
    code = getattr(e, "code", None)
    with _LOCK:
        b = _breaker(name)
        now = time.monotonic()
        b["ostatnia_porazka"] = now
        if code == 401:
            b["wylaczony"] = f"HTTP {code}: zły klucz albo brak uprawnień - wyłączony do restartu"
            return b["wylaczony"]
        if code == 402:
            # 1.32.13 (rozmowa 25.10): HuggingFace "no remaining credits" - kolejne próby też
            # zawiodą, a każda kosztowała czas; wyłączony do restartu, jak zły klucz.
            b["wylaczony"] = "HTTP 402: brak kredytów u dostawcy - wyłączony do restartu (doładuj albo usuń klucz z .env)"
            return b["wylaczony"]
        if code == 403:
            # 1.27.0 (audyt): 403 to często moderacja jednej wiadomości (OpenRouter), zapora
            # Cloudflare albo region - nie zły klucz. Długa przerwa zamiast wyłączenia do restartu.
            b["porazki"] += 1
            b["cooldown_do"] = now + FORBIDDEN_COOLDOWN_S
            b["twardy"] = True
            return f"HTTP 403: przerwa {FORBIDDEN_COOLDOWN_S // 60} min (moderacja, zapora albo uprawnienia)"
        b["porazki"] += 1
        if code == 429 and _DAILY_QUOTA_RE.search(str(e)):
            # 1.32.15 (audyt, transkrypt "cena SOL"/"DISCORD"): openrouter
            # "free-models-per-day", cloudflare "daily free allocation" i
            # gemini "exceeded your current quota" to limity NA CAŁY DZIEŃ,
            # nie na minutę - a te API i tak odsyłają Retry-After rzędu
            # 480 s (8 min), co dawało kółko "cooldown -> znowu 429 -> znowu
            # cooldown" bez szans na sukces, zamiast raz odpuścić na dłużej
            # i oddać szansę innym dostawcom/lokalnemu modelowi.
            b["cooldown_do"] = now + DAILY_QUOTA_COOLDOWN_S
            b["twardy"] = True
            return f"HTTP 429: dzienny limit - przerwa {DAILY_QUOTA_COOLDOWN_S // 3600} godz."
        wait = _retry_after_seconds(e)
        # "twardy": przerwę wyznaczył sam serwer (Retry-After) - nie pukamy przed czasem.
        b["twardy"] = wait is not None
        if wait is None:
            wait = min(COOLDOWN_BASE_S * (2 ** (b["porazki"] - 1)), COOLDOWN_MAX_S)
        b["cooldown_do"] = now + wait
        return f"cooldown {int(wait)} s (porażka {b['porazki']})"


def note_success(name: str) -> None:
    with _LOCK:
        b = _breaker(name)
        b["cooldown_do"], b["porazki"], b["twardy"] = 0.0, 0, False


def exhausted(name: str) -> bool:
    """1.32.15: True tylko gdy ten dostawca jest NAPRAWDĘ bez szans teraz -
    wyłączony (401/402) albo w przerwie, którą wyznaczył SERWER albo nasza
    klasyfikacja 403/429-dzienny (`twardy`), NIE zwykły, krótki cooldown po
    jednej przejściowej porażce (ten może się udać za chwilę - stąd nie
    liczy się jako "wyczerpany"). Rozróżnienie potrzebne wszędzie, gdzie
    "wszyscy sieciowi nie mają szans" ma być inny sygnał niż "akurat jedna
    próba padła" (patrz router._rozmowa_korytem: ostatnia szansa lokalnie)."""
    with _LOCK:
        b = _breaker(name)
        if b["wylaczony"]:
            return True
        return bool(b["twardy"]) and (b["cooldown_do"] - time.monotonic()) > 0


def breaker_state(name: str) -> dict:
    """{"stan": "ok"|"cooldown"|"wylaczony", "sekund": int, "powod": str} - do status()/narracji."""
    with _LOCK:
        b = _breaker(name)
        if b["wylaczony"]:
            return {"stan": "wylaczony", "sekund": 0, "powod": b["wylaczony"]}
        left = b["cooldown_do"] - time.monotonic()
        if left > 0:
            return {"stan": "cooldown", "sekund": int(left) + 1, "powod": f"ostatnie porażki: {b['porazki']}"}
        return {"stan": "ok", "sekund": 0, "powod": ""}


def _breaker_open(name: str) -> bool:
    return breaker_state(name)["stan"] != "ok"


def reset_breakers() -> None:
    with _LOCK:
        _BREAKER.clear()


# --- Dziennik Koryta (1.20.0) ------------------------------------------------
# Dzienne limity i wydatki Claude przeżywają restart (wcześniej liczniki żyły w
# pamięci procesu, a plik par destylacji obejmował tylko rozmowy). Jeden mały
# plik: dzień (UTC), liczniki wywołań per dostawca, tokeny Claude, miesięczne
# wydatki w USD. Ceny w .env (KORYTO_CENA_*_USD, za milion tokenów): to
# SZACUNEK do bezpiecznika, rachunek prowadzi Anthropic Console.
JOURNAL_PATH = Path(os.environ.get("KORYTO_DZIENNIK_PLIK") or (DISTILL_PAIRS_PATH.parent.parent / "koryto_dziennik.json"))
_JOURNAL: dict = {}
_JOURNAL_LOADED = False
_PRICE_IN = env_float("KORYTO_CENA_WEJSCIE_USD", 1.0, 0.0, 1000.0)
_PRICE_OUT = env_float("KORYTO_CENA_WYJSCIE_USD", 5.0, 0.0, 1000.0)
_BUDGET_MONTH_USD = env_float("KORYTO_BUDZET_MIESIAC_USD", 20.0, 0.0, 100000.0)  # 0 = bez limitu
_BUDGET_DAY_USD = env_float("KORYTO_BUDZET_DZIEN_USD", 1.5, 0.0, 100000.0)


def _journal_load_locked() -> None:
    """1.29.0 (kontrola): dziennik to BEZPIECZNIK pieniędzy, więc przy kłopocie
    zamyka się, a nie otwiera. Chwilowy błąd odczytu: próbujemy przy następnym
    wywołaniu, a do tego czasu Claude czeka. Uszkodzony plik (ucięty, nie-JSON):
    kopia .corrupt i dzień uznany za wyczerpany (wcześniej limit cicho spadał do 0)."""
    global _JOURNAL_LOADED
    if _JOURNAL_LOADED:
        return
    try:
        raw = JOURNAL_PATH.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        _JOURNAL_LOADED = True
        return
    except OSError:
        _JOURNAL["_blad_odczytu"] = True  # spróbujemy znowu; over_budget blokuje
        return
    _JOURNAL.pop("_blad_odczytu", None)
    _JOURNAL_LOADED = True
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("nie słownik")
        if not isinstance(data.get("wywolania", {}), dict):
            data["wywolania"] = {}
        # 1.32.12 (audyt tura 16): ręcznie wpisane "abc" albo lista w licznikach wywracały cały
        # łańcuch dostawców (int()) - takie wpisy liczą się jako 0.
        clean = {}
        for k, v in data["wywolania"].items():
            try:
                iv = int(v)
                clean[str(k)] = iv if iv >= 0 else 0
            except (TypeError, ValueError):
                clean[str(k)] = 0
        data["wywolania"] = clean
        for k in ("usd_dzien", "usd_miesiac"):
            v = float(data.get(k) or 0)
            # 1.32.3 (audyt tura 8): "NaN" przechodziło float(), a NaN nigdy nie jest >= limitu -
            # limit Claude znikał na cały miesiąc. Ujemne też nie mają sensu.
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"{k} = {data.get(k)!r}")
        _JOURNAL.update(data)
    except (ValueError, TypeError):
        try:
            import fsutil
            fsutil.quarantine(JOURNAL_PATH)
        except Exception:
            pass
        now = time.gmtime()
        _JOURNAL.update(dzien=time.strftime("%Y-%m-%d", now), miesiac=time.strftime("%Y-%m", now),
                        # 1.32.3: miesiąc też jak wyczerpany (dawniej 0.0 = limit 20 USD od nowa).
                        wywolania={}, usd_dzien=float(_BUDGET_DAY_USD or 0), usd_miesiac=float(_BUDGET_MONTH_USD or 0),
                        uszkodzony=time.strftime("%Y-%m-%d", now))


def _journal_roll_locked() -> None:
    now = time.gmtime()
    today, month = time.strftime("%Y-%m-%d", now), time.strftime("%Y-%m", now)
    # Tylko do przodu: zegar cofnięty (bateria RTC, ręczna zmiana) nie zeruje wydatków.
    if str(_JOURNAL.get("dzien") or "") < today:
        _JOURNAL.update(dzien=today, wywolania={}, usd_dzien=0.0)
    if str(_JOURNAL.get("miesiac") or "") < month:
        _JOURNAL.update(miesiac=month, usd_miesiac=0.0)


def _journal_save_locked() -> None:
    try:
        import fsutil
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _JOURNAL.get("_blad_odczytu"):
            return  # nie nadpisujemy pliku, którego nie udało się przeczytać
        fsutil.atomic_write_text(JOURNAL_PATH, json.dumps(_JOURNAL, ensure_ascii=False))
    except Exception:
        pass  # dziennik to dodatek: brak zapisu nie psuje odpowiedzi


def spent_usd() -> dict:
    """{"dzien": USD, "miesiac": USD, "limit_dzien", "limit_miesiac"} (szacunek)."""
    with _LOCK:
        _journal_load_locked()
        _journal_roll_locked()
        return {"dzien": round(float(_JOURNAL.get("usd_dzien") or 0), 4),
                "miesiac": round(float(_JOURNAL.get("usd_miesiac") or 0), 4),
                "limit_dzien": _BUDGET_DAY_USD, "limit_miesiac": _BUDGET_MONTH_USD}


def over_budget(name: str = "anthropic") -> str:
    """Pusty tekst, gdy można wołać; inaczej powód (tylko płatny dostawca)."""
    if name != "anthropic":
        return ""
    with _LOCK:
        _journal_load_locked()
        if _JOURNAL.get("_blad_odczytu"):
            return "dziennik wydatków chwilowo nieczytelny - Claude czeka (bezpiecznik budżetu)"
    sp = spent_usd()
    if sp["limit_miesiac"] and sp["miesiac"] >= sp["limit_miesiac"]:
        bad = _JOURNAL.get("uszkodzony")
        if bad and str(bad)[:7] == time.strftime("%Y-%m", time.gmtime()):
            # 1.32.3 (przegląd poprawek): nie "wydałeś budżet", tylko prawdziwy powód i co zrobić.
            return (f"dziennik wydatków był uszkodzony ({bad}), więc nie wiem, ile wydano w tym miesiącu - żeby nie "
                    f"przekroczyć limitu, Claude czeka do 1. dnia następnego miesiąca. Jeśli wiesz, ile wydałeś, "
                    f"wpisz to jako usd_miesiac w {JOURNAL_PATH.name} (kopia zepsutego pliku leży obok, .corrupt-*)")
        return f"miesięczny budżet {sp['limit_miesiac']:.2f} USD wyczerpany"
    if sp["limit_dzien"] and sp["dzien"] >= sp["limit_dzien"]:
        return f"dzienny budżet {sp['limit_dzien']:.2f} USD wyczerpany"
    return ""


def _note_spend(usage: dict) -> None:
    try:
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        cw = int(usage.get("cache_creation_input_tokens") or 0)
        cr = int(usage.get("cache_read_input_tokens") or 0)
        # 1.30.17: cena zależnie od modelu TEGO wywołania - Namysł na Sonnecie kosztuje
        # ~3x więcej niż Haiku, a Opus jeszcze więcej. Bez tego dzienny budżet (który chroni
        # kieszeń) liczyłby Sonnet po cenie Haiku i zaniżał koszt. Haiku/domyślny: _PRICE_* (z .env).
        _m = (getattr(_REQ, "model", None) or _MODEL["anthropic"]).lower()
        if "opus" in _m:
            p_in, p_out = 15.0, 75.0
        elif "sonnet" in _m:
            p_in, p_out = 3.0, 15.0
        else:
            p_in, p_out = _PRICE_IN, _PRICE_OUT
        usd = (inp * p_in + cw * p_in * 1.25 + cr * p_in * 0.1 + out * p_out) / 1_000_000
        with _LOCK:
            _journal_load_locked()
            _journal_roll_locked()
            _JOURNAL["usd_dzien"] = float(_JOURNAL.get("usd_dzien") or 0) + usd
            _JOURNAL["usd_miesiac"] = float(_JOURNAL.get("usd_miesiac") or 0) + usd
            _journal_save_locked()
    except Exception:
        pass


def _note_call(name: str) -> None:
    # Rozdzielnica (1.30.23): która szyna faktycznie obsłużyła to zapytanie -
    # darmowa pula czy płatny Claude. Daje na /debug prawdziwą miarę "ile razy
    # obeszło się bez prądu".
    if _ETAP.get(name) == _PLATNY_ETAP:
        _ROZDZ_LICZNIK["z_claude"] += 1
    elif _ETAP.get(name) == "darmowe":
        _ROZDZ_LICZNIK["bez_claude"] += 1
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _LOCK:
        slot = _CALLS_MEM.setdefault(name, {"day": "", "n": 0})
        if slot["day"] != today:
            slot.update(day=today, n=0)
        slot["n"] += 1
        _journal_load_locked()
        _journal_roll_locked()
        calls = _JOURNAL.setdefault("wywolania", {})
        calls[name] = int(calls.get(name) or 0) + 1
        _journal_save_locked()


def _count_lines(blob: bytes, today: str, counts: dict[str, int]) -> None:
    tb = today.encode()
    for raw in blob.split(b"\n"):
        if tb not in raw:  # tania wstępna selekcja, jak w router.py
            continue
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(rec, dict) and "pomin_user" not in rec and str(rec.get("ts", "")).startswith(today):
            # Pary bez pola "provider" zapisała stara "chmura" z router.py
            # (sprzed żonglera) - to były wywołania Anthropic, więc liczą się do
            # dziennego limitu Claude (ten sam warunek, co miał router.py).
            provider = rec.get("provider", "anthropic")
            if provider:
                counts[provider] = counts.get(provider, 0) + 1


def _file_counts_today() -> dict[str, int]:
    """Dzisiejsze wywołania z distill_pairs.jsonl. 1.24.0 (przegląd wydajności): plik
    tylko rośnie (dopisywanie), więc czytamy jedynie DOPISANY koniec od ostatniego
    odczytu; pełny odczyt tylko przy nowym dniu, nowym pliku (inny inode po
    przepisaniu) albo gdy plik się skurczył. Po roku (~90 MB) to było ~0,4 s i
    ~350 MB pamięci na KAŻDĄ wiadomość przez sieć."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        st = DISTILL_PAIRS_PATH.stat()
    except FileNotFoundError:
        return {}
    except OSError:
        return {name: _DAILY_LIMIT[name] for name in _PRIORITY}  # nieczytelny plik = nie ryzykuj kosztów
    key = (st.st_mtime_ns, st.st_size, today)
    with _LOCK:
        if _COUNT_CACHE["key"] == key:
            return _COUNT_CACHE["counts"]
        prev = dict(_COUNT_CACHE)
    incremental = (prev.get("ino") == st.st_ino and prev.get("day") == today
                   and isinstance(prev.get("offset"), int) and 0 <= prev["offset"] <= st.st_size)
    try:
        with open(DISTILL_PAIRS_PATH, "rb") as f:
            if incremental:
                # Odcisk ostatnich bajtów przed miejscem, w którym skończyliśmy: plik
                # przepisany w miejscu (kopia z zapasu, edytor) ma tu co innego -> pełny odczyt.
                fp_from = max(0, prev["offset"] - 64)
                f.seek(fp_from)
                if f.read(prev["offset"] - fp_from) != prev.get("fp", b""):
                    incremental = False
            start = prev["offset"] if incremental else 0
            f.seek(start)
            blob = f.read()
    except Exception:
        return {name: _DAILY_LIMIT[name] for name in _PRIORITY}
    counts: dict[str, int] = dict(prev.get("counts") or {}) if incremental else {}
    cut = blob.rfind(b"\n") + 1  # tylko pełne linie; niedokończona zostaje na następny raz
    _count_lines(blob[:cut], today, counts)
    end = start + cut
    tail = (prev.get("fp", b"") if incremental else b"") + blob[:cut]
    with _LOCK:
        _COUNT_CACHE.update(key=key, counts=counts, ino=st.st_ino, day=today, offset=end, fp=tail[-min(64, end):] if end else b"")
    return counts


def _calls_today(name: str) -> int:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _LOCK:
        mem_slot = _CALLS_MEM.get(name)
        in_memory = mem_slot["n"] if mem_slot and mem_slot["day"] == today else 0
        _journal_load_locked()
        if _JOURNAL.get("dzien") == today:
            in_memory = max(in_memory, int((_JOURNAL.get("wywolania") or {}).get(name) or 0))
    # _file_counts_today() bierze _LOCK sam w sobie (nie-reentrantny) - stąd
    # wywołanie DOPIERO po zwolnieniu blokady wyżej, nie w jej środku.
    return max(_file_counts_today().get(name, 0), in_memory)


def _allowed(name: str) -> bool:
    if not _configured(name):
        return False
    if over_budget(name):
        return False
    return _calls_today(name) < _DAILY_LIMIT[name]


def status() -> dict:
    """Dla /api/system_info (patrz main.py, router.juggler_status): stan
    każdego dostawcy, bez sekretów (tylko czy jest w pełni skonfigurowany -
    patrz _configured)."""
    out = {}
    in_koryto = set(koryto_mod.network_order())
    for name in _PRIORITY:
        key_present = _configured(name)
        today = _calls_today(name) if key_present else 0
        bs = breaker_state(name)
        out[name] = {
            "model": _MODEL[name],
            "etap": _ETAP[name],
            "w_korycie": _ETAP[name] in in_koryto,
            "key_present": key_present,
            "today_calls": today,
            "daily_limit": _DAILY_LIMIT[name],
            "enabled": (key_present and today < _DAILY_LIMIT[name] and bs["stan"] != "wylaczony" and not over_budget(name)
                        and _ETAP[name] in in_koryto),
            "bezpiecznik": bs,
        }
        if name == "anthropic":
            out[name]["wydatki_usd"] = spent_usd()
            out[name]["budzet_wyczerpany"] = over_budget(name)
        if name == "anthropic":
            out[name]["pamiec_podreczna"] = dict(CACHE_USAGE)  # 1.19.0, tokeny od startu usługi
    return out


# --- Wywołania poszczególnych dostawców -------------------------------------
# Każda funkcja: (system_prompt, messages [{"role","content"}, już zmaskowane],
# timeout) -> tekst odpowiedzi. Pusta odpowiedź/błąd HTTP/JSON = wyjątek,
# chat()/research() łapią go i idą dalej.

class ProviderError(RuntimeError):
    """Błąd dostawcy z kodem HTTP i Retry-After (gdy były): bezpiecznik w chat()
    (note_failure) rozróżnia po tym zły klucz (401/403) od chwilowego limitu
    (429 + Retry-After) - zwykły RuntimeError gubił obie informacje."""

    def __init__(self, detail: str, code: int | None = None, retry_after: str | None = None):
        super().__init__(detail)
        self.code = code
        self.headers = {"Retry-After": retry_after} if retry_after else {}


def _provider_error(e: urllib.error.HTTPError, detail: str | None = None) -> ProviderError:
    """`detail`: treść już odczytana przez _http_error_detail (1.19.0, audyt
    rdzenia) - ciało odpowiedzi da się przeczytać tylko RAZ, więc drugi odczyt
    zwracał pusty tekst i z "model xyz decommissioned" zostawało samo "HTTP 400"."""
    try:
        ra = e.headers.get("Retry-After") if e.headers is not None else None
    except Exception:
        ra = None
    return ProviderError(detail if detail is not None else _http_error_detail(e), code=e.code, retry_after=ra)


def _http_error_detail(e: urllib.error.HTTPError) -> str:
    """Treść błędu, jaką ODESŁAŁ dostawca (np. "invalid api key", "model
    decommissioned") - bez tego /debug (juggler_error, patrz router.py
    1.7.6/1.7.7) widział tylko "HTTPError", zawsze to samo, bez względu na
    prawdziwą przyczynę (zły klucz, zła nazwa modelu, limit, ...)."""
    try:
        body = e.read(2048).decode("utf-8", "replace").strip()
    except Exception:
        body = ""
    body = trace_mod.mask(body) if body else ""
    return f"HTTP {e.code}" + (f": {body[:200]}" if body else "")


# Zgłoszenie Grzegorza (2026-10-19, log /debug): Groq (openai/gpt-oss-20b)
# czasem próbuje NATYWNEGO wywołania funkcji (np. "wiki_lookup") przez
# protokół API (nie jako tekst - to jest INNY mechanizm niż leak z 1.8.4,
# _sanitize_leaked_tokens tu nic nie pomoże, bo cała odpowiedź jest odrzucona
# na poziomie API, zanim dojdzie do treści), mimo że to zapytanie NIE
# deklaruje żadnego pola `tools` (tool-execution jest wyłącznie w kroku 1,
# patrz router.py). Dostawca (zgodny z API OpenAI: Groq i OpenRouter) odsyła
# to jako HTTP 400 "tool_use_failed" / "Tool choice is none, but model called
# a tool" - cała próba przepada, mimo że model miał dobry pomysł na
# odpowiedź, tylko błędnie opakowany. Jedna próba ponowienia z mocniejszym,
# wprost adresowanym przypomnieniem (_NO_TOOLS_REMINDER), zanim uznamy tego
# dostawcę za zawiedzionego i przejdziemy do następnego w łańcuchu (patrz
# chat()) - "jedna", nie "w kółko", żeby nie podwajać czasu czekania bez
# końca, i WYŁĄCZNIE dla TEGO konkretnego błędu (inny błąd, np. zły klucz
# albo wyczerpany limit, od razu przechodzi dalej jak dotąd).
_TOOL_USE_REJECTION_RE = re.compile(
    r"tool_use_failed|Tool choice is none, but model called a tool", re.IGNORECASE
)
_NO_TOOLS_REMINDER = (
    "\n\nWAŻNE DLA TEGO ZAPYTANIA: nie zadeklarowano tu ŻADNYCH funkcji/narzędzi "
    "(function calling) - próba wywołania jakiejkolwiek funkcji zostanie odrzucona "
    "przez API dostawcy, zanim odpowiedź dotrze do użytkownika. Odpowiedz WYŁĄCZNIE "
    "zwykłym tekstem, nigdy nie próbuj wywołać żadnej funkcji/tool/narzędzia."
)


def _openai_compatible_chat(url: str, api_key: str, model: str, system_prompt: str,
                             messages: list[dict], timeout: float) -> str:
    """Kształt zapytania wspólny dla OpenRouter, Hugging Face i Cloudflare (zgodne
    z API OpenAI: /chat/completions, Authorization: Bearer, messages z rolą
    system/user/assistant). Dwie próby: druga WYŁĄCZNIE gdy pierwsza padła na
    natywne wywołanie funkcji przez model (patrz _TOOL_USE_REJECTION_RE
    wyżej) - każdy inny błąd kończy się po pierwszej próbie, jak dotąd."""
    prompt = system_prompt

    def _post(msgs: list[dict], call_timeout: float) -> dict:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": prompt}] + msgs,
            "max_tokens": _max_tokens(JUGGLER_MAX_TOKENS, floor=_REASONING_FLOOR_TOKENS),
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        with netguard_mod.urlopen(req, timeout=call_timeout, fresh=True, reuse_s=_guard_reuse()) as resp:
            # Audyt 1.32.1: czytanie treści też w limicie wywołania (nie stałe 60 s).
            return netguard_mod.read_json(resp, deadline=_read_deadline(call_timeout))

    data = None
    for attempt in (1, 2):
        try:
            data = _post(messages, timeout)
            break
        except urllib.error.HTTPError as e:
            detail = _http_error_detail(e)
            if attempt == 1 and _TOOL_USE_REJECTION_RE.search(detail):
                prompt = system_prompt + _NO_TOOLS_REMINDER
                continue
            raise _provider_error(e, detail) from e
    text, truncated = _openai_text(data)
    if not text:
        raise RuntimeError("pusta odpowiedź")
    # 1.32.5: openrouter/free losuje model z darmowych - czasem klasyfikator bezpieczeństwa
    # (odpowiada "User Safety: safe / Response Safety: safe", nie rozmawia). Taki wynik to
    # błąd dostawcy: koryto idzie do następnego, zamiast pokazać etykietę Grzegorzowi.
    if _GUARD_MODEL_RE.search(str((data or {}).get("model") or "")) or _GUARD_REPLY_RE.match(text):
        raise RuntimeError("model-klasyfikator bezpieczeństwa zamiast rozmowy")
    return _continue_once(text, truncated, messages, timeout, lambda msgs, t: _openai_text(_post(msgs, t)))


_GUARD_MODEL_RE = re.compile(r"(?i)guard|safety|shield|moderat")
_GUARD_REPLY_RE = re.compile(r"(?is)^\s*(?:(?:(?:user|response|prompt|assistant)\s+safety|safety\s+categories)\s*:\s*[^\n]*\s*)+$|^\s*(?:safe|unsafe)(?:\s*\n\s*S\d+(?:\s*,\s*S\d+)*)?\s*$")


def _openai_text(data: dict) -> tuple[str, bool]:
    """(tekst, ucięty limitem) z odpowiedzi w kształcie API OpenAI."""
    choices = (data or {}).get("choices") or []
    first = choices[0] if choices else {}
    text = ((first.get("message") or {}).get("content") or "").strip()
    return text, first.get("finish_reason") == "length"


def _groq_http2_chat(api_key: str, system_prompt: str, messages: list[dict], timeout: float) -> str:
    """Groq - WYŁĄCZNIE ten dostawca - przez httpx z realnym HTTP/2, nie przez
    netguard._OPENER (stdlib urllib/http.client, tylko HTTP/1.1). Zgłoszenie
    Grzegorza (2026-10-19): Cloudflare przed api.groq.com odsyłał 403
    "error code: 1010" ("blocked based on your browser's/client's signature")
    dla KAŻDEGO żądania z GREGAI, a ten sam klucz przez `curl` (ten sam
    komputer, ten sam tunel WARP, inna różnica: curl negocjuje HTTP/2) od
    razu przechodził i dostawał normalną odpowiedź JSON. stdlib nie potrafi
    HTTP/2 wcale - stąd ten jeden, świadomy wyjątek od zasady "zero zależności"
    (patrz requirements.txt), zawężony do Groqa, bo tylko tu to potwierdzone.

    Te same zasady bezpieczeństwa co netguard.urlopen(), odtworzone tutaj
    ręcznie (bo to inny klient HTTP, nie da się tego dostać "za darmo" z
    _OPENER): WARP sprawdzany świeżo (netguard.internet_allowed(fresh=True),
    fail-closed), zero proxy ze środowiska (trust_env=False - inaczej
    http_proxy/https_proxy z .env albo systemu obszedłby WARP), żadnych
    przekierowań (follow_redirects=False - prościej i bezpieczniej niż
    powtarzać tu całą logikę _HttpsOnlyRedirect), limit rozmiaru odpowiedzi
    jak w netguard.read_capped."""
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError(
            "brak httpx (potrzebny do HTTP/2 z Groq, patrz 1.8.0) - zainstaluj: "
            "bash install.sh, albo ręcznie: python3 -m pip install --user httpx[http2]"
        ) from e
    # 1.19.0: w oknie świeżego sprawdzenia z chat()/research() bez ponownego warp-cli.
    if not netguard_mod.recently_verified(_guard_reuse()):
        ok, reason = netguard_mod.internet_allowed(fresh=True)
        if not ok:
            raise netguard_mod.NetGuardBlocked(reason)
    limit = netguard_mod.MAX_REPLY_BYTES
    # Dwie próby, ten sam powód co w _openai_compatible_chat wyżej (Groq to
    # jedyny dostawca z osobną funkcją, patrz docstring tej funkcji - stąd
    # ten sam wzorzec powtórzony tutaj, nie wywołany z tamtej, bo klient HTTP
    # jest inny, httpx, nie netguard._OPENER).
    prompt = system_prompt

    def _post(msgs: list[dict], call_timeout: float) -> tuple[int | None, bytes, str | None]:
        payload = {
            "model": _MODEL["groq"],
            "messages": [{"role": "system", "content": prompt}] + msgs,
            "max_tokens": _max_tokens(JUGGLER_MAX_TOKENS, floor=_REASONING_FLOOR_TOKENS),
        }
        try:
            with httpx.Client(http2=True, trust_env=False, follow_redirects=False, timeout=call_timeout) as client:
                with client.stream(
                    "POST", _GROQ_URL, json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                ) as resp:
                    status = resp.status_code
                    retry_after = resp.headers.get("Retry-After")
                    chunks = []
                    got = 0
                    # 1.27.0 (audyt): łączny limit czasu, jak netguard.read_capped - timeout
                    # httpx dotyczy KAŻDEGO odczytu, więc serwer sączący bajty trzymałby rozmowę.
                    read_deadline = time.monotonic() + float(call_timeout)
                    for chunk in resp.iter_bytes(65536):
                        if time.monotonic() > read_deadline:
                            raise TimeoutError(f"odpowiedź nie dotarła w całości w {float(call_timeout):.0f} s")
                        chunks.append(chunk)
                        got += len(chunk)
                        if got > limit:
                            raise ValueError(f"odpowiedź większa niż {limit // 1024} KB, odrzucona")
                    return status, b"".join(chunks), retry_after
        except (httpx.HTTPError, ImportError) as e:  # ImportError: Client(http2=True) bez pakietu "h2"
            raise RuntimeError(f"{type(e).__name__}: {e}"[:300]) from e

    def _error(status: int, raw: bytes, retry_after: str | None) -> tuple[str, ProviderError]:
        body = trace_mod.mask(raw.decode("utf-8", "replace").strip())
        detail = f"HTTP {status}" + (f": {body[:200]}" if body else "")
        return detail, ProviderError(detail, code=status, retry_after=retry_after)

    raw = b""
    for attempt in (1, 2):
        status, raw, retry_after = _post(messages, timeout)
        if status is not None and status >= 400:
            detail, err = _error(status, raw, retry_after)
            if attempt == 1 and _TOOL_USE_REJECTION_RE.search(detail):
                prompt = system_prompt + _NO_TOOLS_REMINDER
                continue
            raise err
        break
    text, truncated = _openai_text(json.loads(raw.decode("utf-8")))
    if not text:
        raise RuntimeError("pusta odpowiedź")

    def _more(msgs: list[dict], call_timeout: float) -> tuple[str, bool]:
        # Dokończenie: WARP sprawdzony przed chwilą (wyżej) albo w oknie chat().
        if not netguard_mod.recently_verified(_guard_reuse() or netguard_mod.FRESH_REUSE_MAX_S):
            ok2, reason2 = netguard_mod.internet_allowed(fresh=True)
            if not ok2:
                raise netguard_mod.NetGuardBlocked(reason2)
        st, body, ra = _post(msgs, call_timeout)
        if st is not None and st >= 400:
            raise _error(st, body, ra)[1]
        return _openai_text(json.loads(body.decode("utf-8")))

    # 1.19.0 (audyt rdzenia): Groq nie sprawdzał finish_reason - ucięta
    # odpowiedź szła do użytkownika urwana w pół zdania.
    return _continue_once(text, truncated, messages, timeout, _more)


def _groq_chat(system_prompt: str, messages: list[dict], timeout: float) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("brak GROQ_API_KEY")
    return _groq_http2_chat(api_key, system_prompt, messages, timeout)


def _openrouter_chat(system_prompt: str, messages: list[dict], timeout: float) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("brak OPENROUTER_API_KEY")
    return _openai_compatible_chat(_OPENROUTER_URL, api_key, _MODEL["openrouter"], system_prompt, messages, timeout)


def _huggingface_chat(system_prompt: str, messages: list[dict], timeout: float) -> str:
    """Router Hugging Face (router.huggingface.co) jest zgodny z API OpenAI
    tak samo jak Groq/OpenRouter - ten sam _openai_compatible_chat, więc
    dostaje za darmo tę samą ochronę przed "tool_use_failed" (patrz wyżej).
    Klucz: token z huggingface.co/settings/tokens, w .env jako
    HUGGINGFACE_API_KEY (nie HF_TOKEN jak w oficjalnych przykładach HF - ta
    nazwa, kończąca się na "_KEY", jest automatycznie maskowana przez
    agent/sysop.py, patrz docstring tego pliku)."""
    api_key = os.environ.get("HUGGINGFACE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("brak HUGGINGFACE_API_KEY")
    return _openai_compatible_chat(_HUGGINGFACE_URL, api_key, _MODEL["huggingface"], system_prompt, messages, timeout)


def _cloudflare_chat(system_prompt: str, messages: list[dict], timeout: float) -> str:
    """Cloudflare Workers AI, endpoint zgodny z API OpenAI - jedyny
    dostawca wymagający DWÓCH zmiennych w .env (patrz _EXTRA_ENV wyżej):
    CLOUDFLARE_API_KEY (sekret, w nagłówku) ORAZ CLOUDFLARE_ACCOUNT_ID
    (identyfikator konta Cloudflare, NIE sekret - wchodzi wprost w ścieżkę
    URL, jak w panelu Cloudflare, stąd nazwa nie kończy się na "_KEY" i
    celowo nie jest maskowana). Oba: panel Cloudflare -> Workers & Pages ->
    Workers AI -> "Use REST API"."""
    api_key = os.environ.get("CLOUDFLARE_API_KEY", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not api_key:
        raise RuntimeError("brak CLOUDFLARE_API_KEY")
    if not account_id:
        raise RuntimeError("brak CLOUDFLARE_ACCOUNT_ID")
    url = f"https://api.cloudflare.com/client/v4/accounts/{urllib.parse.quote(account_id, safe='')}/ai/v1/chat/completions"
    return _openai_compatible_chat(url, api_key, _MODEL["cloudflare"], system_prompt, messages, timeout)


def _gemini_chat(system_prompt: str, messages: list[dict], timeout: float) -> str:
    """Kształt Gemini jest inny niż OpenAI: "contents" (role user/model,
    nie assistant), systemInstruction osobno, klucz w nagłówku
    x-goog-api-key (nie Bearer)."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("brak GEMINI_API_KEY")
    contents = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})
    # 1.17.1 (zgłoszenie Grzegorza, 2026-10-21: odpowiedź po poprawie Gemini
    # ucięta w pół słowa, 111 znaków po 39 s): modele Gemini 3.x "myślą" przed
    # odpowiedzią, a tokeny myślenia liczą się do maxOutputTokens - przy 900
    # myślenie zjadało budżet i widoczna odpowiedź była obcinana (finishReason
    # MAX_TOKENS). thinkingLevel "minimal" = 0 tokenów myślenia (dokumentacja
    # Gemini API, 2026-10): mały model odpowiada na gotowy szkic/pytanie, nie
    # potrzebuje tu rozumowania. Gdyby model nie znał tego pola (HTTP 400 z
    # "thinking" w treści), jedna ponowna próba bez niego z podwojonym budżetem.
    url = f"{_GEMINI_URL_BASE}/{_MODEL['gemini']}:generateContent"
    budget = _max_tokens(JUGGLER_MAX_TOKENS)
    attempts = (
        {"maxOutputTokens": budget, "thinkingConfig": {"thinkingLevel": "minimal"}},
        {"maxOutputTokens": max(budget * 2, _REASONING_FLOOR_TOKENS)},
    )
    chosen = {"config": attempts[0]}

    def _post(conts: list[dict], generation_config: dict, call_timeout: float) -> dict:
        payload = json.dumps({
            "contents": conts,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": generation_config,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        })
        with netguard_mod.urlopen(req, timeout=call_timeout, fresh=True, reuse_s=_guard_reuse()) as resp:
            # Audyt 1.32.1: czytanie treści też w limicie wywołania (nie stałe 60 s).
            return netguard_mod.read_json(resp, deadline=_read_deadline(call_timeout))

    data = None
    for i, generation_config in enumerate(attempts):
        try:
            data = _post(contents, generation_config, timeout)
            chosen["config"] = generation_config
            break
        except urllib.error.HTTPError as e:
            detail = _http_error_detail(e)
            if i == 0 and e.code == 400 and "thinking" in detail.lower():
                continue
            raise _provider_error(e, detail) from e
    text, truncated = _gemini_text(data)
    if not text:
        raise RuntimeError("pusta odpowiedź")

    def _more(msgs: list[dict], call_timeout: float) -> tuple[str, bool]:
        conts = [{"role": "model" if m.get("role") == "assistant" else "user", "parts": [{"text": m.get("content", "")}]}
                 for m in msgs]
        return _gemini_text(_post(conts, chosen["config"], call_timeout))

    # 1.19.0 (audyt rdzenia): MAX_TOKENS nie wyrzuca już całej odpowiedzi do
    # następnego dostawcy - jak u pozostałych: jedna próba dokończenia.
    return _continue_once(text, truncated, messages, timeout, _more)


def _gemini_text(data: dict) -> tuple[str, bool]:
    """(tekst, ucięty limitem) z odpowiedzi Gemini. Części thought=true to echo
    myślenia (tylko przy includeThoughts) - pomijane. "".join, nie "\n".join:
    Gemini potrafi podzielić JEDEN ciąg tekstu na kilka części w środku zdania."""
    candidates = (data or {}).get("candidates") or []
    first = candidates[0] if candidates else {}
    parts = (first.get("content") or {}).get("parts", []) or []
    text = "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought")).strip()
    return text, first.get("finishReason") == "MAX_TOKENS"


_CONTINUE_PROMPT = ("Twoja poprzednia odpowiedź została ucięta przez limit długości. Dokończ ją DOKŁADNIE od miejsca, "
                    "w którym się urwała (zacznij od następnego znaku, nie powtarzaj początku, bez wstępu).")


def _join_continuation(text: str, more: str) -> str:
    """Sklejenie uciętego tekstu z dokończeniem. Ucięcie bywa w pół słowa
    ("na pod" + "stawie"): gdy tekst kończy się literą, a dokończenie zaczyna
    małą literą, sklejamy bez spacji; w każdym innym razie jedna spacja, chyba
    że dokończenie samo zaczyna się od białego znaku."""
    if not more.strip():
        return text
    # Model zamiast kontynuować od znaku potrafi zacząć od początku urwanego
    # słowa albo zdania ("...najbardziej prawdopod" + "Najbardziej prawdopodobną
    # hipotezę..."; żywy przykład, 2026-10-21): szukamy najdłuższego zakończenia
    # tekstu (do 80 znaków, od granicy słowa), które - bez względu na wielkość
    # liter - jest początkiem dokończenia, i ten kawałek wycinamy z tekstu.
    tail = text[-80:]
    low_more = more.lstrip().lower()
    # 1.32.12 (audyt tura 16): model "dokończył" od początku (powtórzył całą odpowiedź) - bierzemy
    # dłuższą wersję zamiast sklejać dwie kopie.
    head60 = text.strip()[:60].lower()
    if len(head60) >= 20 and low_more.startswith(head60):
        return more.strip() if len(more.strip()) >= len(text.strip()) else text
    best = 0
    for i in range(len(tail)):
        if i > 0 and not tail[i - 1].isspace():
            continue  # tylko od granicy słowa
        frag = tail[i:].lower()
        if len(frag) >= 3 and low_more.startswith(frag):
            best = len(tail) - i
            break
    if best:
        head, rest = text[:-best].rstrip(), more.strip()
        if head and head[-1] not in ".!?:" and rest[:1].isupper() and not rest[:2].isupper():
            rest = rest[:1].lower() + rest[1:]  # środek zdania: bez wielkiej litery po sklejeniu
        return head + " " + rest
    if more[:1].isspace():
        return text.rstrip() + more.rstrip()
    if text and text[-1].isalpha() and more[:1].isalpha() and more[:1].islower():
        return text + more.rstrip()
    return text.rstrip() + " " + more.strip()


def _continued(messages: list[dict], partial: str) -> list[dict]:
    """Wiadomości do JEDNEJ próby dokończenia uciętej odpowiedzi (1.17.15):
    ucięty tekst jako tura asystenta + prośba o dokończenie. Jedna próba, nie
    pętla: druga połowa prawie zawsze mieści się w limicie, a bez końca
    dokańczana odpowiedź to już nie odpowiedź, tylko monolog."""
    return messages + [{"role": "assistant", "content": partial.rstrip()}, {"role": "user", "content": _CONTINUE_PROMPT}]  # 1.32.12: API odrzuca białe znaki na końcu


def _continue_once(text: str, truncated: bool, messages: list[dict], timeout: float, ask_more) -> str:
    """Wspólne "ucięte -> jedna próba dokończenia" dla wszystkich dostawców
    (1.19.0, audyt rdzenia: Groq tego nie robił, Gemini wyrzucał całą
    odpowiedź). `ask_more(messages, timeout) -> (tekst, ucięty)`. Dokończenie
    mieści się w czasie danym temu wywołaniu (chat() przycina go do budżetu
    łańcucha i wiadomości): gdy zostało mniej niż 5 s, oddajemy to, co jest.
    Błąd dokończenia nie psuje odpowiedzi - zostaje ucięta część."""
    if not truncated:
        return text
    left = _time_left()
    call_timeout = timeout if left is None else min(timeout, left)
    if call_timeout < 5.0:
        return text
    try:
        more, _ = ask_more(_continued(messages, text), call_timeout)
    except Exception:
        return text
    return _join_continuation(text, more or "")


def _anthropic_chat(system_prompt: str, messages: list[dict], timeout: float) -> str:
    """Jedno wywołanie Messages API Anthropic przez stdlib (bez SDK, jak cała
    reszta serwera) - przeniesione 1:1 z router._cloud_chat (1.17.0), bo Claude
    jest teraz zwykłym wkładem żonglera. Klucz idzie WYŁĄCZNIE w nagłówku,
    nigdy do logów ani śladu; `messages` są już zmaskowane (chat/research).
    Messages API wymaga naprzemiennych tur zaczynających się od użytkownika -
    tak składa je router._cloud_history, a chat() dokleja bieżące pytanie."""
    api_key = os.environ.get(_KEY_ENV["anthropic"], "").strip()
    system = _anthropic_system(system_prompt)

    def _call(msgs: list[dict], call_timeout: float) -> tuple[str, bool]:
        payload = json.dumps({
            "model": (getattr(_REQ, "model", None) or _MODEL["anthropic"]),  # 1.30.17: Namysł może zażądać mocniejszego
            "max_tokens": _max_tokens(_ANTHROPIC_MAX_TOKENS),
            "system": system,
            "messages": msgs,
        }).encode("utf-8")
        req = urllib.request.Request(_ANTHROPIC_URL, data=payload, headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })
        try:
            # netguard: do API Anthropic tylko przez Cloudflare WARP (agent/netguard.py)
            _t = min(call_timeout, _ANTHROPIC_TIMEOUT) if call_timeout else _ANTHROPIC_TIMEOUT
            with netguard_mod.urlopen(req, timeout=_t, fresh=True, reuse_s=_guard_reuse()) as resp:
                data = netguard_mod.read_json(resp, deadline=_read_deadline(_t))
        except urllib.error.HTTPError as e:
            raise _provider_error(e) from e
        _note_cache_usage(data.get("usage") or {})
        _note_spend(data.get("usage") or {})
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "".join(p for p in parts if p), str(data.get("stop_reason") or "") == "max_tokens"

    text, truncated = _call(messages, timeout)
    if not text.strip():
        raise RuntimeError("pusta odpowiedź")
    return _continue_once(text, truncated, messages, timeout, _call).strip()


# Pamięć podręczna promptu Claude (1.19.0, dokumentacja Anthropic "Prompt
# caching", sprawdzona 2026-10-21: bez nagłówka beta, cache_control
# {"type": "ephemeral"} na bloku kończącym stały prefiks, minimum 512 tokenów
# dla Haiku 5.5 - krótszy prompt po prostu nie trafia do pamięci, bez błędu).
# Największa część każdego zapytania do Claude to ten sam prompt.md z opisem
# narzędzi; zmienia się tylko blok „Teraz” na końcu (zegar, rozmowa). Stały
# początek idzie jako blok z cache_control, „Teraz” i wszystko po nim osobno:
# odczyt z pamięci kosztuje ok. 0,1 ceny wejścia i jest szybszy.
_CACHE_WHOLE_MIN_CHARS = 4000
CACHE_USAGE = {"zapis": 0, "odczyt": 0, "zapytania": 0}


def _teraz_marker() -> str:
    try:
        import awareness as awareness_mod  # leniwie: awareness importuje vault/tools
        return "\n\n" + awareness_mod.HEADER
    except Exception:
        return "\n\n## Teraz"


def _anthropic_system(system_prompt: str):
    """Pole "system" Messages API: lista bloków z cache_control albo zwykły tekst."""
    marker = _teraz_marker()
    cut = system_prompt.find(marker)
    if cut > 0:
        static, dynamic = system_prompt[:cut], system_prompt[cut:]
        return [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": dynamic}]
    if len(system_prompt) > _CACHE_WHOLE_MIN_CHARS:
        return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    return system_prompt


def _note_cache_usage(usage: dict) -> None:
    """Tylko do podglądu (status()): ile tokenów zapisano/odczytano z pamięci podręcznej."""
    try:
        with _LOCK:
            CACHE_USAGE["zapytania"] += 1
            CACHE_USAGE["zapis"] += int(usage.get("cache_creation_input_tokens") or 0)
            CACHE_USAGE["odczyt"] += int(usage.get("cache_read_input_tokens") or 0)
    except Exception:
        pass


_PROVIDER_FN = {
    "anthropic": _anthropic_chat,
    "groq": _groq_chat, "gemini": _gemini_chat, "openrouter": _openrouter_chat,
    "huggingface": _huggingface_chat, "cloudflare": _cloudflare_chat,
}


def _try_order(preferred_provider: str | None, etapy: list[str] | None) -> list[str]:
    """Kolejność prób dla chat(): etapami koryta (koryto.network_order() albo
    `etapy` zawężone przez wołającego), w obrębie etapu "darmowe" losowo, z
    `preferred_provider` ("lepkość" rozmowy, patrz chat()) na początku JEGO
    etapu - nigdy przed etapem wcześniejszym: ulubiony darmowy dostawca z
    poprzedniej tury nie może wyprzedzić Claude, skoro Claude jest w korycie
    pierwszy (inaczej "lepkość" cicho odwracałaby decyzję o głównym dostawcy)."""
    order: list[str] = []
    for etap in (etapy if etapy is not None else koryto_mod.network_order()):
        names = _etap_providers(etap)
        if etap == "darmowe":
            random.shuffle(names)
        if preferred_provider in names:
            names.remove(preferred_provider)
            names.insert(0, preferred_provider)
        order.extend(names)
    return order


def _mask_messages(messages: list[dict]) -> list[dict]:
    return [{"role": m.get("role", "user"), "content": trace_mod.mask(m.get("content", ""))} for m in messages]


def chat(system_prompt: str, messages: list[dict], message: str, timeout: float = 60.0,
         preferred_provider: str | None = None, exclude_provider: str | None = None,
         etapy: list[str] | None = None, max_tokens: int | None = None,
         model: str | None = None) -> tuple[str, str]:
    """Łańcuch: etapami koryta (1.17.0, agent/koryto.py - domyślnie Claude,
    potem darmowa pula), w obrębie darmowej puli w LOSOWEJ kolejności,
    losowanej od nowa przy każdym wywołaniu - pierwszy sukces wygrywa.
    `etapy` (router.py) zawęża jedno wywołanie do wskazanych etapów
    sieciowych, gdy router sam idzie korytem etap po etapie (żeby etap
    lokalny mógł stać MIĘDZY sieciowymi, np. KORYTO=anthropic,lokalnie,darmowe).
    Losowanie darmowych - zgłoszenie Grzegorza (2026-10-19, log /debug): przy
    ustalonej kolejności Groq (najwyższy dzienny limit, 1000 vs 100/50)
    odpowiadał niemal zawsze, więc Gemini/OpenRouter były praktycznie
    nieużywane - wprost wbrew powodowi istnienia tego modułu (patrz docstring
    pliku: "żaden pojedynczy dostawca nie widzi całego ruchu"). Losowanie
    kolejności prób (nie kolejności w _PRIORITY, która zostaje jako
    pula/kolejność wyświetlania) sprawia, że każdy skonfigurowany dostawca ma
    szansę być pierwszym, więc realnie rozkłada ruch między nimi, zamiast
    tylko teoretycznie.

    `preferred_provider` (2026-10-19, prośba Grzegorza: "lepkość" w ramach
    jednej rozmowy - router._last_juggler_provider) idzie na początek tej
    wylosowanej kolejności, GDY jest w ogóle skonfigurowany/dozwolony - w
    przeciwnym razie (nieznana nazwa, dostawca wyczerpał dzienny limit,
    brak klucza) po cichu nic nie robi i kolejność zostaje czysto losowa, jak
    dotąd. Najpierw próbujemy GO - jeśli zawiedzie (padł, limit wyczerpał się
    W TRAKCIE rozmowy), łańcuch spada dalej na resztę, też losową, dokładnie
    jak przy braku podpowiedzi: "lepkość" nigdy nie usztywnia łańcucha, tylko
    zmienia, kto jest próbowany PIERWSZY. Dotyczy tylko TEJ jednej rozmowy
    (sam parametr), więc rozkład ruchu między RÓŻNYMI rozmowami w czasie
    zostaje taki jak dotąd - bez tego każda kolejna wiadomość W TEJ SAMEJ
    rozmowie losowała nowego "rozmówcę", a mały, darmowy model dostawcy X nie
    widzi różnicy między swoją własną odpowiedzią z poprzedniej tury a
    odpowiedzią zupełnie innego dostawcy.

    `exclude_provider` (1.9.0, Namysł - agent/namysl.py): dostawca, którego
    NIE próbujemy jako pierwszego, gdy jest inny do wyboru - recenzent
    szkicu ma być INNYM modelem niż jego autor (dwa różne modele rzadziej
    popełniają ten sam błąd). Od 1.17.1: jeden inny zdrowy dostawca, potem
    autor, dopiero potem reszta (powód w kodzie niżej). Gdy to jedyny
    skonfigurowany dostawca, zostaje (lepsza recenzja tym samym modelem niż
    żadna).

    `max_tokens` (1.19.0): limit odpowiedzi dla TEGO wywołania zamiast
    JUGGLER_MAX_TOKENS / CLOUD_MAX_TOKENS - krok 1 routera i planer oczekują
    jednej linii; model, który zaczyna pisać prozę, kończy po kilkudziesięciu
    tokenach, a nie po 1600.

    WARP (1.19.0): sprawdzany RAZ, świeżo, na początku (_guard_check). Blokada
    = od razu NetGuardBlocked, bez pytania dostawców i bez psucia ich
    bezpieczników (przy padniętym WARP to nie wina dostawcy).

    `messages` to już oczyszczona historia (patrz
    router._cloud_history - ten sam kształt), `message` to bieżące pytanie.
    Zwraca (odpowiedź, nazwa_dostawcy). Gdy WSZYSCY zawiodą (brak kluczy,
    limit, błąd sieci/WARP, pusta odpowiedź), rzuca RuntimeError z krótkim
    podsumowaniem - router.py łapie go i idzie dalej (uczeń/model lokalny),
    tak jak dotąd przy błędzie chmury."""
    msgs = list(messages)
    if msgs and msgs[-1].get("role") == "user":
        msgs = msgs[:-1] + [{"role": "user", "content": msgs[-1]["content"] + "\n\n" + message}]
    else:
        msgs = msgs + [{"role": "user", "content": message}]
    msgs = _mask_messages(msgs)
    errors = []
    if etapy is None:
        etapy = samodopasowanie()
    order = _try_order(preferred_provider, etapy)
    if not any(_configured(n) for n in order):
        raise RuntimeError("żaden dostawca nie odpowiedział (brak skonfigurowanych kluczy albo wszystkie limity wyczerpane)")
    _guard_check()
    # Bezpiecznik: dostawcy w cooldownie idą na koniec (próbowani tylko gdy
    # zdrowi zawiedli), wyłączeni (zły klucz) wcale. Gdy wszyscy skonfigurowani
    # są w cooldownie, zostaje kolejność "najdawniej padł pierwszy".
    # 1.32.12 (audyt tura 16): dostawca pominięty przez budżet albo limit dzienny ma to w błędach
    # (dotąd użytkownik widział tylko "brak kluczy albo limity", choć powód był znany).
    for n in order:
        if _configured(n) and not _allowed(n):
            errors.append(f"{n}:pominięty, " + (over_budget(n) or "limit dzienny wyczerpany"))
    healthy = [n for n in order if _allowed(n) and not _breaker_open(n)]
    cooled = sorted((n for n in order if _allowed(n) and breaker_state(n)["stan"] == "cooldown"),
                    key=lambda n: _breaker(n)["ostatnia_porazka"])
    # Audyt 1.32.1: przerwy wyznaczonej przez serwer (Retry-After, 403) nie łamiemy przy
    # każdej wiadomości. Taki dostawca wchodzi tylko wtedy, gdy nie ma nikogo innego -
    # i wtedy jeden, ten, któremu przerwa kończy się najwcześniej.
    soft = [n for n in cooled if not _breaker(n).get("twardy")]
    hard = sorted((n for n in cooled if _breaker(n).get("twardy")), key=lambda n: _breaker(n)["cooldown_do"])
    order = healthy + soft + ([] if (healthy or soft) else hard[:1])
    if exclude_provider and exclude_provider in order and len(order) > 1:
        # 1.17.1 (zgłoszenie Grzegorza, 2026-10-21, noc: "próbuje dostawców i
        # każdy zawodzi"): do 1.17.0 wykluczony autor szkicu szedł NA KONIEC
        # kolejki, więc recenzent Namysłu przy Claude jako autorze przechodził
        # przez CAŁĄ darmową pulę (każdy padający dostawca = do 60 s), zanim
        # wrócił do Claude. "Inny model niż autor" to zaleta, nie wymóg:
        # próbujemy JEDNEGO innego zdrowego dostawcy, potem wracamy do autora,
        # reszta dopiero gdyby oba zawiodły.
        others = [n for n in order if n != exclude_provider]
        # 1.32.12 (audyt tura 16): "inny" recenzent tylko z TEGO SAMEGO etapu co autor - inaczej
        # przy darmowej puli w cooldownie recenzentem zostawał płatny Claude.
        same_stage = [n for n in others if _ETAP.get(n) == _ETAP.get(exclude_provider)]
        # Autor płatny (Claude): recenzent z darmowej puli jest tańszy, więc wolno; autor darmowy:
        # tylko inny darmowy, nigdy awans na płatnego.
        first = same_stage[:1] if same_stage or _ETAP.get(exclude_provider) != _PLATNY_ETAP else others[:1]
        rest = [n for n in others if n not in first]
        order = first + [exclude_provider] + rest
    # Łączny budżet czasu jednego łańcucha (KORYTO_BUDZET_S, domyślnie 120 s):
    # koryto ma oddać lokalnemu modelowi po dwóch minutach, nie po sumie
    # limitów wszystkich dostawców (5 x 60 s). Każdy kolejny dostawca dostaje
    # tylko to, co z budżetu zostało; poniżej 5 s nie ma sensu próbować.
    started = time.monotonic()
    scope = _scope()
    for name in order:
        # 1.32.2 (audyt tura 7): Stop z przeglądarki przerywa łańcuch między dostawcami
        # (dawniej anulowane zadanie trzymało kolejkę rozmów do końca budżetu, do 210 s).
        if _stopped():
            errors.append(f"{name}:pominięty, zatrzymane przez użytkownika")
            break
        remaining = _CHAIN_BUDGET_S - (time.monotonic() - started)
        if remaining < 5.0:
            errors.append(f"{name}:pominięty, budżet czasu łańcucha ({_CHAIN_BUDGET_S:.0f} s) wyczerpany")
            continue
        if scope is not None:
            dead_reason = _scope_dead(scope, name)
            if dead_reason:
                errors.append(f"{name}:pominięty, zawiódł już {_DEAD_AFTER_FAILURES} razy w tej wiadomości: {dead_reason}")
                continue
            left = _scope_left(scope)
            if left < 5.0:
                errors.append(f"{name}:pominięty, budżet czasu sieci tej wiadomości ({scope['budget']:.0f} s) wyczerpany")
                continue
            remaining = min(remaining, left)
        timeout = min(timeout, remaining)
        call_started = time.monotonic()
        try:
            try:
                with _call_flags(max_tokens, timeout, model):
                    text = _PROVIDER_FN[name](system_prompt, msgs, timeout)
                # 1.32.6 (przegląd): każdy dostawca, nie tylko kształt OpenAI (Groq hostuje llama-guard)
                if isinstance(text, str) and _GUARD_REPLY_RE.match(text):
                    raise RuntimeError("model-klasyfikator bezpieczeństwa zamiast rozmowy")
            finally:
                _scope_spend(scope, time.monotonic() - call_started)
        except netguard_mod.NetGuardBlocked as e:
            # WARP padł w trakcie łańcucha: kolejni dostawcy zawiedliby tak samo,
            # a to nie ich wina - bez note_failure i bez licznika porażek zakresu.
            errors.append(f"{name}:zablokowane przez netguard: {e}")
            break
        except Exception as e:
            decision = note_failure(name, e)
            wait = _retry_after_seconds(e)
            # Krótki Retry-After: lepiej odczekać kilka sekund u TEGO SAMEGO
            # dostawcy (zachowuje "lepkość" rozmowy) niż tracić go na minutę.
            # 1.19.0: tylko gdy czekanie i ponowna próba (co najmniej 5 s) mieszczą
            # się w tym, co zostało z budżetu łańcucha i wiadomości; czekanie
            # liczy się do budżetu sieci wiadomości.
            room = _CHAIN_BUDGET_S - (time.monotonic() - started)
            if scope is not None:
                room = min(room, _scope_left(scope))
            if (getattr(e, "code", None) == 429 and wait is not None and wait <= RETRY_AFTER_INLINE_S
                    and wait + 5.0 <= room):
                retry_started = time.monotonic()
                if _stopped():
                    errors.append(f"{name}:zatrzymane przez użytkownika")
                    break
                time.sleep(wait)
                retry_timeout = min(timeout, room - wait)
                try:
                    try:
                        with _call_flags(max_tokens, retry_timeout, model):
                            text = _PROVIDER_FN[name](system_prompt, msgs, retry_timeout)
                    finally:
                        _scope_spend(scope, time.monotonic() - retry_started)
                    note_success(name)
                    _note_call(name)
                    return text, name
                except netguard_mod.NetGuardBlocked as e2:
                    errors.append(f"{name}:zablokowane przez netguard: {e2}")
                    break
                except Exception as e2:
                    decision = note_failure(name, e2)
                    e = e2
            # str(e), nie tylko type(e).__name__: dla błędu HTTP to już treść z
            # _http_error_detail (kod + co odesłał dostawca) - bez tego router.py
            # (juggler_error, 1.7.6/1.7.7) i tak nie miał nic konkretnego do pokazania.
            errors.append((f"{name}:{type(e).__name__}: {e}" if str(e) else f"{name}:{type(e).__name__}") + f" [{decision}]")
            _scope_failed(scope, name, e)
            continue
        note_success(name)
        _note_call(name)
        return text, name
    detail = "; ".join(errors) if errors else "brak skonfigurowanych kluczy albo wszystkie limity wyczerpane"
    raise RuntimeError(f"żaden dostawca nie odpowiedział ({detail})")


def research(message: str, timeout: float = 60.0, n: int = 2) -> list[tuple[str, str]]:
    """Równoległe, NIEZALEŻNE zapytanie badawcze do `n` różnych dostawców
    (patrz moduł: wzorzec "senior + juniorzy"): bez historii, bez osobowości
    GREGAI, zmaskowane (trace.mask). Zwraca listę (nazwa_dostawcy, tekst) -
    TYLKO dla tych, którzy odpowiedzieli; może być pusta, 1 albo n elementów.

    1.18.0 (audyt rdzenia): (a) juniorzy WYŁĄCZNIE z darmowej puli - od 1.17.0
    providers_pool() zawiera też Claude, więc każdy Namysł typu decyzja/analiza
    płacił Claude za "juniora"; Claude jest w tym wzorcu seniorem (router).
    (b) Odpalani są najwyżej n+1 dostawcy (jeden zapasowy na wypadek porażki),
    nie wszyscy naraz - mniej zużytych limitów dziennych. (c) Zwracamy wynik,
    gdy tylko uzbiera się n odpowiedzi: wcześniej `with ThreadPoolExecutor`
    czekał przy wyjściu na WSZYSTKICH, więc jeden wolny dostawca trzymał całość.
    Spóźnione odpowiedzi i tak są liczone do dziennego limitu (callback)."""
    scope = _scope()
    candidates = [name for name in providers_pool("darmowe") if _allowed(name) and not _breaker_open(name) and not _scope_dead(scope, name)]
    random.shuffle(candidates)
    candidates = candidates[:n + 1]
    left = _scope_left(scope)
    if not candidates or (left is not None and left < 5.0):
        return []
    wait_s = timeout + 5 if left is None else min(timeout + 5, left)
    timeout = min(timeout, wait_s)
    # 1.19.0: WARP raz, świeżo, przed odpaleniem juniorów; blokada = brak opinii
    # (Namysł idzie dalej bez nich), bez psucia bezpieczników dostawców.
    try:
        _guard_check()
    except netguard_mod.NetGuardBlocked:
        return []
    masked = trace_mod.mask(message)
    results: list[tuple[str, str]] = []
    pool = ThreadPoolExecutor(max_workers=len(candidates))

    def _late(fut, name):
        # Każde wywołanie, które doszło do skutku, liczy się do limitu - także to,
        # na które już nie czekamy.
        if fut.cancelled():
            return  # nie wystartował (anulowany przy wyjściu) - ani sukces, ani porażka
        try:
            if fut.result():
                _note_call(name)
                note_success(name)
        except netguard_mod.NetGuardBlocked:
            return  # WARP, nie dostawca
        except Exception as e:
            note_failure(name, e)
            _scope_failed(scope, name, e)

    def _run(name: str) -> str:
        # Wątek roboczy: flagi wywołania (okno świeżego sprawdzenia WARP) są per wątek.
        with _call_flags(None, timeout):
            return _PROVIDER_FN[name](_RESEARCH_SYSTEM_PROMPT, [{"role": "user", "content": masked}], timeout)

    futures = {}
    for name in candidates:
        fut = pool.submit(_run, name)
        futures[fut] = name
    wait_started = time.monotonic()
    try:
        for fut in as_completed(futures, timeout=wait_s):
            name = futures[fut]
            try:
                text = fut.result()
            except Exception:
                continue  # porażkę zapisze _late
            if text:
                results.append((name, text))
            if len(results) >= n:
                break
    except _FutureTimeout:
        pass  # bierzemy to, co już zdążyło odpowiedzieć
    finally:
        _scope_spend(scope, time.monotonic() - wait_started)
        for fut, name in futures.items():
            fut.add_done_callback(lambda f, _name=name: _late(f, _name))
        pool.shutdown(wait=False, cancel_futures=True)
    return results
