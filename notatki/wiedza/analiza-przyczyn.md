# Analiza przyczyn
type: Wiedza

Jak od objawu dojść do przyczyny, a nie tylko gasić pożary. Część [[Sztuka
myślenia]]. Powiązane: [[Rozwiązywanie problemów]], [[Błędy poznawcze]],
[[Liczby w praktyce]].

## Objaw, przyczyna bezpośrednia, przyczyna źródłowa

- Objaw: co widzisz (spadek wyświetleń, awaria usługi, reklamacje).
- Przyczyna bezpośrednia: co to wywołało (przepełniony dysk).
- Przyczyna źródłowa: dlaczego do tego doszło i dlaczego system na to
  pozwolił (brak monitoringu miejsca, brak rotacji logów).
- Naprawa objawu przynosi ulgę na chwilę. Naprawa źródła zmniejsza liczbę
  przyszłych problemów. Zwykle warto zrobić oba: szybko ugasić, potem
  naprawić źródło.

## 5 razy dlaczego

Metoda pochodzi z Toyoty, kojarzona z Taiichim Ohno. Pytasz "dlaczego?"
kolejno, aż dojdziesz do przyczyny, na którą masz wpływ.

Przykład:
1. Dlaczego klient nie dostał zamówienia na czas? Bo paczka wyszła
   dzień później.
2. Dlaczego później? Bo zamówienie nie zostało zauważone.
3. Dlaczego? Bo powiadomienie trafiło do spamu.
4. Dlaczego? Bo adres nadawcy nie miał skonfigurowanego SPF i DKIM.
5. Dlaczego? Bo nie było listy kontrolnej uruchomienia sklepu.
   Działanie: skonfigurować uwierzytelnianie poczty i dodać listę kontrolną.

Zasady:
- Liczba 5 jest orientacyjna: czasem wystarczą 3, czasem trzeba 7.
- Odpowiedzi muszą być oparte na faktach, nie domysłach. Weryfikuj każdy
  krok.
- Unikaj zatrzymania na "człowiek zawinił". Pytaj, dlaczego system pozwolił
  na błąd (kultura bez szukania winnych).
- Ograniczenie: metoda idzie jedną ścieżką, a problemy mają często wiele
  przyczyn. Dla złożonych przypadków użyj diagramu ryby.

## Diagram ryby (Ishikawy)

- Autor: Kaoru Ishikawa. Głowa ryby to problem, ości to kategorie przyczyn.
- Przykładowe kategorie ogólne: ludzie, procesy, narzędzia, materiały
  (dane), środowisko, pomiar. Dobierz je do sytuacji.
- Burza mózgów: do każdej kategorii dopisz możliwe przyczyny, potem dopytuj
  "dlaczego" przy najbardziej obiecujących.
- Wybierz kilka najbardziej prawdopodobnych i zaplanuj, jak je sprawdzić
  (zob. [[Rozwiązywanie problemów]]). Diagram to lista hipotez, nie dowód.
- Przydatny, gdy przyczyn może być wiele (spadek zasięgów: algorytm,
  tematyka, godzina publikacji, jakość pierwszych sekund, konkurencja).

## Korelacja a przyczynowość

- Korelacja: dwie rzeczy zmieniają się razem. Przyczynowość: jedna powoduje
  drugą. Z samej korelacji nie wynika przyczynowość.
- Możliwe wyjaśnienia związku A i B: A powoduje B, B powoduje A, wspólna
  trzecia przyczyna (zmienna zakłócająca), przypadek, selekcja próby.
- Klasyczny przykład: sprzedaż lodów i liczba utonięć rosną razem, bo
  łączy je pogoda i lato.
- Odwrócona przyczynowość: osoby, które oglądają dużo poradników, nie muszą
  przez to odnosić sukcesu. Możliwe, że zainteresowani sukcesem oglądają
  więcej.
- Test: czy przyczyna poprzedza skutek? Czy związek jest silny i
  powtarzalny? Czy istnieje wiarygodny mechanizm? Czy po usunięciu
  przyczyny skutek znika? Najmocniejszy dowód to eksperyment z losowym
  przydziałem.
- Paradoks Simpsona: trend w całości może być odwrotny niż w podgrupach
  (zależnie od składu grup). Dlatego dziel dane na segmenty, zanim
  wyciągniesz wniosek.
- Regresja do średniej: po wyjątkowo dobrym lub złym wyniku następny
  zazwyczaj jest bliższy średniej bez żadnej interwencji. Nie przypisuj
  poprawy po kiepskim tygodniu swojej ostatniej zmianie.

## Eksperyment jako narzędzie

- Test A/B: zmieniaj jedną rzecz, porównuj grupy równolegle w tym samym
  czasie, a nie "przed i po" (bo zmienia się także świat).
- Ustal z góry metrykę i minimalną liczebność próby. Zbyt mała próba daje
  losowe wyniki. Szczegóły w [[Liczby w praktyce]].
- Nie zatrzymuj testu w chwili, gdy wynik ci pasuje (podglądanie zawyża
  fałszywe sukcesy).
- Gdy eksperyment jest niemożliwy, porównuj podobne przypadki i szukaj
  zmian, które zbiegają się z efektem w czasie i w dawce.

## Przy awarii technicznej

- Co się zmieniło? Ostatnia wdrożona zmiana, aktualizacja, wygasły
  certyfikat, zmiana ruchu. Dziennik zmian jest bezcenny.
- Skąd wiemy, że to ta zmiana? Cofnij ją i sprawdź.
- Po usunięciu przyczyny napisz krótki post-mortem: co się stało, jak
  wykryto, co naprawiono, co zapobiegnie powtórce. Bez szukania winnych.

## Błędy w analizie przyczyn

- Zatrzymanie na pierwszej wygodnej przyczynie.
- Mylenie okoliczności z przyczyną.
- Jedna przyczyna tam, gdzie jest ich wiele (zwykle czynnik wyzwalający i
  warunki sprzyjające).
- Ocena po wyniku: przy złym wyniku każda decyzja wygląda na błąd, zob.
  [[Błędy poznawcze]].
- Brak działania po analizie: wniosek bez zadania z terminem zostaje na
  papierze.
