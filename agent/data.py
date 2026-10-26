"""
data.py

JEDYNY PLIK, KTÓRY WIE, GDZIE SĄ DANE UŻYTKOWNIKA.

Edytuj REAL_VAULT_ROOTS, aby dodać lub usunąć indeksowane foldery:
to jedno miejsce czyni ten system naprawdę Twoim.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# --- Edytuj tę listę, aby dodać/usunąć indeksowane foldery -----------------
# UWAGA: to powinien być OSOBNY podfolder na notatki, nie folder samej
# aplikacji, inaczej README.md/CLAUDE.md zaindeksują się jako przypadkowe
# notatki razem z prawdziwymi.
#
# Domyślnie: podfolder "notatki" obok tego projektu, niezależnie od tego,
# w jakiej ścieżce leży cały folder GREGAI, dzięki temu nie trzeba tego
# ręcznie poprawiać po przeniesieniu folderu.
REAL_VAULT_ROOTS = [
    str(PROJECT_ROOT / "notatki"),
]
# ----------------------------------------------------------------------------

# Bank wiedzy z Wikipedii (agent/tools.py:wiki_lookup): NIE zrzut całej
# Wikipedii (dziesiątki GB, bez realnego indeksu wyszukiwania nie do
# ogarnięcia na tym sprzęcie), tylko temat-po-temacie cache tego, o co
# użytkownik faktycznie zapytał, zapisany jako prawdziwe notatki
# markdown (type: Wiki). Osobny podfolder w data/ (nie w notatki/),
# żeby nigdy nie wymieszać się z prawdziwymi, własnymi plikami
# użytkownika, a jednak policzony jako korzeń vault niżej, żeby ten
# bank od razu był przeszukiwalny przez search_brain/graph_overview,
# bez osobnego, drugiego systemu wyszukiwania.
WIKI_CACHE_ROOT = str(PROJECT_ROOT / "data" / "wiki_cache")

# Dziennik GREGAI (agent/heartbeat.py): notatki typu Dziennik, jedna na
# dzień, które GREGAI pisze SAM, bez pytania, z policzonymi wnioskami z
# self_status (agent/tools.py:_draw_conclusions). Osobny podfolder w
# data/ z tego samego powodu co WIKI_CACHE_ROOT wyżej (nigdy wymieszany
# z plikami użytkownika), ale policzony jako korzeń vault, żeby był od
# razu przeszukiwalny i widoczny w grafie - to jest literalna pamięć
# GREGAI o sobie w czasie, nie osobny, oddzielony system.
JOURNAL_ROOT = str(PROJECT_ROOT / "data" / "journal")

# To, co kazałeś zapamiętać (agent/memory.py, narzędzie remember): jedna
# notatka (type: Memory) na fakt. Korzeń vault, żeby GREGAI mógł to potem
# znaleźć (search_brain) i żeby fakt był widoczny w grafie.
MEMORY_ROOT = str(PROJECT_ROOT / "memory")

# Zadania stałe (agent/standing.py, "śledź X i daj znać gdy Y"): jedna
# notatka (type: Zadanie) na zadanie, z całą jego historią (zlecenie,
# bieżący stan, dziennik sprawdzeń, alerty) w jednym pliku - to tu żyje
# "spójność", o którą poprosił Grzegorz (2026-10-19), dlatego to korzeń
# vault jak MEMORY_ROOT/JOURNAL_ROOT wyżej, nie osobny, niewidoczny magazyn.
STANDING_TASKS_ROOT = str(PROJECT_ROOT / "data" / "standing_tasks")

# Wiedza zapisana NA PROŚBĘ użytkownika z rozmowy (agent/tools.py:save_note,
# "zapisz to do notatek"/"dodaj do węzłów"): jedna notatka (type: Wiedza) na
# zapis, z treścią researchu i jawną adnotacją "niezweryfikowane". Ląduje w
# notatki/wiedza - czyli TAM, gdzie już mieszka gotowy bank Wiedzy (60+ notatek:
# cyberbezpieczeństwo, programowanie, biznes). Jeden wspólny dom dla typu Wiedza,
# nie drugi, osobny magazyn (1.30.25, scalenie: wcześniej był to data/wiedza, co
# rozbijało Wiedzę na dwa korzenie). notatki/ to już korzeń vault ładowany
# rekurencyjnie, więc nowy zapis od razu jest WĘZŁEM w grafie - i dlatego NIE
# dokładamy tego katalogu drugi raz w get_vault_roots (byłby ładowany podwójnie).
WIEDZA_ROOT = str(PROJECT_ROOT / "notatki" / "wiedza")


def get_vault_roots():
    # mkdir tutaj (nie przy starcie serwera): get_vault_roots() jest
    # jedynym miejscem, które wie, że te foldery muszą istnieć, i jest
    # wołane przy KAŻDYM (prze)budowaniu vault (patrz main.py:get_vault),
    # więc folder istnieje, nawet jeśli to pierwsze pytanie w historii
    # tej instalacji o wiki_lookup/dziennik. exist_ok=True: tanie i
    # bezpieczne wywołać wielokrotnie.
    # Katalog, którego nie da się utworzyć (data/ należy do roota, jest tylko do odczytu albo
    # pod tą nazwą leży zwykły plik), wypada z listy; własne notatki w REAL_VAULT_ROOTS
    # działają dalej, zamiast przewrócić każdą operację na notatkach.
    roots = list(REAL_VAULT_ROOTS)
    # WIEDZA_ROOT celowo NIE jest tu dokładany: to podfolder notatki/, który
    # REAL_VAULT_ROOTS już ładuje rekurencyjnie (dodanie = podwójne wczytanie).
    for extra in (WIKI_CACHE_ROOT, JOURNAL_ROOT, MEMORY_ROOT, STANDING_TASKS_ROOT):
        try:
            Path(extra).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            if extra not in _MKDIR_WARNED:
                _MKDIR_WARNED.add(extra)
                print(f"UWAGA: nie mogę utworzyć {extra} ({type(e).__name__}); ten katalog jest pominięty w notatkach")
            continue
        roots.append(extra)
    return roots


_MKDIR_WARNED: set = set()
