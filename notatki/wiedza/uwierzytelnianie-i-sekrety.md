# Uwierzytelnianie i sekrety
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Hasła, drugi składnik, klucze, zarządzanie
tajemnicami. Najczęstszy realny wektor włamań to skradzione lub słabe
poświadczenia (patrz [[Techniki atakujących (obrona)]]).

## Trzy składniki uwierzytelnienia

1. **Coś, co wiesz** - hasło, PIN.
2. **Coś, co masz** - telefon, klucz sprzętowy, token.
3. **Czym jesteś** - odcisk palca, twarz (biometria).

**MFA/2FA** = co najmniej dwa różne składniki. Samo hasło to za mało.

## Hasła

- **Długość bije złożoność.** Cztery-pięć losowych słów (passphrase) jest
  mocniejsze i łatwiejsze niż `P@ssw0rd!`.
- **Unikatowe na każdą usługę.** Powtórzone hasło = jeden wyciek kompromituje
  wszystko (credential stuffing).
- **Menedżer haseł** (np. KeePassXC, Bitwarden) generuje i pamięta długie,
  losowe hasła. Jedno silne hasło główne + MFA do samego menedżera.
- Sprawdzaj wycieki (np. haveibeenpwned). Zmień hasła po wycieku.
- Uwaga na hasła wpisywane przed startem systemu (szyfrowanie dysku): zanim
  wczyta się układ klawiatury, trzymaj się znaków ASCII (tak jest w
  instrukcji GREGAI).

## MFA/2FA - rodzaje, od najlepszego

1. **Klucz sprzętowy** (FIDO2/WebAuthn, np. YubiKey) - odporny na phishing,
   najlepszy.
2. **Aplikacja TOTP** (kody co 30 s, np. Aegis, Google Authenticator) -
   dobre.
3. **SMS** - słabe (podatne na SIM swap, przechwycenie), ale lepsze niż
   nic.

## Klucze i tokeny

- Klucz prywatny (SSH, GPG) chroń hasłem i prawami pliku (`600`), trzymaj
  tylko na swojej maszynie, najlepiej na kluczu sprzętowym.
- Tokeny API to też sekrety: traktuj jak hasła, rotuj, nadawaj minimalne
  uprawnienia, ustaw datę ważności.

## Zarządzanie sekretami (secrets management)

- **Nigdy** w kodzie, repozytorium, logach, URL-ach ani w historii powłoki.
- Trzymaj w plikach o prawach `600` poza repo (jak `.env`), w menedżerze
  sekretów, albo w keyringu systemu.
- **Rotacja**: zmieniaj okresowo i natychmiast po podejrzeniu wycieku.
- **Least privilege**: każdy sekret daje dostęp tylko do tego, co konieczne.
- W GREGAI: `.env` ma prawa `600`, klucz API idzie tylko w nagłówku
  (nigdy do logów), a sekrety są wycinane z wyników poleceń SYSOP - nawet
  ich fragmenty. Patrz [[Utwardzanie GREGAI]].

## Sesje i tokeny dostępu

- Token sesji = tymczasowy "bilet" po zalogowaniu. Chroń go jak hasło;
  kradzież = przejęcie sesji.
- Dobre praktyki: krótki czas życia, unieważnianie, HttpOnly/Secure dla
  ciasteczek, porównanie w czasie stałym (jak `hmac.compare_digest` w
  GREGAI, odporne na atak czasowy).

## Typowe błędy

- Jedno hasło wszędzie. Hasło w mailu/notatce jawnej. MFA tylko SMS do
  konta krytycznego. Sekret w publicznym repo. Brak rotacji po odejściu
  współpracownika albo po wycieku.
