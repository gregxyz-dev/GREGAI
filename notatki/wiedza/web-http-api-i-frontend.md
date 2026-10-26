# Web: HTTP, API i podstawy frontendu
type: Wiedza

Część [[Programowanie]]. Jak przeglądarka i serwer rozmawiają, jak zbudować proste API w Pythonie, jak je wywołać z vanilla JS i jak uniknąć typowych problemów (CORS, tokeny). Bezpieczeństwo od strony obrony: [[Bezpieczeństwo aplikacji webowych]], sieć: [[Bezpieczeństwo sieci]].

## HTTP w pigułce

Żądanie: metoda, ścieżka, nagłówki, opcjonalne ciało. Odpowiedź: kod statusu, nagłówki, ciało.

- Metody: `GET` (odczyt, bez skutków ubocznych), `POST` (utwórz/wykonaj), `PUT` (zastąp), `PATCH` (zmień część), `DELETE`.
- Kody: `200` OK, `201` utworzono, `204` brak treści, `301/302` przekierowanie, `400` zły request, `401` brak/zły uwierzytelnienie, `403` brak uprawnień, `404` nie ma, `409` konflikt, `422` niepoprawne dane (często w API), `429` za dużo żądań, `500` błąd serwera, `502/503/504` problemy bramy lub niedostępność.
- Ważne nagłówki: `Content-Type` (np. `application/json`), `Authorization`, `Accept`, `Cache-Control`, `Set-Cookie` / `Cookie`.
- HTTPS szyfruje ruch (TLS); do wszystkiego z hasłami i tokenami używaj HTTPS.
- Testowanie z terminala:

```bash
curl -s https://example.com/api/x | python3 -m json.tool
curl -i -X POST http://localhost:8000/api/zadania \
  -H "Content-Type: application/json" \
  -d '{"tytul":"test"}'
```

(`-i` pokazuje nagłówki odpowiedzi, `-s` ucisza pasek postępu.)

## JSON

- Typy: obiekt `{}`, tablica `[]`, napis, liczba, `true`/`false`, `null`. Napisy tylko w podwójnych cudzysłowach, bez końcowych przecinków, bez komentarzy.
- Python: `json.loads(tekst)` / `json.dumps(obj, ensure_ascii=False)`; plik: `json.load(f)` / `json.dump(obj, f)`.
- JS: `JSON.parse(tekst)` / `JSON.stringify(obj)`.
- Nie ma daty ani binariów: zapisuj daty jako tekst ISO 8601, binaria jako base64 lub osobny plik.

## Minimalne API w Pythonie (stdlib)

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

class H(BaseHTTPRequestHandler):
    def _json(self, kod, obj):
        dane = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dane)))
        self.end_headers()
        self.wfile.write(dane)

    def do_GET(self):
        if self.path == "/api/ping":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"blad": "nie ma"})

    def do_POST(self):
        dlugosc = int(self.headers.get("Content-Length", 0))
        if dlugosc > 1_000_000:                     # limit rozmiaru
            return self._json(413, {"blad": "za duże"})
        try:
            wejscie = json.loads(self.rfile.read(dlugosc) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"blad": "zły JSON"})
        self._json(200, {"odebrano": wejscie})

ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
```

- Nasłuchuj na `127.0.0.1`, jeśli usługa ma być tylko lokalna; `0.0.0.0` wystawia ją w całej sieci.
- `http.server` jest do prostych zastosowań; przy większym ruchu lub potrzebie routingu użyj frameworka (np. Flask) za serwerem produkcyjnym.
- Zawsze waliduj wejście (typ, długość, zakres) i zwracaj sensowny kod statusu.

## Frontend: HTML, CSS, JS

```html
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lista</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1rem; }
    .karta { display: flex; gap: .5rem; padding: .5rem; border: 1px solid #ccc; }
  </style>
</head>
<body>
  <ul id="lista"></ul>
  <script>
    async function laduj() {
      const r = await fetch("/api/zadania");
      if (!r.ok) throw new Error("HTTP " + r.status);
      const dane = await r.json();
      const ul = document.getElementById("lista");
      ul.replaceChildren();
      for (const z of dane) {
        const li = document.createElement("li");
        li.textContent = z.tytul;      // textContent, nie innerHTML
        ul.append(li);
      }
    }
    laduj().catch(console.error);
  </script>
</body>
</html>
```

- **Dane z zewnątrz wstawiaj przez `textContent`**, nie `innerHTML` (ochrona przed XSS). Jeśli musisz wstawić HTML, oczyść go.
- `fetch` nie rzuca wyjątku dla kodów 4xx/5xx; sprawdzaj `r.ok`.
- Wysyłanie JSON: `fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(obj)})`.
- Selektory: `document.querySelector(".klasa")`, `addEventListener("click", ...)`.
- Układ: `display: flex` (jeden wymiar) i `display: grid` (dwa wymiary); media query `@media (max-width: 600px) { ... }` dla telefonu.
- Stan lokalny w przeglądarce: `localStorage` (tekst, per domena, brak szyfrowania; nie trzymaj tam sekretów). Opakuj w `try/catch`.
- Narzędzia: F12 (zakładki Console, Network, Elements) to główne narzędzie debugowania. Patrz [[Debugowanie i testowanie]].

## CORS

Przeglądarka blokuje skrypt strony z jednego źródła (schemat + host + port) przed odczytem odpowiedzi z innego, dopóki serwer na to nie pozwoli nagłówkiem `Access-Control-Allow-Origin`.

- To mechanizm przeglądarki; `curl` i serwery go nie dotyczą.
- Strona i API pod tym samym źródłem (np. serwujesz HTML z tego samego serwera) nie potrzebują CORS. To najprostsze rozwiązanie.
- Żądania "nieproste" (np. `Content-Type: application/json` w POST, nagłówek `Authorization`, metody `PUT`/`DELETE`) poprzedza zapytanie wstępne `OPTIONS` (preflight); serwer musi odpowiedzieć `Access-Control-Allow-Methods` i `Access-Control-Allow-Headers`.
- Ustaw dokładne źródło, np. `Access-Control-Allow-Origin: http://localhost:3000`. `*` jest dozwolone tylko dla publicznych danych bez uwierzytelniania i nie działa z ciasteczkami (`credentials`).
- Błąd CORS w konsoli zwykle oznacza błąd konfiguracji serwera, nie kodu JS.

## Uwierzytelnianie tokenem

- Klient wysyła token w nagłówku: `Authorization: Bearer <token>`. Serwer weryfikuje go przy każdym żądaniu (wartość z zapisanej listy lub sprawdzenie podpisu, np. JWT).
- Token generuj losowo i długo: `secrets.token_urlsafe(32)`. Porównuj stałoczasowo: `hmac.compare_digest(a, b)`.
- Przechowywanie: sekret serwera w zmiennej środowiskowej, nie w repozytorium. W przeglądarce token w `localStorage` jest narażony na XSS; ciasteczko z flagami `HttpOnly; Secure; SameSite=Lax` bywa bezpieczniejsze, ale wymaga ochrony przed CSRF przy zmianach stanu.
- Token klucza API innej firmy nie trafia do kodu frontendu: wołaj go z własnego backendu. Szczegóły w [[Uwierzytelnianie i sekrety]].
- Dodaj limit żądań i krótkie czasy życia tokenów, tam gdzie to ma sens.
