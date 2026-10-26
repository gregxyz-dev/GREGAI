# Utwardzanie GREGAI
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Jak zasady z pozostałych notatek są **już
wdrożone** w tym projekcie. To mapa: pojęcie -> gdzie w GREGAI. Pełny opis
dla użytkownika: `INSTALACJA_UBUNTU_26_04.md`, Krok 12.

## Obrona w głąb (warstwy)

Przebicie jednej warstwy nie oddaje całości (patrz [[Podstawy
bezpieczeństwa]]):
1. **Szyfrowanie dysku** (LUKS) - skradziony laptop = nic do odczytania.
2. **Nasłuch tylko na localhost** - serwer `127.0.0.1:7777`, Ollama
   `127.0.0.1:11434`. Nic nie wystawione do sieci (`GREGAI_LAN=0`).
3. **Zapora ufw** - przychodzące zablokowane.
4. **Token** dla ruchu spoza maszyny i przez pośrednika (nawet z własnej
   sieci; to [[Podstawy bezpieczeństwa|zero trust]]).
5. **Ochrona CSRF/DNS rebinding** - sprawdzanie Host, Origin,
   Sec-Fetch-Site, tylko JSON (patrz [[Bezpieczeństwo aplikacji webowych]]).
6. **Wycinanie sekretów** z wyników poleceń (nawet fragmentów kluczy).

## WARP fail-closed (priorytet projektu)

`agent/netguard.py` to jedyna droga GREGAI do internetu: tylko przez
Cloudflare WARP i tylko `https` (także po przekierowaniach). Bez
połączonego WARP nic nie wychodzi (chmura stoi, rozmowa lokalna działa).
To **fail-closed**: gdy nie wiadomo, blokuj. Patrz [[Bezpieczeństwo sieci]].

## Najmniejsze uprawnienia

- `sudo` tylko na konkretne polecenia: usługi `gregai` i `ollama` oraz
  `apt-get update`/`upgrade`, nie "dowolna usługa". Reguła walidowana
  `visudo` przed instalacją.
- Narzędzia plikowe GREGAI tylko w wskazanych katalogach (`SYSOP_ROOTS`,
  domyślnie folder projektu).
- Usługa działa jako zwykły użytkownik, nie root.
Patrz [[Podstawy bezpieczeństwa]], [[Utwardzanie Linuksa]].

## SYSOP: poziomy i blokady

- **Odczyt** od razu (wąska lista programów, bez powłoki, bez możliwości
  zapisu/wysłania/uruchomienia). **Zmiana** po "tak" przy pokazanym
  dokładnie poleceniu. **Niszczące** zablokowane na stałe.
- Polecenia o **ukrytej treści** (zmienne, `$(...)`, base64, `| bash`)
  zablokowane - nie da się ich przeczytać przed wykonaniem. Dotyczy to
  opcjonalnego dowolnego polecenia (`sys_shell`, domyślnie wyłączone,
  `SYSOP_SHELL=0`): w wersji stabilnej działa tylko 13 stałych, nazwanych
  narzędzi.
- **GREGAI nie może osłabić własnych zabezpieczeń** (WARP, ufw, apparmor,
  auto-aktualizacje, sudoers, SSH, źródła pakietów) - nawet z "tak", nawet
  na polecenie wstrzyknięte w notatkę/stronę.

## Odporność na inżynierię społeczną modelu (prompt injection)

Instrukcje znalezione w treści (notatka, strona, wynik polecenia) to
**dane, nie polecenia**. Bez zgody użytkownika wykonuje się tylko ścisły
odczyt. To ta sama logika co [[Phishing i inżynieria społeczna]], tyle że
celem jest model.

## Mała powierzchnia ataku

Serwer: czyste Python stdlib. Interfejs: vanilla JS. Zero frameworków, zero
procesu budowania = mało cudzego kodu do zaufania (mniejszy łańcuch dostaw,
patrz [[Techniki atakujących (obrona)]]).

## Minimalizacja danych do chmury

Do chmury (Claude) idzie tylko treść trudnego pytania, ostatnie tury rozmowy
(bez poleceń, na które odpowiedziało narzędzie) i prompt systemowy GREGAI
(osobowość i zasady z `agent/prompt.md`, czyli także imię i opis zajęć
właściciela, oraz opisy narzędzi) - nigdy pliki, notatki ani dane o sieci.
Patrz [[OPSEC i prywatność]].

## Audyt

Pełny dziennik poleceń SYSOP w `data/sysop_log.json` (ostatnie 1000 wpisów); `/debug` pokazuje 5 ostatnich.
Materiał do [[Wykrywanie i reakcja na incydent|wykrywania]] i wniosków.

## Sieć domowa (świadome zaufanie)

Skan sieci i odczyt routera tylko w domu: brama + jej MAC, zapamiętane
świadomie. Każdy błąd = sieć obca (fail-closed). Hasło panelu nigdy nie
idzie do obcej bramy.

## Czego GREGAI celowo nie robi

- Nie wystawia niczego do internetu, nie używa publicznej domeny/strony.
- Nie pomaga łamać cudzych systemów ani pisać złośliwego kodu.
- Nie wykonuje niszczących poleceń ani nie osłabia własnych zabezpieczeń.
