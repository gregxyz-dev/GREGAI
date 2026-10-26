"""
koryto.py

Jedna kolejność dostawców dla CAŁEGO myślenia GREGAI (1.17.0).

Metafora Grzegorza (2026-10-21): "cały program to koryto, po prostu zmienia
się, co przez to koryto płynie". Rozmowa, Namysł (wszystkie sześć faz),
decyzja "czy i jakie narzędzie" (krok 1 routera), planer pętli zadań i
streszczenia rozmowy NIE wybierają już każde po swojemu, kto ma liczyć -
pytają TEN moduł o kolejność etapów i idą nią po kolei, pierwszy sukces
wygrywa. Sam etap myślenia ("co płynie") zostaje bez zmian; zmienia się tylko
"kto liczy".

Trzy etapy (nazwy w .env, KORYTO=..., oddzielone przecinkami):

  anthropic  - Claude (Anthropic, PŁATNY): domyślnie PIERWSZY. Decyzja
               Grzegorza 2026-10-21 ("głównym dostawcą ma być Anthropic,
               Claude Haiku") - odwrotnie niż do 1.16.x, gdzie Claude był
               ostatnią, płatną rezerwą po darmowej puli. Model: ANTHROPIC_MODEL
               w .env (domyślnie claude-haiku-5-5 - najtańszy i najszybszy z
               aktualnej rodziny; patrz juggler._MODEL). Bez klucza
               (ANTHROPIC_API_KEY) etap po prostu nie istnieje - koryto płynie
               dalej.
  darmowe    - pula darmowych dostawców z agent/juggler.py (Groq, Gemini,
               OpenRouter, Hugging Face, Cloudflare), w LOSOWEJ kolejności
               (powód: juggler.py, docstring - żaden pojedynczy darmowy
               dostawca nie widzi całego ruchu). Domyślnie DRUGI: rezerwa, gdy
               Claude nie odpowie (błąd, limit dzienny, bezpiecznik).
  lokalnie   - ta maszyna (Ollama: uczeń STUDENT_MODEL, potem OLLAMA_MODEL).
               Domyślnie OSTATNI: "ostatecznym fallbackiem będzie lokalna
               maszyna". Bez internetu/WARP (agent/netguard.py, fail-closed)
               to jedyny etap, który w ogóle może odpowiedzieć.

Domyślnie: KORYTO=anthropic,darmowe,lokalnie. Etap pominięty w KORYTO nie
jest używany wcale (np. KORYTO=anthropic,lokalnie = bez darmowej puli);
nieznane nazwy są ignorowane; pusty/błędny wpis = domyślna kolejność. Kto
akurat jest pierwszy w kolejce, widać w Nadzorcy (/api/system_info: koryto).

Co ten moduł ZNA, a czego NIE: zna tylko nazwy etapów i ich kolejność. Nie
woła żadnego dostawcy, nie zna kluczy, nie sprawdza WARP ani limitów - to
robią juggler.py (etapy sieciowe: anthropic + darmowe, w jednym łańcuchu,
patrz juggler.chat/providers_pool) i router.py (etap lokalny). Dzięki temu
nie ma importu kołowego: koryto.py importuje wyłącznie stdlib i env_loader,
a importują GO router.py, juggler.py i namysl.py.

Granica prywatności zostaje ta sama, co dotąd (nie zależy od kolejności):
do KAŻDEGO etapu sieciowego (Claude tak samo jak darmowi) idzie tylko to, co
szło do żonglera do 1.16.x - oczyszczona historia rozmowy bez odpowiedzi
narzędzi (router._cloud_history), sekrety zamaskowane (trace.mask), blok
"Teraz" bez treści notatek (awareness.cloud_prompt); fragmenty notatek/plików
w Namyśle tylko za zgodą w ustawieniach Namysłu (material_do_sieci). Dwie
nowości 1.17.0 idą siecią TYLKO za włączonym przełącznikiem w .env (oba
domyślnie włączone, bo o to prosił Grzegorz - "wszelkie myślenia mają się
dostosowywać pod aktualnie wybrane API"):
  KORYTO_ROUTING=1 - krok 1 routera (decyzja o narzędziu, chudy prompt z
                     wiadomością i dwiema poprzednimi wiadomościami
                     użytkownika jako kontekst, od 1.17.5; bez odpowiedzi
                     narzędzi) też idzie korytem,
                     zanim spadnie na lokalny model.
  KORYTO_ZADANIA=1 - planer pętli zadań SYSOP (agent/agentloop.py) idzie
                     korytem; w jego prompcie są obserwacje z narzędzi (stan
                     systemu, fragmenty logów/plików - zmaskowane), więc kto
                     tego nie chce w sieci, ustawia 0: planer zostaje lokalny.
"""

from __future__ import annotations

import os

ETAPY = ("anthropic", "darmowe", "lokalnie")
SIECIOWE = ("anthropic", "darmowe")
DOMYSLNE = "anthropic,darmowe,lokalnie"

OPIS = {
    "anthropic": "Claude (Anthropic, płatny)",
    "darmowe": "darmowa pula (Groq/Gemini/OpenRouter/Hugging Face/Cloudflare)",
    "lokalnie": "lokalny model (Ollama, ta maszyna)",
}


def _parse(raw: str) -> list[str]:
    out: list[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        name = part.strip().lower()
        if name in ETAPY and name not in out:
            out.append(name)
    return out


def order() -> list[str]:
    """Kolejność etapów z .env (KORYTO), czytana przy każdym wywołaniu -
    zmiana w .env działa po restarcie usługi, jak każda inna zmienna; bez
    pamięci podręcznej, żeby testy/kontrole mogły podmieniać os.environ."""
    return _parse(os.environ.get("KORYTO", "")) or _parse(DOMYSLNE)


def network_order() -> list[str]:
    """Tylko etapy sieciowe, w kolejności koryta (dla juggler.chat)."""
    return [e for e in order() if e in SIECIOWE]


def local_before_network() -> bool:
    """Czy 'lokalnie' stoi PRZED pierwszym etapem sieciowym (np.
    KORYTO=lokalnie,anthropic). Namysł i rozmowa pytają o to, żeby nie
    zakładać na sztywno "sieć, potem lokalnie"."""
    o = order()
    if "lokalnie" not in o:
        return False
    net = [i for i, e in enumerate(o) if e in SIECIOWE]
    return not net or o.index("lokalnie") < net[0]


def local_mode() -> str:
    """KORYTO_LOKALNIE (1.17.3, doprecyzowanie Grzegorza 2026-10-21: "w trybie
    sieciowym mają być używane TYLKO AI sieciowe, a w momencie gdy wysiądzie
    internet - przerzutka na lokalny"):
      bez_internetu (domyślne) - etap "lokalnie" wchodzi do gry WYŁĄCZNIE gdy
                     nie ma internetu/WARP (netguard) albo żaden etap sieciowy
                     nie ma klucza; gdy sieciowi po prostu nie odpowiedzą
                     (limit, błąd), odpowiedź to krótki komunikat z powodami,
                     a nie kilka minut liczenia na CPU,
      zawsze         - jak w 1.17.0-1.17.2: lokalny także jako rezerwa po
                     porażce sieciowych."""
    raw = os.environ.get("KORYTO_LOKALNIE", "").strip().lower()
    return raw if raw in ("bez_internetu", "zawsze") else "bez_internetu"


def local_allowed(network_configured: bool, internet_ok: bool) -> bool:
    """Czy etap "lokalnie" może liczyć TERAZ. Zawsze tak, gdy: KORYTO_LOKALNIE=
    zawsze, "lokalnie" nie ma w korycie żadnego etapu sieciowego przed sobą
    (KORYTO=lokalnie,... albo brak kluczy), albo internet/WARP nie działa."""
    if "lokalnie" not in order():
        return False
    if local_mode() == "zawsze" or not network_configured or not internet_ok:
        return True
    return local_before_network()


def routing_via_network() -> bool:
    return os.environ.get("KORYTO_ROUTING", "1").strip() != "0" and bool(network_order())


def tasks_via_network() -> bool:
    return os.environ.get("KORYTO_ZADANIA", "1").strip() != "0" and bool(network_order())


def describe() -> str:
    return " -> ".join(OPIS[e] for e in order())


def _env_seconds(name: str, default: int, lo: int, hi: int) -> int:
    """Ta sama wartość, której używa juggler.env_int (z tymi samymi granicami),
    żeby `gregai status` nie pokazywał budżetu, którego kod nie stosuje."""
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def status() -> dict:
    """Do /api/system_info (main.py) i panelu Nadzorcy."""
    return {
        "kolejnosc": order(),
        "opis": describe(),
        "lokalnie": local_mode(),
        # Budżety (juggler.py): łańcuch dostawców i cała wiadomość (1.18.0).
        "budzet_s": _env_seconds("KORYTO_BUDZET_S", 120, 10, 3600),
        "budzet_wiadomosc_s": _env_seconds("KORYTO_BUDZET_WIADOMOSC_S", 210, 30, 7200),  # = juggler._REQUEST_BUDGET_S
        "routing_siecia": routing_via_network(),
        "zadania_siecia": tasks_via_network(),
        "domyslne": _parse(DOMYSLNE),
    }
