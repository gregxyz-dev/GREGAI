# GREGAI API Contract

Ten dokument opisuje **rzeczywisty** kontrakt `agent/main.py`, nie projekt
docelowy. Wszystkie odpowiedzi z danymi są JSON-em; wyjątkiem jest
`/api/chat/stream` (SSE) i pliki statyczne.

## Wspólne zasady

- Serwer: `localhost:7777` (albo LAN, gdy `GREGAI_LAN=1`).
- Autoryzacja: żądania z `127.0.0.1`/`::1` bez tokenu; zdalne wymagają
  nagłówka `X-Gregai-Token` równego `GREGAI_TOKEN` z `.env`.
- POST wymaga `Content-Type: application/json`; inny typ dostaje 415.
- Błędy mają zwykle kształt `{ "error": "komunikat" }`. Wyjątki:
  `sources` dodaje `ok`/`why`/`status`, `standing` używa `{ "ok": ..., "why": ... }`.
- Brak nagłówka `Access-Control-Allow-Origin`: API jest same-origin.
- Typowe kody: 200 OK, 400 zły JSON/dane, 401/403 brak autoryzacji,
  404 brak obiektu, 409 konflikt (duplikat/zmiana wersji), 413 za duże,
  415 zły Content-Type, 429 kolejka pełna, 500 błąd serwera.
- Limity: wiadomość `MAX_CHAT_CHARS`, body 2 MB + zapas, upload 25 MB.
- `Cache-Control: no-store` dla JSON; pliki statyczne `no-cache` + ETag/304.

## /api/chat

- Method: POST
- Request:
  ```json
  {
    "message": "str",
    "history": [{"role": "user|assistant", "content": "str"}],
    "project": "opcjonalny slug projektu",
    "client_id": "opcjonalny id idempotencji",
    "pending_action": {"id": "..."},
    "pending_clarify": [{"id": "..."}],
    "files": ["nazwa wgranego pliku"]
  }
  ```
- Response 200:
  - finalnie: `{ "speech": "str", "kind": "chat|tool", "card": {...}|null,
    "provider": "str|null", "model_active": true, "sig": "str",
    "pending_action": {...}|null, "pending_clarify": [...]|null,
    "suggested_node": {...}|null, "graph_changed": true,
    "wezly_auto": true, "wezly_since": 123 }`
  - finalny kształt może też nieść `next` (podpowiedź kolejnego kroku) i
    `skupienie`; `sig` dotyczy odpowiedzi modelu - krótkie ścieżki
    deterministyczne (powitania, zegar) go nie mają.
  - albo `{ "pending_job": "job-id" }` (długie myślenie; odbierz przez
    `/api/chat/wait`).
- Response 400/413/429/500: `{ "error": "str" }`.
- Frontend: `ui/app.js:sendChatMessage`; przy `pending_job` woła
  `/api/chat/wait` w pętli.

## /api/chat/wait

- Method: POST
- Request: `{ "job": "job-id" }`
- Response 200: ten sam finalny kształt co `/api/chat` (łącznie z `speech`,
  `kind`, `card`, `provider`, `pending_action`, `pending_clarify`,
  `suggested_node`, `graph_changed`).
- Response 200: `{ "pending_job": "job-id" }`, gdy model jeszcze liczy.
- Response 404: `{ "error": "Nie ma takiej rozmowy w toku..." }`.
- Response 500: `{ "error": "str" }` dla wyniku z błędem.
- Frontend: `ui/app.js:waitForChatJob`.

## /api/chat/stream

- Method: GET
- Query: `job=job-id`
- Response 200: `text/event-stream; charset=utf-8`
  ```
  event: token
  data: {"t":"kolejny fragment"}

  event: token
  data: {"reset":true}

  event: done
  data: {"ok":true}
  ```
- `event: err` z `{"error":"..."}` przy przekroczeniu czasu podglądu.
- Response 404: JSON `{ "error": "Nie ma takiej rozmowy w toku" }`.
- To jest **tylko podgląd**. Kanoniczny wynik zawsze przychodzi przez
  `/api/chat/wait`; zerwanie strumienia niczego nie anuluje.
- Frontend: `ui/app.js:readChatTokenStream` (fetch + ReadableStream).

## /api/chat/progress

- Method: GET
- Query: `job=job-id&since=N`
- Response 200: `{ "events": [...], "total": N, "done": true|false }`
- Response 404: `{ "error": "..." }`.
- Frontend: `ui/app.js:fetchProgress`.

## /api/chat/cancel

- Method: POST
- Request: `{ "job": "job-id" }`
- Response 200: `{ "ok": true }` albo `{ "ok": false, "why": "str" }`.
- Frontend: `ui/app.js:cancelJob` (odpowiedź nie jest potrzebna do UI).

## /api/status

- Method: GET
- Response 200:
  `{ "model_active": bool, "straz": bool, "usd": {...}|null,
     "straz_blad": str|false }`
- Frontend: `ui/app.js:refreshModelBadge`.

## /api/system_info

- Method: GET
- Response 200: duży obiekt diagnostyczny: `host`, `ollama`,
  `ollama_model`, `router`, `koryto`, `cloud`, `juggler`, `straz`,
  `budzet`, `warp`, `student`, `planner`, `warm`, `ollama_sesja`,
  `sysop`, `version`, `lan`, `project_root`, `service` (`pid`, `uptime_s`).
- `lan.token` jest ZAMASKOWANY (trzy pierwsze + "…" + trzy ostatnie znaki,
  1.45.18); pełna wartość tokena jest tylko w `.env`. Sekrety innych pól
  to wyłącznie flagi `key_present`/`token_configured`, nigdy wartości.
- Frontend: `ui/app.js:fetchNetworkState`, `ui/debug.js`, `gregai status`.

## /api/health

- Method: GET
- Response 200: `{ "ok": bool, "generated_at": "str", "version": "str",
  "service": {...}, "system": {...}, "koryto": {...}, "vault": {...},
  "wezly": {...}, "profil": {...} }`
- Bez treści notatek i sekretów.
- Frontend: `ui/health.js`.

## /api/graph

- Method: GET
- Response 200:
  `{ "nodes": [{"id","title","type","excerpt","modyfikacja","links",
  "readonly","readonly_reason"}], "edges": [{"source","target"}],
  "errors": [...], "skipped": [...] }`
- Frontend: `ui/app.js:refreshGraphData`, `ui/graph.js`.

## /api/notes

- Method: GET
- Query: `q`, `typ`, `data` (`dzis|tydzien|miesiac`), `limit`.
- Response 200: `{ "notatki": [{"id","tytul","typ","modyfikacja","okladka"}] }`
- Frontend: `ui/panele.js`.

## /api/note

- GET: query `id=slug` → `{id,title,type,text,body,version,modyfikacja,
  readonly,readonly_reason}`; 404 `{error}`.
- POST: `{ "id": "slug", "text": "str", "base": "wersja" }` → 200
  `{ "saved": true, ... }`; 409 przy zmianie wersji/tytule; 413 za duże.
- Frontend: `ui/app.js` (inspektor notatki).

## /api/note/create

- Method: POST
- Request: `{ "title": "str", "type": "str", "text": "str" }` albo
  `{ "raw": "pełny Markdown" }`
- Response 200: `{ "created": true, "id": "slug", "title": "str",
  "type": "str" }`
- 400 zły tytuł/treść, 409 duplikat tytułu, 413 za duże.
- Frontend: `ui/app.js:submitCreateNode`, karta sugestii węzła.

## /api/note/delete

- Method: POST
- Request: `{ "id": "slug", "title": "widoczny tytuł" }`
- Response 200: `{ "deleted": true, "id": "slug", "dangling_links": N,
  "repointed_links": N, "kosz": "nazwa" }`
- 404 brak, 400 readonly, 409 tytuł się zmienił.
- Frontend: `ui/app.js:deleteNote`, toast „Cofnij” wezly.

## /api/note/przywroc

- Method: POST
- Request: `{ "kosz": "nazwa wpisu" }`
- Response 200: `{ "restored": true, "file": "nazwa" }`; 409 gdy plik już jest.
- Frontend: `ui/app.js` (kosz/cofnięcie).

## /api/profil

- GET → `{ "exists": bool, "profile": {...} }`
- POST → `{ "ok": true, "exists": true, "profile": {...} }`; 400 zły JSON.
- Profil jest lokalny (`data/profil.json`), hot reload po mtime.
- Frontend: `ui/app.js:loadProfile/saveProfile`, onboarding.

## /api/sources

- GET query `chat=id` → `{ "chat": "...", "foldery": [...],
  "wgrane": [...], "wgrane_katalog": "...", "limit": N }`
- POST `{ "chat": "id", "dodaj": "ścieżka" }` albo `{ "chat",
  "usun": "ścieżka" }` → `{ "ok": bool, "why": "...", "status": {...} }`
  (200 przy ok, 400 przy odmowie).
- Frontend: `ui/app.js:loadSources/changeSources`.

## /api/upload

- Method: POST
- Request: `{ "chat": "id", "name": "nazwa", "data_base64": "..." }`
- Response 200: `{ "ok": true, "name": "nazwa", "size": N }`
- 400 zły base64/rozmiar/rozszerzenie, 413 za duże.
- Frontend: `ui/app.js:uploadAttachment`.

## /api/namysl/settings

- GET → `{ "tryb": "inteligentny"|"zawsze", "material_do_sieci": bool }`
  (domyślnie inteligentny; stary zapis `zawsze` bez `tryb_wybrany` migruje do inteligentnego).
- POST `{ "tryb": "inteligentny"|"zawsze" }` albo `{ "material_do_sieci": bool }`
  → ten sam obiekt; 400 zły typ/wartość.
- Frontend: `ui/app.js:loadNamyslSettings/saveNamyslSettings`.

## /api/wezly/ostatnie

- Method: GET
- Query: `chat=id`, `since=epoch`
- Response 200: `{ "items": [{"slug","title","type","links","hub",
  "chat","at"}] }`
- Frontend: `ui/app.js:scheduleWezlyCheck`.

## /api/rozmowa/tury

- GET query `chat=id` → `{ "tury": [...] }`
- Frontend: `ui/app.js` (odtworzenie rozmowy).

## /api/rozmowa/powrot

- GET query `chat=id` → `{...}` z podsumowaniem „gdzie skończyliśmy”.
- Frontend: `ui/app.js`.

## /api/rozmowa/usun

- POST `{ "chat": "id" }` → `{ "ok": true, ... }`; czyści pamięć rozmowy,
  źródła i wgrane TEJ rozmowy; notatki zostają.
- Frontend: `ui/app.js` (kosz rozmowy).

## /api/komendy, /api/lekcje

- GET → `{ "komendy": [...] }` / `{ "lekcje": [...] }`.
- Frontend: `ui/app.js` (podpowiedzi `/`), panele.

## /api/eval/history, /api/eval/run

- GET → historia evaluacji; POST `{...}` uruchamia eval w tle.
- Frontend: `ui/debug.js`.

## /api/diagnoza, /api/network/scan, /api/network/devices

- GET → wynik diagnozy / skanu sieci / listy urządzeń.
- Frontend: `ui/debug.js`.

## /api/standing, /api/standing/nowe, /api/standing/pauza, /api/standing/usun, /api/standing/wyczysc

- GET `/api/standing` → `{ "zadania": [...] }`.
- POST akcje → `{ "ok": bool, "why": "..."|null }`.
- Frontend: `ui/app.js` / zadania.

## /api/straz/historia, /api/straz/wycisz

- GET → historia alertów; POST `{...}` wycisza.
- Frontend: `ui/debug.js`, drawer.

## /api/budget/daily, /api/koryto/historia, /api/models/log

- GET → dzienny budżet / historia koryta / log modeli.
- Frontend: `ui/debug.js`.

## /api/debug/log, /api/debug/learned, /api/debug/learned/zapomnij,
## /api/debug/teraz, /api/debug/topic_words, /api/debug/lan

- GET/POST diagnostyka Nadzorcy; `/api/debug/lan` zmienia `.env` i wymaga
  restartu. Odpowiedź `/api/debug/lan` pokazuje token ZAMASKOWANY, chyba że
  właśnie go wygenerowano (`token_generated: true` - wtedy w całości, raz,
  żeby dało się przepisać na drugie urządzenie).
- Frontend: `ui/debug.js`.

## /api/restart

- POST → uruchamia `os.execve` po krótkim opóźnieniu; odpowiedź może zniknąć.
- Frontend: `ui/debug.js`.

## SSE – podsumowanie

- Serwer wysyła `event: token`, `event: done`, `event: err`.
- `data:` jest zawsze pojedynczą linią JSON.
- Klient nie może polegać na `done` jako źródle treści: kanoniczny wynik
  pochodzi z `/api/chat/wait`.
