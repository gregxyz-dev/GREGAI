"""
sysinfo.py

Prawdziwe parametry SPRZĘTU, na którym GREGAI akurat działa, odczytane
BEZPOŚREDNIO z systemu (/proc/meminfo, /proc/cpuinfo, shutil.disk_usage),
zero zewnętrznych zależności (żadnego psutil - nie ma gwarancji, że jest
zainstalowany, a instalowanie czegokolwiek tylko po to, by zmierzyć RAM,
to przesada). Powód istnienia tego pliku: decyzje o num_ctx/num_predict/
limitach czasu w router.py muszą się opierać na PRAWDZIWYCH liczbach z
TEGO konkretnego laptopa (Dell Latitude E7270, i7-6600U, 16GB RAM), nie na
zgadywaniu "pewnie ma z grubsza tyle a tyle". Wystawione przez
/api/system_info (main.py) i widoczne na stronie /debug, żeby decyzję o
"rdzeniu" (który model Ollama) podejmować na podstawie liczb, nie
przeczucia.

Działa tylko na Linuksie (ten laptop jest na Ubuntu) - na innych
systemach /proc po prostu nie istnieje, więc zwracamy None dla tych pól
zamiast zgadywać lub fałszywie udawać dokładność.
"""

from __future__ import annotations

import re
import shutil
import sys
import urllib.request
from pathlib import Path

import netguard


def _read_meminfo() -> dict:
    """MemTotal/MemAvailable/SwapTotal/SwapFree w kB -> MB (zaokrąglone).
    MemAvailable (nie MemFree!) to liczba, która faktycznie liczy się dla
    "czy zaraz zacznę swapować": uwzględnia pamięć odzyskiwalną z cache,
    którą jądro i tak odda procesowi, gdy potrzebuje, więc MemFree samo
    w sobie wygląda dużo gorzej niż jest w praktyce."""
    path = Path("/proc/meminfo")
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    values = {}
    for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
        m = re.search(rf"^{key}:\s+(\d+)\s*kB", raw, re.MULTILINE)
        if m:
            values[key] = round(int(m.group(1)) / 1024)  # kB -> MB
    return values


def _read_cpuinfo() -> dict:
    """Nazwa modelu CPU i liczba logicznych rdzeni (z wątkami, np. i7-6600U
    to 2 fizyczne rdzenie / 4 logiczne dzięki Hyper-Threadingowi) - liczba
    logicznych rdzeni to ta, która realnie ogranicza równoległość Ollamy."""
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    model_match = re.search(r"^model name\s*:\s*(.+)$", raw, re.MULTILINE)
    logical_cores = len(re.findall(r"^processor\s*:\s*\d+$", raw, re.MULTILINE))
    result = {}
    if model_match:
        result["model"] = model_match.group(1).strip()
    if logical_cores:
        result["logical_cores"] = logical_cores
    return result


def _disk_free_gb(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
        return round(usage.free / (1024 ** 3), 1)
    except OSError:
        return None


def host_info() -> dict:
    mem = _read_meminfo()
    cpu = _read_cpuinfo()
    return {
        "platform": sys.platform,
        "cpu_model": cpu.get("model"),
        "cpu_logical_cores": cpu.get("logical_cores"),
        "ram_total_mb": mem.get("MemTotal"),
        "ram_available_mb": mem.get("MemAvailable"),
        "swap_total_mb": mem.get("SwapTotal"),
        "swap_free_mb": mem.get("SwapFree"),
        "disk_free_gb": _disk_free_gb(Path(__file__).resolve().parent.parent),  # dysk, na którym leży folder GREGAI
    }


def ollama_info(ollama_host: str, timeout: float = 3.0) -> dict:
    """/api/tags: modele ściągnięte na dysk (nazwa + rozmiar pliku).
    /api/ps: modele AKTUALNIE wczytane do RAM przez Ollamę (nazwa +
    rzeczywiste zajęcie pamięci "size_vram"/"size" w danym momencie -
    to jest liczba, która naprawdę konkuruje z resztą systemu o pamięć).
    Osobna, cicha porażka na każdym z dwóch wywołań: Ollama może akurat
    nie mieć żadnego modelu wczytanego (/api/ps zwraca puste models),
    co jest normalnym stanem, nie błędem."""
    base = ollama_host.rstrip("/")
    result: dict = {"reachable": False, "installed": [], "loaded": []}
    try:
        with netguard.local_urlopen(urllib.request.Request(base + "/api/tags"), timeout=timeout) as resp:
            data = netguard.read_json(resp)
        result["reachable"] = True
        result["installed"] = [
            {
                "name": m.get("name"),
                "size_mb": round(m.get("size", 0) / (1024 ** 2)) if m.get("size") else None,
            }
            for m in data.get("models", [])
        ]
    except Exception:
        return result
    try:
        with netguard.local_urlopen(urllib.request.Request(base + "/api/ps"), timeout=timeout) as resp:
            data = netguard.read_json(resp)
        result["loaded"] = [
            {
                "name": m.get("name"),
                "size_mb": round(m.get("size", 0) / (1024 ** 2)) if m.get("size") else None,
                "size_vram_mb": round(m.get("size_vram", 0) / (1024 ** 2)) if m.get("size_vram") else None,
            }
            for m in data.get("models", [])
        ]
    except Exception:
        pass
    return result
