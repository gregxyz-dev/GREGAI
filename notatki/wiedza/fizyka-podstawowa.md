# Fizyka podstawowa
type: Wiedza

Część [[Nauka i technika]]. Wzory i zasady na poziomie szkoły podstawowej i liceum, z przykładami z techniki (rower elektryczny, bateria, laptop). Matematyczne narzędzia: [[Matematyka w praktyce]]. Elektryczność w praktyce: [[Elektronika i mikrokontrolery]].

## Jednostki i przeliczenia

- Układ SI: metr (m), kilogram (kg), sekunda (s), amper (A), kelwin (K). Siła w niutonach (N), energia w dżulach (J), moc w watach (W), ciśnienie w paskalach (Pa).
- Prędkość: 1 m/s = 3,6 km/h, więc 25 km/h ≈ 6,94 m/s. Temperatura: K = °C + 273,15.
- Zawsze przelicz jednostki do SI przed podstawieniem do wzoru (minuty na sekundy, km na m, g na kg).

## Kinematyka

- Ruch jednostajny: v = s / t, czyli s = v · t.
- Prędkość średnia = droga całkowita / czas całkowity (nie średnia z prędkości, jeśli czasy różne).
- Przyspieszenie: a = Δv / Δt. Ruch jednostajnie przyspieszony z prędkością początkową v0: v = v0 + a·t, s = v0·t + a·t²/2.
- Spadek swobodny (bez oporu powietrza): przyspieszenie ziemskie g ≈ 9,81 m/s² (w zadaniach często 10). v = g·t, h = g·t²/2.
- Droga hamowania rośnie z kwadratem prędkości. Dwa razy większa prędkość to około cztery razy dłuższa droga hamowania, dlatego rower elektryczny szybszy o kilka km/h hamuje wyraźnie dłużej.
- Wykres v(t): nachylenie to przyspieszenie, pole pod wykresem to droga.

## Dynamika

- Pierwsza zasada Newtona: bez siły wypadkowej ciało zachowuje prędkość (bezwładność).
- Druga: F = m · a. Siła ciężkości Q = m · g. Ciężar 1 kg to ok. 9,81 N.
- Trzecia: siła akcji i reakcji mają równą wartość i przeciwny zwrot, ale działają na różne ciała.
- Tarcie: T = μ · N (μ to współczynnik tarcia, N to siła nacisku). Opór powietrza rośnie z kwadratem prędkości, a moc potrzebna na jego pokonanie z sześcianem prędkości, dlatego przy dużych prędkościach zasięg rowerowy szybko spada.
- Pęd: p = m · v. W układzie zamkniętym pęd się zachowuje (zderzenia).
- Ciśnienie: p = F / S. Ciśnienie hydrostatyczne p = ρ · g · h (gęstość cieczy ρ, głębokość h). Gęstość ρ = m / V (woda ok. 1000 kg/m³, czyli 1 kg na litr).
- Prawo Archimedesa: siła wyporu = ρ_cieczy · g · V_zanurzonej.

## Praca, moc, energia

- Praca: W = F · s (gdy siła działa wzdłuż drogi). Jednostka dżul.
- Moc: P = W / t = F · v. Jednostka wat, 1 kW = 1000 W, 1 KM ≈ 735 W.
- Energia kinetyczna: Ek = m·v²/2. Energia potencjalna grawitacji: Ep = m·g·h.
- Zasada zachowania energii: energia nie ginie, zamienia się w inne formy (część zawsze przechodzi w ciepło). Bez strat: m·g·h = m·v²/2, czyli v = √(2·g·h).
- Sprawność: η = energia użyteczna / energia pobrana. Zawsze mniejsza od 1 (np. silnik elektryczny rzędu kilkudziesięciu procent do wysokich wartości zależnie od konstrukcji).
- Praktyka: wjazd rowerem pod górę wymaga energii m·g·h. Rower plus rowerzysta 100 kg na wzniesieniu 50 m to 100 · 9,81 · 50 ≈ 49 kJ, czyli ok. 13,6 Wh (1 Wh = 3600 J), bez strat.

## Ciepło

- Ilość ciepła: Q = m · c · ΔT. Ciepło właściwe wody c ≈ 4200 J/(kg·K) (dokładniej 4186). Ogrzanie 1 kg wody o 1 K to ok. 4,2 kJ.
- Przemiany fazowe (topnienie, parowanie) pochłaniają ciepło bez zmiany temperatury. Ciepło parowania wody jest bardzo duże.
- Przepływ ciepła: przewodzenie (metale przewodzą dobrze), konwekcja (ruch płynów), promieniowanie. Dlatego radiator laptopa ma metalowe ożebrowanie i wentylator.
- Rozszerzalność cieplna: ciała rozszerzają się przy ogrzewaniu.
- Procesor laptopa pobiera moc (kilkanaście W) i zamienia ją w ciepło. Brak chłodzenia daje spadek taktowania.

## Prąd elektryczny

- Natężenie I = q / t (ładunek na czas). Napięcie U to różnica potencjałów. Opór R.
- Prawo Ohma: U = I · R. Moc: P = U · I. Energia: E = P · t. Szczegóły w [[Elektronika i mikrokontrolery]].
- Obwód szeregowy: ten sam prąd, napięcia się sumują. Równoległy: to samo napięcie, prądy się sumują.
- Rachunek za energię: kWh × cena kWh. Urządzenie 100 W włączone przez 10 h zużywa 1 kWh.
- Akumulator: Wh = V · Ah. Przykład: 12 V i 7 Ah to 84 Wh.
- Pole magnetyczne wytwarza prąd. Silnik elektryczny zamienia energię elektryczną na ruch, a generator odwrotnie. Transformator zmienia napięcie przemienne (nie działa na stałym).
- Ostrzeżenie: prąd o niewielkiej wartości (rzędu kilkudziesięciu mA) przez ciało może być niebezpieczny. Szczegóły w [[Elektronika i mikrokontrolery]].

## Fale i światło

- Prędkość fali: v = λ · f (długość fali razy częstotliwość). Okres T = 1/f.
- Światło w próżni ma prędkość ok. 3·10^8 m/s. Dźwięk w powietrzu ok. 340 m/s (zależy od temperatury).
- Odbicie: kąt padania równa się kątowi odbicia. Załamanie zachodzi na granicy ośrodków.
- Częstotliwość sieci w Polsce to 50 Hz. Wi-Fi pracuje w pasmach 2,4 GHz i 5 GHz.

## Typowe pułapki

- Mieszanie jednostek (km/h z m/s, Wh z J, g z kg).
- Mylenie masy (kg) z ciężarem (N).
- Zakładanie, że 2x większa prędkość to 2x większa energia kinetyczna (jest 4x).
- Zapominanie o stratach: w praktyce sprawność jest mniejsza od 1, więc zasięg, czas ładowania i grzanie wychodzą gorzej niż w obliczeniach idealnych.
- Błędy znaków i kierunków wektorów (siły mają kierunek).
