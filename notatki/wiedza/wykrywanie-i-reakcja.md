# Wykrywanie i reakcja na incydent
type: Wiedza

Część [[Cyberbezpieczeństwo]]. Zakładamy "assume breach": kiedyś coś
przejdzie, więc trzeba to **szybko wykryć** i **spokojnie obsłużyć**.
Komendy: [[Komendy Linuksa: system i procesy]], [[Komendy Linuksa: sieć i
bezpieczeństwo]].

## Wykrywanie: co obserwować

- **Logi systemowe**: `journalctl`, `/var/log/`. Nieudane logowania,
  użycie sudo, restarty usług, błędy.
- **Procesy**: nieznane/nietypowe, wysokie CPU (`top`, `ps`), procesy bez
  pliku na dysku.
- **Sieć**: nietypowe połączenia wychodzące, nasłuch na nowych portach
  (`ss -tulpn`), skoki ruchu.
- **Konta i uprawnienia**: nowe konta, zmiany w `sudoers`, klucze SSH,
  które się pojawiły.
- **Autostart i zadania**: nowe usługi, wpisy cron, `~/.bashrc`.
- **Integralność plików**: zmiany w plikach systemowych (AIDE, sumy
  kontrolne).

## Narzędzia

- **auditd**: śledzi wywołania systemowe i dostęp do wrażliwych plików.
- **fail2ban**: automatycznie blokuje adresy po serii nieudanych prób.
- **SIEM** (w większej skali): zbiera i koreluje logi z wielu źródeł.
- **IDS/IPS** (Suricata, Snort): wykrywa/blokuje znane wzorce ataku w ruchu.
- Logi najlepiej wysyłać **poza maszynę** - napastnik, który przejmie
  system, pierwsze wyczyści lokalne ślady.

## Reakcja na incydent (IR), sześć kroków

1. **Przygotowanie**: kopie zapasowe, kontakty, plan - zanim coś się
   stanie.
2. **Identyfikacja**: czy to naprawdę incydent? Co, gdzie, od kiedy.
3. **Powstrzymanie** (containment): odetnij, zanim się rozleje - odłącz od
   sieci, zablokuj konto. Nie gaś od razu wszystkiego (stracisz dowody).
4. **Usunięcie** (eradication): wyrzuć napastnika i złośliwy kod, załataj
   wejście.
5. **Odtworzenie** (recovery): przywróć z czystej kopii, obserwuj, czy nie
   wrócił.
6. **Wnioski** (lessons learned): co zawiodło, co poprawić. Bez obwiniania,
   z konkretnymi zmianami.

## Higiena dowodów (forensics, podstawy)

- Nie działaj w panice na żywym systemie, jeśli zależy Ci na dowodach.
- Rób kopię (obraz) dysku i pamięci, pracuj na kopii.
- Notuj czas i każdą czynność. Zachowaj logi.
- W poważnych sprawach (wyłudzenie, kradzież tożsamości) rozważ zgłoszenie
  odpowiednim służbom.

## Ransomware: konkretny plan

1. Odłącz od sieci natychmiast (powstrzymanie).
2. **Nie płać** jeśli się da - płatność nie gwarantuje odzyskania i
   finansuje kolejne ataki.
3. Odtwórz z **offline'owej** kopii zapasowej.
4. Znajdź i załataj drogę wejścia, zanim przywrócisz.
Dlatego najważniejsza jest kopia zapasowa, której ransomware nie dosięgnie.

## Dla GREGAI

GREGAI prowadzi pełny **dziennik audytu** poleceń SYSOP
(`data/sysop_log.json`), widoczny też w `/debug`: to materiał do wykrywania
i do wniosków. Patrz [[Utwardzanie GREGAI]]. Wykrywanie i reakcja na
incydent stosuje się do samego laptopa.
