# Audyt GREGAI - 2026-11-11

Audyt autonomiczny przez pomost MCP (`gregai-mcp`, 34 narzędzia) na żywym
systemie GREGAI v1.45.17 (`localhost:7777`, usługa aktywna, PID 1563).
Faza 1: tylko odczyty i testy rozmowy; zapisy w GREGAI - wyłącznie te, które
są częścią normalnej rozmowy (powitanie, test pamięci, zapytanie o cenę).

## Podsumowanie

- Wersja: **1.45.17**
- Health: **OK** (`ok: true`, usługa active/running, uptime 38 min przy starcie audytu)
- Węzły: **134**, Krawędzie: **273** (typy: Wiedza 60, Nauka 43, Wiki 16, Journal 15; errors 0, skipped 0)
- Aktywne zadania stałe: **0** (pusta lista, nic do sprawdzenia w dzienniku)
- Budżet: **0.00 / 1.50 USD** (dziś), **0.00 / 20 USD** (miesiąc) - ale patrz 🟡#3: dziennik nie widzi 0.60 USD z SPEND_LOG
- Straż: **6 alertów w ostatnich 24 h** widocznych w historii (port 8123/43363 = usługi testowe OpenCode; 4x "kod GREGAI zmieniony: ui/crack.css" = lokalne zmiany przed wydaniem); wyciszone: puste
- Diagnoza sieci: **Internet działa na wszystkich warstwach** (WARP OK, netguard OK, DNS 49 ms, DuckDuckGo/Bing/Wikipedia/Coinbase/Groq/OpenRouter odpowiadają)
- Eval: **1 rekord** (2026-11-04, wersja 1.32.30, 59/59) - zaległy, patrz 🟢#4

## Znaleziska

### 🔴 Błędy (blokują funkcję)

| # | Obszar | Opis | Dowód (tool + output) |
|---|--------|------|----------------------|
| 1 | Bezpieczeństwo API | `/api/system_info` zwraca **token LAN w czystym tekście** (`lan.token`). Kontrakt dla `/api/health` mówi "bez sekretów"; `system_info` jest dostępne z localhost bez tokenu, więc każdy lokalny proces (i strona same-origin) może odczytać token uprawniający do pełnego API z LAN. | `gregai_system_info` -> `"lan": {"enabled": true, "token_configured": true, "token": "9w0X..."}` (pełne 43 znaki) |
| 2 | Graf / diagnostyka | **Metryka "wisieńców" jest odwrócona** w `agent/ops.py::_vault_state` (linie 409-417): wpis trafia do `orphan_list`, gdy link **zawiązał się pomyślnie** (`target` znaleziony), a pomijany jest, gdy cel nie istnieje (`if not target ... : continue`). Efekt: health pokazuje `vault.orphans: 433`, podczas gdy prawdziwych wisieńców (cele bez pliku) jest **0** (433 = wszystkie zawiązane linki nie-samowskie; liczenie tym samym kodem rozwiązywania). Zgubione linki są niewidoczne, a health pokazuje fałszywy alarm. | `gregai_health` -> `"vault": {"orphans": 433, ...}`; skrypt liczący logiką `build_vault`: RAW=433, resolved_nonself=433, dangling=0 |
| 3 | Straż / integralność | **Łańcuch dziennika bezpieczeństwa nie przechodzi weryfikacji**: `dziennik_bezp: {ok: false, wpisy: 927, zerwane_w: 1, "brakuje wpisów z początku dziennika"}`. Wykrywanie działa zgodnie z projektem (kotwica pamięta 932 wpisy, plik ma 927), ale stan jest naruszony od zdarzenia "odtworzona: usunięta (2026-11-06 11:23)". Przyczyna prawdopodobnie: **dwa klucze/kotwice** przy współdzielonym pliku - usługa działa jako `gregai` (kotwica w `~gregai`, `log_n: 932`, wersja 1.45.17), a ręczne uruchomienia jako `gregxyz2` mają własną, starą kotwicę (`log_n: 699`, wersja 1.39.1) i inny klucz HMAC w `~gregxyz2`. Wspólne dopisywanie do `data/straz/bezpieczenstwo.jsonl` z dwóch tożsamości psuje spójność łańcucha i licznika. | `gregai_system_info` -> `straz.dziennik_bezp`; pliki: `data/straz/bezpieczenstwo.jsonl` (927 rekordów wg weryfikatora, 928 linii surowo), backupy `.przed-20261106T*`; kotwice z obu HOME |

### 🟡 Ograniczenia (działa, ale nieoptymalnie)

| # | Obszar | Opis | Dowód | Sugestia |
|---|--------|------|-------|----------|
| 1 | Budżet / metric | **Log inferencji pakuje śmieciowy `tok_s: 1000000`** przy `tokeny: 1`, `sekund: 976.26` (wywołanie, które wisiało 16 min i zwróciło 1 token; `router.py:1380` dzieli przez `eval_s` ~1 µs). Taki rekord zatruwa medianę tok/s w `ollama_sesja`. | `gregai_models_log` -> `{ts: 2026-11-10T13:26:29, tok_s: 1000000, tokeny: 1, sekund: 976.26}` | W `router.py::_log_ollama_use` zwracaj `tok_s: null`, gdy `eval_s < 0.1` albo `tokeny < 2`. |
| 2 | Budżet / spójność | **Licznik budżetu nie widzi realnych wydatków**: `SPEND_LOG` (koryto_wydatki.jsonl) ma 4 wpisy po 0.15 USD w tym miesiącu (3x 2026-11-09, 1x 2026-11-11 08:41 UTC), a `usd_dzien`/`usd_miesiac` w `koryto_dziennik.json` = **0.00**. Tę samą rozbieżność widać w jednej odpowiedzi `/api/budget/daily` (`budzet.dzien: 0`, `wydatki: [usd: 0.15]`). | `gregai_budget` -> `{budzet: {dzien: 0, miesiac: 0}, wydatki: [{usd: 0.15, ts: 2026-11-11T08:41:41}]}` | Skrypty `spent_usd`/`_note_spend` są w juggler.py (zasada audytu: nie ruszać); do zbadania poza audytem: zapis dziennika przy uruchomieniach mieszanych (usługa `gregai` vs ręczne `gregxyz2`) - plik ma własność mieszaną (`gregai` vs `gregxyz2`). bezpiecznik "dziennik nieczytelny = Claude czeka" działa fail-safe, ale tu plik jest czytelny, tylko suma jest zerowa. |
| 3 | Koryto / czas | **Budżety czasowe miękkie**: `KORYTO_BUDZET_S=120`, a historia etapów pokazuje `zongler_rozmowa` 459 s, 511/532 s, `ollama_narzedzie` 310 s, `lokalnie_awaryjnie` 371 s, rekord 989 s (16,5 min). Rozmowa testowa o BTC potrzebowała >120 s (2 awarie dostawców: groq HTTP 413 - znane TPM 8000, openrouter "pusta odpowiedź" -> cooldown, potem lokalnie). | `gregai_koryto_history` sekundy: [205.2, 459.3, 459.3, 511.6, 532.6, 989.2...]; `gregai_chat` ("Ile kosztuje 1 BTC?") -> timeout pomostu po 120 s, zadanie dokończone serwerowo | Rozważyć twardy deadline łańcucha albo wyraźne raportowanie przekroczenia w `decision_log`. |
| 4 | Pomost MCP | **`gregai_chat` przy porażce sieci w pętli wait gubi podpowiedź**: gdy czekający POST /api/chat/wait wywala się na timeout fetch, odpowiedź ma `{error, job, progress_events: []}` bez `hint` (hint trafia tylko do ścieżki zaplanowanej) - agent widzi ślepy błąd, choć zadanie żyje po stronie serwera. Druga lakierka: dokumentacja `gregai_straz_history` sugerowała poziomy "low/medium/high", a rzeczywiste to "średnie/wysokie/inne". | `gregai_chat` ("Zapamiętaj...") -> `{"error": "...aborted due to timeout", "job": "HoUmOSmZ6nZwZmW0puLrew", "progress_events": []}`; serwer dokończył: "Zapisane: mój ulubiony kolor to turkusowy." | W gregai-mcp/src/tools/chat.ts: przy rejection też zwracać `hint` i częściowe `progress_events`; poprawić opis enum poziomów. |
| 5 | Kontrakt API | `api_contract.md` nie opisuje pól `next` i `skupienie` w finalnej odpowiedzi czatu (widziane w `/api/chat/wait`), a `sig` bywa nieobecny na szybkich ścieżkach deterministycznych (kontrakt wymienia `sig` w finalnym kształcie). | `gregai_chat_wait` -> keys: [speech, card, model_active, kind, next, skupienie]; `gregai_chat` ("Cześć!") -> bez `sig` | Uaktualnić api_contract.md (to dokument, nie ui/). |
| 6 | Straż / UX danych | Alerty Straży są wklejane do `speech` rozmowy (`"🔔 Straż systemu: nowy port nasłuchujący: 43363..."` przed właściwą odpowiedzią). Dla agenta MCP alert miesza się z treścią odpowiedzi. | `gregai_chat_wait` -> speech zaczyna się od alertu, potem "BTC/USD: 73 839,37" | Zgodne z projektem GREGAI (UI wycina alert do toasta); pomost MCP mógłby zwracać `alert` jako osobne pole. Nie blokuje. |

### 🟢 Sugestie (nice-to-have)

| # | Obszar | Opis |
|---|--------|------|
| 1 | Bezpieczeństwo | `.env` ma prawa 640; zalecane 600 (ostrzeżenie `gregai state`). |
| 2 | Sieć | Skan urządzeń poprawnie odmawia na sieci nie-domowej (brama 192.168.122.1 - libvirt), stąd `urzadzenia: 0`; oczekiwane w tym środowisku, ale w health widać pustkę bez wyjaśnienia - endpoint mógłby zwracać `skan.skipped` w health. |
| 3 | Pomost MCP | Brak narzędzia `gregai_namysl_settings` (endpoint `/api/namysl/settings` istnieje w GREGAI). W audycie oznaczone jako nieprzetestowane. |
| 4 | Evaluacja | Historia eval jest zaległa: 1 rekord z 2026-11-04, wersja **1.32.30** (59/59), czyli sprzed 12 wydań. Po poprawkach audytu uruchomić szybki eval offline (`bash gregai eval`, bez `--zywo`). |
| 5 | Wiedza | Graf jest zdrowy: 0 błędów, 0 pominiętych, maskowanie kodu działa (bashowe `[[ -f ... ]]` w blokach nie tworzą linków); 31 notatek bez połączeń (izolowane) i naturalne wisieńce zamiaru `[[Programowanie]]` itd. to kandydaci do ręcznego domknięcia, nie błąd. |
| 6 | Straż | Dedyplikacja alertów działa (34 dedup_wpisy); "kod GREGAI zmieniony: ui/crack.css" to lokalne, zamierzone zmiany przed wydaniem - do potwierdzenia przez wersjonowanie (pieczęć przebazuje się przy bump VERSION). |

## Testy rozmowy

| Wiadomość | Odpowiedź (skrót) | Czas | Provider | Fazy | Uwagi |
|-----------|-------------------|------|----------|------|-------|
| "Cześć!" | "Cześć! W czym mogę pomóc?" | 0.1 s | (brak - deterministycznie) | brak (szybka ścieżka) | kind=tool, bez sig |
| "Jaka jest godzina?" | "Jest 14:19 CET." | 0.1 s | (brak) | brak | poprawna strefa, zgodna z systemem |
| "Dziękuję" | "Nie ma za co!" | 0.1 s | (brak) | brak | krótko, bez Namysłu |
| "Ile kosztuje 1 BTC?" | "BTC/USD: 73 839,37" + karta (type/query/symbol/source/data) | >123 s w pomoście; dokończone serwerowo | groq -> openrouter -> lokalnie (2 restarty Namysłu) | rozpoznanie, zbieranie (sieć: 5 wyników + notowanie btcusd), szkic, restart x2 | narzędzie rynku zadziałało, cena ma źródło; groq HTTP 413 (TPM 8000 - znane), openrouter pusta odpowiedź + cooldown 15 s |
| "Zapamiętaj: mój ulubiony kolor to turkusowy" | "Zapisane: mój ulubiony kolor to turkusowy." | >83 s w pomoście; dokończone serwerowo | (ścieżka narzędziowa, brak faz w progress) | brak zdarzeń | potem `gregai_notes_list typ=Memory` -> `2026-11-11-moj-ulubiony-kolor-to-turkusowy.md` - fakt trwale zapisany |

## Pokrycie testów

Przetestowano: health, system_info, status, graf (pełny + spójność wikilinków na 4 notatkach różnych typów), notes_list (bez filtrów, `q=`, `typ=Note`/`Wiedza`/`Nauka`/`Memory`, `data=dzis`), note_get x4, chat x5 + chat_wait x2, standing_list, koryto_history(50), straz_history(50), budget, models_log(30), decision_log(30), profile_get, sources_get, network_devices, diagnoza, eval_history(20). Pomocniczo (lokalne CLI, read-only): `gregai state --orphans`, skrypty python na `agent/vault.py`.

**Nieprzetestowane / nieobowiązkowe**: `note_create`/`note_update`/`note_delete`/`note_restore`, `standing_create/pause/delete/clear`, `sources_add/remove`, `upload`, `chat_cancel` (wszystkie to operacje zapisu - poza zakresem audytu read-only); `network_scan` (uruchamia skan - pominięto); `eval_run` (start evaluacji - pominięto); `gregai_namysl_settings` (brak takiego narzędzia w pomoście); `chat_cancel`/`chat_wait` na żywym Namyśle w fazach (tylko wait na dokończonych zadaniach).

## Koniec audytu

## Dodatek: po poprawkach (Faza 2, 2026-11-11 14:39)

Wydanie **1.45.18** (VERSION + CHANGELOG, `bash weryfikuj.sh` -> GOTOWE):

- 🔴#1 (token LAN): maska `_mask_token` w `agent/main.py`; na żywej usłudze
  `/api/system_info` zwraca `lan.token: "9w0…VGo"` (kontrola **117** OK,
  statycznie + offline).
- 🔴#2 (wisieńce): warunek odwrócony w `agent/ops.py::_vault_state`;
  na żywej usłudze `vault.orphans` = **0** (przed poprawką fałszywe 433)
  (kontrola **118** OK na atrapie vaulta: zawiązany / wiszący /
  samowskazanie).
- 🟡 (tok_s): strażnik w `agent/router.py::_log_ollama_use`
  (`eval_s >= 0.1` i `tokeny >= 2`).
- 🟡 (pomost): `gregai_chat` zwraca `hint` także przy porażce sieci w
  pętli wait; opis poziomów w `gregai_straz_history` zgodny z wartościami
  ("średnie"/"wysokie"/"inne").
- `api_contract.md`: maska tokena, pola `next`/`skupienie`, `sig` tylko
  na ścieżkach modelowych. `check.sh`: TOTAL 116 -> 118, banner poprawiony.
- `bash check.sh --no-sudo`: 73/118 OK (pominięte: 1), kontrole 117/118 OK.
  Pełny przebieg z sudo wymaga hasła z terminala - do uruchomienia przez
  użytkownika (`bash check.sh`).

Nienaprawiane (świadomie): łańcuch dziennika bezpieczeństwa (🔴#3 - stan
operacyjny: dwie kotwice przy mieszanych uruchomieniach, wymaga decyzji,
nie łatki w straz.py) i rozbieżność licznika budżetu z SPEND_LOG (🟡#2 -
juggler.py poza zakresem poprawek audytu).
