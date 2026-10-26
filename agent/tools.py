"""
tools.py

Narzędzia GREGAI (zestaw i opisy: capabilities.py). Każde zwraca dict {"speech": "...", "card": {...}}:
speech to krótka wypowiedź (1-2 zdania), card to uporządkowane szczegóły.

Zasada: narzędzia tylko CZYTAJĄ zindeksowane foldery (przez vault, już
wczytany). Zapisy: remember() -> memory/ (przez memory.py), network_status ->
data/network_inventory.json (przez siec.py; też tylko odczyt sieci, zero
zmian w jej konfiguracji) oraz wiki_lookup -> data/wiki_cache/ (strona z
Wikipedii jako notatka typu Wiki).
"""

from __future__ import annotations

import json
import os
import math
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

import data as data_mod
import fsutil
import memory as memory_mod
import netguard as netguard_mod
import siec as network_mod
import trace as trace_mod
import vault as vault_mod

# Jeden komplet nagłówków "jak prawdziwa przeglądarka" na WSZYSTKIE żądania
# HTTP tego pliku (research_web, wiki_lookup): bez tego gołe
# "User-Agent: Mozilla/5.0" wygląda jak bot, nie jak przeglądarka, i część
# serwisów (np. DuckDuckGo, patrz research_web niżej) po cichu zwraca
# stronę bez wyników. Wydzielone w jedno miejsce, żeby drugie narzędzie
# (wiki_lookup) nie powtarzało tego samego kompletu nagłówków od nowa.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    # Mniej danych na LTE; netguard.read_capped rozpakowuje z limitem po rozpakowaniu.
    "Accept-Encoding": "gzip",
}


# 1.32.0: API (Wikipedia, Open-Meteo) dostają UCZCIWY identyfikator klienta, zgodnie
# z zasadami Wikimedia (User-Agent policy): "przeglądarkowy" nagłówek wysłany z
# biblioteki skryptowej bywa tam ograniczany. Strony HTML (wyszukiwarki) zostają
# przy nagłówkach przeglądarki - tam goły identyfikator klienta dostaje pustą stronę.
_API_HEADERS = {
    "User-Agent": "GREGAI/1.32 (osobisty asystent AI na prywatnym komputerze; Python)",
    "Accept": "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept-Encoding": "gzip",
}

# Odpowiedzi z internetu czytamy z górnym limitem rozmiaru: strona wyników czy
# artykuł mają kilkaset KB, nic poza tym nie ma po co trafiać do pamięci.
_MAX_WEB_BYTES = 2 * 1024 * 1024
# Zapytanie wychodzące do internetu jest krótkie i bez sekretów z .env: wiadomość
# wklejona w całości (log, notatka) nie może w całości wyjść do wyszukiwarki ani
# trafić do kolejki ponowień.
MAX_QUERY_CHARS = 200


def _outbound_text(text: str) -> str:
    """Tekst, który wyjdzie w internet: bez sekretów z .env i bez sekretów wpisanych
    w rozmowie (hasła, PIN-y, klucze: te same wzorce, co w śladzie), jedna linia, krótko."""
    return " ".join(trace_mod.mask(text or "", outbound=True).split())[:MAX_QUERY_CHARS].rstrip()

# Ścieżki, które nie czekały na model (ręczny albo wyuczony wzorzec, dopytanie
# rozwiązane mechanicznie, korekta): wspólne dla wniosków i samooceny.
_MECHANICAL_STAGES = frozenset({
    "szybka_sciezka", "wyuczona_sciezka", "doprecyzowanie_rozwiazane", "korekta_wyuczonego",
})


def _polish_form(n: int, one: str, few: str, many: str) -> str:
    """Poprawna polska odmiana liczebnika: `one` dla 1, `few` dla 2-4
    (poza 12-14), `many` dla 5+ i 12-14. Zwraca samo słowo (bez liczby
    z przodu), np. _polish_form(3, "alert", "alerty", "alertów") ->
    "alerty"; wołający sam dopisuje f"{n} {...}". Jedno miejsce na tę
    zasadę, żeby każda nowa fraza liczbowa (urządzenia, alerty, co
    kolejne) nie powtarzała tej samej odmiany od nowa."""
    if n == 1:
        return one
    last_two = n % 100
    last = n % 10
    if last_two not in (12, 13, 14) and last in (2, 3, 4):
        return few
    return many


def _count_urzadzenia(n: int) -> str:
    """Poprawna polska odmiana liczebnika z 'urządzenie' (1/2-4/5+).
    Drobna rzecz, ale odpowiedzi czatu mają brzmieć naturalnie, nie
    jak wygenerowany raport."""
    return f"{n} {_polish_form(n, 'urządzenie', 'urządzenia', 'urządzeń')}"


def _count_alerty_siecowe(n: int) -> str:
    """Poprawna polska odmiana '<n> nowy/nowe/nowych alert/alerty/
    alertów sieciowy/sieciowe/sieciowych' (przymiotnik + rzeczownik +
    przymiotnik, każdy osobno odmieniony przez _polish_form wyżej).
    Powód, dla którego to istnieje: brief_me() zawsze zwracał sztywne
    "nowych alertów sieciowych" (dopełniacz liczby mnogiej), co dla
    1-4 alertów brzmi po polsku źle (np. "3 nowych alertów sieciowych"
    zamiast "3 nowe alerty sieciowe")."""
    nowy = _polish_form(n, "nowy", "nowe", "nowych")
    alert = _polish_form(n, "alert", "alerty", "alertów")
    sieciowy = _polish_form(n, "sieciowy", "sieciowe", "sieciowych")
    return f"{n} {nowy} {alert} {sieciowy}"


def _count_komend(n: int) -> str:
    """'<n> nową komendę/nowe komendy/nowych komend', ta sama zasada co
    _count_urzadzenia wyżej, dla self_status (patrz niżej)."""
    return f"{n} {_polish_form(n, 'nową komendę', 'nowe komendy', 'nowych komend')}"


def _count_slow_tematow(n: int) -> str:
    return f"{n} {_polish_form(n, 'nowe słowo', 'nowe słowa', 'nowych słów')}"


def _count_tematow_wiki(n: int) -> str:
    return f"{n} {_polish_form(n, 'temat', 'tematy', 'tematów')}"


def _count_tematow_do_sprawdzenia(n: int) -> str:
    return f"{n} {_polish_form(n, 'temat', 'tematy', 'tematów')} do sprawdzenia"


def _draw_conclusions(log: list) -> list:
    """Prawdziwe, POLICZONE wnioski z historii decyzji (agent/trace.py),
    nigdy zmyślone: zapamiętywanie nowych wzorców i zapominanie błędnych
    to mechanika, ale najważniejsze jest to, co z tej mechaniki WYNIKA.
    Każdy wniosek tutaj to statystyka na realnych wpisach z
    decision_log.json, nigdy liczba z powietrza (patrz prompt.md:
    "Nigdy nie zmyślaj liczb, dat... Rozdzielaj wyraźnie fakty,
    założenia, prognozy i rekomendacje"). Jeśli materiału jest za mało
    na sensowne porównanie, dany wniosek po prostu się nie pojawia,
    zamiast zgadywać na podstawie kilku wpisów.

    `log` to trace_mod.recent(...): NAJNOWSZY wpis pierwszy."""
    conclusions = []
    mechanical_stages = _MECHANICAL_STAGES

    # Trend: czy druga połowa historii (nowsza) jest SAMODZIELNIEJSZA
    # (mniej Ollamy) niż pierwsza (starsza). Jedyny sposób, by na "czy
    # GREGAI faktycznie się rozwija?" odpowiedzieć liczbą, nie wrażeniem:
    # dwa okna czasu, dwa realne odsetki, porównane. `log` jest
    # najnowszy-pierwszy, więc "starsza połowa" to DRUGA połowa listy.
    if len(log) >= 20:
        half = len(log) // 2
        newer, older = log[:half], log[half:]
        newer_pct = round(100 * sum(1 for e in newer if e.get("stage") in mechanical_stages) / len(newer))
        older_pct = round(100 * sum(1 for e in older if e.get("stage") in mechanical_stages) / len(older))
        if newer_pct > older_pct + 5:
            conclusions.append(
                f"Wniosek: ostatnio radzę sobie bez modelu częściej niż wcześniej "
                f"({older_pct}% -> {newer_pct}%)."
            )
        elif older_pct > newer_pct + 5:
            conclusions.append(
                f"Wniosek: ostatnio częściej potrzebuję modelu niż wcześniej "
                f"({older_pct}% -> {newer_pct}%), może trafiają się nowe tematy."
            )

    corrections = [e for e in log if e.get("stage") == "korekta_wyuczonego"]
    if corrections:
        by_tool: dict = {}
        for e in corrections:
            t = e.get("tool") or "?"
            by_tool[t] = by_tool.get(t, 0) + 1
        worst_tool, worst_count = max(by_tool.items(), key=lambda kv: kv[1])
        razy = _polish_form(len(corrections), "raz", "razy", "razy")
        conclusions.append(
            f"Wniosek: poprawiłeś mnie {len(corrections)} {razy}, "
            f"najczęściej przy „{worst_tool}” ({worst_count})."
        )

    if len(log) >= 10:
        errors = [e for e in log if e.get("stage") in ("ollama_blad", "ollama_niedostepna")]
        pct = round(100 * len(errors) / len(log))
        if pct >= 15:
            conclusions.append(
                f"Wniosek: model lokalny nie odpowiedział w {pct}% ostatnich "
                f"rozmów, to dużo, warto sprawdzić, czy Ollama działa stabilnie."
            )

    return conclusions


_PROVIDER_LABEL = {"anthropic": "Claude (Anthropic)", "groq": "Groq", "gemini": "Google Gemini",
                   "openrouter": "OpenRouter", "huggingface": "Hugging Face", "cloudflare": "Cloudflare Workers AI"}


def self_model(message: str = "") -> dict:
    """1.30.31 (zgłoszenie Grzegorza: „z jakiego modelu korzystasz?” -> „Jestem
    trenowany przez badaczy z NVIDIA”, a chwilę później „Jestem LFM od Liquid AI”):
    model z darmowej puli odpowiadał o SOBIE, nie o GREGAI. Ta odpowiedź jest
    składana w kodzie z prawdziwej konfiguracji (kolejność koryta, modele z .env,
    dostawcy z kluczem), więc zawsze mówi prawdę i za każdym razem to samo."""
    import juggler as juggler_mod
    import koryto as koryto_mod
    import persona as persona_mod
    lines = [f"Jestem GREGAI. Moim twórcą jest {persona_mod.CREATOR}.",
             "Nie jestem jednym modelem jednej firmy: jestem programem, który myśli przez „koryto” - po kolei "
             "próbuje kilku modeli i bierze pierwszą dobrą odpowiedź. Charakter, pamięć, notatki i zasady są moje, "
             "a model to tylko „wkład”, który akurat liczy."]
    order = []
    for etap in koryto_mod.order():
        if etap == "lokalnie":
            order.append(f"lokalnie na tym laptopie: {os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')} (Ollama)")
            continue
        names = juggler_mod.providers_pool(etap)
        if not names:
            continue
        opis = ", ".join(f"{_PROVIDER_LABEL.get(n, n)} ({juggler_mod._MODEL.get(n, '?')})" for n in names)
        order.append(("płatny etap: " if etap == "anthropic" else "darmowa pula: ") + opis)
    if order:
        lines.append("Kolejność teraz: " + "; ".join(order) + ".")
    lines.append("Jeśli kiedyś przedstawię się jako inny model (np. Llama, LFM, GPT), to pomyłka modelu z puli, "
                 "nie prawda o mnie.")
    return {"speech": "\n\n".join(lines), "card": None}


def self_status(vault) -> dict:
    """Samoocena: co GREGAI się do tej pory SAM nauczył, na obu
    warstwach samouczenia (patrz agent/learning.py: wzorce-wyzwalacze i
    słowa-tematy do dopytań), plus bank wiedzy z Wikipedii (patrz
    wiki_lookup wyżej), plus jaka część ostatnich rozmów nie potrzebowała
    już modelu wcale (patrz agent/trace.py). To jest narzędzie, przez
    które można bezpośrednio ZAPYTAĆ GREGAI o postęp jego własnego
    samouczenia się, zamiast patrzeć wyłącznie na stronę /debug: ten sam
    materiał, inna forma, do rozmowy."""
    import learning as learning_mod

    routes = learning_mod.all_routes()
    topic_words_map = learning_mod.all_learned_topic_words()
    topic_words_count = sum(len(v) for v in topic_words_map.values())
    wiki_notes = [n for n in vault.notes.values() if n.ntype == "Wiki"]
    journal_notes = [n for n in vault.notes.values() if n.ntype == "Journal"]
    pending_questions = pending_open_questions_count()

    # Cały dostępny ślad decyzji (trace.py trzyma maks. 300 wpisów), nie
    # tylko ostatnie kilka: wnioski niżej (_draw_conclusions) porównują
    # DWA okna czasu, więc potrzebują jak najdłuższej historii, jaka
    # jeszcze jest zapisana, żeby to porównanie miało sens.
    log = trace_mod.recent(300)
    # "Bez pomocy modelu" = każda ścieżka, która NIE czekała na Ollamę:
    # ręczny/wyuczony szybki wzorzec, dopytanie rozwiązane mechanicznie,
    # albo korekta (ta też jest czysto mechaniczna, patrz router.py).
    mechanical_stages = _MECHANICAL_STAGES
    total_recent = len(log)
    without_model = sum(1 for e in log if e.get("stage") in mechanical_stages)
    pct = round(100 * without_model / total_recent) if total_recent else None

    parts = []
    if routes:
        parts.append(f"Mam już {_count_komend(len(routes))} w pamięci.")
    if topic_words_count:
        parts.append(f"Do tego {_count_slow_tematow(topic_words_count)} do dopytań.")
    if wiki_notes:
        parts.append(f"Bank wiedzy z Wikipedii ma {_count_tematow_wiki(len(wiki_notes))}.")
    if pending_questions:
        parts.append(f"Mam jeszcze {_count_tematow_do_sprawdzenia(pending_questions)}, sprawdzę to sam, w tle.")
    if journal_notes:
        parts.append(f"Piszę sobie dziennik, mam już {len(journal_notes)} {_polish_form(len(journal_notes), 'wpis', 'wpisy', 'wpisów')}.")
    if pct is not None:
        parts.append(f"Z ostatnich {total_recent} decyzji, {pct}% obsłużyłem bez pomocy modelu.")
    if not parts:
        parts.append("Na razie niczego jeszcze się sam nie nauczyłem, wszystko idzie przez ręczne wzorce albo model.")

    # To jest ta część, o którą poproszono wprost: nie samo zapamiętywanie
    # i zapominanie (to mechanika wyżej), ale WYCIĄGANIE WNIOSKÓW z tego,
    # co się już wydarzyło (patrz _draw_conclusions: każdy z nich to
    # policzona statystyka na prawdziwych wpisach, nigdy zmyślona liczba).
    conclusions = _draw_conclusions(log)
    # 1.24.0: czy straż pilnuje i ile poszło z miesięcznego budżetu na Claude.
    try:
        import straz as straz_mod
        conclusions.append(straz_mod.summary_pl())
    except Exception:
        pass
    try:
        import juggler as juggler_mod
        sp = juggler_mod.spent_usd()
        if sp.get("limit_miesiac"):
            pl = lambda x: f"{float(x):.2f}".replace(".", ",")
            conclusions.append(f"Na Claude poszło w tym miesiącu około {pl(sp['miesiac'])} z {sp['limit_miesiac']:.0f} USD (dziś {pl(sp['dzien'])}).")
    except Exception:
        pass

    return {
        "speech": " ".join(parts + conclusions),
        "card": {
            "type": "self_status",
            "learned_routes": len(routes),
            "learned_topic_words": topic_words_count,
            "wiki_notes": len(wiki_notes),
            "journal_notes": len(journal_notes),
            "pending_open_questions": pending_questions,
            "recent_decisions": total_recent,
            "recent_without_model_pct": pct,
            "most_recent_route": routes[0] if routes else None,
            "conclusions": conclusions,
        },
    }


def search_brain(vault, query: str) -> dict:
    results = vault.search(query, limit=5)
    if not results:
        return {
            "speech": "Nic na ten temat nie mam w notatkach.",
            "card": {"type": "search_brain", "query": query, "results": []},
        }
    sources = [n.title for n in results]

    # Kontekst z GRAFU, nie tylko dopasowanie słów: notatki bezpośrednio
    # połączone z najlepszym wynikiem (patrz vault.py:related). To jest
    # różnica między "znalazłem słowa" a "rozumiem powiązania": sam
    # tekst nigdy nie powie, że ten Projekt ma przypisanego Klienta i
    # otwartą Fakturę, ale graf już to wie, bo to [[wikilinki]] między
    # notatkami. Wspominamy to w mowie TYLKO gdy faktycznie coś jest
    # połączone, nigdy jako wypełniacz dla notatek bez żadnych linków.
    top = results[0]
    related = vault.related(top.slug)
    related_titles = ", ".join(f"„{n.title}”" for n in related[:4])

    if len(sources) == 1:
        speech = f"Mam to w notatce „{sources[0]}”."
        if related:
            speech += f" Połączona jest z {related_titles}."
    else:
        speech = f"Znalazłem to w kilku notatkach: {', '.join(sources)}."
        if related:
            speech += f" „{top.title}” jest połączona z {related_titles}."

    card = {
        "type": "search_brain",
        "query": query,
        "results": [
            # 1.18.0: wycinek bez "# Tytuł" i "type: ..." - karta pokazywała
            # te dwie linie zamiast treści, a tytuł i tak stoi obok.
            # 1.19.0: wokół słów zapytania, nie początek notatki (vault.excerpt).
            {"title": n.title, "type": n.ntype, "source": n.slug,
             "excerpt": _mask(vault_mod.excerpt(n, query, 300))}
            for n in results
        ],
        "related": [{"title": n.title, "type": n.ntype, "source": n.slug} for n in related],
    }
    return {"speech": speech, "card": card}


# Odpowiedź z notatek (router.route()._answer_from_notes, 1.17.8): ile treści
# na notatkę i od jakiej długości najlepszej notatki dokładamy jej sąsiadów.
NOTES_CONTEXT_SHORT = 600
NOTES_CONTEXT_RELATED = 2


def notes_context(vault, results: list, limit_chars: int = 4000, query: str = "", max_results: int = 3) -> list[tuple[str, str]]:
    """Treść do odpowiedzi z notatek (1.18.0): (tytuł, tekst bez H1 i linii
    `type:`) dla najwyżej trzech znalezionych notatek, a gdy najlepsza jest
    krótka (< NOTES_CONTEXT_SHORT znaków), także jej najwyżej dwóch
    bezpośrednich sąsiadów z grafu (vault.related). Żywy powód: notatka
    "Grzegorz Żelazowski" odsyła do [[Uwierzytelnianie i sekrety]], a model
    odpowiadał "link prowadzi do innej notatki, której treści tu nie widzę".
    `results`: lista Note albo słowników z polem "source" (karta search_brain).
    Każdy tekst przycięty do `limit_chars`; bez duplikatów. 1.19.0: z `query`
    długa notatka daje wycinek wokół słów zapytania (vault.excerpt), nie
    początek; sąsiedzi z grafu i tak idą od początku (to kontekst, nie trafienie)."""
    notes = getattr(vault, "notes", {}) or {}
    picked: list = []
    for r in (results or [])[:max(1, max_results)]:
        note = notes.get(r.get("source")) if isinstance(r, dict) else r
        if note is not None and note not in picked:
            picked.append(note)
    direct = set(id(n) for n in picked)
    if picked:
        top_body = vault_mod.strip_title_and_type(picked[0].text)
        if len(top_body) < NOTES_CONTEXT_SHORT and hasattr(vault, "related"):
            # Najpierw notatki, do których najlepsza SAMA odsyła ([[link]] w jej
            # treści), potem te, które odsyłają do niej.
            own = picked[0].links
            neighbours = sorted(vault.related(picked[0].slug), key=lambda n: n.slug not in own)
            for rel in neighbours[:NOTES_CONTEXT_RELATED]:
                if rel not in picked:
                    picked.append(rel)
    return [(n.title, vault_mod.excerpt(n, query if id(n) in direct else "", limit_chars)) for n in picked]


# Wychwytywanie wyników DuckDuckGo odporne na zmiany wyglądu strony. DDG co
# jakiś czas zmienia i nazwy klas CSS, i sposób linkowania, i wtedy sztywny
# parser po cichu zwracał zero wyników przy działającym połączeniu - dokładnie
# to, co widział użytkownik ("nic sensownego nie znalazłem"). Dwa znane
# warianty, dziś naraz w użyciu:
#   - html.duckduckgo.com: link przez redirect "...?uddg=<adres>", klasa
#     result__a (w podwójnych cudzysłowach), fragment w result__snippet;
#   - lite.duckduckgo.com: link WPROST do adresu, klasa 'result-link' (w
#     POJEDYNCZYCH cudzysłowach), fragment w <td class='result-snippet'>.
# Dlatego czytamy KAŻDĄ kotwicę <a> i same rozstrzygamy, czy to wynik:
# po klasie (result-link/result__a), albo po redirect uddg. Reklamy (y.js,
# result--ad) i linki wewnętrzne DuckDuckGo odpadają. Cudzysłów klasy nieistotny.
_DDG_ANCHOR_RE = re.compile(r'<a\b([^>]*)>(.{0,2000}?)</a>', re.DOTALL | re.IGNORECASE)
_ATTR_HREF_RE = re.compile(r'''href\s*=\s*["']([^"']+)["']''', re.IGNORECASE)
_ATTR_CLASS_RE = re.compile(r'''class\s*=\s*["']([^"']*)["']''', re.IGNORECASE)
_DDG_UDDG_RE = re.compile(r'''[?&]uddg=([^&"']+)''')
# Fragmenty opisu: oba warianty, oba rodzaje cudzysłowów. Tytuł bez fragmentu
# to nadal dobry wynik, więc fragment jest opcjonalny.
_DDG_SNIPPET_RES = (
    re.compile(r'''class=["']result-snippet["'][^>]{0,200}>(.{0,3000}?)</td>''', re.DOTALL | re.IGNORECASE),
    re.compile(r'''class=["']result__snippet["'][^>]{0,200}>(.{0,3000}?)</a>''', re.DOTALL | re.IGNORECASE),
)
# Strona blokady/wyzwania: DDG tak bywa odpowiada na ruch z VPN/WARP.
_DDG_BLOCK_RE = re.compile(r"anomaly|unusual traffic|challenge-platform|captcha|if this error persists",
                           re.IGNORECASE)


def _mask(text: str) -> str:
    """Sekrety z .env (hasło routera, klucze) zamaskowane we wycinkach notatek (1.32.3)."""
    try:
        import sysop as _sysop
        return _sysop.mask_secrets(text)
    except Exception:
        return text


def pl_num(x, nd: int = 2) -> str:
    """Liczba po polsku: spacja między tysiącami, przecinek dziesiętny (67 123,45).
    Poniżej 1 więcej miejsc po przecinku, żeby kurs 0,000012 nie stał się „0,00”
    (audyt 1.32.1: mowa mówiła „67,123.45”, a karta „67 123,45”)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    if v != 0 and abs(v) < 1:
        nd = max(nd, min(12, 3 - math.floor(math.log10(abs(v)))))  # 4 cyfry znaczące
    txt = f"{v:,.{nd}f}"
    if nd > 2 and abs(v) < 1:
        head, _, dec = txt.partition(".")
        dec = dec.rstrip("0").ljust(2, "0")
        txt = f"{head}.{dec}"
    return txt.replace(",", " ").replace(".", ",")


def _strip_tags(s: str) -> str:
    # 1.32.11: komentarze HTML precz, znacznik = spacja (nie klejone "FoundNie znaleziono").
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)
    return re.sub(r"[ \t]{2,}", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _ddg_dest(href: str) -> str:
    """Prawdziwy adres docelowy z href wyniku: rozkodowany z redirectu uddg,
    albo wzięty wprost (wariant lite). Gołe "//host/..." dopełniamy do https."""
    um = _DDG_UDDG_RE.search(href)
    url = urllib.parse.unquote(um.group(1)) if um else href
    if url.startswith("//"):
        url = "https:" + url
    return url


def _parse_ddg(page: str) -> list:
    """Wyniki z surowej strony DDG (html albo lite), niezależnie od nazw klas
    i sposobu linkowania. Czytamy wszystkie kotwice, odsiewamy nie-wyniki."""
    items, seen = [], set()
    for m in _DDG_ANCHOR_RE.finditer(page):
        attrs, inner = m.group(1), m.group(2)
        hm = _ATTR_HREF_RE.search(attrs)
        if not hm:
            continue
        href = hm.group(1)
        cm = _ATTR_CLASS_RE.search(attrs)
        low_cls = (cm.group(1) if cm else "").lower()
        # kotwica fragmentu, reklama albo link wewnętrzny DDG - to nie wynik
        if "snippet" in low_cls or "result--ad" in low_cls or "result-sponsored" in low_cls:
            continue
        if "/y.js" in href:
            continue
        is_result = ("result-link" in low_cls) or ("result__a" in low_cls) or ("uddg=" in href)
        if not is_result:
            continue
        url = _ddg_dest(href)
        if not url.lower().startswith(("http://", "https://")):
            continue
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except ValueError:
            continue
        if not host or host.endswith("duckduckgo.com"):
            continue  # nawigacja wewnętrzna DuckDuckGo, nie wynik
        title = _strip_tags(inner)[:200]  # 1.32.11: tytuł z sieci ma limit jak w _clean_result
        if not title or url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "snippet": ""})
        if len(items) >= 5:
            break
    snippets = []
    for rx in _DDG_SNIPPET_RES:
        snippets = [_strip_tags(s) for s in rx.findall(page)]
        if snippets:
            break
    for i, it in enumerate(items):
        if i < len(snippets) and snippets[i]:
            it["snippet"] = snippets[i]
    return items


def _ddg_fetch(url: str, data: bytes | None = None) -> str:
    """Jeden strzał do DuckDuckGo przez netguard (WARP sprawdzony od nowa).
    Komplet nagłówków przeglądarki - z gołym User-Agentem DDG oddaje stronę
    bez wyników. Z `data` to POST (wariant lite).

    HTTP/2 (httpx) ma pierwszeństwo: DuckDuckGo odrzuca HTTP/1.1 z urllib jako
    ruch bota (202 + strona-wyzwanie „anomaly"), a przez HTTP/2 oddaje normalne
    wyniki (sprawdzone 2026-10-22 na żywym WARP). Bez pakietu h2 albo przy błędzie
    HTTP/2 spadamy na starą drogę urllib (HTTP/1.1)."""
    headers = dict(_BROWSER_HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    # 1) curl --http2: DuckDuckGo akceptuje odcisk curla, a odcisk httpx/urllib odrzuca
    #    (202 + strona-wyzwanie), mimo HTTP/2 i tego samego adresu WARP - sprawdzone na żywo.
    try:
        return netguard_mod.fetch_via_curl(url, data=data, headers=headers, timeout=12,
                                           fresh=True, max_bytes=_MAX_WEB_BYTES)
    except netguard_mod.NetGuardBlocked:
        raise  # WARP rozłączony - niech research_web powie o WARP
    except Exception:
        pass  # brak curla albo błąd - próba httpx niżej
    # 2) httpx HTTP/2 (gdyby nie było curla)
    try:
        return netguard_mod.fetch_http2(url, data=data, headers=headers, timeout=12,
                                        fresh=True, max_bytes=_MAX_WEB_BYTES, deadline=30.0)
    except netguard_mod.NetGuardBlocked:
        raise
    except Exception:
        pass  # brak h2 albo błąd HTTP/2 - ostatnia deska niżej
    # 3) urllib (HTTP/1.1) - ostatnia deska; DDG to zwykle odrzuca, ale dla innych serwisów działa
    req = urllib.request.Request(url, data=data, headers=headers)
    with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
        return netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=30.0).decode("utf-8", errors="ignore")


# --- Wiele wyszukiwarek (1.32.0) -------------------------------------------------
# Do 1.31 jedyną wyszukiwarką był DuckDuckGo, a on najczęściej odrzuca ruch z
# adresów WARP (współdzielone wyjście Cloudflare) stroną-wyzwaniem - wtedy GREGAI
# "nie miał internetu", choć internet działał. Teraz kolejno: DuckDuckGo (lite i
# html), Mojeek (niezależny indeks, bez JS), Bing, a na końcu wyszukiwarka
# Wikipedii (prawie nigdy nie blokuje; same hasła encyklopedyczne). Kolejność i
# zestaw: SZUKAJ_SILNIKI w .env. Silnik, który odrzucił ruch, odpoczywa
# _ENGINE_COOLDOWN_S; ten, który ostatnio odpowiedział, idzie pierwszy. To samo
# zapytanie (już zgodne z zasadą „wychodzi tylko krótki tekst bez sekretów”)
# może więc trafić do więcej niż jednego serwisu - dokładnie tak, jak gdybyś
# sam wpisał je po kolei w kilka wyszukiwarek.
_ENGINE_COOLDOWN_S = 600
_SEARCH_BUDGET_S = 32.0
_ENGINE_STATE: dict = {}
_ENGINE_LOCK = threading.Lock()
_ENGINE_LABEL = {"duckduckgo": "DuckDuckGo", "mojeek": "Mojeek", "bing": "Bing", "wikipedia": "Wikipedia"}
_DEFAULT_ENGINES = ("duckduckgo", "mojeek", "bing", "wikipedia")

_MOJEEK_TITLE_RE = re.compile(r"""<a\b([^>]*\bclass=["'][^"']*\btitle\b[^"']*["'][^>]*)>(.{0,600}?)</a>""", re.DOTALL | re.IGNORECASE)
_MOJEEK_SNIPPET_RE = re.compile(r"""<p\b[^>]*\bclass=["']s["'][^>]*>(.{0,2000}?)</p>""", re.DOTALL | re.IGNORECASE)
_BING_BLOCK_SPLIT_RE = re.compile(r"""<li\b[^>]*\bclass=["'][^"']*\bb_algo\b""", re.IGNORECASE)
_BING_LINK_RE = re.compile(r"""<h2\b[^>]*>\s*<a\b([^>]*)>(.{0,600}?)</a>""", re.DOTALL | re.IGNORECASE)
_BING_SNIPPET_RE = re.compile(r"""<p\b[^>]*>(.{0,2000}?)</p>""", re.DOTALL | re.IGNORECASE)
_GENERIC_BLOCK_RE = re.compile(r"b_captcha|captcha|unusual traffic|are you a robot|verify you are human|challenge-platform|"
                               r"access denied|too many requests", re.IGNORECASE)
# Powody, po których silnik odpoczywa (odrzucił ruch), a nie tylko nic nie znalazł.
_REFUSAL_RE = re.compile(r"wyzwanie|odrzucił|odmówił|HTTP 403|HTTP 429|HTTP 202", re.IGNORECASE)


def _engines() -> list[str]:
    raw = os.environ.get("SZUKAJ_SILNIKI", "").strip().lower()
    names = [n.strip() for n in raw.split(",") if n.strip() in _ENGINE_LABEL] if raw else list(_DEFAULT_ENGINES)
    names = list(dict.fromkeys(names)) or list(_DEFAULT_ENGINES)
    now = time.monotonic()
    with _ENGINE_LOCK:
        resting = [n for n in names if _ENGINE_STATE.get(n, {}).get("rest_until", 0) > now]
        ready = [n for n in names if n not in resting]

        def recent_ok(n: str) -> float:
            ok_at = _ENGINE_STATE.get(n, {}).get("ok_at", 0)
            return ok_at if ok_at and now - ok_at < 1800 else 0

        ready.sort(key=lambda n: -recent_ok(n))  # sort stabilny: reszta w kolejności z .env
    # Odpoczywające na końcu: gdy wszystko inne zawiedzie, i tak spróbujemy.
    return ready + resting


def _engine_mark(name: str, ok: bool) -> None:
    with _ENGINE_LOCK:
        st = _ENGINE_STATE.setdefault(name, {})
        if ok:
            st["ok_at"] = time.monotonic()
            st["rest_until"] = 0
        else:
            st["rest_until"] = time.monotonic() + _ENGINE_COOLDOWN_S


def engine_status() -> dict:
    """Stan silników wyszukiwania (Nadzorca, /diagnoza): kto ostatnio działał, kto odpoczywa."""
    now = time.monotonic()
    with _ENGINE_LOCK:
        return {n: {"ostatnio_ok_s_temu": int(now - st["ok_at"]) if st.get("ok_at") else None,
                    "odpoczywa_s": max(0, int(st.get("rest_until", 0) - now))}
                for n, st in _ENGINE_STATE.items()}


def _bing_dest(href: str) -> str:
    """Bing bywa, że linkuje przez przekierowanie /ck/a?...&u=a1<base64url adresu>."""
    href = unescape(href)
    if "bing.com/ck/a" in href:
        m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", href)
        if not m:
            return ""
        import base64
        b = m.group(1)
        try:
            return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "ignore")
        except (ValueError, UnicodeDecodeError):
            return ""
    return href


def _clean_result(url: str, title: str, snippet: str, own_host: str) -> dict | None:
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host or host == own_host or host.endswith("." + own_host):
        return None
    title = _strip_tags(title)
    if not title:
        return None
    return {"title": title[:200], "url": url[:500], "snippet": _strip_tags(snippet)[:400]}


def _parse_mojeek(page: str) -> list:
    items, seen = [], set()
    for m in _MOJEEK_TITLE_RE.finditer(page):
        hm = _ATTR_HREF_RE.search(m.group(1))
        if not hm:
            continue
        sm = _MOJEEK_SNIPPET_RE.search(page, m.end(), m.end() + 4000)
        it = _clean_result(unescape(hm.group(1)), m.group(2), sm.group(1) if sm else "", "mojeek.com")
        if it and it["url"] not in seen:
            seen.add(it["url"])
            items.append(it)
        if len(items) >= 5:
            break
    return items


def _parse_bing(page: str) -> list:
    items, seen = [], set()
    for block in _BING_BLOCK_SPLIT_RE.split(page)[1:]:
        block = block[:8000]
        lm = _BING_LINK_RE.search(block)
        if not lm:
            continue
        hm = _ATTR_HREF_RE.search(lm.group(1))
        if not hm:
            continue
        sm = _BING_SNIPPET_RE.search(block, lm.end())
        it = _clean_result(_bing_dest(hm.group(1)), lm.group(2), sm.group(1) if sm else "", "bing.com")
        if it and it["url"] not in seen:
            seen.add(it["url"])
            items.append(it)
        if len(items) >= 5:
            break
    return items


def _search_wikipedia(query: str) -> list:
    url = _WIKI_API + "?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                                      "srlimit": "5", "format": "json", "utf8": "1"})
    req = urllib.request.Request(url, headers=_API_HEADERS)
    with netguard_mod.urlopen(req, timeout=10, fresh=True) as resp:
        data = json.loads(netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=20.0).decode("utf-8", errors="ignore"))
    out = []
    hits = (data.get("query") or {}).get("search") or [] if isinstance(data, dict) else []
    for hit in hits[:5]:
        title = str(hit.get("title") or "")
        if not title:
            continue
        out.append({"title": title[:200], "url": _WIKI_PAGE_URL.format(title=urllib.parse.quote(title.replace(" ", "_"))),
                    "snippet": _strip_tags(str(hit.get("snippet") or ""))[:400]})
    return out


def _search_engine(name: str, query: str) -> tuple[list, str]:
    """(wyniki, powód porażki). Rzuca NetGuardBlocked (WARP) - to rozstrzyga za wszystkie silniki."""
    if name == "wikipedia":
        items = _search_wikipedia(query)
        return items, "" if items else "Wikipedia nie zwróciła wyników"
    if name == "duckduckgo":
        attempts = (("https://lite.duckduckgo.com/lite/", urllib.parse.urlencode({"q": query}).encode("utf-8")),
                    ("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}), None))
        why = ""
        for url, data in attempts:
            try:
                page = _ddg_fetch(url, data)
            except netguard_mod.NetGuardBlocked:
                raise
            except Exception as e:
                why = f"DuckDuckGo: {netguard_mod.explain_error(e)}"
                continue
            items = _parse_ddg(page)
            if items:
                return items, ""
            why = ("DuckDuckGo oddał stronę-wyzwanie (ochrona przed botami; częste dla adresów WARP)"
                   if _DDG_BLOCK_RE.search(page) else "DuckDuckGo nie zwrócił wyników")
        return [], why
    if name == "mojeek":
        page = _ddg_fetch("https://www.mojeek.com/search?" + urllib.parse.urlencode({"q": query}))
        items = _parse_mojeek(page)
        return items, "" if items else ("Mojeek odrzucił zapytanie" if _GENERIC_BLOCK_RE.search(page) else "Mojeek nie zwrócił wyników")
    if name == "bing":
        page = _ddg_fetch("https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "setlang": "pl", "cc": "PL"}))
        items = _parse_bing(page)
        return items, "" if items else ("Bing odrzucił zapytanie" if _GENERIC_BLOCK_RE.search(page) else "Bing nie zwrócił wyników")
    return [], "nieznany silnik"


def research_web(query: str) -> dict:
    """Wyszukiwanie bez kluczy i kosztów, tylko przez netguard (WARP), kolejnymi
    silnikami (patrz wyżej), aż któryś odda wyniki. Przy porażce mówi DLACZEGO,
    silnik po silniku - nie ogólnik."""
    query = _outbound_text(query)
    if not query:
        return {"ok": False, "speech": "Czego mam szukać w internecie?", "card": None}
    started = time.monotonic()
    reasons: list[str] = []
    tried: list[str] = []
    for name in _engines():
        if tried and time.monotonic() - started > _SEARCH_BUDGET_S:
            reasons.append("skończył się czas na wyszukiwanie")
            break
        tried.append(name)
        label = _ENGINE_LABEL[name]
        try:
            items, why = _search_engine(name, query)
        except netguard_mod.NetGuardBlocked as e:
            return _warp_blocked("research_web", query, str(e))
        except Exception as e:
            items, why = [], f"{label}: {netguard_mod.explain_error(e)}"
        if items:
            _engine_mark(name, True)
            return {"speech": f"W sieci znalazłem to: {items[0]['title']}.",
                    "card": {"type": "research_web", "query": query, "results": items,
                             "engine": label, "proby": [_ENGINE_LABEL[n] for n in tried]}}
        if _REFUSAL_RE.search(why or ""):
            _engine_mark(name, False)
        reasons.append(why if (why or "").startswith(label) else f"{label}: {why or 'brak wyników'}")
    refused = any(_REFUSAL_RE.search(r) for r in reasons)
    nothing = bool(reasons) and all(("nie zwrócił" in r or "nie zwróciła" in r) for r in reasons)
    if nothing:
        speech = ("Sprawdziłem w " + ", ".join(_ENGINE_LABEL[n] for n in tried)
                  + ", ale nic sensownego nie znalazłem. Spróbuj innymi słowami.")
    else:
        speech = ("Nie udało się wyszukać. " + "; ".join(reasons[:4]) + ". "
                  + ("Internet działa, ale wyszukiwarki odrzucają ruch z WARP - spróbuj za kilka minut. " if refused else "")
                  + "Pełny obraz połączenia: napisz /diagnoza.")
    return {"ok": False, "speech": speech,
            "card": {"type": "research_web", "query": query, "results": [],
                     "error": "SearchBlocked" if refused else ("NoResults" if nothing else "SearchFailed"),
                     "powody": reasons[:6], "proby": [_ENGINE_LABEL[n] for n in tried]}}


# Znaczniki, których treść to nie tekst strony (skrypty, style, nawigacja) -
# wycinamy je razem z zawartością, zanim zdejmiemy resztę tagów.
_PAGE_DROP_TAGS = ("script", "style", "noscript", "svg", "head", "nav", "footer", "form", "aside")
_PAGE_OPEN_RE = re.compile(r"(?i)<(script|style|noscript|svg|head|nav|footer|form|aside)\b")
_PAGE_CLOSE_RE = {t: re.compile(rf"(?i)</{t}\s*>") for t in _PAGE_DROP_TAGS}
_PAGE_BODY_RE = re.compile(r"(?i)<body\b")


def _drop_page_blocks(page: str) -> str:
    """Wycina bloki <script>...</script> itd. w czasie liniowym. Audyt 1.32.1: dawne
    wyrażenie `<(script|...)\\b.*?</\\1>` przy otwarciu bez zamknięcia przeszukiwało
    resztę strony od KAŻDEGO otwarcia - kwadratowo (2 MB strony = minuty CPU).
    Zamknięcie to dokładnie `</tag>` (nie `</header>` dla `<head>`). Znacznik bez
    zamknięcia: wycinamy tylko sam znacznik, tekst zostaje (jak dawniej), a dla tego
    znacznika już nie szukamy zamknięcia (stąd liniowo). `<head>` bez `</head>`
    (HTML5 pozwala) kończy się na `<body`."""
    out: list[str] = []
    pos = 0
    unclosed: set[str] = set()
    while True:
        m = _PAGE_OPEN_RE.search(page, pos)
        if not m:
            out.append(page[pos:])
            break
        out.append(page[pos:m.start()])
        out.append(" ")
        tag = m.group(1).lower()
        tag_end = page.find(">", m.end())
        if tag_end < 0:
            break  # urwany znacznik na końcu strony: reszta to nie tekst
        tag_end += 1
        close = None if tag in unclosed else _PAGE_CLOSE_RE[tag].search(page, tag_end)
        if close is None and tag == "head":
            close = _PAGE_BODY_RE.search(page, tag_end)
            if close is not None:
                pos = close.start()  # <body> zostaje do zwykłego zdejmowania tagów
                continue
        if close is None:
            unclosed.add(tag)
            pos = tag_end
            continue
        pos = close.end()
    return "".join(out)


def _page_title(page: str) -> str:
    low = page.lower()
    i = low.find("<title")
    if i < 0:
        return ""
    j = low.find(">", i)
    k = low.find("</title", j + 1) if j >= 0 else -1
    if j < 0 or k < 0:
        return ""
    return page[j + 1:k][:2000]
_PAGE_WS_RE = re.compile(r"[ \t\r\f\v]+")
_PAGE_NL_RE = re.compile(r"\n{3,}")
_MAX_PAGE_TEXT = 6000


def fetch_page_text(url: str, max_chars: int = _MAX_PAGE_TEXT) -> dict:
    """Czytelny TEKST całej strony (nie sam fragment z wyszukiwarki) - żeby
    GREGAI mógł oprzeć odpowiedź na treści, nie na tytule i jednym zdaniu.
    Tylko https, tylko przez netguard (WARP), tym samym curlem co wyszukiwarka
    (serwisy odrzucające odcisk urllib/httpx przepuszczają curl). Zdejmuje
    skrypty/style/nawigację i tagi, skleja białe znaki. Zwraca
    {"ok","url","title","text"} albo {"ok":False,"error"}.

    Nie zgaduje treści: przy błędzie sieci / pustej stronie oddaje ok=False,
    nigdy zmyślonego tekstu. Nie wywołuje modelu - czysty scraping."""
    url = (url or "").strip()
    if not url.lower().startswith("https://"):
        return {"ok": False, "url": url[:200], "error": "NieHttps"}
    if netguard_mod.local_target_reason(url):
        return {"ok": False, "url": url[:200], "error": "AdresLokalny"}
    headers = dict(_BROWSER_HEADERS)
    try:
        # 1.32.11 (audyt tura 15): status i przekierowania. Strona błędu (404, 500) to nie treść;
        # 301/302 śledzimy do 3 skoków, każdy cel przez tę samą bramkę (https, nie adres lokalny).
        page, meta = "", {}
        for _hop in range(4):
            _got = netguard_mod.fetch_via_curl(url, headers=headers, timeout=12, fresh=True,
                                               max_bytes=_MAX_WEB_BYTES, want_meta=True)
            page, meta = _got if isinstance(_got, tuple) else (_got, {})
            st = int(meta.get("status") or 0)
            if 300 <= st < 400 and meta.get("redirect_url"):
                nxt = meta["redirect_url"]
                if not nxt.lower().startswith("https://") or netguard_mod.local_target_reason(nxt):
                    return {"ok": False, "url": url[:200], "error": "PrzekierowanieZablokowane"}
                url = nxt
                continue
            break
        st = int(meta.get("status") or 0)
        if st >= 400:
            return {"ok": False, "url": url[:200], "error": f"HTTP {st}"}
        if 300 <= st < 400:
            return {"ok": False, "url": url[:200], "error": "ZaDuzoPrzekierowan"}
    except netguard_mod.NetGuardBlocked:
        raise
    except Exception:
        # brak curla albo błąd - próba httpx, potem urllib (jak _ddg_fetch)
        try:
            page = netguard_mod.fetch_http2(url, headers=headers, timeout=12, fresh=True,
                                            max_bytes=_MAX_WEB_BYTES, deadline=30.0)
        except netguard_mod.NetGuardBlocked:
            raise
        except Exception:
            try:
                req = urllib.request.Request(url, headers=headers)
                with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
                    page = netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=30.0).decode("utf-8", errors="ignore")
            except netguard_mod.NetGuardBlocked:
                raise
            except Exception as e:
                return {"ok": False, "url": url[:200], "error": type(e).__name__}
    title = _strip_tags(_page_title(page))[:200]
    body = _drop_page_blocks(page)
    text = _strip_tags(body)
    text = _PAGE_WS_RE.sub(" ", text)
    text = _PAGE_NL_RE.sub("\n\n", text).strip()
    if not text:
        return {"ok": False, "url": url[:200], "title": title, "error": "PustaTresc"}
    return {"ok": True, "url": url[:300], "title": title, "text": text[:max(500, int(max_chars))]}


# Symbol/ticker idzie w URL: tylko litery/cyfry/kropka/daszek/podkreślnik/myślnik,
# max 20 znaków (np. "aapl.us", "^spx", "btcusd"). Nic innego - zero miejsca na
# cokolwiek poza prawdziwym tickerem, zamiast zgadywać z pełnego zdania.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^_-]{1,20}$")
_MARKET_QUOTE_UNVERIFIED = (
    "Nie znam symbolu „{symbol}” - sprawdź dokładny ticker (np. aapl.us, ^spx, btcusd)."
)


# Kryptowaluty: Stooq przestał oddawać notowania (endpoint CSV zwraca "strona
# nie istnieje" dla KAŻDEGO symbolu - sprawdzone 2026-10-22 na żywym WARP, nawet
# aapl.us). Dla krypto idziemy więc do publicznego, bez-kluczowego Coinbase
# (spot), a gdyby nie odpowiadał - do CoinGecko. Oba https, oba przez netguard.
# Klucz mapy to i forma ze Stooq (btcusd), i goła nazwa (btc) - trafiamy z obu
# stron: symbols.detect() oddaje "btcusd", a wpisany wprost ticker bywa "btc".
_CRYPTO_PAIRS = {
    "btcusd": ("BTC", "USD"), "btc": ("BTC", "USD"),
    "ethusd": ("ETH", "USD"), "eth": ("ETH", "USD"),
    # 1.30.16: więcej głównych krypto (wszystkie są na Coinbase jako <BASE>-USD).
    "solusd": ("SOL", "USD"), "sol": ("SOL", "USD"),
    "bonkusd": ("BONK", "USD"), "bonk": ("BONK", "USD"),  # 1.32.13: pytanie o BONK szło do wyszukiwarki
    "xrpusd": ("XRP", "USD"), "xrp": ("XRP", "USD"),
    "adausd": ("ADA", "USD"), "ada": ("ADA", "USD"),
    "dogeusd": ("DOGE", "USD"), "doge": ("DOGE", "USD"),
    "dotusd": ("DOT", "USD"), "dot": ("DOT", "USD"),
    "ltcusd": ("LTC", "USD"), "ltc": ("LTC", "USD"),
    "linkusd": ("LINK", "USD"), "link": ("LINK", "USD"),
    "avaxusd": ("AVAX", "USD"), "avax": ("AVAX", "USD"),
}
_COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/{pair}/spot"
# Historia dzienna krypto - bez klucza, z hostów już sprawdzonych na WARP Grzegorza
# (Coinbase/CoinGecko działają, Yahoo na WARP dostaje "Edge: Too Many Requests").
# Coinbase candles: pełne OHLC, wiersze [czas, low, high, open, close, volume], od
# najnowszego. CoinGecko market_chart: tylko ceny (close), [[ms, cena], ...].
_COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{pair}/candles?granularity=86400"
_COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart?vs_currency={cur}&days={days}&interval=daily"
_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies={cur}"
_COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
    "ADA": "cardano", "DOGE": "dogecoin", "DOT": "polkadot", "LTC": "litecoin",
    "LINK": "chainlink", "AVAX": "avalanche-2",
}


def _crypto_quote(symbol_lower: str, base: str, cur: str) -> dict:
    """Notowanie kryptowaluty z Coinbase (spot), z CoinGecko jako zapasem.
    Zwraca kartę type market_quote (ten sam kształt co notowania z Yahoo),
    żeby interfejs i podpowiedzi „Co dalej?" działały bez zmian."""
    amount = None
    # 1) Coinbase: {"data":{"amount":"82685.51","base":"BTC","currency":"USD"}}
    try:
        url = _COINBASE_SPOT_URL.format(pair=urllib.parse.quote(f"{base}-{cur}", safe="-"))
        req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
        with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
            raw = netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=20.0).decode("utf-8", errors="ignore")
        amount = float(json.loads(raw)["data"]["amount"])
    except netguard_mod.NetGuardBlocked as e:
        return _warp_blocked("market_quote", symbol_lower, str(e))
    except Exception:
        amount = None
    # 2) Zapas: CoinGecko {"bitcoin":{"usd":82736}}
    if amount is None:
        gid = _COINGECKO_IDS.get(base)
        if gid:
            try:
                url = _COINGECKO_URL.format(id=gid, cur=cur.lower())
                req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
                with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
                    raw = netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=20.0).decode("utf-8", errors="ignore")
                amount = float(json.loads(raw)[gid][cur.lower()])
            except netguard_mod.NetGuardBlocked as e:
                return _warp_blocked("market_quote", symbol_lower, str(e))
            except Exception:
                amount = None
    if amount is None:
        return {
            "ok": False,
            "speech": "Nie udało się sprawdzić notowania, połączenie nie działa albo serwis nie odpowiada.",
            "card": {"type": "market_quote", "query": symbol_lower, "error": "CryptoSourceDown"},
        }
    speech = f"{base}/{cur}: {pl_num(amount)}"
    return {
        "speech": speech,
        "card": {"type": "market_quote", "query": symbol_lower,
                 "symbol": f"{base}{cur}", "source": "coinbase/coingecko",
                 "data": {"base": base, "currency": cur, "amount": amount}},
    }


# --- Yahoo Finance: darmowe, bez-kluczowe notowania I HISTORIA dla WSZYSTKICH
# klas aktywów (akcje, indeksy, waluty, surowce, krypto). Zastępuje martwy Stooq
# (CSV znikł 2026-10-22 - "strona nie istnieje" dla każdego symbolu, nawet
# aapl.us). Jeden endpoint `chart` oddaje i cenę bieżącą (meta.regularMarketPrice),
# i cały szereg dzienny (timestamp + OHLC) jednym zapytaniem, więc "ostatni
# miesiąc" nie wymaga osobnego źródła. Yahoo, jak DuckDuckGo, bada odcisk
# TLS/HTTP klienta i odrzuca urllib/httpx (202/403), a to samo z WARP przez
# systemowy curl przechodzi - dlatego idziemy przez netguard_mod.fetch_via_curl.
# Zero klucza, zero konta: sam publiczny endpoint, tak jak Coinbase. 1.30.20.
# Dwa hosty brzegowe Yahoo - gdy jeden odrzuca ruch z adresu WARP ("Edge: Too
# Many Requests", limit per-IP na współdzielonym wyjściu), próbujemy drugiego.
_YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
_YAHOO_CHART_URL = "https://{host}/v8/finance/chart/{sym}?range={rng}&interval={iv}"
# Potoczne / Stooq-owe skróty indeksów -> symbol Yahoo (^GSPC, ^IXIC, ...).
_YAHOO_INDEX = {
    "^spx": "^GSPC", "^gspc": "^GSPC", "spx": "^GSPC", "sp500": "^GSPC",
    "^ixic": "^IXIC", "nasdaq": "^IXIC", "^ndx": "^NDX",
    "^dji": "^DJI", "djia": "^DJI",
    "^dax": "^GDAXI", "dax": "^GDAXI",
    "^ftse": "^FTSE", "ftse": "^FTSE",
    "wig20": "WIG20.WA", "^wig20": "WIG20.WA",
}
# Surowce -> ciągły kontrakt terminowy Yahoo. "złoto"/"zloto" rozpoznaje też
# symbols.py (alias xauusd), więc tu łapiemy obie formy.
_YAHOO_COMMODITY = {
    "xauusd": "GC=F", "zloto": "GC=F", "złoto": "GC=F", "gold": "GC=F",
    "xagusd": "SI=F", "srebro": "SI=F", "silver": "SI=F",
    "wti": "CL=F", "ropa": "CL=F", "oil": "CL=F", "brent": "BZ=F",
}


# 1.32.5: zapas dla złota i srebra, gdy Yahoo nie odpowiada (brzeg Yahoo często odrzuca
# ruch z WARP: w rozmowie 25.10 srebro dwa razy "serwis nie odpowiada"). gold-api.com:
# darmowe, bez klucza, cena spot w USD za uncję trojańską: {"symbol":"XAG","price":..}.
_METAL_SPOT_URL = "https://api.gold-api.com/price/{sym}"
_METAL_SPOT = {"GC=F": "XAU", "SI=F": "XAG"}


def _metal_spot(yahoo_sym: str):
    """(cena, waluta, symbol) z gold-api.com albo None. Tylko przez netguard (WARP)."""
    sym = _METAL_SPOT.get(yahoo_sym)
    if not sym:
        return None
    req = urllib.request.Request(_METAL_SPOT_URL.format(sym=sym), headers=_BROWSER_HEADERS)
    with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
        raw = netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=20.0).decode("utf-8", errors="ignore")
    price = json.loads(raw).get("price")
    lo, hi = {"XAU": (300.0, 50000.0), "XAG": (3.0, 1000.0)}[sym]
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not (lo <= price <= hi):
        return None
    return price, "USD", sym + "USD (spot, uncja)"


class _YahooUnknown(Exception):
    """Yahoo zna endpoint, ale nie zna symbolu (chart.error 'Not Found')."""


def _yahoo_symbol(symbol_lower: str) -> str:
    """Nasz zapis symbolu (btcusd, aapl.us, ^spx, eurusd, złoto) -> symbol Yahoo.
    Nie zgaduje tickera z nazwy firmy (zbyt niejednoznaczne) - operuje tylko na
    jawnych tickerach i krótkiej, znanej liście skrótów (indeksy, surowce)."""
    s = (symbol_lower or "").strip().lower()
    pair = _CRYPTO_PAIRS.get(s)
    if pair:
        return f"{pair[0]}-{pair[1]}"            # btcusd / btc -> BTC-USD
    if s in _YAHOO_COMMODITY:
        return _YAHOO_COMMODITY[s]
    if s in _YAHOO_INDEX:
        return _YAHOO_INDEX[s]
    if s.startswith("^"):
        return s.upper()                          # ^GSPC, ^IXIC wprost
    if s.endswith(".us"):
        return s[:-3].upper()                     # aapl.us -> AAPL (NYSE/Nasdaq u Yahoo bez sufiksu)
    if re.fullmatch(r"[a-z]{6}", s):              # eurusd -> EURUSD=X (para walutowa)
        return s.upper() + "=X"
    return symbol_lower.strip().upper()           # AAPL, BTC-USD, cokolwiek jawnego


def _yahoo_fetch(yahoo_sym: str, rng: str, iv: str) -> dict:
    """Surowy wynik `chart.result[0]` z Yahoo albo wyjątek. Tylko przez curl
    (fetch_via_curl) - Yahoo odrzuca odcisk urllib/httpx jak DuckDuckGo.
    _YahooUnknown = nieznany symbol; ValueError = zepsuty kształt / brzeg Yahoo
    odrzucił ruch z WARP (np. "Edge: Too Many Requests" - to nie JSON);
    NetGuardBlocked (WARP) i FileNotFoundError (brak curl) propagują.
    Próbuje kolejnych hostów brzegowych, aż któryś odda sensowny JSON."""
    hdrs = {"User-Agent": _BROWSER_HEADERS.get("User-Agent", "Mozilla/5.0"), "Accept": "application/json"}
    sym_enc = urllib.parse.quote(yahoo_sym, safe="^=-.&")
    last_err = None
    for host in _YAHOO_HOSTS:
        url = _YAHOO_CHART_URL.format(host=host, sym=sym_enc, rng=rng, iv=iv)
        try:
            raw = netguard_mod.fetch_via_curl(url, headers=hdrs, timeout=12, fresh=True, max_bytes=_MAX_WEB_BYTES)
        except netguard_mod.NetGuardBlocked:
            raise
        except FileNotFoundError:
            raise
        except Exception as e:
            last_err = e
            continue
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError):
            # Brzeg Yahoo oddał stronę-blokadę ("Edge: Too Many Requests"), nie JSON.
            last_err = ValueError("Yahoo: nie-JSON (brzeg odrzucił ruch z WARP?)")
            continue
        chart = doc.get("chart") or {}
        if chart.get("error"):
            err = chart["error"] or {}
            code = (err.get("code") or "") if isinstance(err, dict) else str(err)
            if "Not Found" in str(code) or "No data" in str(err):
                raise _YahooUnknown(str(code or err)[:120])
            last_err = ValueError(f"Yahoo error: {str(err)[:120]}")
            continue
        results = chart.get("result") or []
        if not results or not isinstance(results[0], dict):
            raise _YahooUnknown("pusty wynik")
        return results[0]
    raise last_err or ValueError("Yahoo: brak odpowiedzi")


def _yahoo_spot(result: dict):
    """(cena, waluta, symbol) z meta wyniku Yahoo. Gdy meta nie ma ceny,
    bierze ostatnie niepuste domknięcie z szeregu. (None, ...) = brak."""
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        try:
            closes = [c for c in (result["indicators"]["quote"][0]["close"] or []) if c is not None]
            price = closes[-1] if closes else None
        except Exception:
            price = None
    if price is None:
        return None, None, None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None, None, None
    return price, (meta.get("currency") or "USD"), (meta.get("symbol") or "")


def _yahoo_series(result: dict) -> list:
    """Szereg dzienny [{t,o,h,l,c}] z wyniku Yahoo, z pominięciem luk (null close).
    Brakujące OHLC w danym dniu uzupełnia domknięciem tego dnia, nie zgaduje."""
    ts = result.get("timestamp") or []
    q = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    opens, highs, lows, closes = (q.get("open") or [], q.get("high") or [], q.get("low") or [], q.get("close") or [])
    out = []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        h = highs[i] if i < len(highs) and highs[i] is not None else c
        lo = lows[i] if i < len(lows) and lows[i] is not None else c
        out.append({"t": int(t), "o": float(o), "h": float(h), "l": float(lo), "c": float(c)})
    return out


_WARP_DOWN_SPEECH = ("Internet jest dla mnie teraz zablokowany, bo Cloudflare WARP jest rozłączony. "
                     "Połącz go w terminalu poleceniem: warp-cli connect.")  # zapas, gdy nie ma przyczyny


def _warp_blocked(card_type: str, query: str, reason: str = "") -> dict:
    """Jedna, wspólna odpowiedź "WARP rozłączony" dla wszystkich narzędzi
    sieciowych (1.30.25: scalone - ta sama treść była wklejona osobno w
    research_web, market_quote, _crypto_quote i market_history)."""
    card = {"type": card_type, "query": query, "error": "NetGuardBlocked"}
    if reason:
        card["reason"] = reason
    try:
        speech = netguard_mod.blocked_speech(reason)
    except Exception:
        speech = _WARP_DOWN_SPEECH
    return {"ok": False, "speech": speech, "card": card}


def market_quote(symbol: str) -> dict:
    """Jedno notowanie. Kryptowaluty (BTC, ETH, SOL...) z publicznego,
    bez-kluczowego Coinbase/CoinGecko; reszta (akcje, indeksy, FX, surowce) z
    Yahoo Finance (też bez klucza). Wszystko tylko przez netguard (WARP), jak
    research_web.

    Nie zgaduje: Yahoo na nieznany symbol oddaje `chart.error` ('Not Found'),
    co kończy się jasnym "nie znam symbolu", nigdy zmyśloną ceną. Brak ceny w
    poprawnej odpowiedzi też jest sygnalizowany wprost."""
    raw_symbol = (symbol or "").strip()
    clean_symbol = _outbound_text(raw_symbol)
    if not clean_symbol or not _SYMBOL_RE.match(clean_symbol):
        return {
            "ok": False,
            "speech": "Jakiego symbolu/tickera mam sprawdzić? (np. aapl.us, ^spx, btcusd)",
            "card": {"type": "market_quote", "query": raw_symbol[:MAX_QUERY_CHARS]},
        }
    symbol_lower = clean_symbol.lower()
    crypto = _CRYPTO_PAIRS.get(symbol_lower)
    if crypto:
        return _crypto_quote(symbol_lower, crypto[0], crypto[1])
    yahoo_sym = _yahoo_symbol(symbol_lower)
    _yahoo_err = "ValueError"
    try:
        result = _yahoo_fetch(yahoo_sym, "5d", "1d")
    except netguard_mod.NetGuardBlocked as e:
        return _warp_blocked("market_quote", symbol_lower, str(e))
    except _YahooUnknown:
        return {
            "ok": False,
            "speech": _MARKET_QUOTE_UNVERIFIED.format(symbol=symbol_lower),
            "card": {"type": "market_quote", "query": symbol_lower, "error": "UnknownSymbol"},
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "speech": "Nie udało się sprawdzić notowania - brakuje programu curl (powinien być po instalacji).",
            "card": {"type": "market_quote", "query": symbol_lower, "error": "CurlMissing"},
        }
    except Exception as e:
        result = None
        _yahoo_err = type(e).__name__
    if result is None:
        try:
            spot = _metal_spot(yahoo_sym)
        except netguard_mod.NetGuardBlocked as e:
            return _warp_blocked("market_quote", symbol_lower, str(e))
        except Exception:
            spot = None
        if not spot:
            return {
                "ok": False,
                "speech": "Nie udało się sprawdzić notowania, połączenie nie działa albo serwis nie odpowiada.",
                "card": {"type": "market_quote", "query": symbol_lower, "error": _yahoo_err},
            }
        price, cur, disp = spot
        return {
            "speech": f"{disp}: {pl_num(price)} {cur}",
            "card": {"type": "market_quote", "query": symbol_lower, "symbol": disp, "source": "gold-api.com",
                     "data": {"symbol": disp, "price": price, "currency": cur}},
        }
    price, cur, ysym = _yahoo_spot(result)
    if price is None:
        return {
            "ok": False,
            "speech": _MARKET_QUOTE_UNVERIFIED.format(symbol=symbol_lower),
            "card": {"type": "market_quote", "query": symbol_lower, "error": "UnknownSymbol"},
        }
    disp = ysym or yahoo_sym
    speech = f"{disp}: {pl_num(price)} {cur}".rstrip()
    return {
        "speech": speech,
        "card": {"type": "market_quote", "query": symbol_lower, "symbol": disp, "source": "yahoo",
                 "data": {"symbol": disp, "price": price, "currency": cur}},
    }


def _history_card(symbol_lower: str, disp: str, cur: str, series: list, source: str) -> dict:
    """Z gotowego szeregu [{t,o,h,l,c}] liczy otwarcie/zamknięcie/min/max/zmianę%
    i buduje wypowiedź + kartę market_history. Jedno miejsce dla krypto i Yahoo,
    żeby liczby i kształt karty były identyczne niezależnie od źródła."""
    first_c, last_c = series[0]["c"], series[-1]["c"]
    hi = max(p["h"] for p in series)
    lo = min(p["l"] for p in series)
    # WSZYSTKIE pochodne liczby liczymy TU, deterministycznie, i podajemy modelowi
    # gotowe - nie zostawiamy mu dzielenia w głowie (1.30.21: w 1.30.20 model
    # policzył "max 20% powyżej otwarcia" zamiast +1,3% i wysłał to pod tabelą,
    # choć sama tabela była spójna; opis ma cytować te pola, nie przeliczać ich).
    pct = lambda a, b: round((a - b) / b * 100.0, 2) if b else 0.0
    change = pct(last_c, first_c)                 # zamknięcie względem otwarcia
    max_vs_open = pct(hi, first_c)                # ile % maksimum nad otwarciem
    min_vs_open = pct(lo, first_c)                # ile % minimum pod otwarciem
    range_pct = round((hi - lo) / last_c * 100.0, 2) if last_c else 0.0  # rozpiętość / zamknięcie
    daily = [abs(series[i]["c"] - series[i - 1]["c"]) / series[i - 1]["c"] * 100.0
             for i in range(1, len(series)) if series[i - 1]["c"]]
    avg_daily = round(sum(daily) / len(daily), 2) if daily else 0.0
    cur = cur or ""
    speech = (f"{disp} przez ostatnie {len(series)} dni: otwarcie {pl_num(first_c)}, "
              f"zamknięcie {pl_num(last_c)} {cur}, min {pl_num(lo)}, max {pl_num(hi)}, "
              f"zmiana {'+' if change >= 0 else '-'}{pl_num(abs(change))}%.").replace(" ,", ",").replace("  ", " ")
    return {
        "speech": speech,
        "card": {"type": "market_history", "query": symbol_lower, "symbol": disp, "source": source,
                 "currency": cur,
                 "data": {"symbol": disp, "currency": cur, "days": len(series),
                          "first": first_c, "last": last_c, "min": lo, "max": hi,
                          "change_pct": change, "max_vs_open_pct": max_vs_open,
                          "min_vs_open_pct": min_vs_open, "range_pct": range_pct,
                          "avg_daily_abs_pct": avg_daily, "points": series}},
    }


def _crypto_history(symbol_lower: str, base: str, cur: str, days: int) -> list:
    """Dzienny szereg krypto za `days` dni, z hostów sprawdzonych na WARP:
    najpierw Coinbase candles (pełne OHLC), zapas CoinGecko market_chart (sama
    cena). Zwraca [{t,o,h,l,c}] od najstarszego, albo [] gdy nic nie wyszło.
    NetGuardBlocked (WARP) propaguje - wołający powie o WARP."""
    # 1) Coinbase Exchange candles: [[time, low, high, open, close, volume], ...], od najnowszego.
    try:
        pair = urllib.parse.quote(f"{base}-{cur}", safe="-")
        req = urllib.request.Request(_COINBASE_CANDLES_URL.format(pair=pair), headers=_BROWSER_HEADERS)
        with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
            raw = netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=20.0).decode("utf-8", errors="ignore")
        rows = json.loads(raw)
        pts = []
        for r in rows:
            if isinstance(r, list) and len(r) >= 5:
                t, lo, hi, op, cl = r[0], r[1], r[2], r[3], r[4]
                pts.append({"t": int(t), "o": float(op), "h": float(hi), "l": float(lo), "c": float(cl)})
        pts.sort(key=lambda p: p["t"])          # Coinbase daje od najnowszego - odwracamy
        if len(pts) >= 2:
            return pts[-days:]
    except netguard_mod.NetGuardBlocked:
        raise
    except Exception:
        pass
    # 2) CoinGecko market_chart: {"prices": [[ms, cena], ...]} - tylko close.
    gid = _COINGECKO_IDS.get(base)
    if gid:
        try:
            url = _COINGECKO_CHART_URL.format(id=gid, cur=cur.lower(), days=max(5, min(int(days), 180)))
            req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
            with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
                raw = netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=20.0).decode("utf-8", errors="ignore")
            prices = (json.loads(raw) or {}).get("prices") or []
            pts = []
            for p in prices:
                if isinstance(p, list) and len(p) >= 2 and p[1] is not None:
                    c = float(p[1])
                    pts.append({"t": int(p[0] // 1000), "o": c, "h": c, "l": c, "c": c})
            if len(pts) >= 2:
                return pts[-days:]
        except netguard_mod.NetGuardBlocked:
            raise
        except Exception:
            pass
    return []


def market_history(symbol: str, days: int = 31) -> dict:
    """Szereg dzienny instrumentu za ostatnie ~`days` dni. Krypto (BTC, SOL...)
    z Coinbase candles / CoinGecko (hosty sprawdzone na WARP); akcje, indeksy,
    FX i surowce z Yahoo Finance (na WARP bywa odrzucany przez brzeg Yahoo -
    wtedy jasny komunikat, nigdy zmyślony trend). Zwraca kartę `market_history`
    z punktami OHLC, ceną otwarcia i zamknięcia okna, minimum, maksimum i zmianą
    procentową - materiał dla Namysłu do analizy "ostatni miesiąc" i do wykresu.
    Bez klucza, przez WARP."""
    raw_symbol = (symbol or "").strip()
    clean_symbol = _outbound_text(raw_symbol)
    if not clean_symbol or not _SYMBOL_RE.match(clean_symbol):
        return {
            "ok": False,
            "speech": "Jakiego symbolu/tickera mam sprawdzić historię? (np. aapl.us, ^spx, btcusd)",
            "card": {"type": "market_history", "query": raw_symbol[:MAX_QUERY_CHARS]},
        }
    symbol_lower = clean_symbol.lower()
    try:
        days = max(5, min(int(days), 180))
    except (TypeError, ValueError):
        days = 31
    # Krypto: osobne, pewne źródło (Yahoo na WARP dostaje "Too Many Requests").
    crypto = _CRYPTO_PAIRS.get(symbol_lower)
    if crypto:
        base, cur = crypto
        try:
            series = _crypto_history(symbol_lower, base, cur, days)
        except netguard_mod.NetGuardBlocked as e:
            return _warp_blocked("market_history", symbol_lower, str(e))
        if len(series) < 2:
            return {
                "ok": False,
                "speech": f"Nie udało się pobrać historii {base}/{cur} (serwisy nie odpowiedziały).",
                "card": {"type": "market_history", "query": symbol_lower, "error": "CryptoHistoryDown"},
            }
        return _history_card(symbol_lower, f"{base}{cur}", cur, series, source="coinbase/coingecko")
    rng = "1mo" if days <= 35 else ("3mo" if days <= 95 else "6mo")
    yahoo_sym = _yahoo_symbol(symbol_lower)
    try:
        result = _yahoo_fetch(yahoo_sym, rng, "1d")
    except netguard_mod.NetGuardBlocked as e:
        return _warp_blocked("market_history", symbol_lower, str(e))
    except _YahooUnknown:
        return {
            "ok": False,
            "speech": _MARKET_QUOTE_UNVERIFIED.format(symbol=symbol_lower),
            "card": {"type": "market_history", "query": symbol_lower, "error": "UnknownSymbol"},
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "speech": "Nie udało się pobrać historii - brakuje programu curl (powinien być po instalacji).",
            "card": {"type": "market_history", "query": symbol_lower, "error": "CurlMissing"},
        }
    except Exception as e:
        out = {
            "ok": False,
            "speech": "Nie udało się pobrać historii, połączenie nie działa albo serwis nie odpowiada.",
            "card": {"type": "market_history", "query": symbol_lower, "error": type(e).__name__},
        }
        # 1.32.8: dla złota i srebra przynajmniej bieżąca cena z zapasowego źródła (bez historii).
        try:
            spot = _metal_spot(yahoo_sym)
        except Exception:
            spot = None
        if spot:
            price, cur, disp = spot
            out["speech"] += f" Bieżąca cena (gold-api.com): {disp}: {pl_num(price)} {cur}."
            out["card"]["spot"] = {"symbol": disp, "price": price, "currency": cur, "source": "gold-api.com"}
        return out
    series = _yahoo_series(result)
    if len(series) < 2:
        return {
            "ok": False,
            "speech": f"Za mało danych historycznych dla „{symbol_lower}”, by cokolwiek policzyć.",
            "card": {"type": "market_history", "query": symbol_lower, "error": "NoHistory"},
        }
    _, cur, ysym = _yahoo_spot(result)
    return _history_card(symbol_lower, ysym or yahoo_sym, cur or "", series[-days:], source="yahoo")


_WIKI_API = "https://pl.wikipedia.org/w/api.php"
_WIKI_SUMMARY_URL = "https://pl.wikipedia.org/api/rest_v1/page/summary/{title}"
_WIKI_PAGE_URL = "https://pl.wikipedia.org/wiki/{title}"


# Skróty, po których kropka nie kończy zdania (wstępy z Wikipedii: "(ur. 1798", "(ang. Long").
_ABBREV_RE = re.compile(r"(?:^|[\s(])(?:ur|zm|ang|łac|lac|niem|fr|ros|gr|np|tzw|tzn|prof|dr|hab|inż|mgr|św|ok|m\.in|al|ul|płn|płd|wsch|zach|[A-ZĄĆĘŁŃÓŚŹŻ])$")


def _first_sentence(text: str) -> str:
    """Pierwsze zdanie `text` (do krótkiej wypowiedzi), reszta
    i tak trafia do karty w całości. Gdy nie znajdzie końca zdania
    (brak . ! ?), zwraca cały tekst bez obcinania w pół słowa."""
    text = text.strip()
    for match in re.finditer(r"[.!?](?=\s|$)", text):
        head = text[:match.start()]
        if match.group(0) == "." and _ABBREV_RE.search(head):
            continue  # "Mickiewicz (ur." albo "LTE (ang." to nie koniec zdania
        return text[:match.end()].strip()
    return text


def _wiki_resolve_title(topic: str) -> tuple[str | None, str | None]:
    """Zamienia to, co powiedział użytkownik (częsty skrót, literówka,
    inny przypadek odmiany) na prawdziwy tytuł artykułu Wikipedii,
    przez endpoint `opensearch` (ten sam, z którego korzysta wyszukiwarka
    na samej Wikipedii). (tytuł, None) = znaleziono; (None, None) = nic nie
    znaleziono; (None, nazwa błędu) = serwis nie odpowiedział."""
    url = _WIKI_API + "?" + urllib.parse.urlencode({
        "action": "opensearch",
        "search": topic,
        "limit": "1",
        "namespace": "0",
        "format": "json",
    })
    req = urllib.request.Request(url, headers=_API_HEADERS)
    try:
        with netguard_mod.urlopen(req, timeout=8, fresh=True) as resp:  # WARP sprawdzony od nowa, tuż przed wyjściem
            data = json.loads(netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=30.0).decode("utf-8", errors="ignore"))
    except Exception as e:
        return None, netguard_mod.explain_error(e)
    titles = data[1] if isinstance(data, list) and len(data) > 1 else []
    title = titles[0] if isinstance(titles, list) and titles else None
    if not isinstance(title, str):
        return None, None
    # Tytuł w jednej linii i bez znaków wikilinku: odpowiedź serwisu trafia do nagłówka
    # notatki ("# tytuł"), więc nowa linia w niej dopisałaby własne "type:" albo [[linki]].
    title = " ".join(title.replace("[", "(").replace("]", ")").replace("|", "/").replace("#", "").split())[:200]
    return (title or None), None


_MAX_EXTRACT_CHARS = 20_000


def _wiki_fetch_summary(title: str) -> str | None:
    """Skrót artykułu (pierwszych kilka akapitów, bez tabel/przypisów)
    przez REST endpoint page/summary. None = artykuł bez treści albo
    serwis nie odpowiedział."""
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = _WIKI_SUMMARY_URL.format(title=encoded)
    req = urllib.request.Request(url, headers=_API_HEADERS)
    try:
        with netguard_mod.urlopen(req, timeout=8, fresh=True) as resp:  # WARP sprawdzony od nowa, tuż przed wyjściem
            data = json.loads(netguard_mod.read_capped(resp, _MAX_WEB_BYTES, deadline=30.0).decode("utf-8", errors="ignore"))
    except Exception:
        return None
    extract = data.get("extract") if isinstance(data, dict) else None
    if not isinstance(extract, str):
        return None
    # 1.32.11: strona ujednoznaczniająca ("Zamek może oznaczać:") to nie artykuł - nie do banku wiedzy.
    if isinstance(data, dict) and data.get("type") == "disambiguation":
        return None
    # Treść to dane, nie część grafu: "[[" w niej nie może tworzyć powiązań w notatkach.
    extract = extract.replace("[[", "[ [").replace("]]", "] ]").strip()[:_MAX_EXTRACT_CHARS]
    return extract or None


def _find_cached_wiki_note(vault, title: str):
    """Czy ten temat jest już w banku wiedzy (data/wiki_cache, jeden z
    korzeni vault, patrz data.py)? Ograniczone do notatek type: Wiki, bo
    samo dopasowanie tytułu mogłoby trafić we WŁASNĄ notatkę użytkownika
    o tej samej nazwie (to należy do search_brain, nie tego narzędzia)."""
    wanted = vault_mod.normalize_title(title)
    # 1.26.0 (audyt): typ "Wiki" może mieć też WŁASNA notatka (interfejs pozwala go
    # wybrać); taka treść jest prywatna, więc liczy się tylko plik z data/wiki_cache.
    import data as data_mod
    root = os.path.realpath(data_mod.WIKI_CACHE_ROOT) + os.sep
    for note in vault.notes.values():
        if note.ntype == "Wiki" and vault_mod.normalize_title(note.title) == wanted:
            try:
                if os.path.realpath(str(note.path)).startswith(root):
                    return note
            except Exception:
                continue
    return None


def _wiki_note_body(note) -> str:
    """Treść notatki bez linii `# Tytuł` i `type: Wiki` z nagłówka (ta sama
    funkcja co w interfejsie: vault.strip_title_and_type)."""
    return vault_mod.strip_title_and_type(note.text)


def _save_wiki_note(title: str, extract: str) -> None:
    """Zapisuje znalezisko jako prawdziwą notatkę markdown w
    data/wiki_cache (patrz data.WIKI_CACHE_ROOT), typu Wiki, żeby bank
    wiedzy od razu stał się częścią grafu: przeszukiwalny przez
    search_brain, widoczny w interfejsie, a następne pytanie o ten sam
    temat już nie potrzebuje internetu (patrz _find_cached_wiki_note
    wyżej). To jest cała "Wikipedia w systemie": nie zrzut całej
    Wikipedii (dziesiątki GB, poza możliwościami tego sprzętu), tylko
    bank, który rośnie temat po temacie, dokładnie wtedy, gdy jest
    potrzebny."""
    cache_root = Path(data_mod.WIKI_CACHE_ROOT)
    slug_base = vault_mod.slugify(title)
    source_url = _WIKI_PAGE_URL.format(title=urllib.parse.quote(title.replace(" ", "_")))
    content = (
        f"# {title}\n"
        f"type: Wiki\n\n"
        f"{extract.strip()}\n\n"
        f"Źródło: {source_url}\n"
    )
    # Wyłączne utworzenie: dwa różne tytuły o tym samym slugu (np. same znaki
    # spoza łaciny) nie mogą się nawzajem nadpisać.
    filename, counter = f"{slug_base}.md", 2
    wanted = vault_mod.normalize_title(title)
    while not fsutil.create_new_text(cache_root / filename, content, mode=0o644):
        # Plik o tej nazwie już jest. Jeśli to TEN SAM artykuł (czat i serce zapisały go
        # niemal równocześnie), nie dopisujemy drugiej kopii.
        try:
            with open(cache_root / filename, encoding="utf-8", errors="replace") as existing:
                first = existing.readline().strip()
        except OSError:
            first = ""
        if first.startswith("# ") and vault_mod.normalize_title(first[2:]) == wanted:
            return
        filename = f"{slug_base}-{counter}.md"
        counter += 1


_OPEN_QUESTIONS_PATH = Path(__file__).parent.parent / "data" / "open_questions.json"
_MAX_WIKI_ATTEMPTS = 3


def _load_open_questions() -> list[dict]:
    """Tematy z Wikipedii, które się nie udały (nie znaleziono artykułu
    ALBO nie udało się ściągnąć treści), do ponowienia PÓŹNIEJ, bez
    pytania, przez agent/heartbeat.py (patrz retry_open_questions
    niżej). To jest literalna różnica między "zapytałem raz i
    zapomniałem" a "wiem, że czegoś jeszcze nie ustaliłem, i spróbuję
    ponownie, gdy będzie okazja" - jedna z rzeczy, o którą poprosił
    użytkownik (pełna autonomia, samodzielne wnioski z własnych
    niepowodzeń, nie tylko z sukcesów)."""
    if not _OPEN_QUESTIONS_PATH.exists():
        return []
    try:
        raw = _OPEN_QUESTIONS_PATH.read_text(encoding="utf-8-sig")
    except OSError:
        return []  # chwilowy błąd odczytu to nie uszkodzony plik
    try:
        data = json.loads(raw)
    except ValueError:  # JSONDecodeError i UnicodeDecodeError
        # Uszkodzony plik odsuwamy, zamiast nadpisać go pierwszym nowym wpisem.
        fsutil.quarantine(_OPEN_QUESTIONS_PATH)
        return []
    if not isinstance(data, list):
        fsutil.quarantine(_OPEN_QUESTIONS_PATH)
        return []
    return [it for it in data if isinstance(it, dict) and isinstance(it.get("topic"), str)]


# Czat i serce (heartbeat) działają w osobnych wątkach i oba czytają, zmieniają i
# zapisują ten sam plik: bez blokady jeden nadpisałby zmianę drugiego.
_OPEN_QUESTIONS_LOCK = threading.RLock()


def _save_open_questions(items: list[dict]) -> None:
    # Kolejka ponowień to dodatek: pełny dysk albo plik tylko do odczytu nie może
    # zamienić zwykłej odpowiedzi o Wikipedii w błąd.
    try:
        fsutil.atomic_write_text(_OPEN_QUESTIONS_PATH, json.dumps(items, ensure_ascii=False, indent=2))
    except OSError as e:
        sys.stderr.write(f"UWAGA: nie zapisano kolejki ponowień: {type(e).__name__}: {e}\n")


def _queue_open_question(topic: str) -> None:
    """Dopisuje `topic` do kolejki, jeśli jeszcze go tam nie ma
    (dopasowanie bez rozróżniania wielkości liter: ten sam temat
    zapytany dwa razy w różnym zapisie to wciąż jeden wpis, nie dwa)."""
    key = topic.strip().lower()
    if not key:
        return
    with _OPEN_QUESTIONS_LOCK:
        items = _load_open_questions()
        if any(it["topic"].strip().lower() == key for it in items):
            return
        items.append({
            "topic": topic.strip(),
            "first_seen": datetime.now().isoformat(timespec="seconds"),
            "attempts": 0,
            "given_up": False,
        })
        _save_open_questions(items)


def _resolve_open_question(topic: str) -> None:
    """Usuwa `topic` z kolejki, jeśli akurat tam był (np. użytkownik sam
    trafił w poprawny zapis tematu, zanim agent/heartbeat.py zdążył go
    ponowić). Bezpieczne wołać dla KAŻDEGO udanego wiki_lookup, nawet
    jeśli ten temat nigdy nie był w kolejce - po prostu nic nie znajdzie
    i nic się nie zmieni."""
    key = topic.strip().lower()
    with _OPEN_QUESTIONS_LOCK:
        items = _load_open_questions()
        filtered = [it for it in items if it["topic"].strip().lower() != key]
        if len(filtered) != len(items):
            _save_open_questions(filtered)


def pending_open_questions_count() -> int:
    """Ile tematów CZEKA jeszcze na ponowienie (bez tych, z których
    GREGAI się już poddał po _MAX_WIKI_ATTEMPTS próbach) - używane przez
    self_status niżej, żeby zdać sprawę z tego, co jeszcze zostało do
    zrobienia, nie tylko z tego, co już się udało."""
    return sum(1 for it in _load_open_questions() if not it.get("given_up"))


def retry_open_questions(vault, limit: int = 2) -> dict:
    """Wołane cyklicznie przez agent/heartbeat.py, NIGDY w ramach
    odpowiedzi na wiadomość użytkownika: próbuje ponownie, po kolei, do
    `limit` tematów z kolejki, które jeszcze nie przekroczyły
    _MAX_WIKI_ATTEMPTS. Czasem to tylko chwilowy problem z siecią albo z
    rozpoznaniem tytułu (patrz _wiki_resolve_title), nie trwały brak
    artykułu, więc warto spróbować więcej niż raz, zanim się podda.
    Ograniczone do `limit` NA JEDNO TYKNIĘCIE serca: słaby sprzęt i
    jedno łącze nie powinny nagle odpytywać Wikipedii dziesiątek razy
    naraz, tylko po kawałku, w tle."""
    items = _load_open_questions()
    pending = [it for it in items if not it.get("given_up")][:limit]
    resolved = []
    invalidate = False
    for it in pending:
        topic = it["topic"]
        result = wiki_lookup(vault, topic)
        card = result.get("card") or {}
        if card.get("error") == "NetGuardBlocked":
            # WARP rozłączony to nie porażka tematu: nie zużywamy próby, bo po
            # 90 minutach bez WARP-a wszystkie tematy byłyby porzucone na stałe.
            continue
        if card.get("found"):
            # wiki_lookup powyżej już samo wywołało _resolve_open_question
            # dla tego dokładnego tematu przy sukcesie (patrz niżej),
            # na dysku ten wpis już nie istnieje, nic więcej do zrobienia.
            resolved.append(topic)
            if not card.get("cached"):
                invalidate = True
                # Nowa notatka w banku: `vault` z początku tej funkcji jej nie zna, więc kolejny
                # temat mógłby zapisać drugą notatkę o tym samym artykule ("USA" i "Stany
                # Zjednoczone"). Reszta kolejki dostaje świeży vault na następnym tyknięciu.
                break
            continue
        # Nieudane: wiki_lookup nie dotyka attempts/given_up (to nie jego
        # odpowiedzialność), więc odczytaj plik NA NOWO (nie `items` z
        # góry tej funkcji, bo wiki_lookup mógł w międzyczasie zmienić
        # plik przy INNYM temacie z tej samej partii) i zwiększ licznik
        # tylko temu jednemu wpisowi, zapisując od razu - jeśli serwer
        # padnie w połowie partii, postęp z już sprawdzonych tematów
        # i tak zostaje.
        with _OPEN_QUESTIONS_LOCK:
            current = _load_open_questions()
            for entry in current:
                if entry["topic"].strip().lower() == topic.strip().lower():
                    attempts = entry.get("attempts", 0)
                    entry["attempts"] = (attempts if isinstance(attempts, int) else 0) + 1
                    if entry["attempts"] >= _MAX_WIKI_ATTEMPTS:
                        entry["given_up"] = True
                    break
            _save_open_questions(current)
    return {"resolved": resolved, "invalidate_vault": invalidate}


def wiki_lookup(vault, topic: str) -> dict:
    """Bank wiedzy na żądanie: zamiast wgrywać całą Wikipedię (dziesiątki
    GB, bez realnego indeksu wyszukiwania nie do ogarnięcia na tym
    sprzęcie), ściąga JEDEN temat na raz z żywego API Wikipedii i
    zapisuje go jako prawdziwą notatkę w data/wiki_cache (patrz
    _save_wiki_note), więc bank rośnie temat po temacie, a drugie
    pytanie o ten sam temat już nie potrzebuje internetu (cache hit
    niżej) i jest przeszukiwalne przez search_brain/graph_overview za
    darmo, bo to już jest część tego samego grafu notatek."""
    topic = _outbound_text(topic)
    if not topic:
        return {"ok": False, "speech": "Jakiego tematu z Wikipedii mam sprawdzić?", "card": None}

    cached = _find_cached_wiki_note(vault, topic)
    if cached:
        extract = _wiki_note_body(cached)
        _resolve_open_question(topic)
        return {
            "speech": f"To już jest w banku wiedzy: {_first_sentence(extract)}",
            "card": {
                "type": "wiki_lookup", "query": topic, "title": cached.title,
                "extract": extract, "found": True, "cached": True,
            },
        }

    allowed, why = netguard_mod.internet_allowed()
    if not allowed:
        # WARP rozłączony: do sieci nie wychodzimy. Pytanie do kolejki -
        # heartbeat spróbuje sam, gdy WARP znów będzie połączony.
        _queue_open_question(topic)
        return {
            "ok": False,
            "speech": "Tego nie ma jeszcze w banku wiedzy, a internet jest dla mnie teraz zablokowany: "
                      + netguard_mod.blocked_speech(why),
            "card": {"type": "wiki_lookup", "query": topic, "found": False, "error": "NetGuardBlocked", "reason": why},
        }

    resolved_title, net_error = _wiki_resolve_title(topic)
    if resolved_title is None:
        # Zapisz do kolejki, agent/heartbeat.py spróbuje ponownie sam, bez pytania (patrz
        # retry_open_questions wyżej). Brak odpowiedzi serwisu to co innego niż brak artykułu.
        # 1.30.31: brak artykułu dla długiego zapytania (całe pytanie, nie hasło) nie
        # trafia do kolejki - ponawianie nic nie da, a w stanie wiedzy wisiało jako
        # „2 tematy do sprawdzenia”.
        if net_error or len(topic.split()) <= 4:
            _queue_open_question(topic)
        if net_error:
            return {
                "ok": False,
                "speech": f"Nie udało się połączyć z Wikipedią ({net_error}). Zapytanie o „{topic}” zostawiam sobie i sprawdzę sam, gdy połączenie wróci.",
                "card": {"type": "wiki_lookup", "query": topic, "found": False, "error": net_error},
            }
        return {
            "ok": False,
            "speech": f"Nie znalazłem na Wikipedii nic o „{topic}”.",
            "card": {"type": "wiki_lookup", "query": topic, "found": False},
        }

    # Wikipedia mogła rozwiązać skrót/odmianę na inny, już zapisany
    # tytuł (np. "USA" -> "Stany Zjednoczone"), więc sprawdź cache
    # jeszcze raz pod prawdziwym tytułem, zanim pójdziesz do sieci.
    cached = _find_cached_wiki_note(vault, resolved_title)
    if cached:
        extract = _wiki_note_body(cached)
        _resolve_open_question(topic)
        return {
            "speech": f"To już jest w banku wiedzy: {_first_sentence(extract)}",
            "card": {
                "type": "wiki_lookup", "query": topic, "title": cached.title,
                "extract": extract, "found": True, "cached": True,
            },
        }

    extract = _wiki_fetch_summary(resolved_title)
    if extract is None:
        # Tytuł się znalazł, ale pobranie treści akurat się nie udało -
        # to brzmi jak chwilowy problem z serwisem, więc też do kolejki.
        _queue_open_question(topic)
        return {
            "ok": False,
            "speech": f"Znalazłem „{resolved_title}” na Wikipedii, ale nie udało się pobrać treści.",
            "card": {"type": "wiki_lookup", "query": topic, "title": resolved_title, "found": False},
        }

    _save_wiki_note(resolved_title, extract)
    _resolve_open_question(topic)
    source_url = _WIKI_PAGE_URL.format(title=urllib.parse.quote(resolved_title.replace(" ", "_")))
    return {
        "speech": f"Sprawdziłem na Wikipedii: {_first_sentence(extract)}",
        "card": {
            "type": "wiki_lookup", "query": topic, "title": resolved_title,
            "extract": extract, "found": True, "cached": False, "source": source_url,
        },
        # Nowy plik trafił do data/wiki_cache, jednego z korzeni vault
        # (patrz data.get_vault_roots): bez tego sygnału graf w pamięci
        # (main.py:_vault_cache) nie wiedziałby o nowej notatce, dopóki
        # ktoś nie zapisałby/usunął czegoś innego przez interfejs.
        # main.py:_handle_chat sprawdza ten klucz i usuwa go przed
        # odesłaniem JSON-u do przeglądarki (frontend go nie potrzebuje).
        "invalidate_vault": True,
    }


def brief_me(vault) -> dict:
    # Kalendarza i poczty GREGAI nie czyta (świadoma decyzja): brief opiera
    # się wyłącznie na notatkach i alertach sieci, i mówi to uczciwie.
    parts = ["Poczty i kalendarza nie czytam, bo nie są podłączone."]  # zawsze: uczciwe zastrzeżenie

    net_alerts = network_mod.recent_alerts(limit=3, max_age_hours=48)
    if net_alerts:
        parts.append(f"Masz {_count_alerty_siecowe(len(net_alerts))}.")

    hubs = vault.top_hubs(3)
    hub_lines = [{"title": n.title, "type": n.ntype, "connections": deg} for n, deg in hubs]
    if hubs:
        parts.append("Najbardziej połączone notatki: " + ", ".join(f"„{n.title}”" for n, _ in hubs) + ".")
    open_q = len(_load_open_questions())
    if open_q:
        parts.append(f"Czekam z {_count_tematow_do_sprawdzenia(open_q)} na internet.")
    speech = " ".join(parts)
    return {
        "speech": speech,
        "card": {
            "type": "brief_me",
            "top_hubs": hub_lines,
            "network_alerts": net_alerts,
        },
    }


def remember(fact: str) -> dict:
    # 1.18.0: spójnik na początku ("że lubię kawę") odcinany także tutaj, nie
    # tylko w capabilities._call_remember - pętla zadań i inne ścieżki wołają
    # to narzędzie wprost, a zapisany fakt "że ..." to śmieć w pamięci.
    # Bez "ze": bez polskich znaków to zwykle przyimek ("ze znajomymi gram w piątki").
    fact = re.sub(r"^\s*(?:,\s*)?(?:że|iż)\s+", "", (fact or "").strip(" :,-"), count=1)
    if not fact.replace("\x00", "").strip():
        # 1.28.0 (audyt): pusty fakt (same znaki sterujące) dawał pustą notatkę "fakt.md".
        return {"ok": False, "speech": "Nie mam czego zapamiętać: napisz po „zapamiętaj” sam fakt.", "card": None}
    filename, created = memory_mod.remember(fact)
    total = len(fact.strip())
    cut = (f" Fakt miał {total} znaków, zapisałem pierwsze {memory_mod.MAX_FACT_CHARS} (dłuższy tekst "
           f"dodaj jako zwykłą notatkę).") if total > memory_mod.MAX_FACT_CHARS else ""
    return {
        "speech": (f"Zapisane: {fact.strip()[:300]}.{cut}" if created
                   else f"To już jest w pamięci ({filename}), nie zapisuję drugi raz."),
        "card": {"type": "remember", "fact": fact.strip(), "file": filename},
        # memory/ jest korzeniem vault (data.MEMORY_ROOT): nowy fakt ma być od
        # razu do znalezienia (main.py:_run_chat usuwa ten klucz z odpowiedzi).
        "invalidate_vault": True,
    }


_SAVE_NOTE_TITLE_MAX = 90
_SAVE_NOTE_BODY_MAX = 12000


def save_note(title: str, body: str) -> dict:
    """Zapisuje treść (zwykle OSTATNIĄ odpowiedź GREGAI po researchu) jako
    prawdziwą notatkę markdown type: Wiedza w notatki/wiedza (tam, gdzie już jest
    bank Wiedzy), czyli NOWY WĘZEŁ w grafie - to "dodaj do węzłów"/"zapisz to".
    Dokłada jawną adnotację, że wiedza jest niezweryfikowana (GREGAI nie
    potwierdził źródeł w rozmowie). Zwraca potwierdzenie z nazwą pliku; przy
    pustej treści albo gdy folok nie da się zapisać - uczciwy błąd, nie cisza."""
    title = re.sub(r"\s+", " ", (title or "").strip().lstrip("#").strip())[:_SAVE_NOTE_TITLE_MAX].strip()
    body = (body or "").strip()
    if not body:
        return {"ok": False, "speech": "Nie mam czego zapisać - nie widzę treści do dodania jako węzeł.", "card": None}
    # 1.32.10 (audyt tura 14): te same zasady tytułu co /api/note/create - bez [ ] | # (psują
    # powiązania) i bez znaków sterujących.
    title = re.sub(r"\s+", " ", re.sub("[\\[\\]|#\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]", " ", title)).strip()
    if not title:
        title = "Notatka z rozmowy"
    # 1.32.10 (audyt tura 14): tytuł zajęty przez notatkę spoza banku wiedzy (np. Twoją) - nowy
    # węzeł dostaje dopisek, żeby [[Tytuł]] dalej jednoznacznie wskazywał Twoją notatkę.
    try:
        import sys as _sys
        _m = _sys.modules.get("main") or _sys.modules.get("__main__")
        _gv = getattr(_m, "get_vault", None)
        if _gv is not None:
            _v = _gv()
            _hit = _v.by_title.get(vault_mod.normalize_title(title))
            _wroot = Path(data_mod.WIEDZA_ROOT).resolve()
            if _hit and _hit in _v.notes and not Path(_v.notes[_hit].path).resolve().is_relative_to(_wroot):
                title = f"{title} (z rozmowy)"
    except Exception:
        pass
    # Treść bez własnej linii "# Tytuł" na początku (dołożymy swoją) i bez linii
    # "type: ..." (to nagłówek notatki, nie treść) - inaczej zdublowałyby się.
    lines = body.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    lines = [ln for ln in lines if not re.match(r"^\s*type:\s*\w+\s*$", ln)]
    clean_body = "\n".join(lines).strip()[:_SAVE_NOTE_BODY_MAX]
    # 1.32.3 (audyt tura 8): sekret z .env (np. hasło routera) nie ląduje w notatce na dysku.
    try:
        import sysop as _sysop
        clean_body = _sysop.mask_secrets(clean_body)
    except Exception:
        pass
    date_str = datetime.now().strftime("%Y-%m-%d")
    content = (
        f"# {title}\n"
        f"type: Wiedza\n"
        f"data: {date_str}\n\n"
        f"{clean_body}\n\n"
        f"Zapisane z rozmowy z GREGAI ({date_str}). Informacje NIEZWERYFIKOWANE - "
        f"GREGAI nie potwierdził źródeł; sprawdź, zanim na nich polegniesz.\n"
    )
    try:
        root = Path(data_mod.WIEDZA_ROOT)
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False,
                "speech": "Nie udało się zapisać notatki - nie mogę zapisywać w folderze wiedzy (uprawnienia?).",
                "card": {"type": "save_note", "error": type(e).__name__}}
    slug_base = vault_mod.slugify(title) or "notatka"
    wanted = vault_mod.normalize_title(title)
    filename, counter = f"{slug_base}.md", 2
    while not fsutil.create_new_text(root / filename, content, mode=0o644):
        # Plik o tym slugu już jest. Jeśli to TEN SAM tytuł - nie dubluj; inaczej
        # dokładamy licznik, żeby dwa różne tytuły o tym samym slugu nie nadpisały się.
        try:
            with open(root / filename, encoding="utf-8-sig", errors="replace") as existing:
                first = existing.readline().strip()
        except OSError:
            first = ""
        if vault_mod.normalize_title(first.lstrip("#").strip()) == wanted:
            # 1.32.3 (audyt tura 8): ten sam tytuł, NOWA treść - dopisujemy sekcję, zamiast
            # mówić "już jest" i gubić świeży research.
            try:
                existing_text = (root / filename).read_text(encoding="utf-8", errors="replace")
            except OSError:
                existing_text = clean_body
            # Dopisujemy tylko do węzła zapisanego przez GREGAI (type: Wiedza) - notatki, którą
            # Grzegorz napisał sam pod tym tytułem, nie ruszamy (wtedy nowy plik z licznikiem).
            own = bool(re.search(r"(?im)^type:\s*wiedza\s*$", existing_text[:2000]))
            if own and clean_body not in existing_text:
                try:
                    # 1.32.10: odczyt + atomowy zapis pod wspólną blokadą notatek (nie "a" bez blokady).
                    with fsutil.NOTES_LOCK:
                        cur_text = (root / filename).read_text(encoding="utf-8", errors="replace")
                        fsutil.atomic_write_text(root / filename, cur_text.rstrip("\n") + "\n"
                                                 f"\n## Uzupełnienie {date_str}\n\n{clean_body}\n\n"
                                                 f"Dopisane z rozmowy z GREGAI ({date_str}). Informacje NIEZWERYFIKOWANE - "
                                                 f"sprawdź, zanim na nich polegniesz.\n")
                except OSError as e:
                    return {"ok": False, "speech": "Nie udało się dopisać nowej treści do węzła (uprawnienia?).",
                            "card": {"type": "save_note", "error": type(e).__name__}}
                return {"ok": True, "speech": f"Dopisałem nową treść do węzła „{title}” (plik {filename}).",
                        "card": {"type": "save_note", "title": title, "file": filename, "appended": True},
                        "invalidate_vault": True}
            if own:
                return {
                    "ok": True,
                    "speech": f"„{title}” już jest w grafie jako węzeł (type: Wiedza), nie zapisuję drugi raz.",
                    "card": {"type": "save_note", "title": title, "file": filename, "duplicate": True},
                    "invalidate_vault": True,
                }
        filename = f"{slug_base}-{counter}.md"
        counter += 1
        if counter > 50:
            return {"ok": False, "speech": "Nie udało się zapisać notatki (za dużo kolizji nazw).",
                    "card": {"type": "save_note", "error": "TooManyCollisions"}}
    return {
        "ok": True,
        "speech": (f"Zapisane jako węzeł w grafie: „{title}” (type: Wiedza, plik {filename}). "
                   f"Dopisałem, że to wiedza niezweryfikowana. Znajdziesz ją teraz przez przeszukiwanie notatek."),
        "card": {"type": "save_note", "title": title, "file": filename},
        # Korzeń vault: nowy węzeł ma być od razu w grafie i do znalezienia.
        "invalidate_vault": True,
    }


def plan_day(vault) -> dict:
    """Plan dnia budowany WYŁĄCZNIE z notatek w vault, żadnych
    zmyślonych punktów. Jeśli materiału za mało, mówi to wprost."""
    # Bez banku wiedzy, pamięci i dziennika: hasło z Wikipedii z wieloma linkami to nie zadanie na dziś.
    deg = vault.degrees()
    hubs = sorted(((n, deg[n.slug]) for n in vault.notes.values() if n.ntype not in ("Wiki", "Memory", "Journal", "Wiedza", "Nauka")),
                  key=lambda p: -p[1])[:8]
    if not hubs:
        return {
            "speech": "Nie mam jeszcze wystarczająco materiału w notatkach na konkretny plan dnia.",
            "card": {"type": "plan_day", "items": []},
        }
    priority_order = ["Client", "Invoice", "Proposal", "Project", "Call", "Sop", "Concept", "Note"]
    ranked = sorted(
        hubs,
        key=lambda pair: (
            priority_order.index(pair[0].ntype) if pair[0].ntype in priority_order else len(priority_order),
            -pair[1],
        ),
    )
    items = [{"title": n.title, "type": n.ntype, "reason": f"{deg} {_polish_form(deg, 'połączenie', 'połączenia', 'połączeń')} w grafie"} for n, deg in ranked[:5]]
    speech = f"Na dziś najważniejsze to „{items[0]['title']}”."
    return {"speech": speech, "card": {"type": "plan_day", "items": items}}


def graph_overview(vault) -> dict:
    """Przegląd CAŁEGO grafu: to samo, co widać w interfejsie webowym
    (http://localhost:7777): liczba węzłów, podział na typy (panel
    "Filtry"), top huby (panel "Top huby"). Używane dla pytań o sam
    graf/strukturę notatek ("co możesz wyczytać z węzłów?", "ile masz
    notatek?", "jakie typy notatek są w grafie?", "jakie są najbardziej
    połączone węzły?"), NIE dla pytań o konkretny fakt (to search_brain)."""
    total = len(vault.notes)
    if total == 0:
        return {
            "speech": "Graf jest pusty, nie mam jeszcze żadnych zindeksowanych notatek.",
            "card": {"type": "graph_overview", "total": 0, "by_type": {}, "top_hubs": []},
        }

    by_type = vault.counts_by_type()
    hubs = vault.top_hubs(5)

    type_lines = ", ".join(f"{t}: {c}" for t, c in sorted(by_type.items(), key=lambda x: -x[1]))
    # "węzłów" tylko dla 5+ (i 12-14): bez tego "W grafie jest 3 węzłów" brzmiało
    # po robociarsku, poprawnie po polsku to "3 węzły" (żywy przykład błędu,
    # od którego to powstało, tak jak urządzenia/alerty wyżej w tym pliku).
    wezly = _polish_form(total, "węzeł", "węzły", "węzłów")
    speech = f"Masz {total} {wezly} w grafie: {type_lines}."
    if hubs:
        top_note, top_deg = hubs[0]
        speech += f" Najbardziej połączony to „{top_note.title}” ({top_deg} {_polish_form(top_deg, 'połączenie', 'połączenia', 'połączeń')})."
    # Samotne węzły (bez żadnego połączenia): to, o co pyta "co wisi samotnie / bez połączeń".
    orphans = [vault.notes[s].title for s, d in vault.degrees().items() if d == 0]
    if orphans:
        shown = ", ".join(f"„{t}”" for t in sorted(orphans)[:5])
        speech += f" Bez żadnego połączenia: {len(orphans)} ({shown}{', ...' if len(orphans) > 5 else ''})."

    return {
        "speech": speech,
        "card": {
            "type": "graph_overview",
            "total": total,
            "orphans": len(orphans),
            "by_type": by_type,
            "top_hubs": [
                {"title": n.title, "type": n.ntype, "connections": deg}
                for n, deg in hubs
            ],
        },
    }


def network_status() -> dict:
    """Czyta ostatni zapisany stan sieci (urządzenia, producent z MAC,
    online/offline, alerty), NIE wywołuje nowego skanu podsieci (ten
    chodzi osobno, cyklicznie, przez systemd timer, patrz siec.py).
    Do tego JEDNO świeże zapytanie do routera (sygnał, operator, typ
    sieci 4G/5G, zużycie danych w tym miesiącu, nazwa WiFi, bateria
    jeśli urządzenie ją ma), ograniczone czasowo, więc nawet
    nieodpowiadający router nigdy nie zawiesza rozmowy."""
    inventory = network_mod.current_inventory()
    meta = network_mod.scan_meta()
    alerts = network_mod.recent_alerts(limit=5, max_age_hours=72)  # najnowszy pierwszy

    if not inventory:
        return {
            "speech": "Jeszcze nie mam danych o sieci, monitoring pewnie dopiero się rozkręca.",
            "card": {"type": "network_status", "devices": [], "alerts": [], "router": None, "scan": meta},
        }

    online = [d for d in inventory.values() if d.get("online")]
    unidentified = [d for d in inventory.values() if not d.get("hostname") and not d.get("vendor")]

    router_card = None
    try:
        import router_bridge
        if router_bridge.router_configured():
            router_card = router_bridge.router_status()
    except Exception:
        router_card = None

    # Mowa: maks. kilka krótkich zdań, priorytet na to, co NAJWAŻNIEJSZE.
    # Pełny obraz (wszystkie urządzenia, cały stan routera) idzie do karty
    # niżej, żeby nie duplikować tej samej treści w dwóch miejscach.
    total = len(inventory)
    if total == 1:
        speech_parts = [f"Teraz masz {len(online)} z 1 znanego urządzenia online."]
    else:
        speech_parts = [f"Teraz masz {len(online)} z {total} znanych urządzeń online."]
    if meta.get("skipped"):
        # Poza siecią domową siec.py nie skanuje (agent/homenet.py): dane są
        # z ostatniego skanu w domu, więc mówimy to wprost.
        speech_parts = [f"Nie skanuję teraz sieci: {meta['skipped']}. Poniżej stan z ostatniego skanu w domu."]
    else:
        stale = network_mod.hours_since(meta.get("time"))
        if stale is None or stale > 2:
            # Timer skanu co 15 min: starsze dane to zatrzymany timer albo laptop po uśpieniu.
            since = f"sprzed {stale:.0f} h" if stale is not None else "z nieznanego czasu"
            speech_parts = [f"Uwaga: to dane {since} (skan sieci nie odświeżył się). " + speech_parts[0].replace("Teraz masz", "Wtedy było")]

    if alerts:
        a = alerts[0]
        who = a.get("hostname") or a.get("ip") or "nieznane urządzenie"
        if a.get("type") == "urzadzenie_wrocilo":
            speech_parts.append(f"„{who}” wróciło po {a.get('absent_days')} dniach nieobecności.")
        elif a.get("type") == "nowe_urzadzenie":
            speech_parts.append(f"Niedawno dołączyło nowe urządzenie: „{who}”.")

    battery = router_card.get("battery_percent") if router_card else None
    low_battery = False
    if battery is not None:
        try:
            low_battery = float(battery) < 20
        except (TypeError, ValueError):
            low_battery = False

    if low_battery:
        speech_parts.append(f"Uwaga: bateria routera na {battery}%.")
    elif unidentified:
        speech_parts.append(f"Masz {_count_urzadzenia(len(unidentified))} bez rozpoznanej nazwy czy producenta.")
    elif router_card and not router_card.get("error") and router_card.get("operator"):
        bits = [router_card["operator"]]
        if router_card.get("network_type_label"):
            bits.append(router_card["network_type_label"])
        speech_parts.append(f"Internet masz od {' / '.join(bits)}.")

    speech = " ".join(speech_parts)

    devices_card = [
        {
            "ip": entry["ip_history"][-1] if entry.get("ip_history") else "",
            "mac": entry.get("mac", ""),
            "hostname": entry.get("hostname") or "(brak nazwy)",
            "vendor": entry.get("vendor") or "",
            "online": bool(entry.get("online")),
            "first_seen": entry.get("first_seen"),
            "last_seen": entry.get("last_seen"),
        }
        for entry in sorted(
            inventory.values(),
            key=lambda e: (not e.get("online"), (e.get("hostname") or "").lower()),
        )
    ]

    return {
        "speech": speech,
        "card": {
            "type": "network_status",
            "devices": devices_card,
            "online_count": len(online),
            "total_count": len(inventory),
            "alerts": alerts,
            "router": router_card,
            "scan": meta,
        },
    }
