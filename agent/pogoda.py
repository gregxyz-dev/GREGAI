"""
pogoda.py (1.30.31)

Dwie rzeczy, o które Grzegorz pytał w jednej rozmowie i które GREGAI robił źle:

1. Słońce (wschód, zachód, długość dnia i nocy) - LICZONE w kodzie, bez sieci i
   bez modelu (algorytm NOAA, dokładność ok. 1-2 minut). Wcześniej model podał
   "dzień 10 h 14 min, noc 10 h 02 min" (razem 20 godzin) - teraz dzień i noc
   zawsze sumują się do doby, bo noc to 24 h minus dzień. Linia trafia też do
   bloku "Teraz" w prompcie (awareness.py), więc zwykła rozmowa ma te liczby.

2. Pogoda - z Open-Meteo (darmowe, bez klucza i bez konta), tylko przez
   netguard (WARP, https), tak jak notowania z Coinbase. Wcześniej "jaka jest
   pogoda" dawało listę linków z wyszukiwarki, a w trybie Namysłu model składał
   z nich tabelę. Teraz liczby są z prognozy, nie z domysłu.

Miejsce domyślne: GREGAI_MIASTO (domyślnie Warszawa) i opcjonalnie GREGAI_LAT /
GREGAI_LON w .env. Inne miasto z wiadomości ("pogoda w Krakowie") rozwiązuje
geokoder Open-Meteo (nazwa miasta to jedyne, co wychodzi w sieć).
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import netguard as netguard_mod

DEFAULT_CITY = "Warszawa"
DEFAULT_LAT, DEFAULT_LON = 52.2297, 21.0122

_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search?name={name}&count=1&language=pl&format=json"
_FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
    "&current=temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
    "&hourly=temperature_2m,precipitation_probability,weather_code,wind_speed_10m"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
    "precipitation_sum,wind_speed_10m_max,sunrise,sunset"
    "&timezone=auto&forecast_days=3&wind_speed_unit=kmh"
)
_HEADERS = {"User-Agent": "GREGAI/1.30 (osobisty asystent; open-meteo)", "Accept": "application/json"}
_MAX_BYTES = 400_000

# Kody pogody WMO (Open-Meteo) -> opis po polsku.
_WMO = {
    0: "bezchmurnie", 1: "przeważnie słonecznie", 2: "częściowe zachmurzenie", 3: "pochmurno",
    45: "mgła", 48: "mgła z szadzią",
    51: "lekka mżawka", 53: "mżawka", 55: "gęsta mżawka", 56: "marznąca mżawka", 57: "gęsta marznąca mżawka",
    61: "lekki deszcz", 63: "deszcz", 65: "ulewny deszcz", 66: "marznący deszcz", 67: "silny marznący deszcz",
    71: "lekki śnieg", 73: "śnieg", 75: "intensywny śnieg", 77: "ziarna śniegu",
    80: "przelotne opady deszczu", 81: "przelotny deszcz", 82: "gwałtowne ulewy",
    85: "przelotny śnieg", 86: "intensywne opady śniegu",
    95: "burza", 96: "burza z gradem", 99: "silna burza z gradem",
}


def describe_code(code) -> str:
    try:
        return _WMO.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def home_place() -> tuple[str, float, float]:
    city = (os.environ.get("GREGAI_MIASTO", "") or "").strip() or DEFAULT_CITY
    try:
        lat = float(os.environ.get("GREGAI_LAT", "") or "nan")
        lon = float(os.environ.get("GREGAI_LON", "") or "nan")
    except ValueError:
        lat = lon = float("nan")
    if math.isnan(lat) or math.isnan(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat, lon = (DEFAULT_LAT, DEFAULT_LON) if city.lower() in ("warszawa", "warsaw") else (float("nan"), float("nan"))
    return city, lat, lon


# --- Słońce (NOAA, bez sieci) ---------------------------------------------------

def sun_times(day: date, lat: float, lon: float) -> dict | None:
    """Wschód i zachód słońca (czas lokalny komputera) oraz długość dnia i nocy w
    minutach. None przy dniu/nocy polarnej (słońce nie wschodzi albo nie zachodzi)."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    phi = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl))) - math.tan(phi) * math.tan(decl)
    if cos_ha < -1 or cos_ha > 1:
        return None
    ha = math.degrees(math.acos(cos_ha))
    rise_utc = 720 - 4 * (lon + ha) - eqtime   # minuty od północy UTC
    set_utc = 720 - 4 * (lon - ha) - eqtime
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rise = (midnight + timedelta(minutes=rise_utc)).astimezone()
    sset = (midnight + timedelta(minutes=set_utc)).astimezone()
    day_min = int(round(set_utc - rise_utc))
    return {"wschod": rise, "zachod": sset, "dzien_min": day_min, "noc_min": 24 * 60 - day_min}


def _hm(minutes: int) -> str:
    return f"{minutes // 60} h {minutes % 60:02d} min"


def sun_line(now: datetime | None = None) -> str:
    """Jedna linia do bloku "Teraz": słońce dziś w domowym mieście. "" gdy brak
    współrzędnych (inne miasto bez GREGAI_LAT/LON) albo dzień polarny."""
    city, lat, lon = home_place()
    if math.isnan(lat):
        return ""
    st = sun_times((now or datetime.now()).date(), lat, lon)
    if not st:
        return ""
    return (f"Słońce dziś ({city}, liczone w kodzie): wschód {st['wschod']:%H:%M}, zachód {st['zachod']:%H:%M}, "
            f"dzień {_hm(st['dzien_min'])}, noc {_hm(st['noc_min'])} (razem 24 h).")


# --- Pogoda (Open-Meteo przez netguard) ------------------------------------------

_CITY_RE = re.compile(
    r"\b(?:w|we|dla|na)\s+([A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\-]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\-]+)?)")
# Miejscownik -> mianownik dla najczęstszych miast (geokoder chce mianownika).
_LOCATIVE = {
    "warszawie": "Warszawa", "krakowie": "Kraków", "łodzi": "Łódź", "lodzi": "Łódź", "wrocławiu": "Wrocław",
    "wroclawiu": "Wrocław", "poznaniu": "Poznań", "gdańsku": "Gdańsk", "gdansku": "Gdańsk", "szczecinie": "Szczecin",
    "lublinie": "Lublin", "katowicach": "Katowice", "białymstoku": "Białystok", "bialymstoku": "Białystok",
    "gdyni": "Gdynia", "rzeszowie": "Rzeszów", "toruniu": "Toruń", "kielcach": "Kielce", "olsztynie": "Olsztyn",
    "opolu": "Opole", "bydgoszczy": "Bydgoszcz", "radomiu": "Radom", "płocku": "Płock", "sopocie": "Sopot",
    "zakopanem": "Zakopane", "londynie": "Londyn", "berlinie": "Berlin", "paryżu": "Paryż", "pradze": "Praga",
    # dopełniacz ("pogoda dla Gdańska")
    "warszawy": "Warszawa", "krakowa": "Kraków", "wrocławia": "Wrocław", "wroclawia": "Wrocław",
    "poznania": "Poznań", "gdańska": "Gdańsk", "gdanska": "Gdańsk", "szczecina": "Szczecin", "lublina": "Lublin",
    "katowic": "Katowice", "białegostoku": "Białystok", "rzeszowa": "Rzeszów", "torunia": "Toruń",
    "londynu": "Londyn", "berlina": "Berlin", "paryża": "Paryż",
}
_NOT_CITY = {"dzień", "dzien", "dzis", "dziś", "jutro", "weekend", "tydzień", "tydzien", "poniedziałek", "wtorek",
             "środę", "srode", "czwartek", "piątek", "piatek", "sobotę", "sobote", "niedzielę", "niedziele", "ciągu",
             "najbliższy", "najbliższe", "polsce", "nocy"}


def city_from_message(message: str) -> str:
    """Nazwa miasta z wiadomości ("pogoda w Krakowie" -> "Kraków"), albo "" (domyślne)."""
    text = message or ""
    for m in _CITY_RE.finditer(text):
        name = m.group(1).strip()
        first = name.split()[0].lower()
        if first in _NOT_CITY:
            continue
        low = name.lower()
        if low in _LOCATIVE:
            return _LOCATIVE[low]
        return name
    low = text.lower()
    for loc, nom in _LOCATIVE.items():
        if re.search(rf"\b{loc}\b", low):
            return nom
    return ""


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with netguard_mod.urlopen(req, timeout=12, fresh=True) as resp:
        raw = netguard_mod.read_capped(resp, _MAX_BYTES, deadline=20.0)
    data = json.loads(raw.decode("utf-8", errors="ignore"))
    if not isinstance(data, dict):  # 1.32.11: lista zamiast obiektu nie wywraca narzędzia
        raise ValueError("serwis pogody odpowiedział w nieoczekiwanym kształcie")
    return data


def _geocode(name: str) -> tuple[str, float, float] | None:
    data = _get_json(_GEO_URL.format(name=urllib.parse.quote(name[:60])))
    res = (data or {}).get("results") or []
    if not res:
        return None
    r = res[0]
    return str(r.get("name") or name), float(r["latitude"]), float(r["longitude"])


def _fmt_t(v) -> str:
    try:
        return f"{round(float(v)):d}°C"
    except (TypeError, ValueError):
        return "?"


def _num(v, nd: int = 0):
    try:
        return round(float(v), nd) if nd else int(round(float(v)))
    except (TypeError, ValueError):
        return None


def weather(message: str = "", now: datetime | None = None) -> dict:
    """Aktualna pogoda i prognoza na dziś/jutro. Zwraca wynik narzędzia
    ({"speech", "card"}); przy błędzie mówi wprost, czego nie udało się
    sprawdzić - nigdy nie zgaduje liczb."""
    now = now or datetime.now()
    wanted = city_from_message(message)
    city, lat, lon = home_place()
    try:
        if wanted and wanted.lower() != city.lower():
            geo = _geocode(wanted)
            if geo is None:
                return {"ok": False, "speech": f"Nie znalazłem miejscowości „{wanted}”. Podaj nazwę miasta w mianowniku, np. „pogoda Kraków”.",
                        "card": {"type": "weather", "query": wanted, "error": "BrakMiasta"}}
            city, lat, lon = geo
        elif math.isnan(lat):
            geo = _geocode(city)
            if geo is None:
                return {"ok": False, "speech": f"Nie znalazłem miejscowości „{city}” z GREGAI_MIASTO w .env.",
                        "card": {"type": "weather", "query": city, "error": "BrakMiasta"}}
            city, lat, lon = geo
        data = _get_json(_FORECAST_URL.format(lat=lat, lon=lon))
    except netguard_mod.NetGuardBlocked as e:
        return {"ok": False, "speech": netguard_mod.blocked_speech(str(e)),
                "card": {"type": "weather", "query": city, "error": "NetGuardBlocked", "reason": str(e)[:200]}}
    except Exception as e:
        return {"ok": False, "speech": f"Nie udało się pobrać prognozy: {netguard_mod.explain_error(e)}. Spróbuj za chwilę albo napisz /diagnoza.",
                "card": {"type": "weather", "query": city, "error": type(e).__name__}}

    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    hourly = data.get("hourly") or {}
    days = []
    for i, d in enumerate((daily.get("time") or [])[:3]):
        def at(key, i=i):
            arr = daily.get(key) or []
            return arr[i] if i < len(arr) else None
        days.append({"data": d, "opis": describe_code(at("weather_code")), "min": _num(at("temperature_2m_min")),
                     "max": _num(at("temperature_2m_max")), "opady_proc": _num(at("precipitation_probability_max")),
                     "opady_mm": _num(at("precipitation_sum"), 1), "wiatr_max": _num(at("wind_speed_10m_max")),
                     "wschod": str(at("sunrise") or "")[11:16], "zachod": str(at("sunset") or "")[11:16]})
    today = now.strftime("%Y-%m-%d")
    hours = []
    for i, t in enumerate(hourly.get("time") or []):
        if not str(t).startswith(today) or int(str(t)[11:13] or 0) % 3:
            continue
        def ha(key, i=i):
            arr = hourly.get(key) or []
            return arr[i] if i < len(arr) else None
        hours.append({"godz": str(t)[11:16], "temp": _num(ha("temperature_2m")), "opady_proc": _num(ha("precipitation_probability")),
                      "wiatr": _num(ha("wind_speed_10m")), "opis": describe_code(ha("weather_code"))})
    if not cur and not days:
        return {"ok": False, "speech": "Serwis pogodowy odpowiedział bez danych. Spróbuj za chwilę.",
                "card": {"type": "weather", "query": city, "error": "PustaPrognoza"}}

    parts = []
    if cur:
        now_txt = f"{city}, teraz: {_fmt_t(cur.get('temperature_2m'))}"
        if cur.get("apparent_temperature") is not None:
            now_txt += f" (odczuwalna {_fmt_t(cur.get('apparent_temperature'))})"
        opis = describe_code(cur.get("weather_code"))
        if opis:
            now_txt += f", {opis}"
        if cur.get("wind_speed_10m") is not None:
            now_txt += f", wiatr {_num(cur.get('wind_speed_10m'))} km/h"
        parts.append(now_txt + ".")
    labels = ["Dziś", "Jutro", "Pojutrze"]
    for label, d in zip(labels[:2], days[:2]):
        _mn = "?" if d["min"] is None else d["min"]
        _mx = "?" if d["max"] is None else d["max"]
        line = f"{label}: {d['opis'] or 'bez opisu'}, od {_mn} do {_mx}°C"
        if d["opady_proc"] is not None:
            line += f", szansa opadów {d['opady_proc']}%"
        if d["opady_mm"]:
            line += f" ({str(d['opady_mm']).replace('.', ',')} mm)"
        if d["wiatr_max"] is not None:
            line += f", wiatr do {d['wiatr_max']} km/h"
        parts.append(line + ".")
    if days and days[0]["wschod"]:
        parts.append(f"Słońce dziś: wschód {days[0]['wschod']}, zachód {days[0]['zachod']}.")
    speech = " ".join(parts) + " (Open-Meteo)"
    return {"speech": speech, "card": {"type": "weather", "query": city, "miasto": city, "teraz": {
        "temp": _num(cur.get("temperature_2m")), "odczuwalna": _num(cur.get("apparent_temperature")),
        "opis": describe_code(cur.get("weather_code")), "wiatr": _num(cur.get("wind_speed_10m"))} if cur else None,
        "dni": days, "godziny": hours, "source": "open-meteo.com"}}
