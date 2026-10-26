# Elektryczny rower - podstawy
type: Wiedza

Część [[Nauka i technika]]. Wiedza do projektu konwersji roweru na elektryczny (rower 26", pełne zawieszenie, hamulce V-brake, wolnobieg). Wzory elektryczne: [[Elektronika i mikrokontrolery]], [[Fizyka podstawowa]]. Prawo i bezpieczeństwo akumulatorów mają osobne sekcje, bo błąd może być kosztowny lub niebezpieczny.

## Elementy zestawu

- Silnik, kontroler, akumulator z BMS, manetka lub czujnik asysty (PAS), czujniki hamulców, wyświetlacz, okablowanie, bezpiecznik.
- Zestaw konwersyjny zwykle zawiera silnik, kontroler, PAS, manetkę i wyświetlacz. Akumulator często kupuje się osobno.

## Silnik piastowy a centralny

- Piastowy (hub) w kole: prosty montaż, niski koszt, nie obciąża łańcucha ani przerzutek, popularny w zestawach konwersyjnych. Dostępny w kole przednim lub tylnym. Tył zwykle lepszy (przyczepność, rozkład masy). Przód jest prostszy, ale może gubić przyczepność na luźnym podłożu.
- Hub z przekładnią (geared) jest lżejszy i ma wolnobieg wewnętrzny (toczy się bez oporu przy wyłączeniu), ale ma części zużywalne. Direct drive jest cichy i trwały, ale cięższy, a przy wyłączeniu może dawać opór (niektóre mają rekuperację).
- Silnik centralny (mid-drive) przy suporcie: wykorzystuje przerzutki, lepiej się wspina, ale zużywa łańcuch i kasetę, a zestaw i montaż są droższe i trudniejsze.
- Silnik tylny do roweru z wolnobiegiem wymaga zgodności typu kółka zębatego (wolnobieg gwintowany lub kaseta). Przed zakupem sprawdź rozstaw osi tylnego widelca (zwykle 135 mm w tylnym trójkącie, ale mierz) oraz materiał ramy. Moment obrotowy silnika może wymagać stalowych blokad osi, jeśli widelec jest aluminiowy lub cienki.
- Zawieszenie pełne utrudnia umieszczenie akumulatora i okablowania, a także wymaga dopasowania mocowań.

## Kontroler

- Zamienia prąd stały z akumulatora na przebiegi zasilające silnik bezszczotkowy (BLDC).
- Parametry: napięcie pracy (musi pasować do akumulatora, np. 36 V lub 48 V) i maksymalny prąd (A). Moc maksymalna ≈ napięcie × prąd, np. 36 V × 15 A = 540 W (chwilowo). Dobierz kontroler do silnika i do zdolności akumulatora.
- Sinusoidalny działa ciszej i płynniej niż prostokątny. Czujniki hamulców odcinają napęd przy hamowaniu.
- Zabezpiecz obwód bezpiecznikiem i dobierz przewody o przekroju odpowiednim do prądu.

## Akumulator Li-ion

- Ogniwa litowo-jonowe (np. 18650, 21700): napięcie nominalne ok. 3,6-3,7 V, w pełni naładowane 4,2 V, rozładowane powyżej minimum producenta (zwykle ok. 2,5-3,0 V).
- Liczba ogniw w szeregu (S) wyznacza napięcie: 10S ≈ 36 V nominalnie (42 V pełny), 13S ≈ 48 V (54,6 V pełny), 14S ≈ 52 V. Napięcie pakietu to liczba S × napięcie ogniwa.
- Uwaga prawna: pakiet 14S (52 V) przekracza limit 48 V z polskiej definicji roweru, więc rower z takim zasilaniem nie jest już prawnie rowerem. Do legalnej konwersji wybieraj 36 V (10S) albo 48 V (13S, 48 V nominalnie).
- Pojemność w Ah rośnie przez łączenie równoległe (P). Pakiet 10S4P z ogniw 3 Ah to 10 × 3,6 V = 36 V i 4 × 3 Ah = 12 Ah.
- Energia (Wh) = napięcie × pojemność, np. 36 V × 10 Ah = 360 Wh. Zasięg orientacyjnie: energia podzielona przez zużycie. Zużycie jest różne (waga, teren, wiatr, asysta), typowo od kilku do kilkunastu Wh na km, więc zasięg zmierz w praktyce.
- Moc chwilowa ograniczona jest prądem oddawanym przez ogniwa. Ogniwa niskiej jakości lub o niskim prądzie rozładowania nie wytrzymają mocnego silnika.

## BMS

- Battery Management System pilnuje każdej grupy ogniw: ochrona przed przeładowaniem i nadmiernym rozładowaniem, przeciążeniem prądowym, zwarciem, często balansowanie ogniw i czujnik temperatury.
- BMS musi być dobrany do liczby S i do maksymalnego prądu. Niedobór prądu BMS powoduje wyłączanie pod obciążeniem.
- Nie obchodź BMS i nie łącz pakietów o różnym stanie naładowania bez wyrównania napięć.

## Prawo w Polsce (ogólnie, sprawdź aktualne przepisy)

- Zasada w Polsce (art. 2 pkt 47 ustawy Prawo o ruchu drogowym): rower to pojazd o szerokości do 0,9 m poruszany siłą mięśni; może mieć uruchamiany naciskiem na pedały pomocniczy napęd elektryczny zasilany prądem o napięciu nie wyższym niż 48 V, o znamionowej mocy ciągłej nie większej niż 250 W, którego moc wyjściowa zmniejsza się stopniowo i spada do zera po przekroczeniu 25 km/h. Tylko taki pojazd jest traktowany jak rower.
- Manetka działająca bez pedałowania, moc powyżej 250 W lub wspomaganie powyżej 25 km/h mogą zmieniać klasyfikację pojazdu (np. na motorower), co niesie wymogi dotyczące rejestracji, uprawnień i ubezpieczenia. Szczegóły i wyjątki (np. pomoc ruszania) zależą od aktualnych przepisów i normy, więc zweryfikuj w ustawie Prawo o ruchu drogowym i u producenta.
- Rower musi mieć sprawne hamulce, światła i odblask. Wymagania dla sprzętu poza drogą publiczną (teren prywatny) mogą być luźniejsze.

## Bezpieczeństwo akumulatorów

- Używaj ładowarki dedykowanej do pakietu (napięcie końcowe zgodne z liczbą S). Nie ładuj bez nadzoru, nie na łatwopalnym podłożu, nie w nocy w sypialni.
- Nie używaj uszkodzonych, spęczniałych, mokrych lub zgniecionych ogniw. Nie zwieraj. Zwarcie plusa z minusem to pożar.
- Nie ładuj poniżej 0 stopni Celsjusza i nie wystawiaj na upał. Przechowuj w chłodzie, w okolicy połowy naładowania (typowa zasada), w miejscu bez materiałów palnych.
- Pożar Li-ion trudno ugasić, może się wznawiać. Odsuń się, wezwij straż pod 112 i nie wdychaj dymu.
- Lutowanie i spawanie punktowe ogniw to praca wymagająca doświadczenia. Początkujący niech kupi gotowy pakiet z BMS od sprawdzonego dostawcy.
- Zakładaj bezpiecznik blisko akumulatora i izoluj wszystkie złącza.
