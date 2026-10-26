# Podstawy bezpieczeństwa
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Pojęcia, na których stoi cała reszta.

## Triada CIA

- **Poufność** (Confidentiality): dane widzi tylko ten, kto ma prawo.
  Narzędzia: szyfrowanie, kontrola dostępu, [[Kryptografia w praktyce]].
- **Integralność** (Integrity): dane nie zostały po cichu zmienione.
  Narzędzia: skróty (hash), podpisy cyfrowe, sumy kontrolne, logi
  niezmienne.
- **Dostępność** (Availability): system działa, kiedy go potrzebujesz.
  Wrogowie: ransomware, DDoS, awaria dysku. Odpowiedź: kopie zapasowe,
  redundancja, limity zasobów.

Czwarte, często dodawane: **autentyczność** (wiesz, z kim rozmawiasz) i
**niezaprzeczalność** (nie da się wyprzeć wykonanej akcji).

## Model zagrożeń (threat modeling)

Zanim coś zabezpieczysz, odpowiedz na cztery pytania:
1. Co chronię? (aktywa: notatki, klucz API, tożsamość, pieniądze)
2. Przed kim? (ciekawski sąsiad, złodziej laptopa, automat skanujący
   internet, ukierunkowany napastnik, dostawca sieci)
3. Jak bardzo przeciwnik jest zdeterminowany i zasobny?
4. Jakie są konsekwencje porażki?

Nie ma "bezpieczny" w próżni, jest "bezpieczny wobec konkretnego
przeciwnika". Metoda STRIDE porządkuje typy zagrożeń: Spoofing (podszycie),
Tampering (manipulacja), Repudiation (wyparcie), Information disclosure
(wyciek), Denial of service (odmowa usługi), Elevation of privilege
(eskalacja uprawnień).

## Obrona w głąb (defense in depth)

Wiele warstw, każda zakłada, że poprzednia mogła zawieść. Przykład z
GREGAI: szyfrowanie dysku + nasłuch tylko na localhost + zapora ufw +
token + ochrona CSRF + wycinanie sekretów z wyników. Przebicie jednej
warstwy nie oddaje całości. Patrz [[Utwardzanie GREGAI]].

## Zero trust

"Nigdy nie ufaj, zawsze weryfikuj." Nie ma "sieci wewnętrznej", której się
ufa z definicji. Każde żądanie jest uwierzytelniane i autoryzowane,
niezależnie skąd przyszło. W GREGAI: nawet żądanie z własnej sieci (LAN)
wymaga tokenu; sama lokalizacja w sieci niczego nie uprawnia.

## Zasada najmniejszych uprawnień (least privilege)

Każdy proces, użytkownik i klucz dostaje dokładnie tyle uprawnień, ile
potrzebuje do zadania, i ani jednego więcej. W GREGAI: `sudo` tylko na
listę konkretnych usług, nie "dowolna usługa"; narzędzia plikowe tylko w
jednym katalogu. Pokrewne: **rozdział obowiązków** (jeden klucz nie robi
wszystkiego) i **fail-closed** (gdy coś nie wiadomo, blokuj, nie
przepuszczaj, patrz WARP w GREGAI).

## Powierzchnia ataku (attack surface)

Suma wszystkich miejsc, przez które można wejść: otwarte porty, usługi,
konta, biblioteki, wejścia użytkownika. Mniejsza powierzchnia = mniej do
obrony. Zasady: wyłącz, czego nie używasz; nie wystawiaj nic do sieci bez
potrzeby; mniej zależności to mniej cudzego kodu do zaufania (dlatego
GREGAI to czyste Python stdlib i vanilla JS).

## Assume breach

Dojrzałe podejście nie brzmi "nie damy się włamać", tylko "kiedy ktoś
wejdzie, skutek ma być mały, a my dowiemy się szybko". Stąd: segmentacja,
kopie zapasowe offline, monitoring (patrz [[Wykrywanie i reakcja na
incydent]]), minimalne uprawnienia.

## CVE, CVSS, łatanie

- **CVE**: publiczny identyfikator konkretnej podatności (np.
  CVE-2024-xxxxx).
- **CVSS**: ocena wagi od 0 do 10 (krytyczna, wysoka, średnia, niska).
- **Zero-day**: podatność, na którą nie ma jeszcze łatki.
- Najważniejsza, najtańsza i najczęściej pomijana obrona: **aktualizuj
  oprogramowanie**. Większość realnych włamań idzie przez znane, załatane
  już dziury, których ktoś nie zaktualizował.
