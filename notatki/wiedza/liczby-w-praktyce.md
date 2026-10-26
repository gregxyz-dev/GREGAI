# Liczby w praktyce
type: Wiedza

Niezbędnik liczbowy do codziennych decyzji, biznesu i oceny doniesień. Część
[[Sztuka myślenia]]. Powiązane: [[Podejmowanie decyzji]], [[Analiza
przyczyn]], [[Weryfikacja źródeł i research]].

## Rzędy wielkości

- Pytaj najpierw "ile zer?", nie "ile dokładnie?". Pomyłka o czynnik 10
  zmienia decyzję, pomyłka o 5% rzadko.
- Przydatne stałe: doba to 86 400 s, rok to około 31,5 mln s (3,15 * 10^7),
  rok ma około 8760 godzin, 1 GB to 10^9 bajtów (w uproszczeniu).
- Sprawdzaj sensowność: jeśli wynik pokazuje, że kanał zarobi miliony po
  tygodniu, to założenia są błędne.

## Szacowanie Fermiego

Metoda przypisywana Enrico Fermiemu: rozbij nieznaną wielkość na kilka
składników, które potrafisz oszacować, i pomnóż.

Przykład: ile klientów dziennie potrzeba, by zarobić 3000 zł miesięcznie
przy marży 15 zł na zamówieniu?
- 3000 / 15 = 200 zamówień na miesiąc, czyli około 7 dziennie.
- Jeśli konwersja wynosi 2%, potrzeba około 350 odwiedzin dziennie.
Efekt: od razu widać, czy cel jest realny przy obecnym ruchu.

Zasady:
- Rozbij na 3-5 czynników, każdy oszacuj zakresem (min-max).
- Błędy częściowo się znoszą (jedne za wysokie, drugie za niskie).
- Zapisz założenia, żeby móc je później poprawić.
- Sprawdź wynik drugą, niezależną drogą (z góry na dół i z dołu do góry).

## Procenty

- Procent a punkt procentowy: wzrost z 2% do 3% to +1 punkt procentowy i
  +50% względnie. Doniesienia często mieszają te dwie rzeczy.
- Spadek o 50% wymaga potem wzrostu o 100%, by wrócić do punktu wyjścia.
  Spadek o 20% wymaga +25%.
- Marża a narzut: cena 100, koszt 80 daje marżę 20% (od ceny) i narzut 25%
  (od kosztu). Ustal, o którą chodzi.
- Zawsze pytaj: procent czego? Niskie wartości bazowe dają efektowne
  wzrosty ("sprzedaż wzrosła o 300%": z 1 do 4 sztuk).

## Procent składany

- Wzrost o r% w każdym okresie: wartość = start * (1 + r)^n.
- Reguła 72: czas podwojenia w latach to około 72 / r (r w procentach).
  Przy 7% około 10 lat, przy 10% około 7 lat.
- 1% poprawy dziennie przez 365 dni daje około 38-krotność (1,01^365),
  ale jest to model teoretyczny: realne poprawy nie trwają tak liniowo.
  Wniosek praktyczny: małe stałe usprawnienia i małe stałe koszty
  (prowizje, opłaty, odsetki) działają silnie w długim czasie.
- Odsetki od zadłużenia składają się w tę stronę, której nie chcesz.
  Porównuj oferty po rzeczywistej rocznej stopie (RRSO).
- Inflacja to ujemny procent składany dla gotówki.

## Średnia, mediana, rozrzut

- Średnia: suma podzielona przez liczbę. Mediana: wartość środkowa po
  posortowaniu. Przy rozkładach z "ogonami" (zarobki, wyświetlenia filmów,
  wielkość zamówień) średnia jest zawyżana przez skrajne wartości,
  a mediana lepiej pokazuje typowy przypadek.
- Przykład: filmy mają 100, 120, 150, 180 i 50 000 wyświetleń. Średnia
  to około 10 110, mediana 150. Planuj według mediany, marz według średniej.
- Zawsze patrz też na rozrzut (min, max, kwartyle). Średnia 10 przy
  zakresie 9-11 to co innego niż przy 0-100.
- Wielkość próby: błąd sondażu to orientacyjnie 1 / pierwiastek z n.
  Dla 100 osób około 10 punktów procentowych, dla 1000 około 3. Mała
  próba daje przypadkowe wyniki, więc nie wyciągaj wniosków z trzech
  filmów lub pięciu klientów.

## Podstawy prawdopodobieństwa

- Zakres od 0 do 1 (0-100%). Zdarzenia dopełniające: P(nie A) = 1 - P(A).
- Zdarzenia niezależne: P(A i B) = P(A) * P(B). Co najmniej jedno z n prób
  przy szansie p: 1 - (1 - p)^n. Przy szansie 5% na próbę i 20 próbach to
  około 64%, nie 100%.
- Prawdopodobieństwo warunkowe i twierdzenie Bayesa: wiarygodność
  wyniku zależy od częstości bazowej.
  Przykład: choroba dotyka 1% osób, test ma czułość 90% i 9% fałszywych
  alarmów. Na 10 000 osób: 100 chorych, z czego 90 wykrytych; 9900 zdrowych,
  z czego 891 fałszywych alarmów. Dodatni wynik oznacza chorobę z
  szansą 90 / (90 + 891), czyli około 9%. To samo dotyczy detektorów
  spamu, alarmów bezpieczeństwa i filtrów treści.
- Złudzenie gracza: kolejne rzuty są niezależne. Seria nie "wyrównuje się".
- Ludzie źle czują małe szanse i duże liczby. Zamień szanse na
  częstości ("1 na 1000") i licz na przykładowej grupie.

## Wartość oczekiwana

- EV = suma (prawdopodobieństwo * wynik) po wszystkich scenariuszach.
- Przykład: eksperyment kosztuje 200 zł, daje 10% szansy na 3000 zł zysku
  i 90% na zero. EV = 0,1 * 3000 - 200 = 100 zł. Opłaca się powtarzać, jeśli
  stać cię na serię nieudanych prób.
- Dodaj też czas i uwagę jako koszt, a nie tylko pieniądze.
- Ograniczenia: EV ignoruje ryzyko ruiny. Przy zakładzie z szansą bankructwa
  nie wolno ufać średniej. Szacunki prawdopodobieństw są często
  wyssane z palca, więc rób analizę wrażliwości: co, jeśli szansa to 3%
  zamiast 10%?
- Dla serii zakładów licz też wariancję: nawet dodatni EV może oznaczać długie
  serie strat.

## Kontrola jakości liczb

- Jednostki i okresy: zł a tys. zł, na miesiąc a na rok.
- Skąd dana liczba? Zob. [[Weryfikacja źródeł i research]].
- Nie mierz tylko tego, co łatwe. Dobra metryka musi odpowiadać celowi,
  inaczej jej optymalizacja szkodzi (prawo Goodharta: gdy miara staje się
  celem, przestaje być dobrą miarą).
