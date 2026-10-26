"""
router_bridge.py

Most GREGAI do routera Huawei HiLink (adres panelu w stylu 192.168.8.1,
/html/home.html): TYLKO ODCZYT. Używa biblioteki `huawei-lte-api`
(świadomy wyjątek od reguły "tylko stdlib", bo pisanie własnej obsługi
sesji/CSRF dla tego API od zera byłoby dużo bardziej ryzykowne niż
użycie sprawdzonej, utrzymywanej biblioteki).

TWARDA ZASADA: ten moduł wywołuje WYŁĄCZNIE metody z poniższej
białej listy (same gettery, zero `set_`/`save_`/`mac_filter` itp.).
Biblioteka `huawei_lte_api` udostępnia też metody, które ZMIENIAJĄ
ustawienia routera (WiFi, filtrowanie MAC, restart), te nigdy nie są
tu importowane ani wołane, celowo, żeby nawet pomyłka w kodzie nie
mogła niczego nadpisać na routerze.

Biała lista getterów używanych w tym module:
    device.signal                  : siła sygnału (RSRP/RSRQ/SINR)
    device.information             : model, wersja oprogramowania
    monitoring.status              : status połączenia, typ sieci, bateria
    monitoring.traffic_statistics  : ruch w aktualnej sesji
    monitoring.month_statistics    : zużycie danych w tym miesiącu
    net.current_plmn               : operator sieci
    wlan.multi_basic_settings      : nazwa SSID (fallback: wlan.basic_settings)
    wlan.host_list                 : lista podłączonych urządzeń (w scan())
Każdy getter jest wywoływany osobno, w try/except: brak wsparcia w
danym firmware dla JEDNEJ metody nigdy nie blokuje pozostałych.

Konfiguracja przez .env:
    ROUTER_HOST      : domyślnie 192.168.8.1
    ROUTER_SCHEME     : domyślnie https
    ROUTER_USER       : login panelu (wymagany dla pełnych danych)
    ROUTER_PASSWORD   : hasło panelu
Brak loginu/hasła -> moduł jawnie zgłasza "niedostępny", żadnej próby
zgadywania czy obejścia.

Optymalizacja: WSZYSTKIE gettery w router_status() dzielą JEDNĄ sesję/
jedno logowanie (nie jedno logowanie na getter, router HiLink robi
osobny handshake CSRF przy każdej nowej sesji, więc to realna różnica
w czasie odpowiedzi). Całość ograniczona czasowo (OVERVIEW_TIMEOUT_S),
żeby nieodpowiadający router nigdy nie zawiesił rozmowy w czacie,
ta sama zasada, co router.py stosuje wobec Ollamy.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeoutError
from pathlib import Path

import fsutil

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

try:
    from huawei_lte_api.Connection import Connection
    from huawei_lte_api.Client import Client
    HUAWEI_LIB_AVAILABLE = True
except ImportError:
    HUAWEI_LIB_AVAILABLE = False

OVERVIEW_TIMEOUT_S = 6
REQUEST_TIMEOUT_S = 5

# Odcisk certyfikatu routera zapamiętany przy pierwszym połączeniu (TOFU, jak SSH
# known_hosts): router ma certyfikat samopodpisany, więc zwykła weryfikacja łańcucha
# nie ma jak działać, a bez niej ktoś w sieci domowej (podszycie pod bramę) odebrałby
# login i hasło panelu. Zmieniony certyfikat = połączenie odrzucone.
CERT_PIN_PATH = Path(__file__).parent.parent / "data" / "router_cert.json"

# Kody CurrentNetworkType z monitoring.status() -> etykieta człowieka.
# Nie każdy firmware zwraca te same kody, a Huawei nie publikuje jednej
# oficjalnej, kompletnej listy, to najczęściej spotykane wartości.
# Nieznany kod: pokaż go wprost ("typ N"), nigdy nie zgaduj nazwy.
_NETWORK_TYPE_LABELS = {
    "0": "brak sygnału", "1": "GSM", "2": "GPRS", "3": "EDGE",
    "4": "WCDMA", "5": "HSDPA", "6": "HSUPA", "7": "HSPA", "8": "TD-SCDMA",
    "9": "HSPA+", "19": "LTE", "41": "UMTS", "101": "5G (NSA)", "109": "5G",
}


def _config():
    import homenet  # tylko stdlib; adres routera czytany jednym kodem dla mostu i dla rozpoznania domu
    scheme = os.environ.get("ROUTER_SCHEME", "https").strip().lower()
    return {
        "host": homenet.router_host(),
        "scheme": scheme if scheme in ("http", "https") else "https",
        "user": os.environ.get("ROUTER_USER", ""),
        "password": os.environ.get("ROUTER_PASSWORD", ""),
    }


def _private_host(host: str) -> bool:
    """Login i hasło panelu wolno wysłać tylko pod adres z sieci lokalnej
    (prywatny IPv4, np. 192.168.8.1). Nazwa DNS albo adres publiczny w
    ROUTER_HOST (literówka, podmieniony .env) wyniosłyby hasło do internetu."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_unspecified


def router_configured() -> bool:
    """Skonfigurowany ORAZ jesteśmy w sieci domowej (agent/homenet.py): login
    i hasło panelu nigdy nie idą do bramy obcej sieci, nawet jeśli ma ten
    sam adres 192.168.8.1 (fabryczny w wielu routerach Huawei)."""
    cfg = _config()
    if not (HUAWEI_LIB_AVAILABLE and bool(cfg["user"]) and bool(cfg["password"])):
        return False
    if not _private_host(cfg["host"]):
        return False
    try:
        import homenet
        return homenet.is_home()[0]
    except Exception:
        return False


def _peer_fingerprint(host: str, port: int = 443) -> str:
    """SHA-256 certyfikatu, który router pokazuje teraz (bez weryfikacji łańcucha)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=REQUEST_TIMEOUT_S) as sock:
        with ctx.wrap_socket(sock) as tls:
            der = tls.getpeercert(binary_form=True)
    return hashlib.sha256(der).hexdigest()


class CertPinError(RuntimeError):
    """Plik z przypiętym odciskiem certyfikatu jest nieczytelny albo ma zły format.
    Komunikat nie zawiera sekretów i jest pokazywany użytkownikowi."""


def pinned_fingerprint(host: str, port: int = 443, path: Path | None = None) -> str:
    """Zapamiętany odcisk certyfikatu routera `host`. Pierwsze połączenie
    (brak wpisu albo wpis dla innego adresu) zapamiętuje to, co router pokazuje
    TERAZ; kolejne wymagają dokładnie tego samego certyfikatu."""
    path = path or CERT_PIN_PATH
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        stored = None
    except (OSError, ValueError) as e:
        # Istniejący, ale nieczytelny plik NIE oznacza "pierwszego połączenia": ciche
        # przypięcie tego, co router pokazuje teraz, wyłączałoby ochronę właśnie
        # wtedy, gdy ktoś (lub awaria) ruszył przypięty odcisk.
        raise CertPinError(f"Nie mogę odczytać {path.name} ({type(e).__name__}). Jeśli to Twój router, "
                           f"usuń ten plik, a przy następnym połączeniu certyfikat zostanie przypięty od nowa.") from e
    if stored is not None:
        if not (isinstance(stored, dict) and isinstance(stored.get("host"), str)
                and isinstance(stored.get("sha256"), str) and len(stored["sha256"]) == 64
                and all(c in "0123456789abcdef" for c in stored["sha256"])):
            raise CertPinError(f"Plik {path.name} ma zły format. Jeśli to Twój router, usuń go, a przy następnym "
                               f"połączeniu certyfikat zostanie przypięty od nowa.")
        if stored["host"] == host:
            return stored["sha256"]
        # Zapamiętany odcisk dotyczy innego adresu routera: przypinamy ten adres od nowa.
    fp = _peer_fingerprint(host, port)
    fsutil.atomic_write_text(path, json.dumps({"host": host, "sha256": fp}, indent=2))
    return fp


def _pinned_adapter(fingerprint: str):
    """Adapter requests, który wymaga certyfikatu o danym odcisku (urllib3
    assert_fingerprint działa także przy wyłączonej weryfikacji łańcucha)."""
    from requests.adapters import HTTPAdapter

    class PinnedAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["assert_fingerprint"] = fingerprint
            super().init_poolmanager(*args, **kwargs)

    return PinnedAdapter()


def _connect():
    """Sesja bez weryfikacji łańcucha certyfikatu (router HiLink ma samopodpisany
    certyfikat i jest dostępny tylko w sieci lokalnej), za to z przypięciem odcisku
    certyfikatu zapamiętanego przy pierwszym połączeniu (pinned_fingerprint).
    Każde żądanie przez tę sesję ma domyślny timeout (REQUEST_TIMEOUT_S), żeby
    pojedyncze zawieszone żądanie HTTP nie trzymało wątku w nieskończoność
    (dodatkowa warstwa pod spodem OVERVIEW_TIMEOUT_S)."""
    import requests

    cfg = _config()
    session = requests.Session()
    session.verify = False
    # Ani proxy, ani pakiet certyfikatów ze zmiennych środowiska: login i hasło panelu
    # idą wprost do routera w sieci lokalnej (REQUESTS_CA_BUNDLE nadpisywałby verify=False).
    session.trust_env = False
    if cfg["scheme"] == "https":
        session.mount("https://", _pinned_adapter(pinned_fingerprint(cfg["host"])))

    _orig_request = session.request

    def _timed_request(method, url, **kwargs):
        # huawei_lte_api przekazuje timeout=None WPROST, więc setdefault by go
        # nie nadpisał (sprawdzone: żądanie wisiało bez końca).
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = REQUEST_TIMEOUT_S
        # Przekierowanie (np. https -> http) zeszłoby z przypiętego certyfikatu na jawny tekst.
        kwargs["allow_redirects"] = False
        return _orig_request(method, url, **kwargs)

    session.request = _timed_request
    url = f"{cfg['scheme']}://{cfg['host']}/"
    return Connection(url, username=cfg["user"], password=cfg["password"],
                      timeout=REQUEST_TIMEOUT_S, requests_session=session)


def devices_from_router() -> list[dict] | None:
    """Zwraca listę urządzeń zgłoszonych PRZEZ SAM ROUTER (dokładniejsze
    niż ping-sweep: router zna nazwy z DHCP nawet dla urządzeń, które
    nie odpowiadają na ping). None jeśli router niedostępny/nieskonfigurowany."""
    if not router_configured():
        return None
    try:
        with _connect() as connection:
            client = Client(connection)
            raw = client.wlan.host_list()  # tylko odczyt
            hosts = raw.get("Hosts", {}).get("Host", [])
            if isinstance(hosts, dict):  # jedno urządzenie -> biblioteka nie owija w listę
                hosts = [hosts]
            devices = []
            for h in hosts:
                devices.append({
                    "ip": h.get("IpAddress", ""),
                    "mac": (h.get("MacAddress") or "").lower(),
                    "hostname": h.get("HostName", "") or "",
                })
            return devices
    except Exception:
        return None


def _safe_call(thunk):
    """Wywołaj gettera opakowanego w lambda/thunk (tak żeby PRÓBA dostania
    się do nieistniejącego atrybutu/submodułu była też złapana, nie tylko
    sam wywołanie), jedna niewsparta/zepsuta metoda nigdy nie blokuje
    pozostałych getterów w tym samym przeglądzie."""
    try:
        return thunk()
    except Exception:
        return None


def _safe_dict(thunk) -> dict | None:
    """_safe_call, ale wynik inny niż słownik (firmware potrafi oddać listę,
    tekst albo None) liczy się jak brak danych, a nie wywraca dalszą obróbkę."""
    result = _safe_call(thunk)
    return result if isinstance(result, dict) else None


def _network_type_label(code) -> str:
    code = str(code)
    return _NETWORK_TYPE_LABELS.get(code, f"typ {code}")


def _to_mb(value) -> float | None:
    try:
        return round(int(value) / (1024 * 1024), 1)
    except Exception:
        return None


def _clean_text(value, limit: int = 63) -> str | None:
    """Napisy z routera (operator, nazwa modelu, SSID) to dane z zewnątrz: SSID ustawia
    każdy, kto ma dostęp do routera, a nazwa trafia do rozmowy. Zostają tylko znaki
    drukowalne (bez nowych linii i znaczników <>), najwyżej `limit`."""
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable() and ch not in "<>`").strip()[:limit]
    return cleaned or None


def _extract_ssid(wlan: dict | None) -> str | None:
    if not isinstance(wlan, dict):
        return None
    if wlan.get("WifiSsid"):
        return wlan.get("WifiSsid")
    ssids = wlan.get("Ssids", {})
    if isinstance(ssids, dict):
        ssid_entry = ssids.get("Ssid")
        if isinstance(ssid_entry, list) and ssid_entry and isinstance(ssid_entry[0], dict):
            return ssid_entry[0].get("WifiSsid")
        if isinstance(ssid_entry, dict):
            return ssid_entry.get("WifiSsid")
    return None


def _gather_overview(client) -> dict:
    """Jeden przejazd przez wszystkie gettery z białej listy, w ramach
    JEDNEJ już otwartej sesji. Każdy getter osobno zabezpieczony:
    brakujące pole w wyniku = firmware tego nie wsparł, nie błąd."""
    out: dict = {}

    signal = _safe_dict(lambda: client.device.signal())
    status = _safe_dict(lambda: client.monitoring.status())
    traffic = _safe_dict(lambda: client.monitoring.traffic_statistics())
    month = _safe_dict(lambda: client.monitoring.month_statistics())
    plmn = _safe_dict(lambda: client.net.current_plmn())
    info = _safe_dict(lambda: client.device.information())
    wlan = _safe_dict(lambda: client.wlan.multi_basic_settings()) or _safe_dict(lambda: client.wlan.basic_settings())

    out["signal"] = signal
    out["status"] = status
    out["traffic"] = traffic

    if month:
        out["month"] = {
            "download_mb": _to_mb(month.get("CurrentMonthDownload")),
            "upload_mb": _to_mb(month.get("CurrentMonthUpload")),
        }

    if status:
        net_type = status.get("CurrentNetworkType")
        if net_type is not None:
            out["network_type_label"] = _network_type_label(net_type)
        # Tylko BatteryPercent: BatteryStatus to kod stanu (np. ładowanie), nie procent.
        battery = status.get("BatteryPercent")
        if battery is not None:
            out["battery_percent"] = battery

    if plmn:
        out["operator"] = _clean_text(plmn.get("FullName") or plmn.get("ShortName"))

    if info:
        out["device_name"] = _clean_text(info.get("DeviceName"))
        out["software_version"] = _clean_text(info.get("SoftwareVersion"))

    ssid = _clean_text(_safe_call(lambda: _extract_ssid(wlan)))
    if ssid:
        out["wifi_ssid"] = ssid

    return out


def router_status() -> dict | None:
    """Pełny, tylko-do-odczytu przegląd routera (sygnał, status, ruch,
    zużycie danych w miesiącu, operator, SSID, model, bateria jeśli
    urządzenie ją ma), wszystko w JEDNEJ sesji. Ograniczone czasowo
    (OVERVIEW_TIMEOUT_S): jeśli router nie odpowie w tym czasie, zwraca
    błąd zamiast zawiesić rozmowę w czacie. None jeśli router
    niedostępny/nieskonfigurowany."""
    if not router_configured():
        return None

    def _run():
        with _connect() as connection:
            client = Client(connection)
            return _gather_overview(client)

    # UWAGA: celowo NIE `with ThreadPoolExecutor(...) as pool:`: wyjście
    # z `with` czeka (shutdown(wait=True)) na zakończenie wątku, więc
    # TimeoutError z future.result() i tak zostałby zablokowany do czasu,
    # aż zawieszone żądanie HTTP same się zakończy (sprawdzone testem).
    # `shutdown(wait=False)` w finally oddaje kontrolę natychmiast:
    # zawieszony wątek dokończy się i zniknie w tle, ale rozmowa w czacie
    # nigdy na to nie czeka.
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_run)
    try:
        return future.result(timeout=OVERVIEW_TIMEOUT_S)
    except _FutureTimeoutError:
        return {"error": "router nie odpowiedział w czasie"}
    except CertPinError as e:
        return {"error": str(e)}
    except Exception as e:
        # Tylko nazwa błędu: treść wyjątku z biblioteki nie ma prawa trafić do
        # rozmowy (mogłaby zawierać adres z danymi logowania).
        if "SSLError" in type(e).__name__:
            return {"error": "certyfikat routera nie zgadza się z zapamiętanym (data/router_cert.json): hasło nie zostało wysłane. "
                             "Jeśli to Twój router po aktualizacji albo wymianie, usuń ten plik; jeśli nie, ktoś w sieci podszywa się pod router"}
        return {"error": f"router zwrócił błąd ({type(e).__name__})"}
    finally:
        pool.shutdown(wait=False)
