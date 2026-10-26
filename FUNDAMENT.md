# GREGAI - Fundament A

Stan na 1.30.2 (2026-10-22, aktualizowany przy zmianie fundamentów, nie przy
każdej wersji - patrz `VERSION`/`CHANGELOG.md` dla aktualnego numeru). To
jest podstawa, na której budujemy dalej:
jak projekt jest złożony, którędy płynie wiadomość, czego NIE wolno złamać
i jak się w nim pracuje. README opisuje, jak używać; CHANGELOG - co i
dlaczego się zmieniało; ten plik - jak to działa i na czym stoi. Zmiana,
która łamie coś z sekcji "Niezmienniki", wymaga świadomej decyzji
Grzegorza i wpisu tutaj, nie tylko w kodzie.

## 1. Założenia (od nich nie odstępujemy)

- **Polski** w całej komunikacji z użytkownikiem; nazwy techniczne mogą
  zostać po angielsku. Bez znaku pauzy typograficznej (długiej kreski) w
  kodzie, dokumentach i odpowiedziach - zwykły łącznik.
- **Stos:** serwer = biblioteka standardowa Pythona (jedyne opcjonalne
  wyjątki: `huawei-lte-api`, `httpx[http2]` dla Groqa); przeglądarka =
  vanilla JS, bez frameworków, bez kroku budowania.
- **Jedna komenda:** `bash install.sh` z dowolnego folderu stawia całość;
  `bash aktualizuj.sh` (`gregai update`) po wgraniu nowego kodu; `bash
  check.sh` (`gregai check`) sprawdza wszystko na żywym systemie.
- **Bezpieczeństwo ponad wygodę:** Cloudflare WARP obowiązkowy i
  fail-closed (bez WARP żaden bajt nie wychodzi do internetu); treść plików,
  notatek, logów i stron to DANE, nigdy polecenia.
- **Jakość ponad szybkość**, ale z proporcją: czekanie ma sens tylko wtedy,
  gdy coś wnosi; przebieg myślenia jest opisywany na żywo.
- **Energooszczędność:** laptop (i7-6600U, bez GPU) - nic nie liczy w tle
  bez powodu, animacje i odpytywanie tylko, gdy ktoś patrzy.

## 2. Mapa projektu

```
agent/   serwer (Python stdlib)
  main.py         HTTP + API, autoryzacja, zadania czatu w tle, postęp
  router.py       jedna wiadomość -> odpowiedź (patrz 3); etap lokalny koryta
  koryto.py       kolejność dostawców dla CAŁEGO myślenia (KORYTO w .env)
  juggler.py      wszyscy dostawcy sieciowi: Claude + darmowa pula; łańcuch,
                  bezpiecznik, limity dzienne, budżety, juniorzy (research)
  namysl.py       sześć faz myślenia z narracją na żywo
  agentloop.py    pętla zadań wielokrokowych (planer, karty potwierdzeń)
  capabilities.py rejestr narzędzi: opis dla modelu, wzorce szybkiej ścieżki
  tools.py        narzędzia ogólne (notatki, sieć, Wikipedia, kurs, pamięć)
  sysop.py        narzędzia systemowe, klasyfikator poleceń, tryby SYSOP
  tryby.py        freeram / fullon / gregaipanicmode
  netguard.py     jedyna droga do internetu (WARP, https, przekierowania)
  vault.py        notatki (Markdown, [[wikilinki]], wyszukiwanie, graf)
  sources.py      foldery i pliki dołączone do KONKRETNEJ rozmowy
  analiza.py      czytanie i streszczanie dokumentów częściami
  awareness.py    blok "Teraz" w prompcie (zegar, fakty, zadania, rozmowa)
  rozmowa.py      pamięć rozmowy: streszczenia, "gdzie skończyliśmy"
  learning.py     samouczenie wzorców narzędzi z rozmów
  standing.py     zadania stałe (śledź coś w tle, alert)
  straz.py        straż systemu: patrol bez AI + rzadka ocena modelem
  persona.py      krótki prompt ucznia, reguły stylu
  pogoda.py       pogoda (Open-Meteo) i słońce liczone w kodzie (1.30.31)
  diagnoza.py     diagnoza internetu warstwa po warstwie (1.32.0)
  bramka.py       bramka odpowiedzi: oceniacze w kodzie na tekst modelu (1.32.0)
  komendy.py      komendy ukośnikowe; lekcje.py - lekcje po zgodzie (1.32.0)
  ewaluacja.py    testy regresji `gregai eval`, pass@k (1.32.0)
  prompt.md       osobowość, zasady, metoda myślenia (pełny prompt)
  trace.py        ślad decyzji (/debug), maskowanie sekretów
  pozostałe       env_loader, fsutil, heartbeat, sysinfo, siec, homenet,
                  router_bridge, symbols, slowa, data, memory
ui/      przeglądarka: index.html + app.js (rozmowa, Węzły, szufladki),
         graph.js (graf 3D, three.js lokalnie), debug.* (Nadzorca),
         styles.css (jeden :root z tokenami) + sistem.css (komponenty) + kadr.css
         (1.31.0: wygląd „Kadr” i kolory ważności, ostatnia warstwa; fonty/ lokalnie),
         dawny motyw.css scalony w 1.19.0, debug.css osobno dla /debug
training/ trening trzech własnych modeli (router, uczeń, planer)
install.sh / aktualizuj.sh / check.sh / gregai   instalacja, aktualizacja,
         kontrola (50), polecenie zbiorcze (z `update PLIK.zip` i `rollback`)
data/    stan działania (NIGDY w paczce): ślad, pary destylacji, nauka,
         notatki pamięci, dziennik SYSOP
```

API (`agent/main.py`, wszystko za `_authorized` + kontrolą Origin): `/api/chat`
(+ `/api/chat/progress`, oczekiwanie na zadanie), `/api/graph`, `/api/note`,
`/api/sources`, `/api/namysl/settings`, `/api/rozmowa/powrot`, `/api/status`,
`/api/system_info`, `/api/debug/*`.

## 3. Droga jednej wiadomości (`router.route`)

Cała obsługa wiadomości dzieje się w jednym **zakresie koryta**
(`juggler.request_scope`): wspólny budżet CZASU SIECI dla wszystkich zapytań
tej wiadomości (`KORYTO_BUDZET_WIADOMOSC_S`, 600 s; praca narzędzi się nie
liczy) i licznik porażek: dostawca, który w niej zawiódł dwa razy, jest
pomijany do jej końca (z pierwotnym powodem w komunikacie).

1. Odpowiedź na dopytanie / kartę potwierdzenia (deterministycznie).
2. Korekta ("nie o to") - cofa wyuczony wzorzec i wyklucza parę destylacji.
3. Rodzaj zadania (`agentloop.task_kind`): sekwencja, kilka poleceń, zadanie
   systemowe (także "problem + zmiana": najpierw diagnoza) -> pętla zadań.
4. Szybka ścieżka: ręczne wzorce (`capabilities`), potem wyuczone
   (`learning`). Wzorzec narzędzia, które bierze TEMAT (notatki, sieć,
   Wikipedia, zapamiętaj), bez tematu albo z samym wskazaniem ("tego
   gościa") przy istniejącej historii ustępuje routerowi; polecenia bez
   argumentu (gregaipanicmode, freeram, plan dnia) zawsze idą od razu.
5. Krok 1 - "czy i jakie narzędzie": wytrenowany router, a gdy go nie ma -
   pierwszy etap sieciowy koryta (pełne opisy narzędzi + dwie ostatnie
   wiadomości jako kontekst, limit 80 tokenów). Także przed Namysłem: Namysł
   zbiera materiał, ale nie zapisuje faktów ani nie czyta logów.
6. Narzędzie. Wynik z notatek jest CZYTANY i streszczany modelem
   (`_answer_from_notes`), nie tylko nazywany.
7. Namysł (gdy `namysl.wants`): rozpoznanie, zbieranie, szkic, krytyka,
   poprawa, sprawdzenie; zwykła rozmowa bez materiału - tylko rozpoznanie i
   szkic.
8. Rozmowa korytem (`_rozmowa_korytem`): etap po etapie, pierwszy sukces
   wygrywa; każda porażka z powodem w śladzie.
9. Gdy nic nie odpowie: tryb zapasowy ze słów kluczowych + uczciwe zdanie,
   dlaczego (w tym: "lokalnego nie użyłem, bo internet działa").

Każda droga kończy się w `_finish`: czyszczenie wycieków, zamiana długich
pauz w tekście modelu (`normalize_dashes`), odpowiedź Namysłu z prywatnego
materiału bez zgody oznaczona jak narzędzie (nie wraca do sieci), potem
`trace.record` (ślad w Nadzorcy).

**Historia** jest czyszczona RAZ (`clean_history`, idempotentne: tura już
oczyszczona niesie znacznik procesu, którego JSON z przeglądarki nie
podrobi). Do sieci idzie `_cloud_history`: rozmowa bez odpowiedzi narzędzi
i bez pytań, na które odpowiedziało narzędzie. Kontrola 27 pilnuje, żeby
historia rozmowy do sieci w ogóle docierała (1.18.0 i starsze gubiły ją
przy drugim czyszczeniu).

## 4. Koryto - kto liczy

| etap | kto | kiedy |
|---|---|---|
| `anthropic` | Claude, domyślnie `claude-haiku-5-5` | pierwszy; limit `CLOUD_DAILY_LIMIT` (300) |
| `darmowe` | Groq, Gemini, OpenRouter, Hugging Face, Cloudflare (losowo) | gdy Claude nie odpowie |
| `lokalnie` | uczeń -> Qwen2.5-3B (Ollama) | wg `KORYTO_LOKALNIE`: domyślnie TYLKO bez internetu/WARP albo bez kluczy |

Ta sama kolejność obowiązuje: rozmowę, fazy Namysłu, krok 1
(`KORYTO_ROUTING`), planer zadań (`KORYTO_ZADANIA`), streszczenia, odpowiedź
z notatek, zadania stałe. Budżet jednego łańcucha `KORYTO_BUDZET_S` (120 s).
WARP sprawdzany raz na łańcuch (wynik ważny 10 s); zablokowany WARP nie
psuje stanu dostawców. Ucięta odpowiedź każdego dostawcy jest raz
dokańczana (`_continue_once`). U Claude stała część promptu (prompt.md +
narzędzia) idzie z pamięcią podręczną, blok „Teraz” osobno.
Odpowiedź ucięta limitem tokenów jest jednorazowo dokańczana. Juniorzy
(`research`) - wyłącznie darmowa pula.

**Budżet i dziennik (1.20.0).** `data/koryto_dziennik.json` (dzień UTC,
wywołania per dostawca, wydatki USD dziś i w miesiącu) przeżywa restart i
jest jedynym źródłem dziennych limitów obok par destylacji. Wydatki Claude
to SZACUNEK z tokenów API i cen w `.env` (`KORYTO_CENA_*`);
`KORYTO_BUDZET_MIESIAC_USD` (20) i `KORYTO_BUDZET_DZIEN_USD` (1,5) wyłączają
etap `anthropic` (`juggler.over_budget`), a rozmowę przejmują darmowi albo
lokalny. Opłacona odpowiedź nigdy nie jest powtarzana u drugiego dostawcy
z powodu błędu po naszej stronie.

**Straż (`straz.py`).** Patrol bez AI co 60 s (porty LISTEN, sumy
kontrolne `.env`, kodu, kont i miejsc trwałości, katalog `/etc/sudoers.d`,
procesy z /tmp, połączenia na porty zdalnej kontroli, nieudane logowania z
`auth.log` albo z journald). `~/.ssh` jest przed usługą schowane
(InaccessiblePaths), więc `authorized_keys` NIE jest pilnowany; model
tylko dla anomalii, w limitach godzinowych i dobowych, po `trace.mask`;
bez budżetu/sieci ocenia reguła z kodu. Tylko obserwuje i alarmuje.
Baza odniesienia zeruje się przy zmianie `VERSION` (aktualizacja zmienia kod).

**Twierdza - obrona GREGAI (1.30.0, `straz.py` + `main.py`).** Czysta obrona,
która działa na miejscu, bez niczyjej pomocy. GREGAI nie kontratakuje i nikomu
nie zgłasza - broni się sam.
- **Blokada zgadywania tokenu** (`main._auth_gate`): kilka złych tokenów z
  jednego adresu i adres dostaje 429 na 15 min. Klucz blokady to PRAWDZIWY adres
  gniazda TCP (`_ban_key`), nigdy nagłówek od klienta - inaczej napastnik omijałby
  blokadę, zmieniając `CF-Connecting-IP`, albo blokował właściciela, podszywając
  jego adres (red-team 1.30.1). Zaufany localhost (fizycznie przy komputerze)
  nigdy nie jest liczony ani blokowany. Za tunnelem cloudflared wszyscy z
  internetu mają jeden kubełek - świadomy kompromis; token to 32 losowe bajty.
  Tablice `_AUTH_FAILS`/`_AUTH_BANNED` twardo ograniczone.
- **Pieczęć kodu** (`straz.seal_check`): kod (`agent/`, `ui/`, skrypty) porównany
  z sumami z paczki (`GREGAI.sha256`) przy starcie i w każdym obchodzie. Podmiana
  pliku = anomalia. Brak albo wyczyszczenie manifestu = anomalia (nie ciche
  wyłączenie). Podmiana samego manifestu przy tej samej wersji = anomalia (skrót
  manifestu trzymany z kluczem w kotwicy, patrz niżej). To integralność, nie
  autentyczność: podpis manifestu to osobny krok (dług §9).
- **Dziennik bezpieczeństwa** (`straz.log_security`, `data/straz/bezpieczenstwo.jsonl`):
  każde zdarzenie w łańcuchu KLUCZOWANYM (`h = HMAC(klucz, poprzedni + wpis)`).
  Klucz i kotwica (licznik + ostatni skrót) żyją POZA `data/`
  (`~/.config/gregai/straz.klucz`, 0600), więc napastnik, który może pisać do
  `data/straz/`, nie przeliczy łańcucha (nie zna klucza) ani nie obetnie/nie
  usunie pliku niepostrzeżenie (kotwica pamięta, ile było wpisów). `verify_seclog`
  wykrywa zmianę, przestawienie, usunięcie i obcięcie. To pamięć GREGAI o tym, że
  ktoś przy nim majstrował - dla samego GREGAI, nie dowód dla kogokolwiek.
- **Ochrona SSH** (`install.sh`, fail2ban): gdy działa serwer SSH, zgadywanie
  hasła kończy się blokadą adresu. Sprawdzamy sam jail (`fail2ban-client status
  sshd`), nie tylko demona (`GREGAI_FAIL2BAN=0` pomija).

Uczciwa granica: pełne przejęcie konta usługi (atakujący z prawami usługi) defeat
uje każdy mechanizm w procesie - przeczyta klucz z kotwicy i klucze z `.env`.
Twardsza granica to osobny użytkownik systemowy `gregai` i podpis manifestu (§9).

## 5. Granice prywatności

| co | lokalnie | sieć (każdy etap sieciowy) |
|---|---|---|
| treść rozmowy (bez odpowiedzi narzędzi) | tak | tak, sekrety maskowane |
| blok "Teraz" | pełny | zegar z godziną, liczby, bez treści notatek |
| notatki, pliki, materiał Namysłu | tak | tylko za zgodą "materiał do sieci" |
| odpowiedź z notatek w dalszej rozmowie | tak | tylko za tą samą zgodą |
| obserwacje planera zadań | tak | przy `KORYTO_ZADANIA=1`; prywatne ścieżki w trybie pełnym - karta |
| `.env`, klucze | nigdy | nigdy |

## 6. SYSOP - dwa tryby

- **Strażniczy** (domyślny): odczyt od razu, zmiana po "tak", niebezpieczne
  zablokowane na stałe; shell tylko przy `SYSOP_SHELL=1`; sudo tylko dla
  listy w `install.sh`.
- **Pełny** (`SYSOP_MODE=pelny`, wyizolowane Ubuntu): shell zawsze, cały
  system (bez `.env`), każda usługa, sudo `ALL`; odczyt i zmiany od razu,
  niebezpieczne i prywatne odczyty za jedną kartą (`SYSOP_PYTAJ`). Prywatny
  odczyt rozpoznawany jest po tekście polecenia (ścieżki, nazwy plików z
  kluczami, wzorce sięgające ukrytych katalogów, hurtowe czytanie całego
  katalogu domowego) - to karta dla typowych przypadków, nie piaskownica.
  Granicą bezpieczeństwa trybu pełnego jest wyizolowana maszyna.
- Zawsze: dziennik audytu, maskowanie, WARP dla poleceń sieciowych, odmowa
  dla poleceń, których nie da się bezpiecznie pokazać, "nie zatrzymam sam
  siebie", gregaipanicmode z wymuszonym sudo.

## 7. Niezmienniki (pilnuje ich `check.sh`)

1. Żaden ruch do internetu poza `netguard.urlopen` (wyjątek: Groq przez
   httpx, te same zasady) - kontrola 24.
2. Bez WARP sieć stoi, a lokalny model przejmuje - kontrole 15, 27.
3. Blokady bezpieczeństwa rozpoznawane bez względu na wielkość liter -
   kontrola 20; reguły sudo zgodne z trybem - kontrola 17.
4. Notatki nie idą do sieci bez zgody - kontrole 21, 22.
5. Koryto: kolejność z `.env`, porażki z powodami, lokalny wg polityki -
   kontrola 27; tryb pełny bez rozjazdów - kontrola 28.
6. gregaipanicmode odpowiada, zanim zamknie sieć - kontrola 26.
7. Prompt systemowy zostawia miejsce na 10 tur historii - kontrola 18.
8. `data/` nigdy nie trafia do paczki; paczka ma `GREGAI.sha256`, a
   `gregai update PLIK.zip` sprawdza go przed podmianą kodu.
9. Wyłącznik WARP w jądrze (nftables, cgroup usługi gregai): poza lo,
   CloudflareWARP i siecią domową nic nie wychodzi - kontrola 29.
10. Tryb SYSOP działającej usługi zgodny z `.env` - kontrola 30.
10b. Dziennik Koryta i budżet, straż, prywatne polecenia poza streszczeniem - kontrola 31.
11. Wzorce szybkiej ścieżki bez znanych fałszywych trafień (5G w
   telefonie, "co nowego w Pythonie", "daj znać kiedy skończysz") -
   kontrola 27.
12. Audyt 1.32.1: maska sekretów i wzorce bez katastrofalnego cofania,
   panicmode odcina LAN także na otwartych połączeniach, uszkodzony wpis
   dziennika bezpieczeństwa to naruszenie, wgrane pliki jednej rozmowy
   niewidoczne w innej, notatki zadań stałych bez zgody nie idą do sieci,
   pobieranie stron z limitem po rozpakowaniu i bez adresów lokalnych -
   kontrola 47.
13. Audyt tura 7 (1.32.2): planer nie zakłada zadań stałych, pogoda w pętli tylko za
   zgodą, karty i dziennik bezpieczeństwa odporne na wątki, kolejka alertów z limitem,
   aktualizacja odrzuca obce pliki i paczkę tej samej wersji z inną treścią - kontrola 48.
14. Audyt tura 8 (1.32.3): zgoda na sieć tylko dla prawdziwego true, zepsute pliki do
   kwarantanny (nigdy nadpisane pustym), straż alarmuje przy zepsutej bazie i kotwicy,
   dane w ramkach <<< >>> nie do zamknięcia - kontrola 49.
15. Decyzje 1.32.4: zapora WARP w jądrze obowiązkowa (bez niej usługa nie startuje), dostawca
   bez wskazanej kolejności zaczyna od darmowej puli, planer bez zgody nie widzi treści notatek
   i plików, model lokalny ma zwięzły prompt - kontrola 50.
16. Rozmowa 25.10 (1.32.5): etykieta klasyfikatora bezpieczeństwa nie jest odpowiedzią, cena
   rynkowa bez wyniku narzędzia nie dociera, złoto i srebro mają zapasowe źródło - kontrola 51.
17. Tura 10 (1.32.6): potwierdzenia, notowania metali po nazwie, kontekst odpowiedzi dla routera,
   bramka cen w tym samym zdaniu i wartością, klasyfikator u każdego dostawcy - kontrola 52.
18. Decyzje 1.32.7: dokładne myślenie jedynym trybem (powitania i podziękowania krótko), pigułka
   rozmowy tylko przy problemie, jednolity przełącznik widoków - kontrola 53.
19. Tura 12 (1.32.8): shell i odczyt pliku bez treści dla planera w sieci bez zgody, czas ze
   strefą (zadania stałe, straż, zegar), Namysł z tematem od routera i limitem lokalnym - kontrola 54.
20. Tura 13 (1.32.9): Namysł nie przepuszcza kwot bez pokrycia, znaczników faz, angielskiej ani
   rozdętej poprawki; instalator nie budzi fałszywych alarmów straży; bez zapory usługa stoi - kontrola 55.
21. Tura 14 (1.32.10): nic z notatek nie ginie (kosz i „Cofnij”), jeden adres z LAN nie zapcha
   serwera, plik nie zamrozi GREGAI, memory/ nie idzie jako plik do sieci, Węzły śpią - kontrola 56.
22. Tura 15 (1.32.11): narzędzia plików nie czytają notatek, pamięci ani rozmów (projekty
   naprawdę osobne), strona błędu to nie treść, zadania stałe z limitem, wzorce bez zatrucia - kontrola 57.
23. Tura 16 (1.32.12): nazwa usługi w poleceniu porównywana bez względu na wielkość liter
   (warp-svc.SERVICE), instalator nie kończy w połowie bez słowa, offline: gołe TOOL: i angielski
   szkic nie docierają, blokada internetu mówiona wprost, koryto mówi o budżecie - kontrola 58.
24. Rozmowa 25.10 wieczorem (1.32.13): liczba z notowania idzie od kodu, gdy model dopytuje o walutę;
   „w pln” dociąga kurs USD/PLN; tylko cena instrumentu bez źródła jest usuwana, bez echa liczby;
   LaTeX zamieniany na tekst; dostawca bez kredytów (402) wyłączony do restartu - kontrola 59.
25. Tura 17 (1.32.14): odpowiedź przechodzi przez czyszczenie typografii (łączniki, wąskie spacje,
   powtórzone źródła, pogrubienia, wołacz, formułki); pytanie o fakt bez recenzenta i bez
   wyszukiwarki, gdy jest notowanie; późna odpowiedź wraca do swojego pytania - kontrola 60.
26. Kolejny transkrypt (1.32.15): limit dzienny (nie minutowy) u darmowego dostawcy dostaje
   godziny przerwy, nie minuty jego własnego Retry-After; gdy wszyscy skonfigurowani sieciowi
   są naprawdę wyczerpani (`juggler.exhausted`: wyłączeni albo w przerwie wyznaczonej przez
   serwer/naszą klasyfikację, nie jedna zwykła przejściowa porażka), lokalny model odpowiada
   jako ostatnia szansa; załącznik, który nie trafił w ścisłe dopasowanie nazwy, wciąż dociera
   do Namysłu jako sama nazwa (lenientsze wyszukiwanie po źródłach rozmowy); "nie trzeba,
   dziękuję" zamyka wątek bez pełnego namysłu - kontrola 61.
27. Tura 18 (1.32.16, trzej niezależni recenzenci): zadania stałe pod jedną blokadą (bez
   wyścigu przy dwóch wiadomościach naraz); cytowanie źródła wymaga postaci "ETYKIETA:
   wartość" (zwykły powtórzony dopisek w nawiasie już nie jest kasowany); etykieta
   wewnętrzna Namysłu wycinana też w środku linii, nie tylko na początku; wołacz
   "Grzegorzu" poprawiany gdziekolwiek w zdaniu; wielokrotne spacje zwijane; dowiązanie
   do .env pod inną nazwą wykrywane w poleceniach shella (realpath, tak jak odczyt
   plików); uczenie się wzorców odrzuca wyzwalacz złożony wyłącznie z pospolitych,
   nic-nie-mówiących-o-temacie słów - kontrola 62.
28. Tura 19 (1.32.17, trzej niezależni recenzenci): wgrywanie plików pod jedną blokadą
   (dwa równoległe wgrania nie mogą już razem przebić limitu łącznego); "ps" z kolumną
   środowiska cudzych procesów (sekrety) jest zawsze zmianą, niezależnie od stylu zapisu
   (z myślnikiem czy bez); czasownik realnej prośby po podziękowaniu/potwierdzeniu budzi
   dokładne myślenie, zamiast zostać uznany za czysto społeczną reakcję; sanity-check po
   podmianie kodu przy aktualizacji (cały katalog `agent/` musi się skompilować) z
   automatycznym powrotem do poprzedniej wersji, gdy przerwanie w środku kopiowania
   zostawiło obcięty plik; czas na zamknięcie usługi systemd dopasowany do najdłuższej
   operacji zlecanej przez samego agenta (apt upgrade) - kontrola 63.
29. Tura 20 (1.32.18, trzej niezależni recenzenci, ostatnia z zaplanowanej serii
   dwudziestu): dziennik audytu Nadzorcy maskuje teraz też sekrety wpisane wprost w
   poleceniu albo jego wyniku (Bearer, JWT, hasło w adresie), nie tylko te nazwane
   w .env - jeden wspólny filtr z `agent/trace.py`, nie dwa niezależne; wołacz
   "Grzegorzu" nie jest już błędnie poprawiany, gdy "Grzegorz" jest podmiotem
   czasownika w trzeciej osobie; zapis tury do pamięci rozmowy zachowuje też kawałek
   z KOŃCA długiej wiadomości, nie tylko jej początek; strona zapasowa `/debug` sama
   prosi o token dostępu i ponawia żądanie po odmowie autoryzacji, tak jak główna
   aplikacja - kontrola 64.

## 8. Konwencje pracy

- **Komentarz mówi DLACZEGO**, z wersją i datą ("1.18.0 (zgłoszenie
  Grzegorza, ...)"); kod mówi co. Zgłoszenie z rozmowy = cytat w CHANGELOG.
- **Wydanie:** VERSION, nagłówek README, wpis "Co nowego w X" w CHANGELOG
  (co, dlaczego, jak sprawdzone - uczciwie, co NIE było sprawdzone),
  przeliczony `GREGAI.sha256`, test świeżego rozpakowania.
- **Testy:** każda poprawka zachowania dostaje kontrolę w `check.sh` na
  atrapach (bez sieci, bez Ollamy, bez zapisu do prawdziwego `data/`).
- **Weryfikacja przed "gotowe":** kompilacja, `bash -n`, `node --check`,
  wszystkie pythonowe kontrole na rozpakowanej paczce.
- **Nazwy zostawione dla zgodności** (czytają je ślad, Nadzorca, trening):
  etapy śladu `chmura_rozmowa` (= Claude), `zongler_rozmowa` (= darmowa
  pula), funkcje `cloud_status`/`juggler_status`, `_cloud_history` (= co
  widzi KAŻDY etap sieciowy). Nowy kod używa słownictwa koryta.

## 9. Znany dług (świadomie odłożony)

- (1.21.0) Manifest paczki daje integralność, nie autentyczność (brak podpisu).
- (1.28.0) Wiedza sprawdzona z aktualnymi źródłami 2026-10-22 (prawo e-roweru,
  prawa konsumenta, KSeF, OWASP 2025, Ubuntu 26.04, Python 3.14, pisownia 2026).
- (1.21.0) Wiedza (`notatki/wiedza`) pisana jednorazowo przez Claude: daty,
  prawo i ceny w niej zawarte trzeba okresowo weryfikować; notatki wskazują
  źródła, tam gdzie to się zmienia.

- (1.20.0) Obserwacje narzędzi odczytowych pętli (notatki) idą do planera
  przez koryto bez `material_do_sieci` - do decyzji razem z zadaniami stałymi.
- (1.23.0) Zapora WARP: Ollama ma RestrictNetworkInterfaces=lo CloudflareWARP
  (działa od systemd 251, czyli Ubuntu 24.04; na 22.04 systemd ignoruje to
  ustawienie). Zapytania DNS przez lokalny resolver (127.0.0.53) przy
  rozłączonym WARP nadal mogą zdradzić nazwę hosta dostawcy internetu;
  bezpośredni DNS do routera usługa ma zablokowany.
- (1.23.0) Straż widzi już procesy z katalogów tymczasowych i połączenia na
  porty zdalnej kontroli, ale bez roota tylko procesy własnego użytkownika;
  połączenia na zwykłe porty (443) do obcych serwerów są dla niej niewidoczne.

- CSS (po scaleniu w 1.19.0: 3 pliki zamiast 4, ok. 430 deklaracji mniej,
  wygląd sprawdzony porównaniem stylów obliczonych w 28 stanach) nadal ma
  deklaracje nadpisywane w każdym sprawdzonym stanie, ale nie DOWODNIE
  martwe (hover/focus niesprawdzone) - zostają do przeglądu z pokryciem
  hover/focus.
- Rozmowy w przeglądarce trzyma localStorage (per urządzenie). Od 1.23.0
  pusta rozmowa proponuje wczytanie tur z serwera (rozmowa.py), ale serwer
  zna tylko tekst (karty i wyniki narzędzi to skróty).
- Zadania stałe wysyłają do sieci zlecenie, stan i streszczenie zebranych
  informacji (mogą pochodzić z notatek) bez pytania o zgodę
  `material_do_sieci` z Namysłu. Tak było od początku zadań stałych; do
  decyzji, czy mają podlegać tej samej zgodzie. (Od 1.19.0 zadanie nie
  czyta już własnej notatki jako "wyniku".)
- Fakty z „Zapamiętaj” (memory/) nie idą do sieci, więc Claude ich nie
  zna; widzi je tylko lokalny model. Do decyzji: przełącznik w `.env`.
- Tryb pełny działa na koncie Grzegorza (`NOPASSWD: ALL` dla jego konta);
  osobny użytkownik systemowy `gregai` dałby twardszą granicę. Do decyzji.
- Klucze API leżą w czytelnym dla usługi `.env`. Klasyfikator łapie
  typowe próby wyniesienia, ale skrypt, który sam czyta `.env`, przejdzie;
  jedyna mocna poprawka to klucze w pliku tylko dla roota
  (`EnvironmentFile=`). Do decyzji.
- Krok 1 przez sieć to osobne zapytanie przed odpowiedzią; scalenie
  decyzji o narzędziu i odpowiedzi w jedno wywołanie zmniejszyłoby koszt o
  połowę, ale zmienia kontrakt routera i trening - do osobnej decyzji.
- Trzy własne modele trzeba przetrenować po zmianach promptów planera i
  narzędzi (manifesty same je wyłączą do tego czasu).

- (1.32.20, tura 2/5, ROZWIĄZANE) `training/*.jsonl` uczyły model dosłownie
  "Grzegorz Żelazowski" - zamienione na "administrator tej instalacji" we
  wszystkich przypadkach gramatycznych (`distill_seed.jsonl`,
  `teacher/tozsamosc.jsonl`, `ewaluacja/regresja.jsonl`), spójnie z domyślnym
  `persona.CREATOR`.
- (1.32.20, tura 2/5, ROZWIĄZANE) `notatki/wiedza/*.md` nie podaje już
  konkretnego modelu laptopa/telefonu autora jako rzekomo uniwersalnego
  faktu - zamienione na generyczne opisy (starszy CPU bez GPU, starszy
  telefon Android), treść merytoryczna (porady o ustawieniach) bez zmian.
- (1.32.20, tura 2/5, ROZWIĄZANE) `SECURITY.md` dodany; `requirements.txt` ma
  teraz przypięte wersje (dolna granica = przetestowana, górna = następny
  major); `ROADMAP_1.0.md` ma banner "dokument historyczny" u góry;
  `FUNDAMENT.md` i `PROTOKOL_TWIERDZA.md` mają dopisek tłumaczący, że
  nagłówek z numerem wersji to data ostatniej zmiany fundamentu, nie
  oznaka nieaktualności; README ma sekcję "Dokumentacja" mapującą rolę
  każdego pliku top-level.
- (1.32.19 -> 1.32.21, tura 3/5, ROZWIĄZANE) Nazwa użytkownika "Grzegorz"
  była wpisana na trwałe w `agent/prompt.md` (ok. 10 wystąpień), w wołaczu
  `agent/bramka.py` i w kilkunastu INNYCH promptach wysyłanych do modeli,
  odkrytych dopiero osobnym przeglądem w tej turze (streszczenie rozmowy,
  cztery etapy Namysłu - w tym druga kopia szczegółu finansowego "budżet
  operacyjny na ok. 3 miesiące" - etykiety mówcy w kontekście rozmowy w
  trzech miejscach, podsumowanie wyszukiwania, opis `gregaipanicmode`, tryby
  `/plan` i `/sprawdz`, moduł lekcji, pętla agenta, skrócony prompt czatu).
  Rozwiązane trzema kluczami `.env` (`GREGAI_USER_NAME`, `_GENITIVE`,
  `_VOCATIVE` w `persona.py`), z domyślną wartością odtwarzającą dawny
  literał - zero zmiany zachowania, dopóki nikt nie ustawi `.env`. Świadomie
  BEZ automatycznej odmiany dowolnego imienia przez polskie przypadki
  (nieregularna deklinacja, zła zgadnięta forma gorsza niż nieodmieniona) -
  kto zmienia imię, podaje własne, poprawnie odmienione formy.
- (1.32.21 -> 1.32.23, tury 3/5 i 5/5, ROZWIĄZANE w ograniczonym, świadomym
  zakresie) Założenie rodzaju męskiego w instrukcji stylu dla modelu
  ("Grzegorz to mężczyzna: formy męskie") było wpisane na trwałe w trzech
  miejscach (`agent/awareness.py`, `agent/namysl.py` x2). Po sprawdzeniu w
  turze 5/5 okazało się to węższe niż zapisano wyżej w turze 3/5: tylko te
  trzy literalne miejsca, nie koniugacja w wielu plikach. Rozwiązane
  kluczem `.env` `GREGAI_USER_GENDER` (puste/"m" = męski domyślnie - zero
  zmiany zachowania; "z" = żeński) w `persona.py`
  (`USER_GENDER_NOUN`/`USER_GENDER_FORMS`/`USER_GENDER_FORM_LOC`). Klucz
  steruje WYŁĄCZNIE treścią instrukcji stylu - sama poprawność gramatyczna
  generowanego tekstu zależy od modelu, dokładnie tak, jak zależała zawsze
  (kod nigdy nie wymuszał koniugacji, tylko o nią prosił). Przy tej okazji
  regex wołacza w `agent/bramka.py` (rozpoznawanie, kiedy imię użytkownika
  jest podmiotem trzeciej osoby, a kiedy zwrotem wprost) rozszerzony, by
  łapać też żeński/neutralny czas przeszły ("-ła"/"-ło"), nie tylko męski
  ("-ł") - inaczej zwrot wprost (przy `GREGAI_USER_GENDER=z`) byłby mylony
  z podmiotem. Świadomie POZA zakresem, i zostaje: WŁASNA, pierwszoosobowa
  mowa GREGAI o sobie ("Zapisałem", "Sprawdziłem" - męski czas przeszły)
  jest wpisana literalnie w setkach miejsc w całym kodzie jako głos
  asystenta, nie odnosi się do użytkownika i jest zmianą wykraczającą daleko
  poza tę serię pięciu tur - nie jest to "pozostałość" w rozumieniu tej
  serii, tylko świadomie nieruszany, odrębny temat na przyszłość.
- (1.32.22, tura 4/5, ROZWIĄZANE) `install.sh`/README opisywały zaporę
  Cloudflare WARP jako bezwarunkowo obowiązkową, bez wyjaśnienia, że to
  świadoma decyzja bezpieczeństwa tego projektu (jednoosobowa, izolowana
  maszyna z realną władzą SYSOP-a) - nie techniczny wymóg samego programu.
  README ma teraz akapit "Skąd ten priorytet" na początku sekcji
  "Bezpieczeństwo"; `install.sh` ma analogiczne doprecyzowanie w
  komentarzu. Świadomie BEZ flagi instalatora `--no-warp`: inny rozkład
  warstw obrony wymaga realnej zmiany kodu (`nftables` w `install.sh`,
  `agent/netguard.py`), nie przełącznika - cofanie decyzji 1.32.4 nie jest
  "sprzątaniem pozostałości". Tabela "Sprzęt" w README ma teraz akapit
  "to maszyna referencyjna, nie minimalne wymagania" (wcześniej README
  obiecywał to wyjaśnienie gdzie indziej, bez treści za obietnicą).
  `PROTOKOL_KONTROLI.md` (audyt 1.29.0) oznaczony jako dokument historyczny,
  jak `ROADMAP_1.0.md` w turze 2.
- (1.32.22, tura 4/5, ROZWIĄZANE) Dodatkowy przegląd `agent/*.py`: cztery
  nieużywane importy (`capabilities_mod` w `main.py`, `datetime` na
  poziomie modułu w `namysl.py`, `functools` w `vault.py`) i zbędny
  `global _ANCHOR` w `straz.py:_load_anchor` (funkcja tylko czyta, nigdy
  nie przypisuje) usunięte; `.gitignore` uzupełniony o standardowe wpisy
  edytorów/systemów (`.vscode/`, `.idea/`, `.DS_Store`, `*.pyo`,
  `.pytest_cache/`).
- (1.32.23, tura 5/5, ostatnia tury serii, ROZWIĄZANE) `LICENSE` miał
  wciąż `Copyright (c) 2026 Grzegorz Żelazowski` - ostatnie pełne nazwisko
  autora w publicznie wysyłanej części repo poza `CLAUDE.md` (ten jest w
  `.gitignore`). Wykryte niezależnym przeglądem na koniec tej tury, nie
  złapane w turach 1-4 mimo szerokiego genericowania gdzie indziej. Zmienione
  na `Copyright (c) 2026 GREGAI project`. Gender w promptach opisany
  wyżej w tej samej sekcji.
- **Koniec serii pięciu tur przygotowania pod open source (1.32.19 ->
  1.32.23).** Kontrole 65-69 w `check.sh` pilnują każdej z pięciu tur.
  Znane, świadomie pozostawione ograniczenia na przyszłość, żadne z nich
  blokujące publikacji: (a) własna, pierwszoosobowa mowa GREGAI o sobie
  pozostaje gramatycznie męska w setkach miejsc (opisane wyżej); (b)
  automatyczna polska deklinacja dowolnego podanego imienia/nazwiska
  użytkownika nie jest próbowana (kto zmienia `GREGAI_USER_NAME`, podaje
  własne poprawne formy, patrz tura 3/5 wyżej); (c) `CONTRIBUTING.md` i
  konfiguracja CI świadomie nie istnieją - to projekt jednego użytkownika
  na własnym sprzęcie, nie projekt zespołowy czekający na kontrybutorów
  z zewnątrz, więc dodanie ich teraz byłoby pozorowaniem procesu, którego
  nikt nie będzie prowadził.
