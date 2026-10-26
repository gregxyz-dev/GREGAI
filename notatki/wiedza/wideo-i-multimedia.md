# Wideo i multimedia
type: Wiedza

Część [[Nauka i technika]]. Kodeki, kontenery, kompresja i ffmpeg. Podstawa stron z kompresją wideo działających w przeglądarce (FeatherCut, FeatherClip) i przygotowania filmów pod YouTube. Polecenia z tej notatki zostały sprawdzone w ffmpeg z kodekami libx264, libx265, libvpx-vp9, libsvtav1, aac, libmp3lame.

## Kodek a kontener

- Kodek (codec) kompresuje obraz lub dźwięk. Kontener (MP4, MKV, WebM, MOV) pakuje strumienie obrazu, dźwięku i napisów w jeden plik. Rozszerzenie pliku nie mówi, jaki jest kodek w środku: `ffprobe plik.mp4` pokaże.
- MP4: najbardziej kompatybilny (H.264/H.265 + AAC). WebM: VP9 lub AV1 + Opus. MKV: elastyczny, wiele ścieżek, gorzej na telefonach i w przeglądarkach.

## Kodeki wideo

- H.264 (AVC, `libx264`): standard wszędzie, szybki koder, dobra jakość. Domyślny wybór.
- H.265 (HEVC, `libx265`): przy podobnej jakości plik mniejszy (rzędu kilkudziesięciu procent), ale kodowanie znacznie wolniejsze, a odtwarzanie w przeglądarkach bywa ograniczone licencyjnie i sprzętowo. Dla zgodności w przeglądarce Apple użyj tagu `-tag:v hvc1`.
- VP9 (`libvpx-vp9`): wolny koder, dobra jakość, wsparcie YouTube i przeglądarek, kontener WebM.
- AV1 (`libsvtav1`, `libaom-av1`): najlepsza kompresja, ale kodowanie na CPU bez GPU jest bardzo wolne. SVT-AV1 jest szybszy od libaom. Dekodowanie sprzętowe jest na nowszych urządzeniach, na starszych odtwarzanie obciąża procesor.
- Na starszym CPU bez GPU realistyczny kompromis to H.264 z presetem `medium` lub `fast`. Cięższe kodeki wymagają dużo czasu.

## Bitrate a CRF

- Bitrate (kb/s lub Mb/s) to ile danych na sekundę. Rozmiar pliku ≈ (bitrate wideo + bitrate audio) × czas / 8.
- CRF (Constant Rate Factor) trzyma stałą jakość, a rozmiar wynika z treści (ruch, szczegóły). Niższy CRF = lepsza jakość i większy plik. H.264: skala 0-51, domyślnie 23, zakres sensowny orientacyjnie 18-28. H.265: domyślnie 28. VP9: `-crf 31` z `-b:v 0` to zwykły start. SVT-AV1: domyślnie 35. Wartości CRF nie są porównywalne między kodekami.
- Różnica o 6 w CRF H.264 to w przybliżeniu dwukrotna zmiana rozmiaru.
- Preset (ultrafast ... medium ... veryslow) wymienia czas na rozmiar przy tej samej jakości. Wolniejszy preset daje mniejszy plik, nie lepszy obraz przy tym samym CRF.
- Dwuprzebiegowe kodowanie (2-pass) ma sens, gdy trzeba trafić w zadany rozmiar. W większości zastosowań wystarczy CRF.
- Gdy limit rozmiaru jest sztywny: bitrate wideo ≈ (rozmiar docelowy w bitach / czas w sekundach) minus bitrate audio.

## ffmpeg: typowe polecenia

- Informacje: `ffprobe -hide_banner plik.mp4`.
- Kompresja ogólna: `ffmpeg -i in.mp4 -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k -movflags +faststart out.mp4`.
- Zmiana rozdzielczości z zachowaniem proporcji: `-vf scale=-2:720` (`-2` dobiera szerokość podzielną przez 2, co wymaga H.264). Zmiana klatek: `-r 30` lub filtr `fps=30`.
- Wycięcie fragmentu bez ponownego kodowania: `ffmpeg -ss 00:00:10 -to 00:00:20 -i in.mp4 -c copy cut.mp4`. Przy `-c copy` cięcie trafia w najbliższe klatki kluczowe, więc początek bywa niedokładny. Dokładne cięcie wymaga ponownego kodowania.
- Zmiana kontenera bez kodowania: `ffmpeg -i in.mkv -c copy out.mp4`.
- Łączenie plików o tych samych parametrach: lista w `lista.txt` (linie `file 'a.mp4'`), potem `ffmpeg -f concat -safe 0 -i lista.txt -c copy out.mp4`.
- Klatka jako obraz: `ffmpeg -ss 5 -i in.mp4 -frames:v 1 klatka.png`.
- Tylko obraz bez dźwięku: `-an`. Zgodność z odtwarzaczami: `-pix_fmt yuv420p`.
- Wiele plików w pętli: `for f in *.mp4; do ffmpeg -i "$f" -crf 26 "k_$f"; done`. Dodaj `-nostdin`, by ffmpeg nie połykał wejścia pętli.
- Ostrożnie z nadpisywaniem: `-n` nie nadpisuje, `-y` nadpisuje bez pytania.
- Przyspieszenie na słabym CPU: niższa rozdzielczość, szybszy preset, `-threads 0`, uruchomienie z `nice -n 19`.

## Kompresja pod YouTube

- YouTube i tak ponownie koduje wideo, więc wysyłaj dobrej jakości plik, a nie maksymalnie skompresowany. Zalecany format: MP4, H.264, AAC, `-movflags +faststart`, stałe klatki, proporcje 16:9 dla poziomych filmów, pionowe do Shorts.
- Zalecane bitrate'y YouTube zależą od rozdzielczości i klatek i bywają aktualizowane, więc sprawdź aktualną stronę pomocy YouTube. Praktyczna zasada: lepiej niższy CRF (np. 18-20) niż agresywna kompresja przed uploadem.
- Do udostępniania lub archiwizacji wystarczy CRF 23-28 i 720p lub 1080p.
- Limity wysyłki (rozmiar, długość) zależą od konta i polityki, więc sprawdź w YouTube Studio.

## Dźwięk

- Wyciągnięcie do MP3: `ffmpeg -i in.mp4 -vn -c:a libmp3lame -q:a 2 out.mp3` (VBR, jakość 0 najlepsza, 9 najgorsza). Do AAC: `-c:a aac -b:a 128k` (192k dla muzyki).
- Wyrównanie głośności (EBU R128): `-af loudnorm=I=-14:TP=-1.5:LRA=11` (cel -14 LUFS to częsty punkt odniesienia dla serwisów strumieniowych). Dokładniejsze jest przejście dwuprzebiegowe z pomiarem.
- Kopiowanie dźwięku bez zmian: `-c:a copy`. Zmiana ścieżki: `-map 0:v -map 1:a`.
- Opus (`libopus`) to dobry kodek do WebM i mowy, przy niskich bitrate lepszy od AAC i MP3.

## ffmpeg w przeglądarce (ffmpeg.wasm)

- Działa w WebAssembly, więc dane zostają w komputerze użytkownika, bez wysyłania na serwer. Jest wyraźnie wolniejszy od natywnego ffmpeg.
- Wersja wielowątkowa wymaga `SharedArrayBuffer`, czyli nagłówków izolacji (`Cross-Origin-Opener-Policy: same-origin` i `Cross-Origin-Embedder-Policy: require-corp`).
- Pamięć przeglądarki jest ograniczona (rzędu kilku GB zależnie od przeglądarki), więc bardzo duże pliki mogą się nie zmieścić. Ucz użytkowników, że lepiej krótsze pliki i prostsze ustawienia (H.264, brak AV1).
- Powiązane: [[Sieci komputerowe - podstawy]] (hosting, nagłówki), [[Linux: administracja zaawansowana]] (zadania wsadowe).
