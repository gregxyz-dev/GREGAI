# Android i telefony
type: Wiedza

Część [[Nauka i technika]]. Podstawy pracy z telefonem z Androidem (przykład w tekście: starszy telefon Samsung z nakładką One UI) i narzędziem ADB z Ubuntu. Nazwy menu zależą od konkretnego modelu, wersji Androida i nakładki, więc jeśli opcja leży gdzie indziej, użyj wyszukiwarki w Ustawieniach.

## Tryb deweloperski

- Ustawienia > Informacje o telefonie > Informacje o oprogramowaniu > stuknij 7 razy "Numer kompilacji". Potem w Ustawieniach pojawia się "Opcje programisty".
- W opcjach programisty włącz "Debugowanie USB". Po podłączeniu kabla telefon pyta o zaufanie komputerowi (odcisk RSA), zaakceptuj tylko na własnym komputerze.
- Po zakończeniu prac wyłącz debugowanie USB. Połączenie ADB daje dużą kontrolę nad telefonem.

## ADB na Ubuntu

- Instalacja: `sudo apt install adb`. Sprawdzenie: `adb devices` (telefon powinien mieć status `device`, a `unauthorized` znaczy brak akceptacji na telefonie, `no permissions` zwykle brak reguł udev lub zły kabel).
- Powłoka na telefonie: `adb shell`. Pojedyncze polecenie: `adb shell getprop ro.build.version.release` (wersja Androida), `adb shell getprop ro.product.model`.
- Instalacja aplikacji: `adb install aplikacja.apk` (`-r` zastępuje istniejącą). Odinstalowanie: `adb uninstall nazwa.pakietu`.
- Pliki: `adb push plik /sdcard/Download/` (na telefon), `adb pull /sdcard/DCIM/Camera ./kopia` (z telefonu).
- Zrzut ekranu: `adb exec-out screencap -p > ekran.png`. Nagranie: `adb shell screenrecord /sdcard/film.mp4` (do 3 minut domyślnie).
- Logi: `adb logcat` (strumień logów, `adb logcat *:E` tylko błędy). Przy programowaniu aplikacji (np. projekt VR HUD lub aplikacja do nauki) to podstawowe narzędzie diagnostyczne.
- Lista pakietów: `adb shell pm list packages`, z filtrem `| grep nazwa`.
- ADB przez Wi-Fi: na starszych wersjach przy podłączonym kablu `adb tcpip 5555`, potem `adb connect IP_TELEFONU:5555`. Nowsze Androidy (11 i nowsze) mają parowanie w opcjach programisty (`adb pair`). Telefon i laptop muszą być w jednej sieci. Wyłącz po użyciu.
- Restart serwera ADB, gdy coś się zacina: `adb kill-server` i `adb start-server`.

## Uprawnienia aplikacji

- Aplikacja prosi o uprawnienia (aparat, mikrofon, lokalizacja, kontakty, pamięć). Przyznawaj minimum. Ustawienia > Aplikacje > wybrana aplikacja > Uprawnienia. W nowszych wersjach jest też Menedżer uprawnień, który pokazuje, kto ich używa.
- Z ADB: `adb shell dumpsys package nazwa.pakietu` pokazuje przyznane uprawnienia, a `adb shell pm grant` i `pm revoke` zmieniają niektóre z nich.
- Instaluj aplikacje ze sklepu (Google Play, Galaxy Store). Instalacja z nieznanych źródeł (APK) niesie ryzyko złośliwego oprogramowania, więc włączaj tę opcję tylko dla zaufanego pliku. Patrz [[Cyberbezpieczeństwo]].
- Uprawnienia dostępności i administratora urządzenia są szczególnie wrażliwe, bo dają aplikacji wgląd w ekran.

## Bateria

- Zużycie sprawdzisz w Ustawieniach (Konserwacja urządzenia lub Bateria) oraz poleceniem `adb shell dumpsys battery`, które pokazuje poziom, napięcie, temperaturę i stan.
- Co pomaga: niższa jasność, tryb oszczędzania, wyłączanie zbędnej synchronizacji i lokalizacji, ograniczenie pracy aplikacji w tle, aktualizacje.
- Zdrowie ogniwa: baterie Li-ion starzeją się z liczbą cykli i temperaturą. Unikaj upału i ładowania w pokrowcu na słońcu. Spuchnięta bateria to zagrożenie i trzeba ją wymienić, bez ładowania. Zasady z [[Elektryczny rower - podstawy]] dotyczące ogniw Li-ion dotyczą też telefonu.
- Bateria J6 jest wymienna tylko w serwisie, a starsze ogniwo daje krótszy czas pracy.

## Zwalnianie miejsca

1. Sprawdź, co zajmuje miejsce: Ustawienia > Pamięć (lub Konserwacja urządzenia > Pamięć), albo aplikacja Moje pliki.
2. Zdjęcia i filmy: skopiuj na komputer (`adb pull /sdcard/DCIM ./kopia` lub kabel) lub do chmury, a potem usuń z telefonu. Sprawdź kopię przed usunięciem.
3. Pamięć podręczna aplikacji: Ustawienia > Aplikacje > wybrana aplikacja > Pamięć > Wyczyść pamięć podręczną (to nie kasuje danych użytkownika). Przycisk "Wyczyść dane" kasuje konto i ustawienia.
4. Odinstaluj nieużywane aplikacje. Pobrane pliki: folder Download. Komunikatory przechowują duże pliki multimedialne, więc czyść je w ustawieniach aplikacji.
5. Karta microSD (jeśli telefon ma slot) może przechować zdjęcia i filmy.
6. Zimna kopia przed czyszczeniem: kopia zapasowa konta Google i Samsung.
7. Odinstalowanie aplikacji preinstalowanych bez roota: `adb shell pm uninstall -k --user 0 nazwa.pakietu` (usuwa dla bieżącego użytkownika, przywrócenie: `adb shell cmd package install-existing nazwa.pakietu`). Usuwanie aplikacji systemowych może zepsuć funkcje telefonu, więc najpierw wyszukaj, co to za pakiet.

## Wydajność i aktualizacje

- Telefon z kilkoma GB (lub mniej) RAM i starszym procesorem zwalnia przy dużej liczbie aplikacji w tle. Restart raz na jakiś czas pomaga. Wyłącz animacje w opcjach programisty (skala animacji 0,5x lub wyłączona).
- Aktualizacje zabezpieczeń kończą się po kilku latach wsparcia, więc na starym modelu ostrożniej z bankowością, hasłami i nieznanymi aplikacjami.
- Reset do ustawień fabrycznych kasuje dane, więc wcześniej zrób kopię.

## Bezpieczeństwo i prywatność

- Blokada ekranu (PIN, odcisk) i szyfrowanie włączone. Funkcja "Znajdź moje urządzenie" pozwala zlokalizować i zablokować zgubiony telefon.
- Uważaj na SMS-y i linki z wiadomości (phishing). Szczegóły: [[Cyberbezpieczeństwo]].
