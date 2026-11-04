# Bezpieczeństwo

GREGAI ma realny dostęp do komputera, na którym działa (SYSOP, Straż, Koryto),
więc bezpieczeństwo jest deklarowanym priorytetem projektu (patrz `FUNDAMENT.md`
i `PROTOKOL_TWIERDZA.md`). Jeśli znalazłeś/aś podatność, zgłoś ją prywatnie.
Publiczne issue daje przepis atakującym, zanim zdąży powstać łatka.

## Zgłaszanie podatności

**Nie otwieraj publicznego issue na GitHubie.** Napisz na:

**security@example.com**

> To placeholder. Przed publikacją repozytorium zastąp go realnym adresem,
> na który faktycznie odbierasz pocztę.

W zgłoszeniu podaj:

- wersję GREGAI (`VERSION` albo `/debug`),
- system (np. Ubuntu 24.04, Python 3.12),
- kroki odtworzenia (najkrótsze, jakie wystarczą),
- oczekiwany i rzeczywisty wynik,
- realny skutek: co atakujący zyskuje i w jakich warunkach.

**Czas reakcji (SLA):**

- potwierdzenie przyjęcia zgłoszenia: **72 godziny**,
- poprawka albo konkretny plan z terminem: **30 dni**.

Jeśli poprawka wymaga większej zmiany architektury, dostaniesz uczciwą
informację o stanie prac i nowym terminie, zamiast ciszy.

Alternatywnie, jeśli repozytorium ma włączone prywatne zgłoszenia podatności,
możesz użyć GitHub Security -> Report a vulnerability. To kanał dodatkowy,
nie zastępuje adresu e-mail.

Projekt nie oferuje wynagrodzenia za zgłoszenia (bug bounty). Każde sensowne
zgłoszenie zostanie przeczytane i poważnie potraktowane.

## Zakres

W zakresie są pliki utrzymywane w tym repozytorium:

- **`agent/` (Python)** - logika serwera i API, SYSOP, Straż, Koryto, bramka
  odpowiedzi, obsługa notatek i plików.
- **`ui/` (vanilla JS)** - XSS, CSP, obsługa tokenu dostępu, autoryzacja
  żądań z przeglądarki.
- **`install.sh`, `aktualizuj.sh`, `check.sh`** - łańcuch dostaw: pobieranie,
  weryfikacja sum, instalacja zależności, aktualizacja i audyt.

## Poza zakresem

Te elementy są zależnościami systemowymi, nie kodem GREGAI. Podatności w nich
zgłaszaj ich autorom:

- **Ollama** - lokalne modele i serwer inferencji.
- **Cloudflare WARP** - tunel sieciowy i klient.
- **systemd** - jednostki usług, sandboxing procesów.

Zgłoszenia dotyczące konfiguracji tych zależności (np. błędna jednostka
`gregai.service`) nadal są w zakresie, bo pliki jednostek są w repozytorium.

## Znane ograniczenia

To świadome decyzje, nie przeoczenia. Zgłoszenie ich jako podatności jest
mile widziane jako dyskusja o modelu zagrożeń, ale nie jest błędem do naprawy
w ramach SLA:

- **`SYSOP_MODE=pelny` oznacza sudo bez hasła do wszystkiego.** GREGAI może
  wtedy wykonać dowolne polecenie administracyjne. To świadoma decyzja dla
  jednej, wyizolowanej maszyny (laptop bez innych użytkowników i bez
  wrażliwych danych); nie używaj tego trybu na maszynie współdzielonej.
- **`GREGAI_LAN=1` wystawia panel w sieci domowej.** Dostęp jest chroniony
  tokenem, ale każdy w tej samej sieci widzi otwarty port. Domyślnie panel
  słucha wyłącznie na `localhost`.
- **Killswitch WARP opiera się na `nftables` i wymaga roota.** Bez uprawnień
  administracyjnych reguła zapory nie powstanie; instalator wymaga więc sudo,
  a brak WARP oznacza brak ruchu sieciowego (fail-closed), nie obejście.
