"""
netguard.py

Strażnik połączeń GREGAI z internetem. Decyzja z 2026-10-09
(cyberbezpieczeństwo = priorytet): GREGAI łączy się z internetem WYŁĄCZNIE
przez Cloudflare WARP. Zasada jest twardo zakodowana: nie ma zmiennej w
.env, która by ją wyłączała.

Jak działa:
- każde połączenie GREGAI z internetem (chmura Claude w router.py,
  research_web i Wikipedia w tools.py) idzie przez urlopen() z tego
  modułu, nie przez gołe urllib.request.urlopen,
- przed połączeniem sprawdzamy (`warp-cli status` co najwyżej co 3 s, a
  co 30 s także na stronie Cloudflare, że ruch naprawdę idzie przez
  WARP: warp=on), czy WARP jest połączony; jeśli nie, połączenie NIE wychodzi
  (fail-closed): rzucamy NetGuardBlocked, a wołający odpowiada lokalnie
  albo komunikatem "internet zablokowany, WARP rozłączony",
- tylko https:// (żadnego nieszyfrowanego http do internetu), także po
  przekierowaniach,
- połączenia z tą maszyną (Ollama na localhost) NIE przechodzą tędy i nie
  zależą od WARP: rozmowa lokalna działa zawsze.

Wynik sprawdzenia jest pamiętany STATUS_TTL / TRACE_TTL sekund (zegar
monotoniczny: cofnięcie zegara systemowego, np. przez NTP, nie przedłuża
ważności wyniku), żeby nie odpalać `warp-cli` ani strony Cloudflare przy
każdym zapytaniu. Zapytanie z całą rozmową (chmura Claude) sprawdza WARP
od nowa (urlopen(..., fresh=True)): `warp-cli status` i interfejs tunelu bez
pamięci podręcznej; strona kontrolna Cloudflare z pamięci TRACE_TTL s, ale tylko
przy niezmienionym obrazie lokalnym (patrz _trace_cached, 1.32.0).

Z poziomu GREGAI nie da się WARP wyłączyć: sysop.py blokuje na stałe
polecenia osłabiające zabezpieczenia (warp-cli disconnect, ufw disable,
zatrzymanie warp-svc itd.). Użytkownik może to zrobić sam, w swoim
terminalu.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

STATUS_TTL = 3    # s: `warp-cli status` (lokalnie, bez sieci) - krótko, żeby
                  # po rozłączeniu WARP blokada działała praktycznie od razu
TRACE_TTL = 30    # s: potwierdzenie, że ruch NAPRAWDĘ idzie przez WARP
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
_CONNECTED_RE = re.compile(r"\bConnected\b")  # "Disconnected" ma małe c, nie pasuje

# 1.32.0 (prośba Grzegorza: "napraw mu bardzo dokładnie dostęp do internetu").
# Dowód, że ruch idzie tunelem, ma teraz DWIE warstwy:
#   1. lokalną, w każdej chwili i bez sieci: `warp-cli status` = Connected ORAZ
#      istnieje interfejs tunelu CloudflareWARP (w trybie proxy i "tylko DNS"
#      klient też pisze Connected, ale tunelu nie zakłada - wtedy blokada);
#   2. sieciową, co TRACE_TTL s: strona kontrolna Cloudflare widzi nas jako warp=on.
# Do 1.31 każde "świeże" sprawdzenie odpytywało stronę kontrolną od nowa, a JEDNA
# chwilowa porażka tego zapytania (zgubiony pakiet na LTE, limit po stronie
# Cloudflare) blokowała cały internet na 10 s, choć tunel działał - stąd
# przerywane "internet zablokowany". Teraz: przy błędzie strony kontrolnej jedna
# natychmiastowa powtórka, a jeśli dalej błąd, a tunel był potwierdzony (warp=on)
# w ostatnich TRACE_GRACE_S s i interfejs wciąż istnieje - przepuszczamy z notatką.
# Jawne warp=off blokuje zawsze (to jest dowód, że ruch idzie POZA tunelem). Ruch
# usługi i tak może wyjść tylko przez CloudflareWARP (zapora jądra z install.sh).
TRACE_GRACE_S = 600
WARP_IFACE = "CloudflareWARP"
SYS_NET = Path("/sys/class/net")

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "status": None}
_trace_cache: dict = {"at": 0.0, "ok": False, "why": "", "kind": "", "on_at": 0.0, "info": {}}
_tos_flag: dict = {"use": True}  # --accept-tos: nowsze warp-cli bez niego potrafią czekać na zgodę
# 1.19.0 (audyt rdzenia): chwila ostatniego ŚWIEŻEGO sprawdzenia zakończonego
# zgodą. Juggler sprawdza WARP raz na początku łańcucha i przez kilka sekund
# (FRESH_REUSE_MAX_S) jego zapytania mogą się na to powołać, zamiast przed
# KAŻDYM dostawcą odpalać warp-cli i stronę Cloudflare (24 sprawdzenia na
# jedną wiadomość przy padniętej sieci). Każde sprawdzenie zakończone
# blokadą zeruje tę chwilę: fail-closed zostaje.
FRESH_REUSE_MAX_S = 10.0
_fresh_ok_at = 0.0
_last_block_at = 0.0


class NetGuardBlocked(RuntimeError):
    """Połączenie z internetem zablokowane, bo WARP nie jest połączony."""


# Kody wyjścia curl (man curl, EXIT CODES) -> przyczyna po polsku.
_CURL_RC = {
    5: "nie da się rozwiązać adresu proxy", 6: "nie działa DNS (nie znaleziono adresu serwera)",
    7: "nie da się połączyć z serwerem (odrzucone albo brak trasy)", 16: "błąd protokołu HTTP/2",
    22: "serwis odpowiedział błędem HTTP", 28: "serwer nie odpowiedział w czasie",
    35: "błąd uzgadniania TLS (szyfrowania)", 47: "za dużo przekierowań", 52: "serwer zamknął połączenie bez odpowiedzi",
    56: "połączenie zerwane w trakcie odbioru", 60: "certyfikat serwera nie przeszedł weryfikacji",
    63: "odpowiedź większa niż limit", 92: "strumień HTTP/2 zerwany",
}


def explain_error(e: BaseException) -> str:
    """Jedno krótkie zdanie po polsku: DLACZEGO połączenie się nie udało (1.32.0).
    Zamiast „połączenie nie działa albo serwis nie odpowiada” - przyczyna, z
    której wiadomo, co robić: DNS, czas, certyfikat, blokada serwisu, limit."""
    if isinstance(e, NetGuardBlocked):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        code = e.code
        if code in (401, 403):
            return f"serwis odmówił dostępu (HTTP {code}) - często tak blokuje ruch z adresów WARP"
        if code == 429:
            return "serwis ogranicza liczbę zapytań (HTTP 429) - spróbuj za chwilę"
        if code == 202:
            return "serwis oddał stronę-wyzwanie zamiast wyników (HTTP 202, ochrona przed botami)"
        if code >= 500:
            return f"błąd po stronie serwisu (HTTP {code})"
        return f"serwis odpowiedział błędem HTTP {code}"
    reason = getattr(e, "reason", None) if isinstance(e, urllib.error.URLError) else e
    if isinstance(reason, socket.gaierror):
        return "nie działa DNS (nie znaleziono adresu serwera)"
    if isinstance(reason, (ssl.SSLCertVerificationError,)):
        return "certyfikat serwera nie przeszedł weryfikacji (zły czas systemowy albo przechwycony ruch)"
    if isinstance(reason, ssl.SSLError):
        return "błąd szyfrowania TLS"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "serwer nie odpowiedział w czasie"
    if isinstance(reason, ConnectionRefusedError):
        return "połączenie odrzucone"
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "połączenie zerwane"
    if isinstance(reason, OSError) and getattr(reason, "errno", None) in (101, 113):  # ENETUNREACH, EHOSTUNREACH
        return "brak trasy do internetu (sieć albo tunel nie działa)"
    text = str(e)
    m = re.match(r"curl rc=(\d+)", text)
    if m:
        rc = int(m.group(1))
        return f"{_CURL_RC.get(rc, 'błąd połączenia')} (curl {rc})"
    if "przekroczony czas" in text or "Timeout" in type(e).__name__:
        return "serwer nie odpowiedział w czasie"
    if type(e).__name__ in ("ConnectError", "ConnectTimeout"):
        return "nie da się połączyć z serwerem"
    if isinstance(e, FileNotFoundError):
        return f"brak programu ({e.filename or e})"
    return f"{type(e).__name__}: {text[:80]}" if text else type(e).__name__


_UNKNOWN_FLAG_RE = re.compile(r"unexpected argument|unrecognized|Found argument|unknown (?:flag|option)", re.IGNORECASE)


def _run_warp(*args: str, timeout: float = 5.0) -> tuple[int, str]:
    """(kod wyjścia, tekst) z `warp-cli [--accept-tos] ARGS`. stdin=DEVNULL: polecenie
    nie może zawisnąć na pytaniu. --accept-tos (1.32.0): nowsze klienty w trybie
    nieinteraktywnym (usługa systemd) bez tej flagi odmawiają albo pytają o warunki
    korzystania; starsze jej nie znają - wtedy jedna powtórka bez niej i zapamiętanie."""
    exe = shutil.which("warp-cli")
    if not exe:
        return 127, ""
    for attempt in range(2):
        use_tos = _tos_flag["use"]
        argv = [exe] + (["--accept-tos"] if use_tos else []) + list(args)
        try:
            res = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "timeout: warp-cli nie odpowiedział"
        except Exception as e:
            return 1, f"{type(e).__name__}"
        out = (res.stdout or "") + (res.stderr or "")
        if use_tos and res.returncode != 0 and _UNKNOWN_FLAG_RE.search(out) and attempt == 0:
            _tos_flag["use"] = False
            continue
        return res.returncode, out
    return 1, "warp-cli: nieoczekiwana odpowiedź"


def _run_warp_status() -> tuple[int, str]:
    return _run_warp("status")


# Znane odpowiedzi warp-cli -> co to znaczy i co zrobić (po polsku, z poleceniem).
# Kolejność ma znaczenie: pierwsze trafienie wygrywa.
_WARP_HINTS = (
    (re.compile(r"timeout: warp-cli", re.I),
     "klient WARP nie odpowiedział w 5 s", "sudo systemctl restart warp-svc"),
    (re.compile(r"Registration Missing|registration.{0,20}(missing|not found)|not registered|Missing registration", re.I),
     "WARP nie jest zarejestrowany na tym komputerze", "warp-cli registration new && warp-cli connect"),
    (re.compile(r"Terms of Service|\bToS\b|accept the terms", re.I),
     "WARP czeka na akceptację warunków korzystania", "warp-cli --accept-tos status"),
    (re.compile(r"daemon|Unable to connect to the CloudflareWARP|connection refused|No such file or directory|ipc", re.I),
     "usługa WARP (warp-svc) nie działa", "sudo systemctl enable --now warp-svc"),
    (re.compile(r"No Network|no network|Reason: Network", re.I),
     "komputer nie ma teraz sieci (Wi-Fi albo LTE)", "nmcli device status"),
    (re.compile(r"\bConnecting\b", re.I),
     "WARP właśnie się łączy - poczekaj kilka sekund", ""),
    (re.compile(r"Manual Disconnection|Disconnected|disconnected", re.I),
     "WARP jest rozłączony", "warp-cli connect"),
)


def blocked_speech(reason: str = "") -> str:
    """Zdanie dla użytkownika, gdy bramka zablokowała internet (1.32.0): z PRAWDZIWEJ
    przyczyny (brak rejestracji, tryb proxy, usługa nie działa, łączy się...) i z
    poleceniem naprawy - dawniej zawsze „WARP rozłączony, warp-cli connect”."""
    reason = (reason or "").strip()
    if not reason:
        try:
            reason = status().get("reason", "")
        except Exception:
            reason = ""
    core = re.sub(r"^internet dla GREGAI zablokowany:\s*", "", reason)
    core = re.sub(r"\s*-\s*internet dla GREGAI zablokowany", "", core).strip(" ;.")
    if not core:
        core = "Cloudflare WARP nie jest połączony; w terminalu: warp-cli connect"
    return (f"Internet jest dla mnie teraz zablokowany (bez WARP nic nie wychodzi z komputera): {core}. "
            "Szczegóły warstwa po warstwie: /diagnoza.")


def warp_hint(raw: str) -> tuple[str, str]:
    """(co się dzieje, polecenie naprawy) dla tekstu z warp-cli; ("", "") gdy nieznane."""
    for rx, what, fix in _WARP_HINTS:
        if rx.search(raw or ""):
            return what, fix
    return "", ""


def tunnel_present() -> bool | None:
    """Czy istnieje i jest podniesiony interfejs tunelu WARP?
    None = nie da się sprawdzić (brak /sys - wtedy ta warstwa nie rozstrzyga).
    W trybie proxy i "tylko DNS" klient WARP pisze Connected, ale tunelu nie ma.
    Oczekiwana nazwa to CloudflareWARP; na wypadek zmiany nazwy w nowszym kliencie
    liczy się też KAŻDY interfejs z "warp" w nazwie (tryb proxy żadnego nie zakłada)."""
    if not SYS_NET.is_dir():
        return None
    try:
        names = [d.name for d in SYS_NET.iterdir()]
    except OSError:
        return None
    candidates = [n for n in names if n == WARP_IFACE] or [n for n in names if "warp" in n.lower()]
    if not candidates:
        return False
    for n in candidates:
        try:
            if int((SYS_NET / n / "flags").read_text().strip(), 16) & 0x1:  # IFF_UP
                return True
        except (OSError, ValueError):
            return True  # interfejs jest, flag nie odczytaliśmy - nie blokujemy na tym
    return False


def _trace_probe() -> tuple[str, str, dict]:
    """("on" | "off" | "error", opis, pola trace). "on" = Cloudflare widzi nasz ruch
    jako WARP (warp=on/plus); "off" = ruch idzie POZA tunelem (dowód przeciw);
    "error" = strona kontrolna nie odpowiedziała (to nie jest dowód przeciw)."""
    try:
        with _OPENER.open(TRACE_URL, timeout=6) as resp:
            body = resp.read(4096).decode("utf-8", errors="ignore")
    except Exception as e:
        return "error", f"strona kontrolna Cloudflare nie odpowiedziała ({explain_error(e)})", {}
    info = dict(re.findall(r"^(\w+)=(.*)$", body, re.M))
    warp = info.get("warp", "")
    if warp in ("on", "plus"):
        return "on", "", info
    return "off", (f"WARP zgłasza połączenie, ale ruch nie idzie przez tunel (warp={warp or '?'}): klient jest w trybie "
                   "proxy albo tylko DNS"), info


def _trace_ok() -> tuple[bool, str]:
    """Zgodność wstecz (dawny interfejs): (czy warp=on, powód)."""
    kind, why, _info = _trace_probe()
    return kind == "on", why


def _trace_cached(force: bool = False, evidence: str = "") -> tuple[str, str]:
    """(rodzaj, opis) z pamięci podręcznej: "on" ważne TRACE_TTL s, "off" 10 s,
    "error" 5 s. Błąd strony kontrolnej dostaje jedną natychmiastową powtórkę.

    `evidence` = lokalny obraz stanu (pierwsza linia warp-cli + tunel) w chwili
    pytania. Gdy różni się od obrazu, przy którym zapisano wynik, wynik z pamięci
    NIE obowiązuje (przegląd 1.32.0, H1: przełączenie w tryb proxy nie może
    korzystać z "on" sprzed przełączenia).

    Wyścig (przegląd 1.32.0, M2): wynik zapisujemy z chwilą STARTU sprawdzenia i
    tylko wtedy, gdy żadne sprawdzenie zaczęte później nie zapisało już swojego -
    wolne, stare "on" nie nadpisze świeższego "off"."""
    now = time.monotonic()
    with _lock:
        kind = _trace_cache.get("kind") or ""
        ttl = TRACE_TTL if kind == "on" else 10 if kind == "off" else 5
        same = not evidence or _trace_cache.get("evidence") == evidence
        if not force and same and _trace_cache["at"] and now - _trace_cache["at"] < ttl:
            return kind, _trace_cache["why"]
    started = time.monotonic()
    kind, why, info = _trace_probe()
    if kind == "error":
        time.sleep(0.4)
        kind, why, info = _trace_probe()
    with _lock:
        if _trace_cache.get("started", 0.0) > started:
            # Ktoś zaczął sprawdzanie później i już zapisał wynik: jego jest świeższy.
            return _trace_cache.get("kind") or kind, _trace_cache.get("why", why)
        _trace_cache.update(at=started, started=started, ok=(kind == "on"), why=why, kind=kind, evidence=evidence)
        if kind == "on":
            _trace_cache["on_at"] = started
            _trace_cache["info"] = {k: info.get(k, "") for k in ("colo", "loc", "warp", "http", "tls")}
        elif kind == "off":
            # Jawny dowód, że ruch idzie POZA tunelem, kasuje okres łaski (przegląd 1.32.0, H2).
            _trace_cache["on_at"] = 0.0
    return kind, why


def _blocked(reason: str, raw: str = "", **extra) -> dict:
    d = {"installed": True, "connected": False, "reason": reason, "raw": raw[:120]}
    d.update(extra)
    return d


def _check() -> dict:
    rc, out = _run_warp_status()
    if rc == 127:
        return {"installed": False, "connected": False,
                "reason": "Cloudflare WARP nie jest zainstalowany - internet dla GREGAI zablokowany (uruchom bash install.sh)",
                "fix": "bash install.sh"}
    first = out.strip().splitlines()[0].strip() if out.strip() else ""
    if rc == 0 and _CONNECTED_RE.search(out):
        # Najpierw dowód lokalny: bez interfejsu tunelu (tryb proxy albo "tylko DNS")
        # blokujemy OD RAZU i nie pytamy strony kontrolnej - to zapytanie wyszłoby poza
        # tunelem (przegląd 1.32.0, M1). Interfejs rozpoznajemy także po innej nazwie z
        # "warp" (tunnel_present), więc nowszy klient nie zablokuje działającego tunelu.
        tun = tunnel_present()
        if tun is False:
            with _lock:
                _trace_cache["at"] = 0.0
                _trace_cache["on_at"] = 0.0
            return _blocked("WARP zgłasza połączenie, ale nie ma interfejsu tunelu: klient jest w trybie proxy albo "
                            "tylko DNS - internet dla GREGAI zablokowany; w terminalu: warp-cli mode warp",
                            first, fix="warp-cli mode warp && warp-cli connect")
        # Strona kontrolna: warp=on przepuszcza, warp=off blokuje zawsze. Wynik z pamięci
        # obowiązuje tylko przy tym samym obrazie lokalnym (warp-cli + tunel).
        kind, why = _trace_cached(evidence=f"{first}|{tun}")
        if kind == "on":
            return {"installed": True, "connected": True, "reason": "WARP połączony - internet przez Cloudflare",
                    "raw": first[:120], "tunel": tun}
        if kind == "off":
            return _blocked(f"{why} - internet dla GREGAI zablokowany; w terminalu: warp-cli mode warp", first,
                            fix="warp-cli mode warp && warp-cli connect")
        with _lock:
            on_at = _trace_cache.get("on_at") or 0.0
        age = time.monotonic() - on_at if on_at else None
        # Okres łaski tylko przy POTWIERDZONYM interfejsie (tun is True, nie None).
        if age is not None and age < TRACE_GRACE_S and tun is True:
            return {"installed": True, "connected": True, "raw": first[:120], "tunel": tun,
                    "reason": f"WARP połączony (tunel potwierdzony {int(age)} s temu; {why})",
                    "uwaga": why}
        return _blocked(f"{why}; tunelu nie udało się jeszcze potwierdzić - internet dla GREGAI zablokowany "
                        "(spróbuję znowu za kilka sekund)", first, fix="warp-cli status")
    with _lock:
        _trace_cache["at"] = 0.0  # po rozłączeniu: przy ponownym połączeniu sprawdź ruch od nowa
        _trace_cache["on_at"] = 0.0
    what, fix = warp_hint(out)
    detail = what or (first[:80] or "brak odpowiedzi warp-cli")
    if not what:
        fix = "warp-cli connect"
    return _blocked(f"internet dla GREGAI zablokowany: {detail}" + (f"; w terminalu: {fix}" if fix else ""), first, fix=fix)


def status(force: bool = False) -> dict:
    """Stan WARP (z pamięci podręcznej STATUS_TTL s), do /api/system_info."""
    now = time.monotonic()
    with _lock:
        if not force and _cache["status"] is not None and now - _cache["at"] < STATUS_TTL:
            return dict(_cache["status"])
    st = _check()
    with _lock:
        _cache["at"] = now
        _cache["status"] = st
    return dict(st)


def is_local_url(url: str) -> bool:
    """Czy adres wskazuje na tę maszynę (localhost/127.0.0.1/::1). Adres, którego
    nie da się sparsować, nie jest lokalny."""
    # Backslash i białe znaki/znaki sterujące: różne parsery czytają taki adres
    # inaczej ("http://zly.pl\\@localhost/"), więc go nie uznajemy.
    if "\\" in url or any(c.isspace() or not c.isprintable() for c in url):
        return False
    try:
        parts = urllib.parse.urlparse(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    # Tylko http(s): domyślny opener zna też file:// i ftp://, a "file://localhost/..."
    # miałoby hosta localhost.
    return parts.scheme.lower() in ("http", "https") and host in ("localhost", "127.0.0.1", "::1")


def internet_allowed(fresh: bool = False) -> tuple[bool, str]:
    """fresh=True: bez pamięci podręcznej (ponowne `warp-cli status` i strona
    Cloudflare), dla zapytań, które wynoszą z maszyny całą rozmowę."""
    global _fresh_ok_at, _last_block_at
    started = time.monotonic()
    # fresh (1.32.0): od nowa `warp-cli status` i interfejs tunelu (lokalnie, w
    # milisekundach); strona kontrolna Cloudflare z pamięci TRACE_TTL s - dawniej
    # odpytywana przy KAŻDYM świeżym sprawdzeniu, co dawało fałszywe blokady.
    st = status(force=fresh)
    with _lock:
        if not st["connected"]:
            _fresh_ok_at = 0.0
            _last_block_at = time.monotonic()
        elif fresh and started > _last_block_at:
            # Czas STARTU sprawdzenia i tylko, gdy od tamtej chwili nic nie
            # zablokowało (1.19.0, przegląd): wolne sprawdzenie zaczęte przy
            # działającym WARP nie może nadpisać blokady z innego wątku.
            _fresh_ok_at = started
    return st["connected"], st["reason"]


def recently_verified(max_age_s: float) -> bool:
    """Czy świeże sprawdzenie (fresh=True) potwierdziło WARP w ostatnich
    `max_age_s` sekundach (najwyżej FRESH_REUSE_MAX_S) i od tamtej pory żadne
    sprawdzenie nie zakończyło się blokadą."""
    age = min(float(max_age_s or 0.0), FRESH_REUSE_MAX_S)
    with _lock:
        return age > 0 and _fresh_ok_at > 0 and time.monotonic() - _fresh_ok_at < age


# 1.27.0 (audyt): także klucz Gemini (x-goog-api-key) i ogólne api-key - przekierowanie
# na inny host nie może zabrać żadnego klucza.
_CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key", "x-goog-api-key", "api-key"})


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


# Nazwy, które wskazują urządzenia w sieci lokalnej, a nie w internecie.
_LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal", ".home.arpa", ".localdomain", ".intranet")


def local_target_reason(url: str) -> str:
    """Pusty napis, gdy host to nazwa publiczna; inaczej powód odmowy. Ta sama reguła
    co przy przekierowaniach: adres IP (w każdej postaci), localhost, nazwa bez kropki
    i domeny lokalne odpadają (audyt 1.32.1: dotąd sprawdzane tylko po przekierowaniu,
    a adres z wyników wyszukiwania, np. https://192.168.1.1/..., szedł prosto)."""
    target = _host_of(url).rstrip(".")
    if not target or "." not in target or target == "localhost" or target.endswith(_LOCAL_SUFFIXES):
        return "adres lokalny"
    for parse in (ipaddress.ip_address, socket.inet_aton):
        try:
            parse(target)
        except (ValueError, OSError):
            continue
        return "adres IP"
    return ""


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Przekierowanie z https:// na http:// (albo gdziekolwiek poza https)
    jest zatrzymywane: inaczej serwer mógłby nas po cichu zepchnąć na
    połączenie nieszyfrowane."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise NetGuardBlocked(f"przekierowanie poza https zablokowane: {newurl.split('?')[0][:80]}")
        # Cel to nazwa publiczna: adres IP, localhost i nazwa bez kropki (host z sieci
        # lokalnej) to nie jest miejsce, do którego strona z internetu ma nas odsyłać.
        target = _host_of(newurl).rstrip(".")  # "localhost." to ten sam host co "localhost"
        if not target or "." not in target or target == "localhost" or target.endswith(_LOCAL_SUFFIXES):
            raise NetGuardBlocked(f"przekierowanie na adres lokalny zablokowane: {newurl.split('?')[0][:80]}")
        # Adres IP w każdej postaci, jaką rozumie system: także skrócone i szesnastkowe
        # ("127.1", "0x7f.0.0.1"), których ipaddress nie przyjmuje, a inet_aton tak.
        for parse in (ipaddress.ip_address, socket.inet_aton):
            try:
                parse(target)
            except (ValueError, OSError):
                continue
            raise NetGuardBlocked(f"przekierowanie na adres IP zablokowane: {newurl.split('?')[0][:80]}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        # urllib przenosi nagłówki na nowy adres także na INNY host: klucz API
        # (x-api-key) wyszedłby wtedy do obcego serwera. Przy zmianie hosta
        # nagłówki z poświadczeniami są usuwane.
        if new is not None and _host_of(newurl) != _host_of(req.full_url):
            for store in (new.headers, new.unredirected_hdrs):
                for key in [k for k in store if k.lower() in _CREDENTIAL_HEADERS]:
                    del store[key]
        return new


# Bez proxy z http_proxy/https_proxy (także wpisanego w .env): ruch do chmury idzie
# wyłącznie tunelem WARP, a nie przez cudzy serwer pośredniczący.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _HttpsOnlyRedirect)

# urllib.request.build_opener() domyślnie wysyła nagłówek User-Agent
# "Python-urllib/X.Y" (OpenerDirector.__init__) - to jest dosłownie podręcznikowy
# odcisk bota: wiele usług za Cloudflare (w tym api.groq.com) ma reguły WAF/Bot
# Fight Mode blokujące ten konkretny, domyślny ciąg, zanim żądanie w ogóle
# dotrze do serwera dostawcy (Cloudflare "error code: 1010" - "blocked based on
# your browser's/client's signature"). Zgłoszone przez Grzegorza: żongler
# (groq, przez to WŁAŚNIE urlopen) dostawał 403/1010, a ten sam klucz przez
# `curl` (inny, nie-blokowany odcisk) od razu doszedł do Groqa i dostał
# normalną odpowiedź JSON. To NIE jest próba podawania się za przeglądarkę -
# GREGAI nic nie udaje - tylko unikanie domyślnego, rozpoznawalnego z automatu
# podpisu biblioteki skryptowej, zgodnie z celem żonglera (patrz górny komentarz
# modułu juggler.py): żadny dostawca nie ma mieć powodu fałszywie oznaczać ruch
# GREGAI jako bota.
_OPENER.addheaders = [("User-Agent", "GREGAI/1.0 (osobisty asystent AI, Python urllib)")]

# Rozmowa z lokalną Ollamą nigdy nie idzie przez proxy z http_proxy/https_proxy
# w środowisku (treść rozmów wyszłaby wtedy poza tę maszynę) i nie podąża za
# przekierowaniami.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def local_urlopen(req, timeout: float):
    """Połączenie z usługą na TEJ maszynie (Ollama). Adres spoza localhost jest
    odrzucany, a proxy ze środowiska ignorowane."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if not is_local_url(url):
        raise NetGuardBlocked(f"połączenie lokalne odrzucone, adres nie jest localhost: {url.split('?')[0][:80]}")
    return _LOCAL_OPENER.open(req, timeout=timeout)


# Odpowiedź Ollamy albo chmury jest mała (kilkaset tokenów). Wczytujemy najwyżej tyle:
# zwariowany albo podstawiony serwer, który sypie gigabajty, nie ma wypełnić pamięci
# ani zawiesić karty przeglądarki ogromnym tekstem.
MAX_REPLY_BYTES = 4 * 1024 * 1024


def read_capped(resp, limit: int, deadline: float = 60.0) -> bytes:
    """Najwyżej `limit` + 1 bajtów z odpowiedzi, w kawałkach, z łącznym limitem czasu:
    `timeout` w urlopen ogranicza każde pojedyncze odebranie, więc serwer sączący
    bajt co kilka sekund trzymałby rozmowę (i jej blokadę) godzinami."""
    chunks: list[bytes] = []
    got = 0
    stop = time.monotonic() + deadline
    # 1.24.0+: strony WWW (tools._BROWSER_HEADERS prosi o gzip) przychodzą skompresowane,
    # 3-5x mniej danych na LTE. Limit dotyczy treści PO rozpakowaniu (bomba gzip nie
    # wypełni pamięci): dekompresor oddaje najwyżej tyle, ile jeszcze wolno.
    enc = ""
    try:
        enc = (resp.headers.get("Content-Encoding") or "").strip().lower()
    except Exception:
        enc = ""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if enc in ("gzip", "x-gzip") else None
    pending = b""
    while got <= limit:
        if time.monotonic() > stop:
            raise TimeoutError(f"odpowiedź nie dotarła w całości w {deadline:.0f} s")
        if inflater is None:
            chunk = resp.read(min(65536, limit + 1 - got))
            if not chunk:
                break
        else:
            if not pending:
                pending = resp.read(65536)
                if not pending:
                    chunk = inflater.flush()[: limit + 1 - got]
                    if chunk:
                        chunks.append(chunk)
                        got += len(chunk)
                    break
            chunk = inflater.decompress(pending, limit + 1 - got)
            pending = inflater.unconsumed_tail
            if inflater.eof:
                pending = b""
            if not chunk:
                if inflater.eof:
                    break
                continue
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def read_json(resp, limit: int = MAX_REPLY_BYTES, deadline: float = 60.0):
    """Odpowiedź JSON z otwartego połączenia, najwyżej `limit` bajtów."""
    raw = read_capped(resp, limit, deadline)
    if len(raw) > limit:
        raise ValueError(f"odpowiedź większa niż {limit // 1024} KB, odrzucona")
    return json.loads(raw.decode("utf-8"))


def urlopen(req, timeout: float, fresh: bool = False, reuse_s: float = 0.0):
    """Jedyna droga GREGAI do internetu. `req`: urllib.request.Request albo
    adres. Rzuca NetGuardBlocked, gdy WARP nie jest połączony albo adres
    nie jest https://. fresh=True: stan WARP sprawdzany od nowa (bez pamięci
    podręcznej), dla zapytań niosących całą rozmowę. reuse_s (1.19.0): gdy
    świeże sprawdzenie zakończone zgodą było nie dawniej niż reuse_s sekund
    temu (recently_verified), nie powtarzamy go; inaczej jak dotąd."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if not url.lower().startswith("https://"):
        raise NetGuardBlocked(f"tylko https:// do internetu, odrzucono: {url.split('?')[0][:80]}")
    if not (fresh and reuse_s and recently_verified(reuse_s)):
        ok, reason = internet_allowed(fresh=fresh)
        if not ok:
            raise NetGuardBlocked(reason)
    return _OPENER.open(req, timeout=timeout)


def fetch_http2(url: str, *, data: bytes | None = None, headers: dict | None = None,
                timeout: float = 12.0, fresh: bool = True, reuse_s: float = 0.0,
                max_bytes: int = MAX_REPLY_BYTES, deadline: float = 30.0) -> str:
    """Pobranie strony przez HTTP/2 (httpx), z TĄ SAMĄ bramką WARP co urlopen.
    Potrzebne tam, gdzie serwis odrzuca HTTP/1.1 z urllib jako ruch bota:
    DuckDuckGo na HTTP/1.1 oddaje 202 + stronę-wyzwanie (anomaly), a na HTTP/2 -
    normalne wyniki (sprawdzone 2026-10-22 na żywym WARP). Zwraca treść jako tekst
    (httpx sam rozpakowuje gzip). Rzuca NetGuardBlocked, gdy WARP rozłączony albo
    adres nie jest https://; ImportError/httpx.* gdy brak pakietu h2 albo błąd
    HTTP/2 - wtedy wołający spada na urllib (HTTP/1.1). trust_env=False: bez proxy
    ze środowiska, prosto przez tunel WARP, jak w juggler._groq_http2_chat."""
    if not url.lower().startswith("https://"):
        raise NetGuardBlocked(f"tylko https:// do internetu, odrzucono: {url.split('?')[0][:80]}")
    _why_local = local_target_reason(url)
    if _why_local:
        raise NetGuardBlocked(f"{_why_local} zablokowany (strony tylko z internetu): {url.split('?')[0][:80]}")
    if not (fresh and reuse_s and recently_verified(reuse_s)):
        ok, reason = internet_allowed(fresh=fresh)
        if not ok:
            raise NetGuardBlocked(reason)
    import httpx  # leniwie, jak w juggler._groq_http2_chat
    method = "POST" if data is not None else "GET"
    stop = time.monotonic() + deadline
    total = bytearray()
    with httpx.Client(http2=True, trust_env=False, follow_redirects=False, timeout=timeout) as client:
        with client.stream(method, url, content=data, headers=headers or {}) as resp:
            enc = resp.encoding or "utf-8"
            for chunk in resp.iter_bytes():
                total += chunk
                if len(total) > max_bytes:
                    break
                if time.monotonic() > stop:
                    raise TimeoutError(f"odpowiedź nie dotarła w całości w {deadline:.0f} s")
    return bytes(total).decode(enc, errors="ignore")


def fetch_via_curl(url: str, *, data: bytes | None = None, headers: dict | None = None,
                   timeout: float = 12.0, fresh: bool = True, reuse_s: float = 0.0,
                   max_bytes: int = MAX_REPLY_BYTES, want_meta: bool = False):
    """Pobranie strony systemowym `curl --http2`, z TĄ SAMĄ bramką WARP co urlopen.
    Niektóre serwisy rozpoznają ODCISK TLS/HTTP bibliotek Pythona (urllib, httpx)
    jako bota i oddają 202 + stronę-wyzwanie, a to samo zapytanie z tego samego
    adresu WARP przez curl przechodzi - sprawdzone 2026-10-22 na GREGAI2 w tej samej
    chwili: curl h2 -> 200 i wyniki, httpx h2 -> 202 i zero. curl jest i tak zależnością
    (install.sh krok 1). Ruch i tak idzie przez WARP (tunel systemowy + zapora nftability
    na cgroup usługi), więc fail-closed zostaje. Zwraca treść jako tekst (curl --compressed
    sam rozpakowuje). Rzuca NetGuardBlocked (WARP/nie-https); FileNotFoundError gdy brak
    curl; RuntimeError na błąd/limit - wtedy wołający spada na httpx/urllib."""
    if not url.lower().startswith("https://"):
        raise NetGuardBlocked(f"tylko https:// do internetu, odrzucono: {url.split('?')[0][:80]}")
    _why_local = local_target_reason(url)
    if _why_local:
        raise NetGuardBlocked(f"{_why_local} zablokowany (strony tylko z internetu): {url.split('?')[0][:80]}")
    if not (fresh and reuse_s and recently_verified(reuse_s)):
        ok, reason = internet_allowed(fresh=fresh)
        if not ok:
            raise NetGuardBlocked(reason)
    curl = shutil.which("curl")
    if not curl:
        raise FileNotFoundError("brak curl")
    # --proto =https: nawet po przekierowaniu tylko https (jak netguard _OPENER).
    # --max-filesize: twardy limit po stronie curl; dla pewności i tak tniemy stdout.
    # --noproxy '*' + środowisko bez zmiennych proxy (przegląd 1.32.0, M4): jak _OPENER
    # i httpx(trust_env=False) - ruch tylko tunelem WARP, nie przez cudze proxy.
    args = [curl, "-s", "--noproxy", "*", "--http2", "--compressed", "--proto", "=https",
            "--max-time", str(int(timeout)), "--max-filesize", str(int(max_bytes))]
    for k, v in (headers or {}).items():
        # Accept-Encoding i Content-Type zostawiamy curl (--compressed; --data ustawia formularz).
        if k.lower() in ("accept-encoding", "content-type"):
            continue
        args += ["-H", f"{k}: {v}"]
    if data is not None:
        body = data.decode("utf-8", "ignore") if isinstance(data, (bytes, bytearray)) else str(data)
        args += ["--data-raw", body]  # POST z gotowym, już zakodowanym ciałem (bez ponownego kodowania)
    # 1.32.11 (audyt tura 15): status HTTP, typ treści (kodowanie znaków) i cel przekierowania
    # jako ogon za treścią - dotąd strona błędu 404 albo "301 Moved" uchodziła za treść strony.
    args += ["-w", _CURL_META_SEP + "%{http_code} %{content_type}\t%{redirect_url}"]
    args.append(url)
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    # Audyt 1.32.1: --max-filesize liczy bajty SKOMPRESOWANE, a --compressed rozpakowuje -
    # 300 KB gzipu dawało 300 MB na stdout, które capture_output trzymało w pamięci w
    # całości. Czytamy strumień kawałkami i zabijamy curl po max_bytes rozpakowanych.
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    timed_out = threading.Event()

    def _kill() -> None:
        try:
            os.killpg(p.pid, 9)  # cała grupa: nic nie trzyma potoku po zabiciu
        except OSError:
            try:
                p.kill()
            except OSError:
                pass

    def _on_timeout() -> None:
        timed_out.set()
        _kill()

    timer = threading.Timer(timeout + 5, _on_timeout)
    timer.start()
    chunks: list[bytes] = []
    got = 0
    capped = False
    try:
        while True:
            piece = p.stdout.read(65536)
            if not piece:
                break
            chunks.append(piece)
            got += len(piece)
            if got >= max_bytes:
                capped = True
                _kill()
                break
        try:
            err = p.stderr.read(4096) if not capped else b""
        except Exception:
            err = b""
        rc = p.wait(timeout=5)
    finally:
        timer.cancel()
        for f in (p.stdout, p.stderr):
            try:
                f.close()
            except Exception:
                pass
        if p.poll() is None:
            _kill()
    if timed_out.is_set() and not capped:
        raise RuntimeError(f"curl: przekroczony czas {timeout:.0f} s")
    if not capped and rc != 0:
        raise RuntimeError(f"curl rc={rc}: {err.decode('utf-8', 'ignore')[:160]}")
    raw = b"".join(chunks)
    meta = {"status": 0, "content_type": "", "redirect_url": ""}
    sep = _CURL_META_SEP.encode()
    i = raw.rfind(sep)
    if i >= 0 and not capped:
        try:
            tail = raw[i + len(sep):].decode("utf-8", "ignore")
            head, _, redir = tail.partition("\t")
            code, _, ctype = head.strip().partition(" ")
            meta = {"status": int(code or 0), "content_type": ctype.strip(), "redirect_url": redir.strip()}
        except ValueError:
            pass
        raw = raw[:i]
    text = decode_html(raw[:max_bytes], meta["content_type"])
    return (text, meta) if want_meta else text


_CURL_META_SEP = "\n\x1e\x1eGREGAI-META:"
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset=["']?\s*([A-Za-z0-9_\-]+)""", re.IGNORECASE)


def decode_html(raw: bytes, content_type: str = "") -> str:
    """1.32.11: strona po polsku w windows-1250/ISO-8859-2 traciła wszystkie ogonki
    (utf-8 z errors=ignore). Kodowanie: nagłówek Content-Type, potem <meta charset>, potem
    utf-8 ściśle, na końcu cp1250 (najczęstsze polskie strony sprzed UTF-8)."""
    cs = ""
    m = re.search(r"charset=([A-Za-z0-9_\-]+)", content_type or "", re.IGNORECASE)
    if m:
        cs = m.group(1)
    else:
        mm = _META_CHARSET_RE.search(raw[:4096])
        if mm:
            cs = mm.group(1).decode("ascii", "ignore")
    for enc in ([cs] if cs else []) + ["utf-8", "cp1250", "iso-8859-2"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")
