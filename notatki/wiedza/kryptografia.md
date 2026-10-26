# Kryptografia w praktyce
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Co, kiedy i czym, bez matematyki. Zasada
nadrzędna: **nie wymyślaj własnej kryptografii**. Używaj sprawdzonych,
publicznie zrecenzowanych bibliotek i protokołów.

## Trzy narzędzia, trzy zadania

1. **Szyfrowanie** - poufność (nikt nie przeczyta).
2. **Skrót (hash)** - integralność (wykryjesz zmianę) i przechowywanie
   haseł.
3. **Podpis cyfrowy** - autentyczność + niezaprzeczalność (wiesz, kto to
   stworzył, i nie da się wyprzeć).

## Szyfrowanie symetryczne vs asymetryczne

- **Symetryczne** (jeden wspólny klucz): szybkie, do dużych danych.
  Standard: **AES** (np. AES-256-GCM). Szyfrowanie dysku (LUKS), archiwów
  (gpg), plików.
- **Asymetryczne** (para: klucz publiczny + prywatny): wolniejsze, do
  wymiany kluczy i podpisów. **RSA**, **ECC/Curve25519**. Publicznym
  szyfrujesz/weryfikujesz, prywatnym odszyfrowujesz/podpisujesz. Prywatny
  nigdy nie opuszcza Twojej maszyny.
- W praktyce łączy się oba: asymetrycznie ustala się klucz sesji, dalej
  leci szybkie symetryczne (tak działa TLS).

## Skróty (hash)

- Funkcja jednokierunkowa: z danych liczy krótki "odcisk". To samo wejście
  = ten sam skrót; mała zmiana = zupełnie inny skrót.
- Dobre: **SHA-256**, SHA-3, BLAKE2/3. Złamane, **nie używać** do
  bezpieczeństwa: MD5, SHA-1 (kolizje).
- Zastosowania: sumy kontrolne plików (`sha256sum`, tak sprawdzamy paczkę
  GREGAI i obraz ISO), weryfikacja integralności, fundament podpisów.

## Hasła: hashowanie z solą

- Haseł **nigdy** nie trzyma się jawnie ani zwykłym szybkim skrótem.
- Specjalne, **celowo wolne** funkcje: **Argon2** (najlepszy dziś),
  **bcrypt**, **scrypt**, PBKDF2. Wolne = brute force kosztuje.
- **Sól** (losowy dodatek na hasło) uniemożliwia tablice tęczowe i to, że
  dwa takie same hasła mają ten sam skrót.
- Patrz [[Uwierzytelnianie i sekrety]].

## Podpisy cyfrowe

- Podpisujesz kluczem **prywatnym**, każdy weryfikuje **publicznym**.
  Gwarantuje, że to Ty i że treść się nie zmieniła.
- Zastosowania: podpisane pakiety (apt), commity git, wiadomości (GPG),
  aktualizacje oprogramowania.

## Dobre nawyki

- Szyfruj **w spoczynku** (dysk, kopie) i **w drodze** (TLS, VPN).
- Zarządzaj kluczami: generuj bezpiecznie, trzymaj prywatne offline/w
  sprzęcie, rotuj, miej plan na kompromitację.
- **Forward secrecy**: nawet jeśli klucz długoterminowy wycieknie później,
  stare sesje zostają tajne (TLS to zapewnia).
- Preferuj uwierzytelniane szyfrowanie (AEAD, np. AES-GCM, ChaCha20-
  Poly1305): poufność + integralność naraz.
- **Kryptografia postkwantowa**: przyszłe komputery kwantowe zagrożą RSA/ECC;
  standardy odporne (np. ML-KEM, dawniej Kyber, i ML-DSA, dawniej Dilithium) są już wdrażane. Warto wiedzieć,
  na razie nie pilne dla laptopa domowego.

## Czego nie robić

- Nie wymyślaj szyfru ani "ukrywania przez zaciemnianie" jako jedynej
  ochrony (security by obscurity nie jest bezpieczeństwem).
- Nie używaj MD5/SHA-1/DES/RC4 do niczego wrażliwego.
- Nie zapisuj kluczy prywatnych i haseł w kodzie, repozytorium ani logach.
