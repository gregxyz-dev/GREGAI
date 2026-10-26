# OPSEC i prywatność
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Higiena operacyjna: jak nie zostawiać po
sobie więcej śladów i danych, niż trzeba.

## Prywatność vs anonimowość vs bezpieczeństwo

- **Bezpieczeństwo**: nikt nie przejmie Twojego systemu/danych.
- **Prywatność**: wiadomo, kim jesteś, ale nie wiadomo, co robisz
  (szyfrowany ruch, mało śladów).
- **Anonimowość**: nie wiadomo nawet, kim jesteś.
To różne cele, różne narzędzia. VPN/WARP daje prywatność wobec lokalnego
dostawcy sieci, **nie** anonimowość (dostawca tunelu widzi ruch).

## OPSEC: minimalizacja śladów

- **Minimalizacja danych**: nie zbieraj i nie trzymaj, czego nie
  potrzebujesz. Czego nie ma, nie wycieknie.
- **Rozdzielanie tożsamości**: osobne maile/konta do różnych ról; jeden
  wyciek nie łączy wszystkiego.
- **Metadane zdradzają**: zdjęcia (lokalizacja EXIF), dokumenty (autor),
  czas aktywności. Czyść metadane przed udostępnieniem.
- **Powierzchnia informacyjna**: im mniej o sobie publikujesz, tym mniej
  materiału do spear phishingu (patrz [[Phishing i inżynieria społeczna]]).

## Narzędzia prywatności

- **Szyfrowany komunikator** (Signal) do rozmów wrażliwych.
- **Szyfrowany DNS** i tunel (WARP) w obcych sieciach.
- **Przeglądarka**: blokada trackerów, rozsądne ciasteczka, osobne profile.
- **Tor** dla anonimowości (wolniejszy; inne zagrożenia, trzeba umieć go
  używać poprawnie).
- **Szyfrowanie dysku i kopii** - prywatność danych w spoczynku.

## Dane w chmurze i u trzecich

- Każda usługa zewnętrzna to zaufanie komuś z danymi. Czytaj, co wysyłasz.
- W GREGAI celowo: do chmury (Claude) idzie **tylko** treść trudnego
  pytania, ostatnie tury rozmowy (bez poleceń, na które odpowiedziało narzędzie)
  i prompt systemowy GREGAI (osobowość i zasady z `agent/prompt.md`, w tym imię
  i opis zajęć właściciela, oraz opisy narzędzi), **nigdy** pliki, notatki czy dane o sieci. Router, pamięć,
  narzędzia zostają lokalnie. To minimalizacja w praktyce.

## Prawo i etyka (krótko)

- RODO/GDPR: dane osobowe wymagają podstawy, minimalizacji, ochrony.
- Testuj/badaj bezpieczeństwo tylko tam, gdzie masz **zgodę** (własny
  sprzęt, własne konta, programy bug bounty). Bez zgody to łamanie prawa.
- GREGAI pomaga się **bronić i uczyć**, nie atakować cudzych systemów.

## Codzienna higiena (lista)

1. Menedżer haseł + MFA.
2. Aktualizacje włączone.
3. Kopie zapasowe (offline) i sprawdzone odtwarzanie.
4. Tunel + HTTPS w obcych sieciach.
5. Myśl, zanim klikniesz/udostępnisz.
6. Mniej kont, mniej danych, mniej śladów.
