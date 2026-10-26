# Bezpieczeństwo aplikacji webowych
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Najczęstsze klasy błędów w aplikacjach
(rama: OWASP Top 10), od strony **obrony**: jak ich nie popełnić. Przydatne
też do zrozumienia, dlaczego serwer GREGAI jest napisany tak, a nie inaczej.

## Zasada przewodnia

**Nigdy nie ufaj wejściu od użytkownika** ani niczemu, co przyszło z
zewnątrz. Waliduj (allowlista dozwolonych wartości), a dane wstawiaj do
zapytań/HTML/komend przez mechanizmy, które je bezpiecznie "opakowują",
nie przez sklejanie tekstu.

## OWASP Top 10 (skrótowo, obronnie; wg edycji 2025)

1. **Broken Access Control** (tu jest też SSRF): użytkownik robi to, czego nie
   powinien, albo serwer odpytuje wewnętrzny zasób na jego zlecenie. Obrona:
   sprawdzaj uprawnienia po stronie serwera przy każdej akcji, domyślnie
   odmawiaj; dla SSRF allowlista adresów wyjściowych i blokada adresów lokalnych.
2. **Błędna konfiguracja**: domyślne hasła, nadmiarowe uprawnienia, odkryte
   panele, gadatliwe błędy. Obrona: utwardzenie, minimalizm, ciche błędy.
3. **Awarie łańcucha dostaw oprogramowania**: zatrute lub stare zależności,
   niezweryfikowane paczki. Obrona: mało zależności, aktualizacje, sumy
   kontrolne i podpisy (jak `sha256sum` paczki GREGAI).
4. **Wady kryptograficzne**: dane wrażliwe bez szyfrowania, słabe algorytmy.
   Obrona: TLS wszędzie, [[Kryptografia w praktyce]].
5. **Injection** (SQL, komendy, LDAP): wstrzyknięcie kodu przez wejście.
   Obrona: zapytania parametryzowane, uruchamianie poleceń przez listę
   argumentów bez powłoki (tak robi SYSOP w GREGAI dla odczytu), allowlisty.
6. **Niebezpieczny projekt** (insecure design): brak modelowania zagrożeń.
   Obrona: myśl o bezpieczeństwie od początku, nie na końcu.
7. **Błędy uwierzytelniania**: słabe sesje, brak limitów prób. Obrona: MFA,
   limity (fail2ban), bezpieczne sesje. Patrz [[Uwierzytelnianie i sekrety]].
8. **Błędy integralności oprogramowania i danych**: brak weryfikacji
   aktualizacji i paczek. Obrona: podpisy, sumy kontrolne.
9. **Braki w logowaniu i alertowaniu**: atak przechodzi niezauważony.
   Obrona: loguj zdarzenia bezpieczeństwa i reaguj na alerty, patrz
   [[Wykrywanie i reakcja na incydent]].
10. **Złe obsługiwanie sytuacji wyjątkowych**: błąd, który otwiera dostęp
    albo ujawnia dane (fail-open). Obrona: fail-closed, jednolita obsługa
    błędów, ciche komunikaty.

## Dodatkowo

- **XSS** (cross-site scripting): wstrzyknięcie skryptu do strony. Obrona:
  kodowanie wyjścia (escaping), Content Security Policy, nie wstawiaj
  surowego HTML od użytkownika (w GREGAI UI używa `escapeHtml`).
- **CSRF** (cross-site request forgery): obca strona wykonuje akcję w Twoim
  imieniu. Obrona: sprawdzanie Origin/Host/Sec-Fetch, token, wymóg JSON
  (dokładnie tak robi serwer GREGAI, chroni też przed DNS rebinding).
- **Clickjacking**: nakładka wabiąca kliknięcie. Obrona: nagłówki
  ramkowania (X-Frame-Options/CSP frame-ancestors).

## Jak to widać w GREGAI

Serwer to czyste Python stdlib (mało zależności = mała powierzchnia),
żądania API tylko JSON, sprawdzanie Host/Origin/Sec-Fetch-Site, token dla
ruchu przez pośrednika, brak dostępu do plików poza dozwolonym katalogiem,
ciche i spójne błędy. To OWASP w praktyce. Patrz [[Utwardzanie GREGAI]].
