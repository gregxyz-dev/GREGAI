"""
tryby.py

Trzy tryby, wpisywane WPROST w okienku czatu GREGAI (user_only w
capabilities.py: tylko dosłowna fraza użytkownika, nigdy decyzja modelu/
routera/planera - patrz tam):

  freeram - zwalnia pamięć i oddaje moc maszynie: wyładowuje duży model z
            Ollamy i zatrzymuje jej usługę, żeby RAM i CPU były wolne (np.
            na trening albo inne ciężkie zadanie). GREGAI zostaje włączony i
            odpowiada dalej: polecenia i notatki działają jak zwykle, a
            pytanie, na które nie ma nic w notatkach, idzie etapami sieciowymi
            koryta (KORYTO: Claude, potem darmowa pula), o ile jest klucz,
            WARP i dzienny limit. Lokalnego
            modelu nie ma aż do 'fullon' (albo restartu komputera). Zwykła
            wiadomość Ollamy sama NIE uruchamia.

  fullon  - pełna moc dla lokalnego AI: startuje Ollamę (jeśli stoi),
            wczytuje duży model i PRZYPINA go w RAM (keep_alive -1) oraz
            rozgrzewa, żeby odpowiadał od razu, bez czekania na wczytanie.

  gregaipanicmode (2026-10-19, prośba Grzegorza) - awaryjna blokada: najpierw
            zamyka dostęp z sieci (zapora + wyłączenie trybu LAN), POTEM
            wyłącza CAŁY komputer, nie tylko usługę GREGAI. Zobacz
            panicmode() niżej po pełne uzasadnienie i kolejność kroków.

Zasada bezpieczeństwa (priorytet projektu): freeram/fullon NIE ruszają
zabezpieczeń - Cloudflare WARP, zapora ufw, apparmor zostają nietknięte.
Operacje na usłudze Ollamy idą przez sysop.run_cmd, czyli sudo wyłącznie na
'ollama' (z listy w install.sh), nigdy "dowolna usługa". Reszta to lokalne
API Ollamy (http://127.0.0.1:11434), bez sudo. Governor procesora nie jest
ruszany: nowoczesne jądro samo przyspiesza pod obciążeniem. gregaipanicmode
jest JEDYNYM, świadomym wyjątkiem od "zapora nietknięta" - idzie wyłącznie w
stronę BARDZIEJ restrykcyjną (blokada, nigdy otwarcie), i tylko z tej jednej,
literalnej, user_only frazy, nigdy z decyzji modelu (patrz panicmode()).
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import env_loader as env_loader_mod
import netguard as netguard_mod
import sysop as sysop_mod

# Tryby dotyczą WYŁĄCZNIE lokalnej Ollamy na tej maszynie (ta sama zasada co
# router.py): adres spoza localhost w .env jest ignorowany, nie wysyłamy nic
# w sieć.
_HOST = os.environ.get("OLLAMA_HOST", "").strip() or "http://localhost:11434"  # jak router.py: puste = domyślny
if not netguard_mod.is_local_url(_HOST):
    _HOST = "http://localhost:11434"
_HOST = _HOST.rstrip("/")


# Funkcja zwracająca pełny prompt systemowy (main.get_system_prompt), ustawiana przez main.py
# przy starcie; bez niej fullon tylko wczytuje wagi.
SYSTEM_PROMPT = None


def _model() -> str:
    # Odczytywane przy każdym wywołaniu, nie na starcie: gdyby ktoś zmienił
    # OLLAMA_MODEL w .env i zrestartował, tryby od razu biorą nową wartość.
    return os.environ.get("OLLAMA_MODEL", "").strip() or "qwen2.5:3b"  # jak router.py: puste = domyślny


def _api(path: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(_HOST + path, data=data, headers=headers)
    with netguard_mod.local_urlopen(req, timeout=timeout) as resp:
        return netguard_mod.read_json(resp)


def _ollama_up() -> bool:
    try:
        _api("/api/version", timeout=2)
        return True
    except Exception:
        return False


def _loaded_models() -> list[str]:
    try:
        return [m.get("name", "") for m in _api("/api/ps", timeout=3).get("models", []) if m.get("name")]
    except Exception:
        return []


def _mem():
    """(RAM całkowita GB, RAM dostępna GB) z /proc/meminfo, bez sudo. None na
    błędzie (np. system inny niż Linux)."""
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, _, val = line.partition(":")
                info[key.strip()] = int(val.strip().split()[0])  # kB
        return info.get("MemTotal", 0) / 1024 / 1024, info.get("MemAvailable", 0) / 1024 / 1024
    except Exception:
        return None


def _mem_line() -> str:
    m = _mem()
    return f"RAM wolna {m[1]:.1f} / {m[0]:.1f} GB" if m else "RAM: nie odczytano"


def freeram() -> dict:
    """Tryb Freeram: zwolnij RAM i CPU. Zwraca kartę jak narzędzia SYSOP."""
    before = _mem_line()
    steps: list[str] = []

    # 1. Wyładuj modele z pamięci przez API (bez sudo). keep_alive 0 =
    #    Ollama zwalnia wagi z RAM od razu po tym wywołaniu.
    for name in _loaded_models():
        try:
            _api("/api/generate", {"model": name, "keep_alive": 0, "prompt": "", "stream": False}, timeout=15)
            steps.append(f"wyładowano model {name} z pamięci")
        except Exception:
            pass

    # 2. Zatrzymaj usługę Ollamy (sudo TYLKO na ollama - lista install.sh).
    res = sysop_mod.run_cmd(["systemctl", "stop", "ollama"], sudo=True)
    sysop_mod.audit("freeram", "systemctl stop ollama", "tryb", res["rc"] == 0,
                    "zatrzymano usługę Ollamy" if res["rc"] == 0 else f"nie powiodło się (kod {res['rc']})")
    if res["rc"] == 0:
        steps.append("zatrzymano usługę Ollamy")
    else:
        steps.append("Ollamy nie zatrzymałem (brak uprawnień) - w terminalu: sudo systemctl stop ollama")

    after = _mem_line()
    stopped = res["rc"] == 0
    speech = ("Tryb Freeram: zwolniłem pamięć i oddałem moc maszynie. Zabezpieczenia (WARP, zapora) "
              "zostają włączone. Do czasu „fullon” odpowiadam bez lokalnego modelu." if stopped else
              "Tryb Freeram: wyładowałem modele z pamięci, ale usługi Ollamy nie zatrzymałem (brak uprawnień), "
              "więc model wróci przy następnym pytaniu. Zatrzymaj ją sam: sudo systemctl stop ollama.")
    output = (f"PRZED:  {before}\n"
              f"PO:     {after}\n\n"
              + "\n".join("- " + s for s in steps)
              + "\n\nBufory dysku Linux zwalnia sam, gdy pamięć jest potrzebna, "
                "więc nie ma po co ich 'czyścić'. WARP, ufw i apparmor celowo "
                "nietknięte.")
    import router  # leniwie: router importuje capabilities, a te ten moduł
    router.pin_big(False)
    return {"speech": speech, "card": {"type": "sysop", "tool": "freeram", "output": output}, "model_active": not stopped}


def fullon() -> dict:
    """Tryb Fullon: pełna moc dla lokalnego AI. Może potrwać (wczytanie
    dużego modelu na tym CPU to minuty) - czat czeka przez long-poll."""
    model = _model()
    steps: list[str] = []

    # 1. Uruchom Ollamę, jeśli stoi (sudo tylko na ollama).
    if not _ollama_up():
        res = sysop_mod.run_cmd(["systemctl", "start", "ollama"], sudo=True)
        sysop_mod.audit("fullon", "systemctl start ollama", "tryb", res["rc"] == 0,
                        "uruchomiono usługę Ollamy" if res["rc"] == 0 else f"nie powiodło się (kod {res['rc']})")
        if res["rc"] == 0:
            steps.append("uruchomiono usługę Ollamy")
            for _ in range(30):  # poczekaj aż wstanie (do 30 s)
                if _ollama_up():
                    break
                time.sleep(1)
        else:
            # Start się nie udał: czekanie nic nie da, więc od razu zgłaszamy.
            steps.append("Ollamy nie uruchomiłem (brak uprawnień) - w terminalu: sudo systemctl start ollama")

    # 2. Wczytaj i PRZYPNIJ duży model w RAM (keep_alive -1), rozgrzej.
    #    Pusty prompt = samo wczytanie modelu (zalecany sposób preloadu w
    #    Ollamie). Długi timeout, bo na zimno na i7-6600U to kilka minut.
    loaded = False
    warm_big = False
    if _ollama_up():
        try:
            _api("/api/generate", {"model": model, "keep_alive": -1, "prompt": "", "stream": False}, timeout=900)
            loaded = True
            steps.append(f"wczytano i przypięto model {model} w RAM (keep_alive -1)")
            import router  # leniwie: router importuje capabilities, a te ten moduł
            router.pin_big(True)
            # Same wagi w RAM to nie wszystko: pierwsza odpowiedź płaciłaby jeszcze
            # przetworzenie promptu systemowego (minuty na tym CPU), więc rozgrzewamy go w tle
            # tym samym promptem, co przy starcie (main.py podaje go przez SYSTEM_PROMPT).
            warm_big = SYSTEM_PROMPT is not None and not router._student_manifest_ok()[0]
            if warm_big:  # z aktywnym uczniem duży model nie rozmawia, więc nie ma czego rozgrzewać
                router.warm_up_async(SYSTEM_PROMPT())
                steps.append("rozgrzewam prompt systemowy w tle (stan w /debug)")
        except Exception as e:
            steps.append(f"nie udało się wczytać modelu {model} ({type(e).__name__})")
    else:
        steps.append("Ollama nie odpowiada - nie wczytałem modelu")

    after = _mem_line()
    # Bez podpowiedzi "governor performance": na tym procesorze (intel_pstate) dawałby +1-2 W
    # w bezczynności przez cały dzień i najwyżej kilka procent szybsze odpowiedzi.
    gov_hint = "Procesor sam przyspiesza pod obciążeniem; na baterii pełna moc skraca jej czas."
    speech = (f"Tryb Fullon: jestem na pełnej mocy, model {model} siedzi w pamięci"
              + (" i rozgrzewa się na pierwszą odpowiedź." if warm_big else ".") if loaded else
              f"Tryb Fullon: próbowałem wejść na pełną moc, ale model {model} się nie "
              f"wczytał. Sprawdź /debug albo czy Ollama działa.")
    output = "\n".join("- " + s for s in steps) + f"\n\n{after}\n\n{gov_hint}"
    return {"speech": speech, "card": {"type": "sysop", "tool": "fullon", "output": output}, "model_active": loaded}


# Port i sieci prywatne: te same wartości co main.py (PORT) i install.sh (pętla
# po sieciach przy GREGAI_LAN). Zmiana w jednym miejscu wymaga zmiany w obu -
# nie da się zaimportować main.py tutaj (import kołowy: main.py -> capabilities
# -> tryby), a install.sh to bash, nie Python.
_PORT = 7777
_PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")

# 1.19.0 (audyt systemu): czy sudo w ogóle pozwoli na poweroff. Sprawdzane
# RAZ, w tle, przy starcie modułu (sudo -n -l niczego nie wykonuje, tylko pyta
# o reguły) - panicmode() nie może czekać na nic systemowego przed odpowiedzią
# (kontrola 26), ale ma mówić prawdę: przy braku reguł (np. stary install.sh
# kasował je razem z SYSOP_ENABLED=0) "wyłączam komputer" było kłamstwem.
# Audyt 1.32.1: ustawiane przez gregaipanicmode; main._authorized odrzuca wtedy wszystko spoza localhost.
PANIC_LOCK = threading.Event()
_SUDO_PANIC: dict = {"ok": None, "why": ""}


def _probe_panic_sudo() -> None:
    import subprocess
    time.sleep(3.0)  # nie w chwili importu: start usługi ma inne rzeczy do zrobienia
    try:
        res = subprocess.run(["sudo", "-n", "-l", "/usr/bin/systemctl", "poweroff"], capture_output=True,
                             text=True, timeout=5)
        _SUDO_PANIC["ok"] = res.returncode == 0
        _SUDO_PANIC["why"] = "" if res.returncode == 0 else (res.stderr.strip()[:160] or "brak reguły sudo")
    except Exception as e:
        _SUDO_PANIC["ok"] = False
        _SUDO_PANIC["why"] = f"{type(e).__name__}"


threading.Thread(target=_probe_panic_sudo, daemon=True, name="panic-sudo-probe").start()


def panicmode() -> dict:
    """GREGAIPANICMODE - awaryjna blokada (prośba Grzegorza, 2026-10-19):
    "ta komenda ma blokować serwer od środka, czyli stawiać znowu zaporę i
    wyłączać tryb LAN (...) a później wyłącza cały komputer, tylko z poziomu
    serwera żebym mógł znowu włączyć LAN". Dwa etapy, w TEJ kolejności:

    1. Zamyka dostęp z sieci:
       - cofa w zaporze (ufw) reguły wpuszczające GREGAI z sieci prywatnych -
         DOKŁADNIE te same polecenia, co install.sh przy GREGAI_LAN=0 (ufw
         delete allow ... dla _PRIVATE_NETS/_PORT wyżej). Domyślna polityka
         ufw (deny incoming) zostaje z instalacji, więc bez tych reguł port
         jest z sieci domowej całkowicie niedostępny.
       - zapisuje GREGAI_LAN=0 w .env (ten sam zapis co przełącznik na
         /debug, env_loader.set_env_vars): po ponownym włączeniu komputera
         GREGAI wstaje domyślnie tylko na localhost - włączenie LAN z
         powrotem wymaga bycia PRZY komputerze (panel na 127.0.0.1:_PORT),
         nie z telefonu czy innego urządzenia w sieci.
    2. Wyłącza CAŁY komputer (systemctl poweroff) - nie restart usługi
       GREGAI, nie zatrzymanie Ollamy: cała maszyna.

    Poprawka 1.16.2 (kolejność względem ODPOWIEDZI, nie tylko względem
    poweroff): do 1.16.1 etap 1 (ufw delete x3 + zapis .env) wykonywał się
    SYNCHRONICZNIE w wątku obsługującym to zapytanie czatu, PRZED zwróceniem
    odpowiedzi do main.py/long-poll - tylko etap 2 (poweroff) miał opóźnienie.
    To realne ryzyko akurat na TYM telefonie-przez-LAN scenariuszu, dla
    którego panicmode w ogóle powstał: jeśli domyślna reguła ufw "ESTABLISHED,
    RELATED ACCEPT" (before.rules) zostanie kiedyś zmieniona przy dalszym
    utwardzaniu zapory, zamknięcie portu MOGŁOBY przeciąć akurat trwające
    połączenie długiego odpytywania (/api/chat/wait), zanim odpowiedź
    "zablokowałem sieć, wyłączam komputer" w ogóle zdąży wyjść - czyli
    Grzegorz straciłby jedyne potwierdzenie, że polecenie się przyjęło,
    dokładnie w chwili, w której najbardziej go potrzebuje. Teraz CAŁA
    sekwencja (ufw, .env, poweroff) idzie w wątku w tle, a ta funkcja wraca
    NATYCHMIAST, zanim cokolwiek dotknie sieci: main.py ma więc zawsze czas
    dokończyć i wysłać tę jedną odpowiedź, która by się liczyła, zanim zapora
    się zamknie. Kolejność ufw-przed-poweroff (świadomy wymóg wyżej) zostaje
    dokładnie taka sama - zmienia się tylko to, że obie liczą się od momentu,
    gdy odpowiedź już opuściła tę funkcję, nie od momentu wywołania. Pełny,
    rzeczywisty wynik każdego kroku (OK/kod błędu) nadal trafia do dziennika
    SYSOP (sysop_mod.audit, Nadzorca -> System i dostęp) - tylko już nie do
    TEJ konkretnej wiadomości czatu, bo ta musi wyjść pierwsza.

    Zapora jest dla kodu GREGAI normalnie NIETKNIĘTA (agent/sysop.py traktuje
    ufw jako chronione, read-only; main._handle_lan_mode też jej nie rusza) -
    to jedyny, świadomy wyjątek: idzie wyłącznie w stronę BARDZIEJ
    restrykcyjną, nigdy odwrotnie, i tylko z tej jednej, literalnej,
    user_only frazy (capabilities.py: ani router, ani planer pętli agenta
    nie mogą jej wybrać). Oba polecenia (ufw, systemctl poweroff) idą przez
    sysop_mod.run_cmd z force_sudo=True (1.18.0: `sudo -n` zawsze, także przy
    SYSOP_USE_SUDO=0 - wcześniej wtedy szły bez sudo, cicho padały, a
    użytkownik słyszał "w toku"), czyli BEZ przejścia przez klasyfikator
    agent/sysop.py (classify_shell/DESTRUCTIVE_PATTERNS blokuje poweroff na
    stałe na TEJ ścieżce, ale ta ścieżka jest dla poleceń, które model/
    SYSOP_SHELL mógłby wybrać dowolnie - run_cmd() samo niczego nie
    klasyfikuje, dokładnie tak, jak freeram/fullon wyżej już obchodzą ją dla
    `systemctl stop/start ollama`). W trybie strażniczym osobny, wąski wpis
    sudoers (/etc/sudoers.d/gregai-panic, install.sh: PANIC_RULES; 1.19.0:
    osobny plik instalowany ZAWSZE, także przy SYSOP_ENABLED=0 - wcześniej
    leżał w gregai-sysop i znikał razem z nim) zezwala TYLKO na te (ufw x3 i trzy formy poweroff)
    dokładne polecenia, nic więcej. Gdy sudo ich nie pozwala (_SUDO_PANIC),
    odpowiedź mówi to wprost zamiast obiecywać wyłączenie."""

    def _zablokuj_i_wylacz() -> None:
        # 0. Audyt 1.32.1: od tej chwili serwer odrzuca KAŻDE żądanie API spoza tego
        #    komputera (main._authorized), także na już otwartych połączeniach z
        #    telefonu - reguła ESTABLISHED w ufw by je przepuściła. Zostaje do restartu,
        #    więc chroni także wtedy, gdy wyłączenie komputera się nie uda.
        PANIC_LOCK.set()
        # 1a. Zapora: cofnij reguły wpuszczające GREGAI z sieci prywatnych.
        for net in _PRIVATE_NETS:
            res = sysop_mod.run_cmd(
                ["ufw", "delete", "allow", "from", net, "to", "any", "port", str(_PORT), "proto", "tcp"],
                force_sudo=True,
            )
            sysop_mod.audit("gregaipanicmode", f"ufw delete allow from {net} to any port {_PORT} proto tcp",
                            "panicmode", res["rc"] == 0,
                            "reguła zapory cofnięta" if res["rc"] == 0 else f"nie powiodło się (kod {res['rc']})")

        # 1b. .env: GREGAI_LAN=0, żeby komputer po ponownym włączeniu wstał tylko na localhost.
        try:
            env_loader_mod.set_env_vars({"GREGAI_LAN": "0"}, {
                "GREGAI_LAN": "# gregaipanicmode (panic mode) wyłączył dostęp z sieci lokalnej. Z powrotem:\n"
                              "# tylko z /debug NA TYM komputerze.\n",
            })
            sysop_mod.audit("gregaipanicmode", "zapis .env GREGAI_LAN=0", "panicmode", True,
                            "tryb LAN wyłączony w .env")
        except OSError as e:
            sysop_mod.audit("gregaipanicmode", "zapis .env GREGAI_LAN=0", "panicmode", False,
                            f"nie udało się zapisać .env ({type(e).__name__})")

        # 2. Wyłącz cały komputer - z opóźnieniem, żeby zapora z 1a/1b na pewno
        #    zdążyła się już zastosować (osobny proces ufw) i żeby dowolny
        #    jeszcze otwarty długi odpyt miał margines, zanim systemd zacznie
        #    zatrzymywać usługi.
        time.sleep(2.0)
        # 1.30.31 (zgłoszenie Grzegorza: zapora i .env "wykonane", a "systemctl poweroff:
        # odmowa/błąd" - komputer został włączony). Zwykłe poweroff odmawia, gdy coś trzyma
        # blokadę wyłączenia (inhibitor: aktualizacje w tle, sesja pulpitu, drugi
        # zalogowany użytkownik) - a wyłącznik awaryjny nie może się na tym zatrzymać.
        # Kolejne próby, od najłagodniejszej: zwykłe -> z pominięciem blokad (-i) ->
        # wymuszone (--force: bez porządnego zatrzymania usług, ale dyski i tak są
        # odmontowywane; .env jest już zapisany atomowo). Każda próba z powodem w dzienniku.
        attempts = (["systemctl", "poweroff"], ["systemctl", "poweroff", "-i"], ["systemctl", "poweroff", "--force"])
        for i, argv in enumerate(attempts):
            res = sysop_mod.run_cmd(argv, force_sudo=True)
            ok_ = res["rc"] == 0
            why = " ".join(((res.get("err") or "") + " " + (res.get("out") or "")).split())[:200]
            sysop_mod.audit("gregaipanicmode", " ".join(argv), "panicmode", ok_,
                            "wyłączono komputer" if ok_ else
                            f"nie powiodło się (kod {res['rc']}" + (f": {why}" if why else "") + ")"
                            + (" - próbuję mocniej" if i + 1 < len(attempts) else ""))
            if ok_:
                break
            time.sleep(1.0)
        else:
            sysop_mod.audit("gregaipanicmode", "blokada dostępu z sieci", "panicmode", True,
                            "komputer NIE wyłączył się; GREGAI odrzuca wszystko spoza tego komputera do restartu")

    threading.Thread(target=_zablokuj_i_wylacz, daemon=True).start()

    if _SUDO_PANIC["ok"] is False:
        # Kroki i tak idą (sprawdzenie mogło się pomylić), ale odpowiedź nie obiecuje
        # czegoś, na co system nie pozwala.
        speech = ("GREGAIPANICMODE: wyłączam tryb LAN w .env, ale NIE MAM uprawnień sudo do zapory ani do wyłączenia "
                  "komputera (" + (_SUDO_PANIC["why"] or "brak reguły") + "). Zrób to sam: sudo ufw status, "
                  "sudo systemctl poweroff. Napraw na stałe: bash install.sh (instaluje /etc/sudoers.d/gregai-panic).")
        output = ("- wyłączenie trybu LAN w .env: w toku\n"
                  "- zapora (ufw) i wyłączenie komputera: próbuję, ale sudo najpewniej odmówi\n\n"
                  "Wynik każdego kroku trafia do dziennika SYSOP (Nadzorca -> System i dostęp).")
    else:
        speech = ("GREGAIPANICMODE: blokuję dostęp z sieci (zapora + tryb LAN) i zaraz potem wyłączam cały komputer. "
                  "Z powrotem tylko bezpośrednio na tym komputerze.")
        output = ("- blokowanie zapory (ufw) i wyłączenie trybu LAN: w toku\n"
                  "- wyłączenie całego komputera (systemctl poweroff): w toku, z krótkim opóźnieniem\n\n"
                  "Pełny wynik każdego kroku (OK/błąd) trafia do dziennika SYSOP (Nadzorca -> System i dostęp), "
                  "bo ta wiadomość musi wyjść pierwsza - zanim zapora się zamknie.")
    return {"speech": speech, "card": {"type": "sysop", "tool": "gregaipanicmode", "output": output}, "model_active": False}
