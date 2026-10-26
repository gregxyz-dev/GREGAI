"""
diagnoza.py (1.32.0)

Diagnoza internetu GREGAI warstwa po warstwie - prośba Grzegorza: "napraw mu
bardzo dokładnie dostęp do internetu". Zamiast jednego "internet nie działa"
sprawdzamy KAŻDĄ warstwę, od najniższej, tą samą drogą, którą idą prawdziwe
funkcje (netguard, curl, te same nagłówki), i wskazujemy PIERWSZĄ, która nie
działa, z poleceniem naprawy:

  1. Klient WARP       - czy warp-cli jest zainstalowany
  2. Usługa i status   - czy warp-svc odpowiada, co mówi `warp-cli status`
  3. Tunel             - czy istnieje interfejs CloudflareWARP (nie tryb proxy/DNS)
  4. Ruch przez WARP   - strona kontrolna Cloudflare: warp=on, centrum (colo)
  5. Bramka GREGAI     - decyzja netguard.internet_allowed (to, co widzi kod)
  6. DNS               - czy nazwy serwerów się rozwiązują
  7. Usługi            - wyszukiwarki, Wikipedia, pogoda, notowania, dostawcy AI
  8. Narzędzia         - curl i httpx/h2 (od nich zależy, czy DuckDuckGo przepuści)

Uruchamiana w USŁUDZE gregai (czat: /diagnoza, Nadzorca, `gregai diagnoza`
przez /api/diagnoza), bo tylko tam działa ta sama zapora jądra (cgroup usługi)
co dla prawdziwych zapytań. Do dostawców AI NIE idzie żaden klucz: sprawdzamy
samo połączenie (odpowiedź 401/403 bez klucza = serwer osiągalny).

Warstwy sieciowe (6-7) ruszają tylko przy otwartej bramce WARP: diagnoza nie
może sama łamać zasady "bez WARP nic nie wychodzi".
"""

from __future__ import annotations

import re
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import netguard as netguard_mod

KILLSWITCH_FILE = Path("/etc/gregai/warp-killswitch.nft")
PROBE_TIMEOUT_S = 10.0
TOTAL_BUDGET_S = 40.0

# Adresy do sprawdzenia samego połączenia z dostawcami AI - bez klucza.
_PROVIDER_PROBE = {
    "anthropic": ("Claude (Anthropic)", "https://api.anthropic.com/v1/models"),
    "groq": ("Groq", "https://api.groq.com/openai/v1/models"),
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/models"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1/models"),
    "huggingface": ("Hugging Face", "https://router.huggingface.co/v1/models"),
    "cloudflare": ("Cloudflare Workers AI", "https://api.cloudflare.com/client/v4/"),
}


def _layer(nazwa: str, ok: bool | None, szczegoly: str, rada: str = "", warstwa: int = 0, ms: int | None = None) -> dict:
    """ok: True działa, False nie działa, None nie sprawdzono (np. pominięte bez WARP)."""
    d = {"warstwa": warstwa, "nazwa": nazwa, "ok": ok, "szczegoly": szczegoly}
    if rada:
        d["rada"] = rada
    if ms is not None:
        d["ms"] = ms
    return d


def _probe_http(url: str, headers: dict | None = None) -> tuple[bool, str, int]:
    """(osiągalny, opis, ms). Każda odpowiedź HTTP (także 401/403/404) = serwer
    osiągalny przez tunel; brak odpowiedzi = przyczyna z netguard.explain_error."""
    t0 = time.monotonic()
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    try:
        with netguard_mod.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            code = resp.status
        return True, f"odpowiada (HTTP {code})", int((time.monotonic() - t0) * 1000)
    except urllib.error.HTTPError as e:
        ms = int((time.monotonic() - t0) * 1000)
        if e.code in (401, 403, 404, 405, 400):
            return True, f"osiągalny (HTTP {e.code} bez klucza - tak ma być)", ms
        if e.code == 429:
            return True, "osiągalny, ale ogranicza liczbę zapytań (HTTP 429)", ms
        return False, netguard_mod.explain_error(e), ms
    except Exception as e:
        return False, netguard_mod.explain_error(e), int((time.monotonic() - t0) * 1000)


def _search_probe(name: str) -> tuple[bool, str, int]:
    import tools as tools_mod
    t0 = time.monotonic()
    try:
        items, why = tools_mod._search_engine(name, "pogoda Warszawa")
    except Exception as e:
        return False, netguard_mod.explain_error(e), int((time.monotonic() - t0) * 1000)
    ms = int((time.monotonic() - t0) * 1000)
    if items:
        return True, f"zwraca wyniki ({len(items)})", ms
    return False, why or "brak wyników", ms


def _weather_probe() -> tuple[bool, str, int]:
    import pogoda as pogoda_mod
    t0 = time.monotonic()
    try:
        data = pogoda_mod._get_json(pogoda_mod._FORECAST_URL.format(lat=pogoda_mod.DEFAULT_LAT, lon=pogoda_mod.DEFAULT_LON))
        ok = isinstance(data, dict) and bool(data.get("current") or data.get("daily"))
        return ok, "prognoza dostępna" if ok else "serwis odpowiedział bez danych", int((time.monotonic() - t0) * 1000)
    except Exception as e:
        return False, netguard_mod.explain_error(e), int((time.monotonic() - t0) * 1000)


def _service_probes() -> list[tuple[str, str, callable]]:
    """(nazwa, rada przy porażce, funkcja) dla warstwy 7."""
    import tools as tools_mod
    probes = []
    for name in tools_mod._engines():
        label = tools_mod._ENGINE_LABEL[name]
        probes.append((f"Wyszukiwarka {label}", "jeśli odrzuca, GREGAI sam przejdzie do następnej wyszukiwarki",
                       (lambda n=name: _search_probe(n))))
    probes.append(("Wikipedia", "", lambda: _probe_http("https://pl.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json",
                                                         tools_mod._API_HEADERS)))
    probes.append(("Pogoda (Open-Meteo)", "", _weather_probe))
    probes.append(("Notowania krypto (Coinbase)", "", lambda: _probe_http("https://api.coinbase.com/v2/prices/BTC-USD/spot")))
    try:
        import juggler as juggler_mod
        configured = juggler_mod.providers_pool()
    except Exception:
        configured = []
    for name in configured:
        if name in _PROVIDER_PROBE:
            label, url = _PROVIDER_PROBE[name]
            probes.append((f"AI: {label}", "", (lambda u=url: _probe_http(u))))
    return probes


def run() -> dict:
    """Pełna diagnoza. Zwraca {"warstwy": [...], "werdykt": str, "naprawa": str,
    "czas_s": float, "internet": bool}. Nigdy nie rzuca."""
    t0 = time.monotonic()
    out: list[dict] = []

    # 1. Klient WARP
    exe = shutil.which("warp-cli")
    out.append(_layer("Klient Cloudflare WARP", bool(exe), exe or "nie znaleziono warp-cli",
                      "" if exe else "bash install.sh (instaluje WARP)", 1))

    # 2. Usługa i status
    raw = ""
    connected = False
    first = ""
    if exe:
        rc, raw = netguard_mod._run_warp_status()
        first = raw.strip().splitlines()[0].strip() if raw.strip() else "(brak odpowiedzi)"
        connected = rc == 0 and bool(netguard_mod._CONNECTED_RE.search(raw))
        what, fix = netguard_mod.warp_hint(raw)
        out.append(_layer("Usługa WARP i połączenie", connected, first[:160] + (f" - {what}" if what and not connected else ""),
                          "" if connected else (fix or "warp-cli connect"), 2))
        mode = ""
        rc2, settings = netguard_mod._run_warp("settings")
        for line in settings.splitlines():
            if line.strip().lower().startswith("mode:"):
                mode = line.split(":", 1)[1].strip()
                break
    else:
        out.append(_layer("Usługa WARP i połączenie", None, "pominięte (brak klienta)", "", 2))
        mode = ""

    # 3. Tunel
    tun = netguard_mod.tunnel_present()
    if not exe:
        out.append(_layer("Tunel (interfejs CloudflareWARP)", None, "pominięte (brak klienta WARP)", "", 3))
    elif not connected:
        # Brak tunelu przy rozłączonym kliencie to SKUTEK warstwy 2, nie osobna przyczyna.
        out.append(_layer("Tunel (interfejs CloudflareWARP)", None, "pominięte (klient WARP nie jest połączony)", "", 3))
    elif tun is None:
        out.append(_layer("Tunel (interfejs CloudflareWARP)", None, "nie da się sprawdzić (brak /sys/class/net)", "", 3))
    else:
        detail = "interfejs CloudflareWARP podniesiony" if tun else "brak interfejsu CloudflareWARP"
        if mode:
            detail += f"; tryb klienta: {mode}"
        fix3 = "warp-cli mode warp && warp-cli connect"
        if not tun and mode.strip().lower().startswith("warp") and "proxy" not in mode.lower():
            fix3 = "sudo systemctl restart warp-svc"  # tryb już "warp", a tunelu brak - klient się zawiesił
        out.append(_layer("Tunel (interfejs CloudflareWARP)", tun, detail, "" if tun else fix3, 3))

    # 4. Ruch przez WARP (strona kontrolna, świeżo) - TYLKO przy połączonym kliencie i
    #    NIE wykluczonym tunelu: inaczej zapytanie do Cloudflare wyszłoby poza WARP.
    #    Wynik idzie do tej samej pamięci co bramka (netguard._trace_cached), więc
    #    warstwa 5 nie pyta drugi raz (przegląd 1.32.0, L4).
    if not connected or tun is False:
        kind, why, info = "skip", "", {}
        out.append(_layer("Ruch przez WARP (strona kontrolna Cloudflare)", None,
                          "pominięte: bez połączonego tunelu nic nie wysyłam", "", 4))
    else:
        ev_first = raw.strip().splitlines()[0].strip() if raw.strip() else ""  # ten sam kształt co netguard._check
        kind, why = netguard_mod._trace_cached(force=True, evidence=f"{ev_first}|{tun}")
        info = dict(netguard_mod._trace_cache.get("info") or {}) if kind == "on" else {}
    if kind == "skip":
        pass
    elif kind == "on":
        where = ", ".join(x for x in (f"centrum {info.get('colo')}" if info.get("colo") else "",
                                       f"kraj wyjścia {info.get('loc')}" if info.get("loc") else "",
                                       f"warp={info.get('warp')}") if x)
        out.append(_layer("Ruch przez WARP (strona kontrolna Cloudflare)", True, where, "", 4))
        # Ruch potwierdzony przez Cloudflare, a interfejsu o oczekiwanej nazwie nie ma:
        # to nie awaria (inna nazwa w nowszym kliencie), tylko informacja.
        for l in out:
            if l["warstwa"] == 3 and l["ok"] is False:
                l["ok"] = None
                l["szczegoly"] += " - ale ruch przez WARP potwierdzony, więc tunel działa (inna nazwa interfejsu)"
                l.pop("rada", None)
    elif kind == "off":
        out.append(_layer("Ruch przez WARP (strona kontrolna Cloudflare)", False, why, "warp-cli mode warp", 4))
    else:
        out.append(_layer("Ruch przez WARP (strona kontrolna Cloudflare)", False, why,
                          "sprawdź sieć (Wi-Fi/LTE); jeśli działa, sudo systemctl restart warp-svc", 4))

    # 5. Bramka GREGAI (to, co widzi kod przy prawdziwych zapytaniach)
    allowed, reason = netguard_mod.internet_allowed(fresh=True)
    st = netguard_mod.status()
    out.append(_layer("Bramka GREGAI (netguard)", allowed, reason[:220], "" if allowed else (st.get("fix") or ""), 5))
    killswitch = KILLSWITCH_FILE.exists()
    # 1.32.9 (audyt tura 13): sam plik reguł to za mało - stara usługa ("ExecStartPre=-+" z 1.32.3)
    # startuje i bez nich. Wymuszona zapora = linia bez "-" w pliku usługi (jak kontrola 29).
    try:
        unit = Path("/etc/systemd/system/gregai.service").read_text(encoding="utf-8", errors="ignore")
        enforced = bool(re.search(r"(?m)^ExecStartPre=\+/usr/sbin/nft -f ", unit))
    except OSError:
        unit, enforced = "", False
    ok_ks = killswitch and (enforced or not unit)
    why = ("reguły zainstalowane i wymuszane przy starcie usługi" if ok_ks and enforced else
           "reguły zainstalowane (usługa systemd nie jest tu zainstalowana)" if ok_ks else
           "reguły są, ale usługa z poprzedniej wersji ich nie wymusza: uruchom instalator" if killswitch else
           "brak pliku reguł: zapora jest obowiązkowa, uruchom instalator")
    out.append(_layer("Zapora jądra (tylko przez WARP)", ok_ks, why, "" if ok_ks else "bash install.sh", 5))

    # 6-7. DNS i usługi - tylko przy otwartej bramce
    if not allowed:
        out.append(_layer("DNS", None, "pominięte: bramka WARP zamknięta (diagnoza też nic nie wysyła bez WARP)", "", 6))
        out.append(_layer("Usługi w internecie", None, "pominięte: bramka WARP zamknięta", "", 7))
    else:
        t_dns = time.monotonic()
        try:
            socket.getaddrinfo("duckduckgo.com", 443, proto=socket.IPPROTO_TCP)
            out.append(_layer("DNS", True, "nazwy serwerów się rozwiązują", "", 6, int((time.monotonic() - t_dns) * 1000)))
        except OSError as e:
            out.append(_layer("DNS", False, f"nie działa ({e.__class__.__name__})",
                              "resolvectl status; sudo systemctl restart systemd-resolved warp-svc", 6))
        results: dict[int, dict] = {}
        probes = _service_probes()

        def worker(i: int, nazwa: str, rada: str, fn) -> None:
            try:
                ok, detail, ms = fn()
            except Exception as e:
                ok, detail, ms = False, netguard_mod.explain_error(e), None
            results[i] = _layer(nazwa, ok, detail, "" if ok else rada, 7, ms)

        threads = [threading.Thread(target=worker, args=(i, n, r, f), daemon=True) for i, (n, r, f) in enumerate(probes)]
        for th in threads:
            th.start()
        deadline = time.monotonic() + max(5.0, TOTAL_BUDGET_S - (time.monotonic() - t0))
        for th in threads:
            th.join(max(0.0, deadline - time.monotonic()))
        for i, (nazwa, _rada, _fn) in enumerate(probes):
            out.append(results.get(i) or _layer(nazwa, False, "nie odpowiedział w czasie diagnozy", "", 7))

    # Wyszukiwarka, która odrzuca ruch, gdy inna działa, to nie awaria: GREGAI sam
    # przechodzi do następnej. Pokazujemy ją jako informację, nie błąd.
    search = [l for l in out if l["nazwa"].startswith("Wyszukiwarka ")]
    if any(l["ok"] for l in search):
        for l in search:
            if l["ok"] is False:
                l["ok"] = None
                l["szczegoly"] += " - zastępuje ją inna wyszukiwarka"
                l.pop("rada", None)

    # 8. Narzędzia
    curl = shutil.which("curl")
    curl_ver = ""
    if curl:
        try:
            curl_ver = subprocess.run([curl, "--version"], capture_output=True, text=True, timeout=4).stdout.split("\n")[0][:60]
        except Exception:
            curl_ver = curl
    out.append(_layer("curl (wyszukiwarki przepuszczają jego odcisk)", bool(curl), curl_ver or "brak curl",
                      "" if curl else "sudo apt install -y curl", 8))
    try:
        import httpx  # noqa: F401
        import h2  # noqa: F401
        h2_ok = True
    except Exception:
        h2_ok = False
    try:
        import juggler as juggler_mod
        needs_h2 = "groq" in juggler_mod.providers_pool() or not curl
    except Exception:
        needs_h2 = not curl
    out.append(_layer("httpx z HTTP/2 (zapas za curl, Groq)", True if h2_ok else (False if needs_h2 else None),
                      "zainstalowane" if h2_ok else ("brak (potrzebne)" if needs_h2 else "brak (opcjonalne: curl wystarcza)"),
                      "" if h2_ok else "python3 -m pip install --user --break-system-packages 'httpx[http2]'", 8))

    # Werdykt: pierwsza warstwa, która nie działa (w kolejności warstw).
    failed = [l for l in out if l["ok"] is False]
    core_failed = [l for l in failed if l["warstwa"] <= 6]
    if not failed:
        verdict, fix = "Internet działa na wszystkich warstwach.", ""
    elif core_failed:
        first = core_failed[0]
        verdict = f"Nie działa warstwa {first['warstwa']}: {first['nazwa']} - {first['szczegoly']}."
        fix = first.get("rada", "")
    else:
        names = ", ".join(l["nazwa"] for l in failed)
        verdict = f"Tunel i bramka działają; problem tylko z: {names}."
        fix = next((l.get("rada") for l in failed if l.get("rada")), "")
    return {"warstwy": out, "werdykt": verdict, "naprawa": fix, "internet": bool(allowed),
            "czas_s": round(time.monotonic() - t0, 1), "wyszukiwarki": _engine_state()}


_RUN_LOCK = threading.Lock()
_RUN_CACHE: dict = {"at": 0.0, "report": None}
CACHE_S = 10.0


def cached_run() -> dict:
    """Jedna diagnoza naraz; wynik ważny CACHE_S s. Wspólne dla czatu (/diagnoza,
    "czemu nie masz internetu"), Nadzorcy i `gregai diagnoza` (/api/diagnoza)."""
    with _RUN_LOCK:
        if _RUN_CACHE["report"] is not None and time.monotonic() - _RUN_CACHE["at"] < CACHE_S:
            return _RUN_CACHE["report"]
        try:
            report = run()
        except Exception as e:
            report = {"warstwy": [], "werdykt": f"Diagnoza nie powiodła się: {type(e).__name__}", "naprawa": "",
                      "internet": False, "czas_s": 0}
        report["tekst"] = text(report)
        _RUN_CACHE.update(at=time.monotonic(), report=report)
        return report


def _engine_state() -> dict:
    try:
        import tools as tools_mod
        return tools_mod.engine_status()
    except Exception:
        return {}


def text(report: dict) -> str:
    """Raport po polsku do czatu i terminala (zwykły tekst, bez Markdownu tabel)."""
    sym = {True: "OK", False: "BŁĄD", None: "-"}
    lines = [f"Diagnoza internetu ({report.get('czas_s', 0)} s): {report.get('werdykt', '')}"]
    if report.get("naprawa"):
        lines.append(f"Co zrobić: {report['naprawa']}")
    lines.append("")
    for l in report.get("warstwy", []):
        ms = f" ({l['ms']} ms)" if l.get("ms") is not None else ""
        line = f"{l['warstwa']}. [{sym[l['ok']]}] {l['nazwa']}: {l['szczegoly']}{ms}"
        if l.get("rada") and l["ok"] is False:
            line += f" -> {l['rada']}"
        lines.append(line)
    return "\n".join(lines)


def card(report: dict) -> dict:
    return {"type": "diagnoza", "werdykt": report.get("werdykt", ""), "naprawa": report.get("naprawa", ""),
            "internet": report.get("internet", False), "czas_s": report.get("czas_s"),
            "warstwy": report.get("warstwy", [])[:30]}


def as_tool_result() -> dict:
    report = cached_run()
    head = report["werdykt"] + (f" Co zrobić: {report['naprawa']}" if report.get("naprawa") else "")
    return {"speech": head, "card": card(report)}


if __name__ == "__main__":  # awaryjnie, gdy usługa nie działa: python3 agent/diagnoza.py
    os.environ.setdefault("GREGAI_DIAGNOZA_POZA_USLUGA", "1")
    print("UWAGA: diagnoza poza usługą gregai - zapora jądra usługi tu nie obowiązuje.\n")
    print(text(run()))
