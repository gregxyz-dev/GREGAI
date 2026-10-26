# Elektronika i mikrokontrolery
type: Wiedza

Część [[Nauka i technika]]. Podstawy elektroniki i wybór płytki (Arduino, ESP32, Raspberry Pi). Zastosowania: czujniki, sterowanie, projekty typu HUD, powiązania z [[Elektryczny rower - podstawy]] i [[Fizyka podstawowa]].

## Wielkości i jednostki

- Napięcie U (wolt, V), prąd I (amper, A), rezystancja R (om, Ω), moc P (wat, W), energia E (Wh lub J).
- Prawo Ohma: U = I · R, czyli I = U / R i R = U / I.
- Moc: P = U · I. Z prawa Ohma także P = I² · R = U² / R.
- Energia: E = P · t. 1 Wh = 3600 J, 1 kWh = 3,6 MJ. Pojemność akumulatora w Ah × napięcie = Wh.
- Przedrostki: m (mili, 10^-3), k (kilo, 10^3), M (mega, 10^6), µ (mikro, 10^-6). 1 kΩ = 1000 Ω, 500 mA = 0,5 A.

## Rezystory

- Szeregowo: R = R1 + R2 (prąd ten sam). Równolegle: 1/R = 1/R1 + 1/R2, dla dwóch R = R1·R2 / (R1+R2) (wypadkowa mniejsza od najmniejszej).
- Dzielnik napięcia: U_wy = U_we · R2 / (R1 + R2). Służy do zmniejszania napięcia czujnika lub do pomiaru napięcia akumulatora wejściem analogowym.
- Dioda LED: rezystor ograniczający R = (U_zas - U_led) / I_led. Przykład: zasilanie 5 V, LED czerwona ok. 2 V, prąd 10 mA daje R = 3 V / 0,01 A = 300 Ω (praktycznie wybierz bliższą wartość, np. 330 Ω). LED bez rezystora się spali.
- Moc na rezystorze nie może przekroczyć jego mocy znamionowej (typowo 0,25 W). Rezystory kolorowe odczytuje się z tabeli lub multimetrem.
- Podciąganie (pull-up) 10 kΩ utrzymuje wejście w stanie wysokim, gdy przycisk jest rozwarty.

## Kondensatory i diody

- Kondensator magazynuje ładunek: filtruje zasilanie, wygładza zakłócenia. Elektrolityczny ma biegunowość, odwrotne podłączenie może go uszkodzić lub rozerwać. Napięcie pracy kondensatora musi być wyższe od napięcia w obwodzie.
- Dioda przewodzi w jedną stronę. Dioda zabezpiecza przed odwrotną polaryzacją i tłumi przepięcia indukcyjne (dioda równoległa przy cewce przekaźnika lub silnika).
- Tranzystor (MOSFET, BJT) działa jak sterowany przełącznik. Mikrokontroler nie powinien bezpośrednio zasilać silnika lub przekaźnika, bo jego pin daje tylko niewielki prąd (rząd kilkudziesięciu mA według noty konkretnego układu), więc użyj tranzystora lub modułu sterownika.

## Mikrokontroler a komputer jednopłytkowy

- Arduino (np. Uno z układem ATmega328P): prosty mikrokontroler, 5 V, brak systemu operacyjnego, program w C/C++ działa w pętli od razu po włączeniu, czas reakcji przewidywalny. Dobry na początek i do prostych czujników, silników, serw.
- ESP32: mikrokontroler z Wi-Fi i Bluetooth, logika 3,3 V, dużo większa moc niż Arduino Uno, programowanie w Arduino IDE, MicroPythonie lub ESP-IDF. Dobry do IoT, czujników sieciowych i projektów bateryjnych. Piny nie tolerują 5 V.
- Raspberry Pi: pełny komputer z Linuksem (Wi-Fi, USB, HDMI, GPIO 3,3 V). Uruchamia Pythona, serwery, kamerę, model AI. Pobiera więcej prądu, wymaga bezpiecznego wyłączania, nie ma gwarantowanego czasu rzeczywistego. Dobry na serwer domowy lub mózg projektu.
- Raspberry Pi Pico (RP2040): tani mikrokontroler, MicroPython/C.
- Reguła: do prostego czujnika i szybkiej reakcji weź mikrokontroler, do sieci i obliczeń Linuksa weź Raspberry Pi, do bateryjnego IoT z Wi-Fi weź ESP32.

## Poziomy logiczne i zasilanie

- 5 V i 3,3 V to dwa standardy logiki. Łączenie 5 V do wejścia 3,3 V może uszkodzić układ. Użyj konwertera poziomów lub dzielnika napięcia.
- Zasilanie USB daje 5 V i prąd zależny od portu (typowo 500 mA do 900 mA dla USB 2 i 3 w specyfikacji, zasilacze więcej). Moduły (silniki, paski LED) mogą wymagać osobnego zasilacza, a masy (GND) trzeba połączyć.
- Wspólna masa jest warunkiem poprawnej komunikacji między dwoma urządzeniami z różnymi zasilaczami.

## Komunikacja

- UART (TX/RX): dwa przewody, prosta transmisja, np. do GPS lub modułów. TX łączy się z RX drugiego urządzenia.
- I2C: dwa przewody (SDA, SCL), wiele urządzeń na jednej magistrali, adresy. SPI: szybsza, więcej przewodów (MOSI, MISO, SCK, CS). PWM: regulacja jasności i prędkości silnika wypełnieniem impulsów.
- ADC odczytuje napięcie analogowe (rozdzielczość w bitach zależy od układu, ESP32 ma nieliniowość i potrzebuje kalibracji).

## Narzędzia

- Multimetr: napięcie, ciągłość (piszczenie), rezystancja, prąd (pomiar szeregowo w obwodzie, uwaga na zakres i bezpiecznik). Najpierw mierz napięcie, a nie prąd.
- Płytka stykowa (breadboard) do prototypów, lutownica z topnikiem do trwałych połączeń.
- Karta katalogowa (datasheet) to źródło prawdy o pinach i maksymalnych napięciach.

## Bezpieczeństwo

- Napięcia małe (do kilkudziesięciu V stałych, USB, 3,3 V, 5 V, 12 V) są względnie bezpieczne dla człowieka, ale zwarcia i akumulatory Li-ion grożą pożarem i poparzeniem. Patrz [[Elektryczny rower - podstawy]].
- Napięcie sieciowe 230 V AC jest śmiertelne. Nie rozbieraj zasilaczy pod napięciem, nie buduj własnych urządzeń podłączanych do gniazdka bez odpowiedniej wiedzy. Kondensatory w zasilaczach trzymają ładunek po odłączeniu. Użyj gotowych, certyfikowanych zasilaczy.
- Odłącz zasilanie przed zmianą połączeń. Sprawdzaj biegunowość przed włączeniem. Przy lutowaniu wentyluj i nie dotykaj grota.
- Lutowanie ołowiowe wymaga mycia rąk, a topnik daje opary.
- Podłączaj silniki i przekaźniki przez zabezpieczenia (dioda, bezpiecznik).
