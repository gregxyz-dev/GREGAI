# Techniki atakujących (obrona)
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Jak myśli przeciwnik, **żeby go rozpoznać
i zatrzymać**. To wiedza obronna (blue team): opis faz i kategorii, nie
instrukcja atakowania. Rama: MITRE ATT&CK, publiczny katalog taktyk
realnych napastników, używany na całym świecie do obrony.

## Łańcuch ataku (cyber kill chain) i taktyki ATT&CK

Większość ataków przechodzi przez podobne fazy. Dla każdej: co to jest i
**jak się bronić / co obserwować**.

1. **Rozpoznanie** (reconnaissance): zbieranie informacji o celu ze źródeł
   publicznych (OSINT), skanowanie portów. Obrona: minimalna powierzchnia
   ataku, mało danych o sobie w sieci, nic niepotrzebnego nie nasłuchuje.
2. **Uzyskanie dostępu** (initial access): najczęściej phishing (patrz
   [[Phishing i inżynieria społeczna]]), podatna usługa wystawiona do
   sieci, skradzione hasło. Obrona: MFA, łatanie, nic bez potrzeby nie
   wystawione (w GREGAI nasłuch tylko na localhost).
3. **Wykonanie** (execution): uruchomienie kodu napastnika. Obrona:
   nieufność wobec załączników i skryptów, allowlista, w GREGAI ścisły
   rozdział "odczyt" od "zmiana" w SYSOP.
4. **Utrwalenie** (persistence): napastnik chce przetrwać restart, zakłada
   ukryte konto, wpis w autostarcie, zadanie cron, backdoor. Obrona:
   monitoring zmian w autostarcie i zadaniach, integralność plików.
5. **Eskalacja uprawnień** (privilege escalation): z konta zwykłego do
   roota. Obrona: least privilege, łatanie jądra, audyt sudo.
6. **Unikanie wykrycia** (defense evasion): czyszczenie logów, ukrywanie
   procesów, kod "żyjący z ziemi" (living off the land: użycie wbudowanych
   narzędzi systemu, żeby nie wnosić własnych plików). Obrona: logi
   wysyłane poza maszynę (żeby ich nie dało się wyczyścić lokalnie),
   wykrywanie anomalii.
7. **Dostęp do poświadczeń** (credential access): kradzież haseł, tokenów,
   kluczy z pamięci i plików. Obrona: nie trzymać sekretów jawnie, szyfrować
   dysk, w GREGAI wycinanie sekretów z wyników poleceń.
8. **Rozpoznanie wewnętrzne i ruch boczny** (discovery, lateral movement):
   mapowanie sieci od środka, przeskok na kolejne maszyny. Obrona:
   segmentacja sieci, zero trust, brak wspólnych haseł.
9. **Zbieranie i eksfiltracja** (collection, exfiltration): pakowanie i
   wyprowadzanie danych, często szyfrowanym kanałem, by wtopić się w ruch.
   Obrona: monitoring nietypowego ruchu wychodzącego, DLP, minimalizacja
   danych.
10. **Wpływ** (impact): ransomware (szyfrowanie dla okupu), kasowanie,
    sabotaż. Obrona: kopie zapasowe offline/niezmiennych (immutable),
    przetestowane odtwarzanie.

## Najczęstsze wektory wejścia (realnie, nie w filmach)

- **Phishing i skradzione hasła** to zdecydowana większość. Nie "geniusz
  łamiący szyfr", tylko ktoś, kto kliknął albo użył tego samego hasła co
  gdzieś, gdzie wyciekło.
- **Niezałatane, znane podatności** w usługach wystawionych do sieci.
- **Źle skonfigurowane usługi**: domyślne hasła, otwarte panele, publiczne
  bazy danych bez uwierzytelnienia.
- **Łańcuch dostaw** (supply chain): zatruta biblioteka, zależność z
  backdoorem. Dlatego mało zależności = mniejsze ryzyko.

## Pojęcia, które warto znać

- **Exploit**: kod/technika wykorzystująca podatność. **Payload**: to, co
  napastnik chce wykonać po wejściu. **C2** (command and control): kanał,
  którym napastnik steruje przejętą maszyną.
- **Botnet**: sieć przejętych maszyn sterowanych zdalnie.
- **Brute force / credential stuffing**: zgadywanie haseł siłowo albo
  podstawianie haseł z wcześniejszych wycieków. Obrona: długie, unikatowe
  hasła + MFA + limity prób (fail2ban).
- **MITM** (man in the middle): podsłuch/podmiana komunikacji w drodze.
  Obrona: TLS wszędzie, HSTS, szyfrowany tunel (WARP).
- **Privilege escalation, pivoting, persistence**: patrz fazy wyżej.

## Jak ta wiedza chroni GREGAI

Projekt jest zbudowany wprost pod te fazy: minimalna powierzchnia (nic
niewystawione), fail-closed WARP, rozdział odczyt/zmiana w SYSOP, brak
możliwości osłabienia własnych zabezpieczeń przez model, wycinanie
sekretów, pełny dziennik audytu. Szczegóły: [[Utwardzanie GREGAI]].
