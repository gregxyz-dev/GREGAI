# Nauka i technika
type: Wiedza

Węzeł-rozdzielacz wiedzy technicznej i naukowej GREGAI. Zbiera notatki praktyczne: od sztucznej inteligencji i Linuksa, przez wideo i sieci, po rower elektryczny, elektronikę, matematykę, fizykę, telefon i ogród. Notatki są pisane pod konkretne projekty użytkownika i jego sprzęt, więc zawierają gotowe polecenia i proste reguły. Tam, gdzie wynik zależy od wersji, sprzętu lub prawa, jest to wyraźnie zaznaczone i trzeba sprawdzić aktualny stan.

## Informatyka i AI

- [[Sztuczna inteligencja i modele językowe]]: jak działa LLM, tokeny, kontekst, halucynacje, RAG, kwantyzacja, Ollama i dobór modelu do laptopa bez GPU.
- [[Sieci komputerowe - podstawy]]: IP, maska, DNS, NAT, porty, TCP/UDP, DHCP, diagnostyka (ping, traceroute, ss, dig). Przydatne przy modemie LTE i własnych serwerach.
- [[Linux: administracja zaawansowana]]: systemd, dyski i LVM, backup rsync/tar, uprawnienia, logi, cron, diagnoza wolnego systemu. Uzupełnienie [[Komendy Linuksa: system i procesy]].
- [[Android i telefony]]: ADB, tryb deweloperski, uprawnienia, bateria, miejsce w pamięci.

## Multimedia

- [[Wideo i multimedia]]: kodeki, CRF i bitrate, kontenery, typowe polecenia ffmpeg, kompresja pod YouTube, dźwięk. Podstawa stron z kompresją wideo.

## Sprzęt i elektryka

- [[Elektronika i mikrokontrolery]]: prawo Ohma, moc, Arduino, ESP32, Raspberry Pi, bezpieczeństwo.
- [[Elektryczny rower - podstawy]]: silnik, kontroler, bateria Li-ion, BMS, przepisy, bezpieczeństwo akumulatorów. Dla projektu konwersji roweru.

## Nauka ogólna

- [[Matematyka w praktyce]]: algebra, funkcje, pochodne, geometria, układy równań, trygonometria w skrócie.
- [[Fizyka podstawowa]]: kinematyka, dynamika, energia, ciepło, prąd.
- [[Ogrodnictwo warzywne - podstawy]]: płodozmian, kalendarz siewu w Polsce, podlewanie, gleba, szkodniki.

## Powiązania z innymi działami

- Bezpieczeństwo sieci i systemu: [[Cyberbezpieczeństwo]], [[Bezpieczeństwo sieci]].
- Elektronika i fizyka spinają się w rowerze elektrycznym: napięcie, prąd, moc i energia (V, A, W, Wh) to te same wzory.
- Sieci i Linux spinają się w modemie LTE i w usługach asystenta (systemd, porty, logi).
- Wideo i AI mają wspólny problem: ograniczony procesor (przykładowo starszy, 2-rdzeniowy/4-wątkowy, bez GPU), więc liczy się dobór ustawień, a nie brutalna siła.

## Zasady korzystania z tych notatek

1. Wzory i polecenia są sprawdzone, ale zawsze lepiej najpierw uruchomić polecenie w trybie bezpiecznym (np. `-n` w rsync, kopia pliku przed ffmpeg), a dopiero potem na prawdziwych danych.
2. Liczby podane jako "orientacyjnie" są rzędami wielkości, nie gwarancją. Konkretne parametry zależą od sprzętu, wersji programu i warunków.
3. Przepisy prawa (rowery elektryczne, ruch drogowy, bezpieczeństwo) zmieniają się. Notatka podaje ogólną zasadę, a ostateczne źródło to aktualny tekst przepisów lub urząd.
4. Przy pracy z prądem sieciowym 230 V, akumulatorami Li-ion i operacjami na dyskach obowiązuje ostrożność: błąd kosztuje zdrowie lub dane.
5. Gdy notatka nie wystarcza, lepiej powiedzieć "nie wiem, sprawdź w dokumentacji" niż zgadywać.

## Jak dobierać notatkę do pytania

- Pytanie o "wolny komputer", "brak miejsca", "usługa nie startuje": [[Linux: administracja zaawansowana]].
- Pytanie o "brak internetu", "który port", "jaki mam adres": [[Sieci komputerowe - podstawy]].
- Pytanie o "za duży plik wideo", "jaki kodek", "jak wyciąć fragment": [[Wideo i multimedia]].
- Pytanie o "jaki model uruchomić lokalnie", "ile RAM": [[Sztuczna inteligencja i modele językowe]].
- Pytanie o "ile wat", "ile Wh", "jaka bateria": [[Elektryczny rower - podstawy]] i [[Elektronika i mikrokontrolery]].
- Pytanie o zadanie z matematyki lub fizyki: [[Matematyka w praktyce]], [[Fizyka podstawowa]].
- Pytanie o telefon: [[Android i telefony]]. O działkę i warzywa: [[Ogrodnictwo warzywne - podstawy]].
