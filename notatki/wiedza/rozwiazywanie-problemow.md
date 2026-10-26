# Rozwiązywanie problemów
type: Wiedza

Metoda na problemy techniczne, biznesowe i życiowe: od mglistego "nie działa"
do konkretnego działania. Część [[Sztuka myślenia]]. Powiązane: [[Analiza
przyczyn]], [[Podejmowanie decyzji]].

## 1. Zdefiniuj problem

- Zapisz jednym zdaniem: stan obecny, stan oczekiwany, różnica.
  Przykład: "strona ładuje się 8 s, a ma poniżej 2 s".
- Oddziel objaw od przyczyny. "Spadły wyświetlenia" to objaw, nie problem.
- Ustal, skąd wiesz, że problem istnieje i jak poznasz, że jest rozwiązany
  (kryterium sukcesu, najlepiej liczbowe).
- Sprawdź, czy problem jest wart rozwiązania. Część problemów lepiej
  zignorować lub obejść.

## 2. Rozbij na części

- Dziel duży problem na mniejsze, niezależne podproblemy. Dzielenie ma sens,
  gdy części można sprawdzać osobno.
- Dla systemów: wejście - przetwarzanie - wyjście. Ustal, w którym miejscu
  dane przestają być poprawne.
- Wyszukiwanie binarne usterki: wyłącz połowę elementów, sprawdź, czy błąd
  zostaje. Po kilku krokach znajdziesz winowajcę nawet wśród setek rzeczy
  (log2 z 1000 to około 10 kroków).
- Dla kodu: `git bisect` robi to automatycznie po historii zmian.

## 3. Uprość

- Zredukuj do minimalnego przykładu, który nadal pokazuje błąd. Często już
  w trakcie redukcji przyczyna staje się oczywista.
- Usuń zmienne: jedna zmiana naraz. Zmiana trzech rzeczy jednocześnie
  uniemożliwia wnioski.
- Rozwiąż najpierw prostszą wersję (mniej danych, jeden użytkownik, jedna
  platforma), potem uogólnij.
- "Wyjaśnij to gumowej kaczce": opowiadanie problemu na głos wymusza
  uporządkowanie założeń i zdumiewająco często ujawnia błąd.

## 4. Odwróć

- Zamiast "jak osiągnąć X?" zapytaj "co gwarantuje brak X?" i unikaj tego.
  Przydatne przy jakości, bezpieczeństwie i unikaniu porażek.
- Pracuj od końca: zacznij od pożądanego wyniku i cofaj się, co musi być
  prawdą bezpośrednio przed nim.
- Zapytaj, co by było, gdyby ograniczenie nie istniało, a potem, jak
  przybliżyć to tanim sposobem.
- Pre-mortem w skali problemu: "zakładam, że to rozwiązanie zawiodło, dlaczego?".
  Szczegóły w [[Podejmowanie decyzji]].

## 5. Hipotezy i najtańszy test

- Wypisz 3-5 możliwych przyczyn. Przy każdej oszacuj: prawdopodobieństwo
  (nisko/średnio/wysoko) i koszt sprawdzenia.
- Zaczynaj od hipotez o wysokim prawdopodobieństwie i niskim koszcie testu,
  nie od najciekawszych.
- Sformułuj hipotezę tak, by dało się ją obalić: "jeśli to wina cache, to po
  jego wyłączeniu czas spadnie". Hipoteza, której nic nie może obalić, nie
  pomaga.
- Najpierw sprawdź rzeczy banalne: literówka, zła wersja, brak miejsca na
  dysku, brak uprawnień, nieaktualna usługa, czy to w ogóle uruchomione.
  Wiele "tajemniczych" awarii to wygasły certyfikat, pełny dysk lub zła
  konfiguracja.
- Zbieraj dowody (logi, pomiary), zanim zaczniesz zgadywać. Mierz, nie
  zakładaj.

## 6. Działaj i ucz się

- Wykonaj test, zapisz wynik, zaktualizuj hipotezy. Prowadź krótki dziennik:
  co zmieniono, co zaobserwowano.
- Po naprawie sprawdź, czy naprawiono przyczynę, a nie tylko objaw.
  Zob. [[Analiza przyczyn]].
- Dopisz zabezpieczenie: test, alarm, lista kontrolna, komentarz w
  dokumentacji. Ten sam błąd nie powinien kosztować dwa razy.

## Kiedy utknąłeś

- Zrób przerwę lub zmień kontekst. Spacer często pomaga, choć nie jest to
  gwarancja.
- Zakwestionuj założenie, które uznajesz za pewne. Zazwyczaj to ono jest
  błędne ("na pewno to działa", "na pewno to wysłałem").
- Zapytaj kogoś lub poszukaj dokładnego komunikatu błędu w cudzysłowie.
  Opisz, co już sprawdziłeś, żeby nie dostać oczywistych rad.
- Ogranicz czas: "dam temu 30 minut, potem zmieniam podejście".
- Sprawdź, czy nie rozwiązujesz złego problemu. Czasem najlepsze
  rozwiązanie to usunięcie wymagania, kupienie gotowca lub zmiana celu.

## Błędy częste

- Skok do rozwiązania bez zrozumienia problemu.
- Naprawianie objawów (restart "pomaga") bez szukania przyczyny.
- Zmiana wielu rzeczy naraz.
- Upór przy pierwszej hipotezie (zob. [[Błędy poznawcze]]).
- Perfekcjonizm tam, gdzie wystarczy rozwiązanie wystarczająco dobre.
