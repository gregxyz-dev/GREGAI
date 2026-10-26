"""
homenet.py

Czy laptop jest teraz w Twojej sieci domowej? (dodane 2026-10-09)

GREGAI działa na laptopie, który bywa w różnych sieciach (dom, kawiarnia,
hotel). Dwie rzeczy mają sens TYLKO w domu:
- skan sieci (agent/siec.py): pingowanie cudzej sieci to skanowanie
  cudzych urządzeń,
- most do routera (agent/router_bridge.py): wysyła login i hasło panelu
  routera pod adres bramy; w obcej sieci z tą samą domyślną bramą
  (192.168.8.1 to fabryczny adres wielu routerów Huawei) hasło poszłoby do
  cudzego urządzenia.

Jak rozpoznajemy dom:
- brama domyślna (fizyczny interfejs, z pominięciem WARP i interfejsów
  wirtualnych) = ROUTER_HOST z .env (domyślnie 192.168.8.1),
- ORAZ jej adres MAC = zapamiętany ŚWIADOMIE w domu (data/home_router.json):
  `python3 agent/homenet.py --pin` robi to install.sh przy instalacji (w
  domu). Nic w tle niczego samo nie zapamiętuje: bez zapamiętanego routera,
  przy błędzie odczytu albo innym MAC - sieć jest traktowana jako obca.
  Wymiana routera: w domu `python3 agent/homenet.py --pin --replace`.

Tylko odczyt: `ip route`, `ip addr`, `ip neigh`. Jedyny pakiet, jaki wysyła, to jeden
ping do bramy, gdy jej wpis sąsiada jest nieświeży (bez tego MAC bramy bywa nieznany).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fsutil

STATE_PATH = Path(__file__).parent.parent / "data" / "home_router.json"
# Interfejsy, które nie są "fizyczną" siecią, w której stoi laptop.
_VIRTUAL_DEV = re.compile(r"^(CloudflareWARP|warp|wg|tun|tap|docker|br-|virbr|veth|lo)", re.I)


def router_host() -> str:
    """Adres routera z ROUTER_HOST. Toleruje to, co ktoś naturalnie wpisze
    ("http://192.168.8.1/", "192.168.8.1:80"): schemat, ścieżka i port są
    zdejmowane, żeby sieć domowa nie była przez to zawsze "obca"."""
    raw = os.environ.get("ROUTER_HOST", "192.168.8.1").strip()
    raw = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", raw)
    raw = raw.split("/", 1)[0].split("?", 1)[0]
    if raw.count(":") == 1:  # host:port (IPv6 ma wiele dwukropków i tu nie występuje)
        raw = raw.split(":", 1)[0]
    return raw.strip() or "192.168.8.1"


def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""


def default_route() -> dict | None:
    """{"gateway", "dev"} trasy domyślnej przez fizyczny interfejs (najniższa
    metryka), albo None."""
    best = None
    for line in _run(["ip", "-4", "route", "show", "default"]).splitlines():
        m_gw = re.search(r"\bvia\s+(\S+)", line)
        m_dev = re.search(r"\bdev\s+(\S+)", line)
        if not m_gw or not m_dev or _VIRTUAL_DEV.match(m_dev.group(1)):
            continue
        m_metric = re.search(r"\bmetric\s+(\d+)", line)
        metric = int(m_metric.group(1)) if m_metric else 0
        if best is None or metric < best[0]:
            best = (metric, {"gateway": m_gw.group(1), "dev": m_dev.group(1)})
    return best[1] if best else None


def own_addresses() -> set[str]:
    """Adresy IPv4 interfejsu z trasą domyślną (do pominięcia we własnym skanie)."""
    route = default_route()
    if not route:
        return set()
    return set(re.findall(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/", _run(["ip", "-4", "-o", "addr", "show", "dev", route["dev"]])))


def local_subnet() -> ipaddress.IPv4Network | None:
    """Podsieć fizycznego interfejsu z trasą domyślną (z jego prawdziwą
    maską), NIE adres tunelu WARP."""
    route = default_route()
    if not route:
        return None
    # Interfejs może mieć kilka adresów (link-local 169.254.x.x bywa pierwszy):
    # bierzemy ten, w którego podsieci leży brama domyślna.
    nets = []
    for m in re.finditer(r"\binet\s+(\d+\.\d+\.\d+\.\d+/\d+)", _run(["ip", "-4", "-o", "addr", "show", "dev", route["dev"]])):
        try:
            nets.append((m.group(1), ipaddress.ip_network(m.group(1), strict=False)))
        except ValueError:
            continue
    try:
        gw = ipaddress.ip_address(route["gateway"])
    except ValueError:
        gw = None
    chosen = next((x for x in nets if gw is not None and gw in x[1]), None) \
        or next((x for x in nets if not x[1].network_address.is_link_local), None)
    if not chosen:
        return None
    addr, net = chosen
    # Bezpiecznik: nigdy nie skanujemy więcej niż /24 (256 adresów).
    if net.prefixlen < 24:
        net = ipaddress.ip_network(f"{addr.split('/')[0]}/24", strict=False)
    return net


def _gateway_mac(gateway: str, dev: str) -> str:
    """MAC bramy NA TYM interfejsie (trasa domyślna). `ip neigh show <ip>` bez
    `dev` pokazuje wpisy ze wszystkich interfejsów, a stary wpis z innej sieci
    o tym samym adresie bramy (192.168.8.1 jest fabryczny w wielu routerach)
    mógłby uchodzić za bramę domową. Ping tylko do bramy odświeża wpis."""
    def _read() -> tuple[str, bool]:
        out = _run(["ip", "neigh", "show", "to", gateway, "dev", dev])
        m = re.search(r"\blladdr\s+([0-9a-fA-F:]{17})", out)
        return (m.group(1).lower() if m else ""), bool(re.search(r"\bREACHABLE\b", out))

    mac, fresh = _read()
    if not (mac and fresh):  # brak wpisu albo wpis nieświeży (STALE): odśwież jednym pingiem
        _run(["ping", "-c", "1", "-W", "1", gateway])
        mac, _ = _read()
    return mac


def _pinned() -> tuple[str | None, str]:
    """(MAC zapamiętanego routera albo None, powód). Tylko brak pliku znaczy
    "jeszcze nie zapamiętany"; każdy inny błąd = traktuj jak obcą sieć."""
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        mac = str(data.get("mac", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac):
            return None, "zapis routera domowego jest uszkodzony"
        return mac, ""
    except FileNotFoundError:
        return None, ("router domowy nie jest jeszcze zapamiętany - w domu uruchom: "
                      "python3 agent/homenet.py --pin (robi to też install.sh)")
    except Exception as e:
        return None, f"nie da się odczytać zapisu routera domowego ({type(e).__name__})"


def is_home() -> tuple[bool, str]:
    """(czy dom, powód po polsku). Nigdy niczego nie zapisuje."""
    expected = router_host()
    route = default_route()
    if not route:
        return False, "brak połączenia z siecią lokalną"
    if route["gateway"] != expected:
        return False, f"to nie jest sieć domowa (brama {route['gateway']}, a domowa to {expected})"
    known, why = _pinned()
    if not known:
        return False, why
    mac = _gateway_mac(route["gateway"], route["dev"])
    if not mac:
        return False, "nie da się odczytać adresu MAC bramy - na wszelki wypadek traktuję sieć jako obcą"
    if known != mac:
        return False, (f"brama {route['gateway']} ma inny adres MAC ({mac}) niż Twój router ({known}) - "
                       "to obca sieć z tym samym adresem bramy; jeśli wymieniłeś router, w domu: "
                       "python3 agent/homenet.py --pin --replace")
    return True, "sieć domowa"


def pin(replace: bool = False) -> tuple[bool, str]:
    """Świadome zapamiętanie routera domowego (uruchamiać w domu)."""
    expected = router_host()
    route = default_route()
    if not route:
        return False, "brak połączenia z siecią lokalną - uruchom to w domu, z włączonym Wi-Fi albo kablem"
    if route["gateway"] != expected:
        return False, (f"brama to {route['gateway']}, a ROUTER_HOST w .env to {expected}. Jeśli jesteś w domu, "
                       f"wpisz w .env ROUTER_HOST={route['gateway']} i powtórz; jeśli nie, uruchom to w domu")
    mac = _gateway_mac(route["gateway"], route["dev"])
    if not mac:
        return False, "nie da się odczytać adresu MAC bramy"
    known, _ = _pinned()
    if known and not replace:
        return (known == mac), ("router domowy już zapamiętany" if known == mac else
                                f"zapamiętany jest inny router ({known}); jeśli wymieniłeś router: --pin --replace")
    # Zapis atomowy z fsync (fsutil): po zaniku zasilania plik nie zostaje pusty, bo pusty
    # oznaczałby "uszkodzony" i trzeba by pinować router od nowa.
    fsutil.atomic_write_text(STATE_PATH, json.dumps({"gateway": route["gateway"], "mac": mac}, indent=2))
    return True, f"zapamiętano router domowy {route['gateway']} ({mac})"


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    import env_loader
    env_loader.load_env()
    if "--pin" in sys.argv:
        ok, msg = pin(replace="--replace" in sys.argv)
    else:
        ok, msg = is_home()
    print(msg)
    sys.exit(0 if ok else 1)
