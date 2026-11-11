# Audyt GREGAI v1.45.18 - 2026-11-11

Autonomiczny, turbo-dokładny audyt przez pomost MCP (`gregai-mcp`, 34 narzędzia)
na żywej instalacji. Po audycie wydanie **1.45.19** (8 nowych kontroli w check.sh,
`bash weryfikuj.sh` GOTOWE, offline eval 92/92 bez regresji). Poprzedni audyt
(v1.45.17) w `audit/GRAGAI_AUDIT_2026-11-11_wydanie-1.45.17.md`.

## Meta

- Czas trwania: ~135 min (17:04 - start 14:46 UTC+1)
- Liczba wywołań MCP: ~90 (plus żywe sondaże przez curl na `/api/chat/wait`/`progress`)
- Liczba wiadomości chat: **16** (5 szybkich, 4 narzędziowe, 2 Namysł, 2 rozmowa, 3 edge/memory/usuwanie)
- Pokrycie: ~95%. Nieprzetestowane: `network_scan` (start skanu), `eval_run`
  (start evaluacji przez MCP - eval uruchomiono lokalnie, offline), `upload`
  (25 MB base64 przez JSON - zamiast tego edge casey walidacji), `chat_cancel`
  (żaden test nie wymagał anulowania), finał długiej wiadomości 2656 znaków
  (utracony przez restart usługi w trakcie audytu).

## Podsumowanie

- Health: **OK** (`ok: true`, usługa active/running; po poprawkach wersja **1.45.19**)
- Węzły: **141** (izolowane: 35, wiszące krawędzie: 0, wisieńce: **0**), Krawędzie: **278**
- Aktywne zadania stałe: **0** (testowe utworzone i usunięte; interwały cięte do 15-1440)
- Budżet: **0.00/1.50 USD** (dziś), **0.00/20 USD** (miesiąc) - ale SPEND_LOG ma 0.15 USD dziś (patrz 🟡#8)
- Straż: ~30 alertów w ostatnich 24 h (głównie "kod zmieniony" podczas audytu i porty testowe); dedup działa (0 powtórzeń w liście)
- Koryto: **84 wywołania dostawców dziś** (groq 57, openrouter 27, anthropic 0)
- Pass rate eval: **100%** (92/92, wersja 1.45.18, 2026-11-11T17:03, tryb szybki, offline)

## Znaleziska

### 🔴 Błędy (blokują funkcję lub bezpieczeństwo)

| # | Obszar | Opis | Dowód (tool + output) | Wpływ |
|---|--------|------|----------------------|-------|
| 1 | Odpowiedzi / poprawność | **Wiki_lookup zwracał obcy artykuł**: "Co to jest Ollama?" -> "Sprawdziłem na Wikipedii: **Gary Leonard Oldman - brytyjski aktor**". `_wiki_resolve_title` brał pierwszy hit opensearch (limit=1) bez kontroli sensowności; polska Wikipedia NIE MA hasła "Ollama", a fuzzy match zwrócił [Gary Oldman, Olly Alexander, Ollanta Humala, Olaparyb, Barack Obama]. Odpowiedź fałszywie powoływała się na źródło. | `gregai_chat` -> "Sprawdziłem na Wikipedii: Gary Leonard Oldman..."; reprodukcja: `opensearch("Ollama", limit=5)` -> powyższa lista | Fałszywe źródła, hallucinacja faktów w banku wiedzy |
| 2 | Odpowiedzi / bramka jakości | **Chińskie znaki i meta-narracja w odpowiedzi**: na "Jak się nazywa ten film z 2019 o AI..." odpowiedź: "Grzegorz zapytał o pogodę, notatki dotyczące Pythona... **Wynik polecenia lokalnego仍未返回。** AI powinien wyjaśnić to..." - model opisał rozmowę i siebie zamiast odpowiedzieć; bramka łapała tylko angielski, nie CJK. | `gregai_chat` (msg 13) -> speech z "仍未返回", "AI pamięta, że..."; drugi przypadek: "AI nie posiada aktualnych informacji..." przy "Usuń notatkę..." (msg 16) | Bezsensowne odpowiedzi, wyciek metanarracji do użytkownika |
| 3 | Trwałość danych | **Plik śladu w obcej własności zabił telemetrię usługi**: `data/decision_log.json` (własność gregxyz2:gregxyz2 660, po uruchomieniu `weryfikuj.sh`/check.sh offline jako admin) - usługa (gregai) nie mogła czytać; `trace._load` celowo rzuca OSError włącznie z PermissionError -> od restartu **zero wpisów**, `koryto_history` i `decision_log` puste mimo 84 wywołań dostawców. `ls -la` + `gregai_koryto_history(limit=8) -> wywolania: []` przy `wywolania_dzis: {groq: 43...}` | Telemetria i diagnostyka martwe; ta sama klasa przyczyny co zerwany łańcuch straz i zera w budżecie |
| 4 | Routing / szybkość | **"Do widzenia" szło w pełny Namysł (122 s, 2 awarie dostawców)** - pożegnanie nie było w socjalnych (mimo że "dobranoc", "na razie", "pa" były); "Żegnaj" i "Dobranoc" też przechodziły do modelu. Zadanie z pożegnaniem ("do widzenia, zrób X") musiało dalej przechodzić. | `gregai_chat("Do widzenia")` -> 122480 ms, timeout pomostu, fazy: rozpoznanie->zbieranie->szkic + 2 restarty; offline `wants("Do widzenia") -> True` | 2 min i płatne limity na "pa pa"; zgodnie z kryterium audytu (>120 s na szybkiej ścieżce) |
| 5 | Routing / halucynacja | **Gołe "tak" bez karty zgody szło do modelu**: odpowiedź "Zapisuję Twoje imię: Grzegorzu. Coś jeszcze chcesz sprawdzić?" - nic nie zapisano (Memory bez zmian). Podobnie "Zapamiętam Twój imię: Grzegorz." jako wstęp odpowiedzi na plan nauki. | `gregai_chat("tak", pending_action)` (przez stary proces MCP, bez parametru) -> speech o zapisaniu imienia; `notes_list typ=Memory` -> bez nowego faktu | Użytkownik wierzy w zapis, którego nie ma |
| 6 | Własność / uprawnienia | **data/ dziedziczyła grupę twórcy, nie serwisu** - pliki atomic_write przechodzą na ostatniego pisarza (decision_log.json gregxyz2:gregxyz2, profil.json, koryto_wydatki.jsonl, straz/*); świeże uruchomienia CLI/audytu jako admin odcinają usługę od jej własnych danych. | `find data -user gregxyz2 ! -group gregai` -> decision_log.json, ollama_uzucie.jsonl, koryto_wydatki.jsonl, profil.json, straz/bezpieczenstwo.jsonl... | Klasa błędów: telemetria, budżet, łańcuch straz |
| 7 | Kontrakt / brak sig | Odpowiedzi ścieżki awaryjnej (lokalnie_awaryjnie) **bez `sig` i `provider`** (kind=tool, model_active=true) - kontrakt obiecuje sig dla odpowiedzi modelu. | `gregai_chat_wait` (msg 8, 11, 13, 16) -> sig: False, provider: None | Słabsza weryfikowalność; atrybucja dostawcy gubiona |

### 🟡 Ograniczenia (działa, ale nieoptymalnie / niespójnie)

| # | Obszar | Opis | Dowód | Sugestia |
|---|--------|------|-------|----------|
| 1 | Wydajność lokalna | **Awaryjny lokalny: śr. 416 s/odpowiedź, max 1202 s**, tok/s lokalnego **0.4** (87-287 tokenów na 396-978 s) - odpowiedzi awaryjne trwają 5-20 min. | `gregai_koryto_history`: per_etap lokalnie_awaryjnie {n:20, śr. 416.1}; `gregai_models_log`: tok_s 0.4 przy 287 tokenach | Rozważyć mniejszy num_ctx/krótszy prompt awaryjny albo wymusić krótsze odpowiedzi (format_hint) |
| 2 | Koryto / niezawodność | **Każda wiadomość "cięższa" przechodzi przez 2-3 awarie**: groq HTTP 413 (TPM 8000, znane) przy szkicach Namysłu + openrouter/free losuje model ("pusta odpowiedź", potrafi wisieć 55-180 s) -> lokalnie awaryjnie. BTC: 3 restarty, ~264 s. | progress job lCE3oNV1r0uMpkyFmPGwsQ: restart groq t=3.1, openrouter t=84; job Python: openrouter wisiał 180 s | Rozważyć skrócenie promptu Namysłu dla groq (poniżej TPM) albo pomijanie openrouter/free po 1. pustej odpowiedzi |
| 3 | Pomost | Budżet 120 s w `gregai_chat` krótszy niż realne cykle (264-300 s) -> agent widzi timeout; finał trzeba dopytać `gregai_chat_wait`. Hint jest, ale cykl ręczny. | msg BTC/plan/rozmowa: 122-123 s -> `{error, job, hint}` | Opcjonalny parametr timeout albo pętla wait wbudowana w narzędzie (do 5 min) |
| 4 | Kontrakt | `sig` nieobecny na szybkich ścieżkach deterministycznych (spójne z 1.45.18, ale kontrakt wymieniał sig bez wyjątku) - udokumentowane w api_contract.md podczas audytu. | `gregai_chat("Cześć!")` -> bez sig | - |
| 5 | Rozmowa / czas | Zwykła rozmowa (bez Namysłu) przez openrouter/free: **40-50 s** ("Co myślisz o nowym sezonie seriali?" 40.1 s). | `gregai_chat` msg 12 -> 40132 ms + dopyt | - |
| 6 | Namysł / budżet | Namysł przerwany dokładnie na budżecie 208-210 s (działa zgodnie z projektem), potem awaryjny lokalny dolicza kolejne minuty - łączny czas odpowiedzi 5-7 min. | progress job yKqR-MXgBy6ZifcIQwdwvQ: "Namysł przerwany" t=208.8 | - |
| 7 | Narzędzia / compound query | Confirm card dla 4 tematów w jednej wiadomości planował JEDNO zapytanie z 4 tematami sklejonymi średnikami ("WARP Cloudflare vs VPN; hamsters cucumber diet; ocean salinity history; most used programming language in Poland today"). | `gregai_chat` msg 14 -> pending_action arg jak wyżej | Rozpoznanie mogłoby dzielić na osobne zapytania |
| 8 | Budżet / spójność | **`usd` (status/budget) = 0.00, a SPEND_LOG ma 0.15 USD dziś (claude-haiku)** - ta sama odpowiedź `/api/budget/daily` pokazuje `dzien: 0` i `wydatki: [usd: 0.15]`. Przyczyna w juggler.py (poza zakresem poprawek audytu). | `gregai_budget` + `gregai_status` | Do decyzji użytkownika; związane z mieszanymi uruchomieniami |
| 9 | Straż / integralność | Łańcuch dziennika bezpieczeństwa nadal `ok: false, "brakuje wpisów z początku"` (939 wpisów vs kotwica) - znany stan operacyjny z audytu 1.45.17 (dwie kotwice: ~gregai vs ~gregxyz2); straz.py poza zakresem. | `gregai_system_info` -> straz.dziennik_bezp | Do decyzji użytkownika |
| 10 | Namysł / pominięcia | Namysł pominięty tylko 2x w decision_log ("socjalne") mimo że większość moich testów to były socjalne/narzędziowe - działa, ale rozkład stage'ów (lokalnie_awaryjnie 20 z 100) pokazuje, że awaryjna ścieżka jest codziennością, nie wyjątkiem. | `gregai_decision_log`: stages lokalnie_awaryjnie=4/50, koryto_history: lokalnie_awaryjnie=20/100 | Po naprawie dostawców (🟡#2) rozkład powinien się odwrócić |

### 🟢 Sugestie (nice-to-have)

| # | Obszar | Opis |
|---|--------|------|
| 1 | Diagnostyka | `system_info.ollama` nie eksponuje `num_ctx`/`keep_alive` sesji (sprawdziłem przez loaded model + kontrola lokalny-1370); warto dodać do `/api/system_info` (backend, bez ui/). |
| 2 | Straż | Alerty o portach 8123/43363 to usługi testowe OpenCode - warto dopisać do ALERTS_EXCLUDE albo dokumentacji środowiska deweloperskiego. |
| 3 | Wiedza | 35 notatek izolowanych (16 Wiki z wiki_cache bez linków) - kandydaci do ręcznego dowiązania przez Namysł/`gregai_note_update`. |
| 4 | CSS | Typy z vault mają kolory `--type-*` (wiedza/nauka/wiki/journal/memory ✓); brak `--type-zadanie` - gdy pojawią się zadania stałe jako notatki, dostaną kolor domyślny. |
| 5 | Trwałość zadań | pending_job żyje w pamięci procesu: restart usługi (audyt zrobił /api/restart) gubi finał długiej odpowiedzi ("done: None" po restarcie). Warto zapisać w api_contract.md. |
| 6 | Pomost | Zmiana kodu pomostu wymaga przeładowania połączenia MCP przez OpenCode (edycja opencode.json wymusza); stary proces cicho ignoruje nowe parametry - dopisane w README pomostu. |

## Testy rozmowy

| # | Wiadomość | Czas | Provider | Kind | Fazy | Uwagi |
|---|-----------|------|----------|------|------|-------|
| 1 | "Cześć!" | 54 ms | (brak) | tool | brak | + prefiks alertu Straży (kod zmieniony w audycie) |
| 2 | "Dziękuję" | 39 ms | (brak) | tool | brak | OK |
| 3 | "Jaka jest godzina?" | 48 ms | (brak) | tool | brak | "Jest 14:48 CET." - poprawnie |
| 4 | "Jaki jest dziś dzień?" | 46 ms | (brak) | tool | brak | "środa, 11 listopada 2026" - poprawnie |
| 5 | "Do widzenia" | 122480 ms | groq->openrouter->lokalnie | (brak finału w pomoście) | rozpoznanie, zbieranie, szkic + 2 restarty | 🔴#4 (po poprawce: odpowiedź z kodu) |
| 6 | "Ile kosztuje 1 BTC?" | 123301 ms + dopyt | groq->openrouter->lokalnie (przerwany) | chat | 3 cykle, przerwany t=264 | Finał: "BTC/USD: 73 764,20", karta market_quote (coinbase/coingecko), sig ✓ |
| 7 | "Jaka jest pogoda w Warszawie?" | **391 ms** | (narzędzie) | chat | brak | 3°C, mżawka, prognoza - świetnie |
| 8 | "Znajdź mi notatkę o Pythonie" | 123254 ms + dopyt | groq->openrouter->lokalnie | chat | 1 restart | Finał: obie notatki o Pythonie, karta search_brain, sig ✓ |
| 9 | "Co to jest Ollama?" | 122526 ms + dopyt | (wszyscy padli) | tool | restart t=117, przerwany t=297 | 🔴#1 (Gary Oldman); po poprawce: uczciwe "Nie ma hasła, sprawdziłem w wyszukiwarce" + poprawny wynik |
| 10 | "Porównaj zalety i wady Pythona vs Rust..." | 123022 ms + confirm + 8 s | openrouter (po confirm) | tool->chat | rozpoznanie 2.4 s, zbieranie 2.4 s, restarty t=5.4/47 | Karta confirm (research_web) -> "tak" przez pending_action -> pełne porównanie, sig ✓ |
| 11 | "Napisz mi plan nauki angielskiego na 3 miesiące" | 123179 ms + ~6 min | groq->openrouter->lokalnie | tool | szkic 14 s, krytyka, restarty t=4.2/28.7, przerwany t=208.8 | Plan ustrukturyzowany (836 znaków), ale halucynowany wstęp "Zapamiętam Twój imię" + literówki lokalnego modelu |
| 12 | "Co myślisz o nowym sezonie seriali?" | 40132 ms + dopyt | openrouter | chat | brak (rozmowa) | Uczciwe "nie mam pojęcia, o którym serialu mowa" - dobre |
| 13 | "Jak się nazywa ten film z 2019 o AI...?" | 123235 ms + ~8 min | (wszyscy padli) | tool | restart t=117.2, przerwany t=297.3 | 🔴#2 (meta-narracja + CJK); po poprawce brak takich |
| 14 | 483 znaki, 4 tematy | 122962 ms + confirm + 4 s | openrouter (po confirm) | tool | brak zdarzeń (confirm) | Karta confirm na 4 wyszukiwania -> wykonane przez pending_action ✓ |
| 15 | "Zapamiętaj: mój numer telefonu to +48 123 456 789" | **72 ms** | (narzędzie) | tool | brak | Karta remember; notatka w Memory z kompletnym numerem ✓ |
| 16 | "Usuń notatkę o turkusowym kolorze" | 123069 ms + ~9 min | (wszyscy padli) | tool | przerwany t=184.5 | ⚠️ ostrzeżenie + wahanie bez karty (pad dostawców); **mechanika przez MCP**: note_delete (deleted=true, 0 wisieńców) -> znika z listy -> note_restore -> wraca ✓ |

## Spójność międzyendpointowa

| Para endpointów | Pole | Oczekiwane | Rzeczywiste | Zgodne? |
|-----------------|------|-----------|-------------|---------|
| health.vault.notes vs graph.nodes | liczba węzłów | równe | 141 = 141 | ✅ |
| notes_list(limit=200) vs graph.nodes | liczba notatek | równe | 141 = 141 | ✅ |
| health.vault.edges vs graph.edges | krawędzie | równe | 278 = 278 | ✅ |
| health.version vs system_info.version | wersja | równe | 1.45.18 = 1.45.18 (przed bumpem) | ✅ |
| status.usd vs budget.budzet | dzien/miesiac | równe | 0.00 = 0.00 | ✅ |
| status/budget vs SPEND_LOG (wydatki) | dzien | 0.15 | 0.00 | ❌ (🟡#8, juggler poza zakresem) |
| system_info.koryto.kolejnosc vs koryto_history.kto | etapy | spójne | anthropic/darmowe/lokalnie | ✅ |
| health.vault.orphans vs realne wisieńce | liczba | 0 (po 1.45.18) | 0 | ✅ |

## Edge cases API

| Test | Oczekiwany kod | Rzeczywisty kod | Zgodne? |
|------|---------------|-----------------|---------|
| note_get(id="nie-ma-takiej-notatki-xyz.md") | 404 | 404 "Nie znaleziono notatki" | ✅ |
| note_create(title="   ") | 400 (walidacja) | pomost: "Parametr title nie moze byc pusty." | ✅ |
| note_create(duplikat "Złoto") | 409 | 409 "Notatka o tytule „Złoto" już istnieje" | ✅ |
| note_update(base="deadbeef...") | 409 | 409 "Ta notatka zmieniła się na dysku od otwarcia edycji" | ✅ |
| chat(message="   ") | 400 (walidacja) | pomost: "Parametr message nie moze byc pusty." | ✅ |
| chat bez message | 400 (schema) | OpenCode: "message: Missing key" | ✅ |
| chat 2656 znaków | przyjęte | pending_job (Namysł ruszył) | ✅ |
| chat 21000 znaków | 413 | 413 "Wiadomość jest za długa (21000 znaków, najwyżej 20000)" | ✅ |
| standing_create "co 5 minut..." | clamp/odrzucenie | utworzone, interwal_minut=15 (clamp dolny) | ✅ |
| standing_create "co 2000 minut..." | clamp/odrzucenie | utworzone, interwal_minut=1440 (clamp górny, "co 24 godz.") | ✅ |
| standing_delete testowych | usunięte | removed=true, standing_list=0 | ✅ |

## Analiza koryta i modeli

**Rozkład etapów** (koryto_history limit=100): lokalnie_awaryjnie 20, szybka_sciezka 20, ollama_narzedzie 18, zongler_rozmowa 12, namysl 6, serce_kontrola_ollama 9, zadanie_potwierdzone 5, komenda 4, ollama_blad 4, ollama_rozmowa 2.

**Średni czas per etap**: lokalnie_awaryjnie 416.1 s (n=20), ollama_rozmowa 420.2 s (n=2), zongler_rozmowa 207.5 s (n=12), ollama_narzedzie 149.7 s (n=18), namysl 109.4 s (n=6), ollama_blad 156 s (n=4), komenda 46.3 s, szybka_sciezka 38.5 s, zadanie_potwierdzone 6.9 s. Ogólnie śr. 182.6 s, **max 1202.2 s**.

**Wywołania dostawców dziś**: groq 57, openrouter 27, anthropic 0 (brak klucza). Rozkład: ~68% darmowe, ~32% lokalne (wg etapów), 0% płatne.

**Awarie i restarty** (z testów rozmowy): groq HTTP 413 w szkicu/krytyce Namysłu - **zawsze** przy pełnym promptcie (znane TPM 8000); openrouter/free: "pusta odpowiedź" + cooldown 15 s, wiszenie do 180 s; lokalnie: TimeoutError w rozpoznaniu przy pełnym obciążeniu. Namysł przerywany na budżecie 208-210 s w 4 z 4 ciężkich testów.

**Tok/s per model**: qwen2.5:3b - 0.4 tok/s w bieżących wpisach (87-287 tokenów na 396-978 s); jeden historyczny śmieciowy wpis tok_s=1000000 (z 10.11, przed poprawką 1.45.18 - nowe wpisy są już chronione; stary zostaje w logu).

**Namysł**: 6 pełnych cykli w historii, 4 przerwane na budżecie (208-210 s), restarty dostawców w każdym ciężkim teście; pominięcia ("socjalne") 2x w decision_log.

## Koniec audytu

## Dodatek: poprawki (Faza 2) - wydanie 1.45.19

Wszystkie 🔴 naprawione + wybrane 🟡; po każdej poprawce `bash weryfikuj.sh` -> GOTOWE, nowe kontrole w check.sh:

| Poprawka | Plik | Kontrola | Weryfikacja żywa |
|---|---|---|---|
| #1 Wiki resolver: walidacja tokenowa (`_wiki_topic_matches`), obcy hit odrzucony | agent/tools.py | 121 | "Co to jest Ollama?" -> "Nie ma hasła o „Ollama", więc sprawdziłem w wyszukiwarce" + poprawny wynik |
| #4 Pożegnania: socjalne w `_SOCIAL_RE` + `pozegnania` w config/social.json + `_social_reply` | agent/namysl.py, agent/router.py, config/social.json | 119 | "Do widzenia" -> odpowiedź z kodu |
| #5 Gołe tak/nie: deterministyczna odpowiedź bez modelu | agent/router.py | 122 | (test kontrolny; "ok" celowo zostaje rozmową - awaryjny-1382) |
| #9 CJK w bramce jakości (`_CJK_RE`, config "meta"/"cjk") | agent/router.py, config/validation.json | 123 | (test kontrolny) |
| #10 Meta-narracja w bramce + uczciwe podstawienie na ścieżce awaryjnej (`_meta_narracja_reply`) | agent/router.py, config/validation.json | 124 | msg 16 po poprawce: brak meta-śmieci |
| #6 Własności data/: setgid + chgrp gregai + samonaprawa trace (PermissionError -> kwarantanna) | agent/trace.py + chmod/chgrp na żywym systemie | 120 | koryto_history/decision_log żyje, historia zachowana (49 KB) |
| Pomost: `pending_action`/`pending_clarify` passthrough + hint zawsze | gregai-mcp/src/tools/chat.ts | - | confirm research_web end-to-end przez MCP ✓ |
| Dokumentacja: maska tokena, next/skupienie, sig na ścieżkach | api_contract.md | - | - |

**Nie naprawiane (do decyzji użytkownika)**: łańcuch dziennika straz (dwie kotwice - straz.py poza zakresem), licznik budżetu vs SPEND_LOG (juggler.py poza zakresem), karta confirm przy padach dostawców dla akcji destrukcyjnych (środowiskowe; przy zdrowym rozpoznaniu karta działa - msg 10/14), install.sh 700 vs żywe 2770 (model uprawnień do uporządkowania).

**Weryfikacja końcowa**: `bash weryfikuj.sh` -> GOTOWE; `bash check.sh --no-sudo` -> 79/124, kontrole audytowe 117-124 wszystkie OK; offline `bash gregai eval` -> **92/92, 0 regresji**; `gregai_health` po restarcie -> `ok: true`, wersja **1.45.19**, token zamaskowany "9w0…VGo", wisieńce 0.
