# Sztuczna inteligencja i modele językowe
type: Wiedza

Część [[Nauka i technika]]. Jak działają duże modele językowe (LLM) i jak uruchamiać je lokalnie na laptopie bez karty graficznej, tak jak robi to GREGAI przez Ollamę.

## Jak działa LLM

- Model przewiduje kolejny token na podstawie wszystkich poprzednich. Odpowiedź powstaje token po tokenie. Nie "wie" faktów jak baza danych: ma w parametrach (wagach) skompresowane wzorce z danych treningowych.
- Sieć to Transformer: mechanizm uwagi (attention) pozwala każdemu tokenowi "patrzeć" na wcześniejsze. Rozmiar modelu to liczba parametrów (np. 3B = 3 miliardy).
- Trening wstępny uczy języka i wiedzy ogólnej. Dostrajanie na instrukcjach (instruct, chat) uczy wykonywania poleceń. Do uruchamiania rozmów wybieraj wersje "instruct".

## Tokeny i kontekst

- Token to kawałek słowa, nie słowo. Dla języka polskiego wychodzi zwykle więcej tokenów na słowo niż dla angielskiego, bo słowa są dłuższe i odmienione. Dokładną liczbę zależy zmierzyć tokenizerem danego modelu.
- Okno kontekstu to maksimum tokenów naraz: prompt + historia + odpowiedź. Po przekroczeniu początek jest obcinany lub błąd.
- Pamięć na kontekst (cache KV) rośnie z długością kontekstu. W Ollamie domyślny kontekst bywa mały i zależy od wersji, więc ustawia się go jawnie opcją `num_ctx`. Większy kontekst = więcej RAM i wolniej.
- Prędkość: generowanie na CPU ogranicza głównie przepustowość pamięci, więc mniejszy i mocniej skwantyzowany model jest szybszy.

## Halucynacje

- Model potrafi pewnym tonem podać nieprawdę: zmyślone cytaty, liczby, nazwy poleceń. Mniejsze modele (3B) robią to częściej.
- Ograniczanie: dawać źródła w prompcie (RAG), prosić o odpowiedź tylko z podanego tekstu, dopuścić odpowiedź "nie wiem", niska temperatura, weryfikacja ważnych faktów.

## Temperatura i próbkowanie

- Temperatura 0 lub niska (np. 0.1-0.3): odpowiedzi stabilne, dobre do faktów, kodu, wyciągania danych.
- Wyższa (0.7-1.0): bardziej kreatywne, mniej powtarzalne. Wartości dokładne zależą od modelu.
- `top_p` i `top_k` ograniczają pulę kandydatów. Zwykle wystarczy zmieniać jedną gałkę naraz.

## Prompting

- Jasna rola i zadanie: kto, co, w jakim formacie, jaka długość.
- Podaj kontekst i przykłady (few-shot): 1-3 wzorcowe odpowiedzi działają lepiej niż długi opis.
- Format wyjścia: "odpowiedz w JSON z polami ..." ułatwia parsowanie.
- Rozbijaj duże zadania na kroki. Małe modele lepiej radzą sobie z krótkimi, konkretnymi poleceniami.
- Prompt systemowy trzyma stałe zasady (persona, język polski, zakazy). Dane od użytkownika oddzielaj od instrukcji, bo tekst z zewnątrz może próbować przejąć sterowanie (prompt injection). Patrz [[Cyberbezpieczeństwo]].

## RAG, fine-tuning, prompt

- RAG: wyszukaj fragmenty notatek (słowa kluczowe lub embeddingi), wklej do promptu, model odpowiada na ich podstawie. Tak działają notatki wiedzy GREGAI. Zalety: aktualne dane, łatwa aktualizacja (edytujesz plik), mniej halucynacji, źródło można wskazać.
- Fine-tuning zmienia wagi: dobry do stylu, formatu, specjalnego zadania. Zły do dopisywania faktów (zapamiętuje słabo i niepewnie). Wymaga danych i mocy obliczeniowej, na CPU jest bardzo wolny.
- Kolejność prób: najpierw lepszy prompt, potem RAG, dopiero na końcu fine-tuning.
- Embedding to wektor liczb opisujący sens tekstu. Podobieństwo (cosinus) znajduje pokrewne fragmenty nawet bez tych samych słów.

## Kwantyzacja

- Zmniejsza precyzję wag (np. z 16 bitów do ok. 4), co zmniejsza plik i RAM kosztem niewielkiej utraty jakości.
- Wzór orientacyjny: rozmiar w GB ≈ parametry (mld) × bity na wagę / 8. Model 3B w 4 bitach to ok. 2 GB, 7B ok. 4-5 GB. Do tego kontekst i narzut.
- Oznaczenia: Q4_K_M to popularny kompromis, Q8_0 prawie bez strat ale dwa razy większy, Q2/Q3 wyraźnie gorsze.

## Ollama

- `ollama pull nazwa:tag` - pobierz. `ollama run nazwa` - rozmowa w terminalu. `ollama list` - zainstalowane. `ollama ps` - co załadowane w pamięci. `ollama rm nazwa` - usuń. `ollama serve` - serwer.
- API HTTP domyślnie na `http://localhost:11434` (np. `/api/chat`, `/api/generate`, `/api/embed`). Zmiana adresu: zmienna `OLLAMA_HOST`. Nie wystawiaj portu do internetu bez uwierzytelnienia, patrz [[Sieci komputerowe - podstawy]].
- Modelfile pozwala ustawić `FROM`, `PARAMETER temperature 0.2`, `PARAMETER num_ctx 4096`, `SYSTEM "..."`. Tworzenie: `ollama create nazwa -f Modelfile`.
- `keep_alive` decyduje, jak długo model zostaje w RAM po odpowiedzi. Pierwsze zapytanie po rozładowaniu jest wolne.

## Dobór modelu do CPU i RAM (starszy CPU, bez GPU)

- Procesor ma 2 rdzenie i 4 wątki, więc generowanie jest wolne: rzędy kilku tokenów na sekundę dla modeli 1-3B, wyraźnie wolniej dla 7B. Dokładne tempo zmierz sam.
- Zasada: model plus kontekst musi się zmieścić w wolnym RAM, inaczej zacznie się swap i wszystko stanie. Sprawdź `free -h`.
- Praktyka: 1-3B w Q4 do szybkich odpowiedzi i narzędzi, 7-8B tylko gdy jest dość RAM i cierpliwość. Do trudniejszych zadań użyj zewnętrznego modelu (np. Claude Haiku), a lokalny zostaw do prostych rzeczy.
- Uruchamiaj ciężkie zadania z niskim priorytetem (`nice -n 19`), by laptop nie przegrzewał się i pozostał użyteczny. Patrz [[Linux: administracja zaawansowana]].
