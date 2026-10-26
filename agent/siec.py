"""
siec.py

GREGAI: monitoring sieci lokalnej. TYLKO ODCZYT. Nigdy nie zmienia konfiguracji
sieci, routera, firewalla. Nigdy nie blokuje ani nie wyłącza żadnego
urządzenia. Jedyne co robi: wykrywa, kto jest w sieci, zapisuje do
własnego inwentarza, i zgłasza alert gdy zobaczy coś nowego (albo gdy
znane urządzenie wraca po długiej nieobecności).

Zasady bezpieczeństwa (twarde, nie do obejścia bez zmiany kodu):
  - Żadnych zapisów poza data/network_inventory.json, data/network_scan_meta.json,
    data/network_alerts.jsonl, blokadą data/.siec.lock i (przez router_bridge.py,
    przy pierwszym połączeniu z routerem) data/router_cert.json.
  - Żadnych komend systemowych budowanych przez sklejanie stringów z
    danych z sieci (nazwy hostów, odpowiedzi DNS): zawsze subprocess
    z listą argumentów, nigdy shell=True z interpolacją.
  - Dane z sieci (hostname, odpowiedzi ARP, adresy MAC) to DANE, nigdy
    polecenia: nic stąd nie jest nigdy wykonywane jako komenda.
  - Brak sudo/root. Jeśli coś wymaga uprawnień, których nie ma,
    zgłasza to jawnie i kończy, zamiast próbować obejść.

Wymaga systemowych narzędzi `ping` i `ip` (standardowe w każdym
Linuksie), bez żadnych nowych zależności pip (poza router_bridge.py,
który ma własną, osobno uzasadnioną zależność).
"""

from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import homenet

import fsutil

DATA_DIR = Path(__file__).parent.parent / "data"
INVENTORY_PATH = DATA_DIR / "network_inventory.json"
ALERTS_PATH = DATA_DIR / "network_alerts.jsonl"
SCAN_META_PATH = DATA_DIR / "network_scan_meta.json"

PING_TIMEOUT_S = 1
MAX_WORKERS = 32

# Po ilu dniach nieobecności powrót znanego urządzenia jest na tyle
# ciekawy, żeby zgłosić go jako alert (a nie po prostu zaktualizować
# "last_seen" po cichu).
RETURN_ALERT_THRESHOLD_DAYS = 3
# Ile ostatnich adresów IP urządzenia pamiętamy (najnowszy na końcu).
MAX_IP_HISTORY = 20

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", re.IGNORECASE)

LOCK_PATH = DATA_DIR / ".siec.lock"
# Plik alertów przycinamy, gdy urośnie ponad MAX_ALERT_BYTES: zostaje KEEP_ALERTS ostatnich.
MAX_ALERT_BYTES = 256 * 1024
KEEP_ALERTS = 500


def _clean_hostname(name: str) -> str:
    """Nazwa urządzenia pochodzi z sieci (DHCP, DNS), więc to dane od obcych:
    zostają tylko drukowalne znaki, najwyżej 63. Dzięki temu nie trafi do
    inwentarza, interfejsu ani rozmowy nic poza zwykłym tekstem nazwy."""
    cleaned = "".join(ch for ch in str(name or "") if ch.isprintable() and ch not in "<>\"'`")
    return cleaned.strip()[:63]


def _sane_device(d: dict) -> dict | None:
    """Urządzenie z routera/skanu w poprawnej postaci albo None (zły adres IP)."""
    try:
        ip = str(ipaddress.ip_address(str(d.get("ip") or "").strip()))
    except ValueError:
        return None
    mac = str(d.get("mac") or "").strip().lower()
    return {"ip": ip, "mac": mac if _MAC_RE.match(mac) else "", "hostname": _clean_hostname(d.get("hostname"))}


# --- Rozpoznawanie producenta z adresu MAC (OUI) ----------------------------
# Skrócona, wyselekcjonowana tabela popularnych prefiksów. NIE jest to
# pełna baza IEEE OUI (ta ma dziesiątki tysięcy wpisów). Celowo: tylko
# prefiksy, których jestem pewny. Nieznany prefiks = puste "", nigdy
# zgadywanie. Największa realna wartość tego mechanizmu: rozpoznanie
# "to raczej gadżet IoT (Espressif/ESP32)" dla urządzeń, które nie
# zgłaszają żadnego hostname przez DHCP, to te najczęściej "nieznane".
_OUI_VENDORS = {
    # Espressif (ESP32/ESP8266, typowy chip w smart-wtyczkach, czujnikach,
    # kamerkach no-name): to jest najcenniejsza część tej tabeli.
    "246F28": "Espressif (IoT/ESP32)",
    "30AEA4": "Espressif (IoT/ESP32)",
    "3C71BF": "Espressif (IoT/ESP32)",
    "84F3EB": "Espressif (IoT/ESP32)",
    "ECFABC": "Espressif (IoT/ESP32)",
    "68C63A": "Espressif (IoT/ESP32)",
    "A020A6": "Espressif (IoT/ESP32)",
    "7C9EBD": "Espressif (IoT/ESP32)",
    # Raspberry Pi Foundation
    "B827EB": "Raspberry Pi",
    "DCA632": "Raspberry Pi",
    "D83ADD": "Raspberry Pi",
    "E45F01": "Raspberry Pi",
    # Routery / sieć domowa
    "50C7BF": "TP-Link",
    "EC086B": "TP-Link",
    "C46E1F": "TP-Link",
    "24A43C": "Ubiquiti",
    "0418D6": "Ubiquiti",
    "FCECDA": "Ubiquiti",
    # Amazon (Echo/Alexa/Fire)
    "44650D": "Amazon (Echo/Fire)",
    "6837E9": "Amazon (Echo/Fire)",
    "74C246": "Amazon (Echo/Fire)",
    "AC63BE": "Amazon (Echo/Fire)",
    # Google / Nest
    "94EB2C": "Google/Nest",
    "F4F5D8": "Google/Nest",
    # Sonos
    "5CAAFD": "Sonos",
    "949F3E": "Sonos",
    # Komputery / laptopy, karty sieciowe
    "3CA9F4": "Intel",
    "A434D9": "Intel",
    "F8B156": "Dell",
    "7C1E52": "Microsoft (Surface/Xbox)",
    # Konsole
    "280DFC": "Sony (PlayStation)",
    "AC9B0A": "Sony (PlayStation)",
    "98B6E9": "Nintendo (Switch)",
    "7CBB8A": "Nintendo (Switch)",
}


def _looks_like_mac(key: str) -> bool:
    return bool(_MAC_RE.match(key))


def _is_locally_administered(mac: str) -> bool:
    """Bit 'locally administered' w pierwszym oktecie: ustawiony, gdy
    system losuje adres MAC dla prywatności (standard od Androida 10+,
    iOS). W takim wypadku szukanie producenta w tabeli OUI nie ma sensu
    (adres jest losowy, nie przypisany fabrycznie), lepiej to jasno
    powiedzieć niż zgadywać."""
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0x02)
    except Exception:
        return False


def vendor_for_mac(mac: str) -> str:
    """Najlepsze przybliżenie producenta na podstawie MAC-a. Nigdy nie
    zgaduje: nieznany prefiks -> "". Losowy/prywatny adres -> osobny,
    wyjaśniający komunikat (żeby nie wyglądało to jak "nie wiem")."""
    if not mac:
        return ""
    if _is_locally_administered(mac):
        return "losowy adres (urządzenie chroni prywatność, np. Android/iOS)"
    prefix = mac.upper().replace(":", "")[:6]
    return _OUI_VENDORS.get(prefix, "")


def _local_subnet() -> ipaddress.IPv4Network | None:
    """Podsieć fizycznego interfejsu z trasą domyślną (agent/homenet.py).
    Wcześniej: adres z "połączenia" UDP do 8.8.8.8 - przy włączonym
    Cloudflare WARP to adres tunelu (172.16.0.x), czyli skan zupełnie
    nie tej sieci."""
    return homenet.local_subnet()


def _ping(ip: str) -> bool:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(PING_TIMEOUT_S), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PING_TIMEOUT_S + 3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _read_arp_table() -> dict:
    """ip neigh show: tylko odczyt tablicy ARP już zbudowanej przez
    system po ping-sweepie. Zwraca {ip: mac}."""
    table = {}
    try:
        # Tylko interfejs z trasą domyślną: wpis z docker0/vboxnet o tym samym adresie
        # nadpisałby wpis z sieci domowej.
        route = homenet.default_route()
        cmd = ["ip", "neigh", "show"] + (["dev", route["dev"]] if route else [])
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            m = re.match(r"^(\S+)\s+(?:dev\s+\S+\s+)?lladdr\s+([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\b", line)
            if m:
                table[m.group(1)] = m.group(2).lower()
    except Exception:
        pass
    return table


def _reverse_dns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _scan_via_ping() -> list[dict]:
    subnet = _local_subnet()
    if subnet is None:
        raise RuntimeError("Nie udało się ustalić własnej podsieci, pomijam skan.")

    # Bez `ping` (pakiet iputils-ping) każdy ping "nie odpowiada" i skan wyglądałby
    # na udany z zerem urządzeń, a cały inwentarz dostałby flagę offline.
    if shutil.which("ping") is None:
        raise RuntimeError("Brak polecenia ping (pakiet iputils-ping), pomijam skan.")
    hosts = [str(h) for h in subnet.hosts()]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        alive = list(pool.map(_ping, hosts))
    alive_ips = [ip for ip, ok in zip(hosts, alive) if ok]

    # Własne adresy laptopa odpowiadają na ping, ale nie mają wpisu sąsiada: trafiałyby do
    # inwentarza jako "nowe urządzenie" po każdej zmianie adresu z DHCP.
    own = homenet.own_addresses()
    alive_ips = [ip for ip in alive_ips if ip not in own]
    arp = _read_arp_table()
    # Odwrotny DNS potrafi zwlekać kilka sekund na urządzenie: równolegle.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        names = list(pool.map(_reverse_dns, alive_ips))
    return [{"ip": ip, "mac": arp.get(ip, ""), "hostname": name} for ip, name in zip(alive_ips, names)]


def scan() -> tuple[list[dict], str]:
    """Źródło urządzeń: najpierw router (dokładniejsze, zna nazwy z
    DHCP nawet dla cichych urządzeń), fallback na ping-sweep gdy
    router niedostępny/nieskonfigurowany. Zwraca ([{ip, mac, hostname}],
    źródło), źródło pozwala network_status() powiedzieć, czy dane są
    tak dokładne, jak mogłyby być."""
    try:
        import router_bridge
        router_devices = router_bridge.devices_from_router()
        if router_devices is not None:
            return router_devices, "router"
    except Exception:
        pass
    return _scan_via_ping(), "ping"


def _normalize_entry(entry: dict) -> None:
    """Pole o złym typie (plik edytowany ręcznie, stara wersja) naprawiamy na miejscu,
    zamiast przewracać nim cały skan albo odpowiedź o sieci."""
    for field in ("mac", "hostname", "vendor"):
        if not isinstance(entry.get(field, ""), str):
            entry[field] = ""
    for field in ("first_seen", "last_seen"):
        if field in entry and not isinstance(entry[field], str):
            entry[field] = None
    if "online" in entry and not isinstance(entry["online"], bool):
        entry["online"] = bool(entry["online"])
    history = entry.get("ip_history")
    if "ip_history" in entry and not (isinstance(history, list) and all(isinstance(h, str) for h in history)):
        entry["ip_history"] = [h for h in history if isinstance(h, str)] if isinstance(history, list) else []


def _load_inventory() -> dict:
    if not INVENTORY_PATH.exists():
        return {}
    try:
        raw = INVENTORY_PATH.read_text(encoding="utf-8-sig")
    except OSError as e:
        # Chwilowy błąd odczytu (brak uprawnień po `sudo python3 agent/siec.py`, błąd dysku)
        # to nie uszkodzony plik: odsunięcie go zrobiłoby ze wszystkich urządzeń "nowe".
        raise RuntimeError(f"nie da się odczytać inwentarza ({type(e).__name__}), pomijam ten cykl") from e
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # Wpis nie będący słownikiem (ręczny komentarz) jest pomijany, nie unieważnia całości.
            data = {k: v for k, v in data.items() if isinstance(v, dict)}
            for entry in data.values():
                _normalize_entry(entry)
            return data
    except ValueError:
        pass
    # Uszkodzony inwentarz zostaje obok jako .corrupt-<data>, zamiast zginąć pod
    # nowym, pustym plikiem (wszystkie urządzenia byłyby wtedy "nowe").
    fsutil.quarantine(INVENTORY_PATH)
    return {}


def _save_inventory(inventory: dict):
    fsutil.atomic_write_text(INVENTORY_PATH, json.dumps(inventory, ensure_ascii=False, indent=2))


def _save_scan_meta(meta: dict):
    fsutil.atomic_write_text(SCAN_META_PATH, json.dumps(meta, ensure_ascii=False, indent=2))


def scan_meta() -> dict:
    """Metadane ostatniego cyklu skanowania: kiedy, jakim źródłem (router
    = dokładne DHCP, ping = fallback), ile urządzeń. Używane do uczciwego
    powiedzenia, jak świeże/wiarygodne są dane w odpowiedzi czatu."""
    if not SCAN_META_PATH.exists():
        return {}
    try:
        meta = json.loads(SCAN_META_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def _log_alert(alert: dict):
    fsutil.append_private_line(ALERTS_PATH, fsutil.json_line(alert))
    try:
        if ALERTS_PATH.stat().st_size > MAX_ALERT_BYTES:
            # errors="replace": urwany w połowie znak wielobajtowy (zanik zasilania)
            # nie może przewracać przycinania przy każdym kolejnym alercie.
            lines = ALERTS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-KEEP_ALERTS:]
            fsutil.atomic_write_text(ALERTS_PATH, "\n".join(lines) + "\n")
    except OSError:
        pass


def _days_since(last_seen_iso: str | None, now_iso: str) -> float | None:
    if not last_seen_iso:
        return None
    try:
        last = datetime.fromisoformat(last_seen_iso)
        now = datetime.fromisoformat(now_iso)
        return (now - last).total_seconds() / 86400
    except Exception:
        return None


def _dedup_by_ip(inventory: dict) -> dict:
    """Scala duplikaty tego samego fizycznego urządzenia pod dwoma
    różnymi kluczami. Powstają, gdy raz źródłem skanu jest router (ma
    MAC dla każdego urządzenia) a raz ping-sweep (czasem nie zdobywa
    MAC-a dla tego samego urządzenia, typowo dla samej bramy), ten sam
    IP trafia wtedy do inwentarza pod kluczem-MAC-iem RAZ i kluczem-IP
    drugi raz, i licznik urządzeń w sieci jest zawyżony.

    Reguła scalania: zachowaj wpis kluczowany MAC-iem (wiarygodniejszy,
    bo MAC nie zmienia się przy DHCP tak jak IP), wchłoń do niego dane
    (first_seen/last_seen/ip_history/hostname) z wpisu bez MAC-a o tym
    samym IP, usuń duplikat."""
    # Tylko AKTUALNY adres wpisu (ostatni w historii), tak samo jak w
    # _run_cycle_locked: adres, który wpis miał kiedyś, mógł dostać inny sprzęt,
    # a ten nie może się wchłonąć w znane urządzenie i zniknąć z alertów.
    by_ip: dict[str, list[str]] = {}
    for key, entry in inventory.items():
        history = entry.get("ip_history")
        if isinstance(history, list) and history:
            by_ip.setdefault(history[-1], []).append(key)

    merged = dict(inventory)
    for ip, keys in by_ip.items():
        keys_present = [k for k in keys if k in merged]
        if len(keys_present) < 2:
            continue
        mac_keys = [k for k in keys_present if _looks_like_mac(k)]
        # Dwa różne MAC-i pod jednym IP to dwa różne urządzenia (DHCP oddał
        # adres dalej): nie scalamy ich ze sobą, tylko wpisy bez MAC-a.
        keys_present = [k for k in keys_present if k not in mac_keys[1:]]
        if len(keys_present) < 2:
            continue
        keep = mac_keys[0] if mac_keys else keys_present[0]
        for k in keys_present:
            if k == keep:
                continue
            other = merged.pop(k, None)
            if other is None:
                continue
            keep_entry = merged[keep]
            if other.get("first_seen") and (not keep_entry.get("first_seen") or other["first_seen"] < keep_entry["first_seen"]):
                keep_entry["first_seen"] = other["first_seen"]
            if other.get("last_seen") and (not keep_entry.get("last_seen") or other["last_seen"] > keep_entry["last_seen"]):
                keep_entry["last_seen"] = other["last_seen"]
            for h in other.get("ip_history", []):
                if h not in keep_entry.setdefault("ip_history", []):
                    keep_entry["ip_history"].append(h)
            if not keep_entry.get("hostname") and other.get("hostname"):
                keep_entry["hostname"] = other["hostname"]
            if not keep_entry.get("vendor") and other.get("vendor"):
                keep_entry["vendor"] = other["vendor"]
    return merged


def run_cycle() -> dict:
    """Jeden pełny cykl: skanuj, scal ewentualne duplikaty, porównaj z
    inwentarzem, zapisz, zwróć podsumowanie (ile urządzeń, ile nowych,
    ile wróciło po długiej nieobecności). Dwa uruchomienia (timer systemd i
    ręczne z terminala) nie biegną naraz: drugie widzi blokadę i odpuszcza, bo
    inaczej oba czytałyby i nadpisywały ten sam inwentarz."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        # Cudzy (np. roota) plik blokady: cykl pomijamy, ale z zapisanym powodem, żeby
        # network_status nie pokazywał starego zrzutu jako aktualnego.
        _save_scan_meta({"ok": False, "skipped": f"blokada skanu niedostępna ({type(e).__name__}: {LOCK_PATH.name})",
                         "time": datetime.now().isoformat(timespec="seconds"), "source": None})
        return {"ok": False, "skipped": f"blokada skanu niedostępna ({type(e).__name__})"}
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"skipped": "inny skan sieci jest w toku", "ts": datetime.now().isoformat(timespec="seconds")}
        return _run_cycle_locked()
    finally:
        os.close(fd)  # zamknięcie zwalnia blokadę


def _run_cycle_locked() -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    # Skanujemy WYŁĄCZNIE sieć domową (agent/homenet.py): laptop bywa w
    # obcych sieciach, a pingowanie cudzych urządzeń to skanowanie cudzej
    # sieci. Poza domem: nic nie wysyłamy, tylko zapisujemy powód.
    home, why = homenet.is_home()
    if not home:
        _save_scan_meta({"time": now, "source": None, "skipped": why, "ok": False})
        return {"skipped": why, "ts": now}
    try:
        inventory = _dedup_by_ip(_load_inventory())
    except RuntimeError as e:
        _save_scan_meta({"time": now, "source": None, "skipped": str(e), "ok": False})
        return {"skipped": str(e), "ts": now}
    raw_devices, source = scan()
    devices = [d for d in (_sane_device(x) for x in raw_devices) if d is not None]

    # Mapa AKTUALNY IP wpisu -> klucz, żeby urządzenie bez MAC-a w TYM skanie
    # (np. brama przy ping-fallbacku) trafiło do swojego istniejącego wpisu, a nie
    # stworzyło duplikatu. Tylko aktualny adres (ostatni w historii): adres, który
    # wpis miał kiedyś, mógł dostać zupełnie inny sprzęt, a ten nie może się
    # przedstawić jako znane urządzenie i pominąć alertu "nowe w sieci".
    ip_to_key: dict[str, str] = {}
    for key, entry in inventory.items():
        history = entry.get("ip_history") or []
        if history:
            ip_to_key[history[-1]] = key

    new_devices = []
    returning_devices = []
    new_keys: list[str] = []        # klucze wpisów dodanych w tym cyklu (równolegle do new_devices)
    returning_prev: list[tuple] = []  # (klucz, poprzednie last_seen, poprzednie online)
    seen_keys: set[str] = set()

    for d in devices:
        if d["mac"] and d["mac"] not in inventory:
            # Wpis założony wcześniej bez MAC-a (skan pingiem) dostaje MAC, gdy ten
            # sam adres pokazuje się teraz z MAC-iem (skan przez router): to ten sam
            # sprzęt, a nie nowe urządzenie.
            legacy = ip_to_key.get(d["ip"])
            if legacy and legacy != d["mac"] and not inventory[legacy].get("mac"):
                inventory[d["mac"]] = inventory.pop(legacy)
                ip_to_key[d["ip"]] = d["mac"]
        key = d["mac"] or ip_to_key.get(d["ip"]) or d["ip"]
        seen_keys.add(key)
        vendor = vendor_for_mac(d["mac"]) if d["mac"] else ""

        if key not in inventory:
            new_devices.append(d)
            new_keys.append(key)
            inventory[key] = {
                "mac": d["mac"],
                "hostname": d["hostname"],
                "vendor": vendor,
                "first_seen": now,
                "last_seen": now,
                "ip_history": [d["ip"]],
                "status": "nieznane",
                "online": True,
            }
        elif (not d["mac"] and not inventory[key].get("mac") and d["hostname"] and inventory[key].get("hostname")
              and d["hostname"].lower() != str(inventory[key]["hostname"]).lower()):
            # 1.32.11 (audyt tura 15): wpis po samym IP (bez MAC), a pod tym adresem jest już INNY
            # host - to nowe urządzenie, nie "zmiana nazwy" tamtego (telefon po DHCP nie może
            # przejąć tożsamości telewizora i odwrotnie).
            key = f"{d['ip']}#{d['hostname'].lower()}"
            seen_keys.add(key)
            new_devices.append(d)
            new_keys.append(key)
            inventory[key] = {
                "mac": "", "hostname": d["hostname"], "vendor": vendor, "first_seen": now, "last_seen": now,
                "ip_history": [d["ip"]], "status": "nieznane", "online": True,
            }
        else:
            entry = inventory[key]
            gap = _days_since(entry.get("last_seen"), now)
            if gap is not None and gap >= RETURN_ALERT_THRESHOLD_DAYS and entry.get("online") is False:
                returning_devices.append({**d, "absent_days": round(gap, 1)})
                returning_prev.append((key, entry.get("last_seen"), entry.get("online")))
            entry["last_seen"] = now
            entry["online"] = True
            if d["mac"] and not entry.get("mac"):
                entry["mac"] = d["mac"]
            if vendor and not entry.get("vendor"):
                entry["vendor"] = vendor
            if d["hostname"]:
                entry["hostname"] = d["hostname"]
            # Aktualny adres zawsze na końcu (tools.py pokazuje ip_history[-1]),
            # także gdy urządzenie wraca do wcześniejszego adresu (A -> B -> A).
            history = entry.setdefault("ip_history", [])
            if d["ip"] in history:
                history.remove(d["ip"])
            history.append(d["ip"])
            del history[:-MAX_IP_HISTORY]

    # Urządzenia znane z historii, ale nie widziane w TYM cyklu -> offline.
    # Wpis zostaje (historia się liczy), tylko flaga się zmienia.
    for key, entry in inventory.items():
        if key not in seen_keys:
            entry["online"] = False

    # Alerty PRZED zapisem inwentarza: gdy alertu nie da się zapisać (plik należy do
    # roota po jednym `sudo python3 agent/siec.py`, pełny dysk), urządzenie NIE
    # trafia do inwentarza jako znane, więc następny cykl ogłosi je ponownie
    # zamiast zgubić alert na zawsze.
    alert_error = None
    for key, d in zip(new_keys, new_devices):
        try:
            _log_alert({
                "time": now, "type": "nowe_urzadzenie",
                "ip": d["ip"], "mac": d["mac"], "hostname": d["hostname"],
            })
        except (OSError, ValueError) as e:
            alert_error = type(e).__name__
            inventory.pop(key, None)
    prev_by_key = {k: (ls, on) for k, ls, on in returning_prev}
    for d in returning_devices:
        key = d["mac"] or ip_to_key.get(d["ip"]) or d["ip"]
        try:
            _log_alert({
                "time": now, "type": "urzadzenie_wrocilo",
                "ip": d["ip"], "mac": d["mac"], "hostname": d["hostname"],
                "absent_days": d["absent_days"],
            })
        except (OSError, ValueError) as e:
            alert_error = type(e).__name__
            if key in inventory and key in prev_by_key:  # wróci jako "wrócił" w następnym cyklu
                inventory[key]["last_seen"], inventory[key]["online"] = prev_by_key[key]

    _save_inventory(inventory)
    meta = {"time": now, "source": source, "devices_seen": len(devices), "ok": True}
    if alert_error:
        meta["alert_error"] = alert_error
    _save_scan_meta(meta)

    return {
        "time": now,
        "source": source,
        "devices_seen": len(devices),
        "new_devices": new_devices,
        "returning_devices": returning_devices,
        "total_known": len(inventory),
    }


def hours_since(ts) -> float | None:
    """Ile godzin minęło od znacznika czasu ISO (None = brak albo nieczytelny)."""
    try:
        return max(0.0, (datetime.now() - datetime.fromisoformat(str(ts))).total_seconds() / 3600)
    except (TypeError, ValueError):
        return None


def recent_alerts(limit: int = 10, max_age_hours: float | None = None) -> list[dict]:
    """Ostatnie alerty, NAJNOWSZY PIERWSZY; `max_age_hours` odrzuca starsze (brief mówi
    "nowe alerty", więc alert sprzed miesiąca nie może być "nowy" na zawsze)."""
    if not ALERTS_PATH.exists():
        return []
    try:
        lines = ALERTS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-(limit * 4 + 20):]):
        try:
            alert = json.loads(line)
        except Exception:
            continue
        if not isinstance(alert, dict):
            continue
        if max_age_hours is not None:
            age = hours_since(alert.get("time"))
            if age is None or age > max_age_hours:
                continue
        out.append(alert)
        if len(out) >= limit:
            break
    return out


def current_inventory() -> dict:
    try:
        return _load_inventory()
    except RuntimeError:
        return {}  # czat dostaje "jeszcze nie mam danych", nie wyjątek


if __name__ == "__main__":
    import env_loader  # uruchamiane osobno (timer gregai-siec): ROUTER_* z .env
    env_loader.load_env()
    summary = run_cycle()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
