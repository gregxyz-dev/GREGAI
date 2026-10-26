# Protokół Twierdzy GREGAI (wynik testu red-team 1.30.0 -> 1.30.1)

Dla Ciebie, do odczytu. GREGAI broni się sam: nie kontratakuje, nikomu nie
zgłasza, niczego nie udaje. Czysta obrona, która działa na miejscu.

Opisane mechanizmy obrony są częścią fundamentu (patrz `FUNDAMENT.md`) i nie
są świadomie osłabiane w kolejnych wersjach - nagłówek odnosi się do wersji,
w której zostały przetestowane red-teamem, nie do tego, że są nieaktualne.

## Cztery mechanizmy

1. **Blokada zgadywania tokenu** (`agent/main.py`). Kilka złych tokenów z jednego
   adresu i adres dostaje 429 na 15 minut. Twój laptop (fizycznie przy komputerze)
   nigdy nie jest blokowany.
2. **Pieczęć kodu** (`agent/straz.py: seal_check`). GREGAI przy starcie i co minutę
   porównuje swój kod z sumami kontrolnymi z paczki. Podmiana pliku albo usunięcie
   sum = alarm.
3. **Dziennik bezpieczeństwa** (`data/straz/bezpieczenstwo.jsonl`). Łańcuch
   kluczowany HMAC; klucz i kotwica poza `data/`. Napastnik nie podrobi, nie
   obetnie ani nie usunie wpisów niepostrzeżenie.
4. **Ochrona SSH** (fail2ban, jeśli masz serwer SSH).

## Atak czerwonego zespołu (niezależny) i co znalazł

Po pierwszej wersji (1.30.0) napuściłem na to niezależnego atakującego na kopii
testowej. Rozbił trzy z czterech mechanizmów. Wszystko załatane w 1.30.1 i
sprawdzone ponownie.

| # | Zarzut (1.30.0) | Stan (1.30.1) |
|---|---|---|
| 1 | Blokadę tokenu dało się omijać, zmieniając nagłówek `CF-Connecting-IP` co próbę | naprawione: liczy się prawdziwy adres gniazda, nie nagłówek |
| 2 | Napastnik mógł zablokować właściciela, podszywając jego adres w nagłówku | naprawione: jw. (nagłówek ignorowany) |
| 3 | Tablica blokad rosła bez końca (zalew pamięci) | naprawione: twardy limit |
| 4 | **Łańcuch dziennika był bez klucza - dało się go przeliczyć od nowa** | naprawione: HMAC z sekretem poza `data/` |
| 5 | Usunięcie albo obcięcie pliku dziennika nie było wykrywane | naprawione: kotwica (licznik + ostatni skrót) |
| 6 | Rotacja dziennika psuła weryfikację (fałszywy alarm) | naprawione |
| 7 | Usunięcie `GREGAI.sha256` cicho wyłączało pieczęć | naprawione: brak/zmiana manifestu = alarm |
| 8 | fail2ban: sprawdzaliśmy demona, nie sam jail | naprawione: `fail2ban-client status sshd` + `python3-systemd` |

Sprawdzone ponownie: 33 kontrole, testy jednostkowe (rotacja nagłówka nie omija
blokady; odtworzenie łańcucha bez klucza, usunięcie i obcięcie - wszystko
wykryte), ponowny atak czerwonego zespołu.

## Uczciwa granica

Pełne przejęcie konta usługi GREGAI defeat uje każdy mechanizm w procesie:
atakujący z prawami usługi przeczyta klucz z kotwicy i klucze z `.env`. Twardsza
granica to osobny użytkownik systemowy `gregai` i podpis manifestu - osobne,
większe kroki na liście długu (FUNDAMENT §9), do Twojej decyzji.

Czego GREGAI świadomie NIE robi: nie kontratakuje (to w Polsce przestępstwo i
uderzyłoby w niewinnych, bo napastnik działa z cudzego sprzętu), nie zgłasza
nikomu, nie nagrywa. Odbija atak, blokuje, pamięta - i tyle.
