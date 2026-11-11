"""
ops.py (1.44.0) - narzędzia operacyjne dla AGENTA (CLI `gregai`).

Główny odbiorca to agent (OpenCode), nie człowiek:
  - `gregai state`      - maszynowy stan całego systemu (JSON),
  - `gregai diag ...`   - celowana diagnostyka modułu,
  - `gregai impact ...` - analiza zależności przed zmianą,
  - `gregai tokens`     - zużycie / budżet / (częściowo) fazy,
  - `gregai reset ...`  - jawne, wąskie operacje na licznikach dowęzłowywania,
  - `gregai log`        - ostatnie linie dziennika usługi,
  - `gregai verify`     - szybka weryfikacja składni i wersji.

Zasady:
  - Python stdlib tylko, bez sieci (poza jawnym `diag koryto --test`),
  - domyślnie JSON (maszynowo), `--human` = czytelny wydruk,
  - diagnostyka NICZEGO nie zmienia poza jawnym `reset`,
  - moduły projektu są importowane leniwie, żeby `state` był szybki i nie
    uruchamiał serwera ani sieci,
  - żadnych sekretów w wyniku: wartości kluczy z `KEY/TOKEN/SECRET/PASS`
    są maskowane.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"
DATA = ROOT / "data"
UI = ROOT / "ui"

STATE_LAST = DATA / "ops_state_last.json"
VERIFY_LAST = DATA / "ops_verify_last.json"
VAULT_CACHE = DATA / "ops_vault_cache.json"
WEZLY_STATE = DATA / "wezly_grow.json"
SPEND_LOG = DATA / "koryto_wydatki.jsonl"
OLLAMA_LOG = DATA / "ollama_uzycie.jsonl"


def _load_env() -> None:
    """Minimalny loader .env dla CLI (bez importu fsutil/env_loader - chodzi
    o czas startu `state`). Ta sama semantyka: bez nadpisywania środowiska,
    ostatni wpis wygrywa, stare SIECAI_* czytane jako GREGAI_*."""
    path = ROOT / ".env"
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\x00", "")
    except OSError:
        return
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            pairs.append((key, value))
    new_keys = {k for k, _ in pairs if k.startswith("GREGAI_")}
    for key, value in pairs:
        if key.startswith("SIECAI_"):
            renamed = "GREGAI_" + key[len("SIECAI_"):]
            if renamed in new_keys:
                continue
            key = renamed
        if key in os.environ:
            continue
        try:
            os.environ[key] = value
        except ValueError:
            continue


def _journal_path() -> Path:
    return Path(os.environ.get("KORYTO_DZIENNIK_PLIK") or (DATA / "koryto_dziennik.json"))


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return default


def _read_json(path: Path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default
    return value


def _write_json(path: Path, value) -> None:
    """Lekki zapis cache diagnostycznego (bez fsutil: state ma być szybki)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _version() -> str:
    return _read_text(ROOT / "VERSION", "?").strip() or "?"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _run(argv: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    import subprocess
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def _http_json(path: str, timeout: float = 0.6):
    """Tylko localhost: stan z ŻYWEJ usługi (bez tokenu z 127.0.0.1).
    Surowy socket zamiast http.client: import http.client/ssl/email to ~60 ms,
    a `state` ma być tani."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 7777), timeout=timeout) as sock:
            request = (
                f"GET {path} HTTP/1.0\r\n"
                "Host: 127.0.0.1:7777\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            chunks = []
            total = 0
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > 4 * 1024 * 1024:
                    break
        blob = b"".join(chunks)
        head, _, body = blob.partition(b"\r\n\r\n")
        if not head.startswith(b"HTTP/") or b" 200 " not in head.split(b"\r\n", 1)[0] + b" ":
            return None
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return None


def _which(name: str) -> str:
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder:
            continue
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def _human(payload, title: str = "") -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return (title + "\n" if title else "") + text


def _emit(payload, human: bool = False, title: str = "") -> None:
    if human:
        print(_human(payload, title))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _ok(payload: dict) -> dict:
    payload.setdefault("schema", 1)
    payload.setdefault("generated_at", _now_iso())
    return payload


# --- system / usługa -------------------------------------------------------

def _system_state() -> dict:
    uptime = 0.0
    try:
        uptime = float(_read_text(Path("/proc/uptime"), "0").split()[0])
    except (ValueError, IndexError):
        pass
    try:
        load = list(os.getloadavg())
    except (OSError, AttributeError):
        load = [0.0, 0.0, 0.0]
    mem = {}
    try:
        for line in _read_text(Path("/proc/meminfo")).splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                mem[key] = int(rest.strip().split()[0])
    except (ValueError, IndexError):
        pass
    total = mem.get("MemTotal") or 0
    available = mem.get("MemAvailable") or 0
    used_pct = round(100.0 * (total - available) / total, 1) if total else 0.0
    return {
        "uptime_s": int(uptime),
        "uptime": _duration(int(uptime)),
        "cpu_count": os.cpu_count() or 0,
        "loadavg": [round(x, 2) for x in load],
        "memory": {"total_kb": total, "available_kb": available, "used_pct": used_pct},
    }


def _service_state() -> dict:
    if not _which("systemctl"):
        return {"installed": False, "active": False, "state": "brak systemctl", "uptime_s": 0}
    rc, out, _err = _run(
        ["systemctl", "show", "gregai", "-p",
         "ActiveState,SubState,ActiveEnterTimestampMonotonic,MainPID", "--no-pager"],
        timeout=3,
    )
    if rc != 0:
        return {"installed": False, "active": False, "state": "brak usługi", "uptime_s": 0}
    props = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value.strip()
    state = props.get("ActiveState") or "?"
    active = state == "active"
    uptime_s = 0
    if active:
        try:
            boot = float(_read_text(Path("/proc/uptime"), "0").split()[0])
            entered = int(props.get("ActiveEnterTimestampMonotonic") or 0) / 1_000_000
            uptime_s = max(0, int(boot - entered))
        except (ValueError, IndexError):
            pass
    return {
        "installed": True,
        "active": active,
        "state": state,
        "substate": props.get("SubState") or "",
        "pid": int(props.get("MainPID") or 0),
        "uptime_s": uptime_s,
        "uptime": _duration(uptime_s),
    }


def _duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


# --- koryto ----------------------------------------------------------------

def _koryto_state() -> dict:
    info = _http_json("/api/system_info", timeout=0.5)
    if isinstance(info, dict) and isinstance(info.get("koryto"), dict):
        st = info["koryto"]
        providers = (info.get("juggler") or {}).get("providers") or {}
        last_error = ""
        for name, item in providers.items():
            breaker = (item or {}).get("bezpiecznik") or {}
            if breaker.get("stan") in ("cooldown", "wylaczony"):
                last_error = f"{name}: {breaker.get('powod', '')}"
                break
        return {
            "source": "service",
            "live": True,
            "order": st.get("kolejnosc") or [],
            "order_effective": st.get("efektywna") or {},
            "description": st.get("opis") or "",
            "local_mode": st.get("lokalnie") or "",
            "budgets": {"chain_s": st.get("budzet_s"), "message_s": st.get("budzet_wiadomosc_s")},
            "routing_network": st.get("routing_siecia"),
            "tasks_network": st.get("zadania_siecia"),
            "spent_usd": info.get("budzet") or {},
            "providers": providers,
            "last_error": last_error,
            "process": info.get("service") or {},
        }
    try:
        import juggler as juggler_mod
        import koryto as koryto_mod
        st = koryto_mod.status()
        spent = juggler_mod.spent_usd()
        providers = juggler_mod.status()
        last_error = ""
        for name, item in providers.items():
            breaker = (item or {}).get("bezpiecznik") or {}
            if breaker.get("stan") in ("cooldown", "wylaczony"):
                last_error = f"{name}: {breaker.get('powod', '')}"
                break
        return {
            "source": "config",
            "live": False,
            "order": st.get("kolejnosc") or [],
            "description": st.get("opis") or "",
            "local_mode": st.get("lokalnie") or "",
            "budgets": {"chain_s": st.get("budzet_s"), "message_s": st.get("budzet_wiadomosc_s")},
            "routing_network": st.get("routing_siecia"),
            "tasks_network": st.get("zadania_siecia"),
            "spent_usd": spent,
            "providers": providers,
            "last_error": last_error,
            "note": "usługa nie odpowiada: to stan konfiguracji, nie żywe bezpieczniki",
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _service_for(koryto: dict) -> dict:
    if koryto.get("source") == "service":
        proc = koryto.get("process") or {}
        if not proc:
            return _service_state()
        uptime_s = proc.get("uptime_s")
        return {
            "installed": True,
            "active": True,
            "state": "active",
            "substate": "running",
            "pid": proc.get("pid"),
            "uptime_s": uptime_s,
            "uptime": _duration(uptime_s) if isinstance(uptime_s, (int, float)) else "",
            "source": "service",
        }
    return _service_state()


# --- vault -----------------------------------------------------------------

def _vault_signature(roots: list[str]) -> str:
    parts: list[str] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "node_modules")
            for name in sorted(filenames):
                if Path(name).suffix.lower() not in (".md", ".txt", ".pdf"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return "\n".join(parts)


def _vault_state(orphans: bool = False, dups: bool = False, isolated: bool = False,
                 force: bool = False) -> dict:
    try:
        import data as data_mod
        roots = [str(p) for p in data_mod.get_vault_roots()]
        sig = ""
        if not force and not (orphans or dups or isolated):
            sig = _vault_signature(roots)
            cached = _read_json(VAULT_CACHE, None)
            if isinstance(cached, dict) and cached.get("sig") == sig and isinstance(cached.get("summary"), dict):
                return cached["summary"]
        import slowa as slowa_mod
        import vault as vault_mod
        v = vault_mod.build_vault(roots)
        notes = list(v.notes.values())
        try:
            degrees = v.degrees()
        except Exception:
            degrees = {}
        by_fold: dict[str, str] = {}
        by_file: dict[str, str] = {}
        for slug, note in v.notes.items():
            by_fold.setdefault(slowa_mod.fold(vault_mod.normalize_title(note.title)), slug)
            base = vault_mod.normalize_title(re.sub(r"\.(md|txt|pdf)$", "", slug, flags=re.I))
            by_file.setdefault(base, slug)
            by_file.setdefault(base.rsplit("/", 1)[-1], slug)

        edge_set = set()
        for note in notes:
            for target in note.links:
                edge_set.add(tuple(sorted((note.slug, target))))

        seen_titles: dict[str, list[dict]] = {}
        for note in notes:
            seen_titles.setdefault(vault_mod.normalize_title(note.title), []).append(
                {"slug": note.slug, "title": note.title})
        duplicate_groups = [group for group in seen_titles.values() if len(group) > 1]

        orphan_list = []
        for note in notes:
            for raw in note.raw_links:
                key = vault_mod.normalize_title(raw)
                target = (v.by_title.get(key) or by_fold.get(slowa_mod.fold(key))
                          or by_file.get(re.sub(r"\.(md|txt|pdf)$", "", key)))
                # [2026-11-11] (audyt MCP, #2): wisieniec to link, KTÓREGO nie
                # da się zawiązać (cel nie istnieje). Warunek był odwrócony:
                # liczył linki zawiązane pomyślnie (433 przy 0 prawdziwych
                # wisieńców), a zgliszcza "[[Nie ma takiej]]" zostawały
                # niewidoczne w health i gregai state --orphans.
                if target:
                    continue
                orphan_list.append({"source": note.slug, "title": note.title, "link": raw})
        isolated_list = [{"slug": n.slug, "title": n.title, "type": n.ntype}
                         for n in notes if not n.links and int(degrees.get(n.slug) or 0) == 0]
        mtimes = []
        for note in notes:
            try:
                mtimes.append(os.stat(note.path).st_mtime)
            except OSError:
                pass
        last_change = datetime.fromtimestamp(max(mtimes)).isoformat(timespec="seconds") if mtimes else ""
        out = {
            "roots": roots,
            "notes": len(notes),
            "edges": len(edge_set),
            "by_type": v.counts_by_type(),
            "last_change": last_change,
            "orphans": len(orphan_list),
            "duplicates": len(duplicate_groups),
            "isolated": len(isolated_list),
            "skipped": len(getattr(v, "skipped", []) or []),
            "errors": len(getattr(v, "errors", []) or []),
        }
        if orphans:
            out["orphan_list"] = orphan_list[:100]
        if dups:
            out["duplicate_groups"] = duplicate_groups[:100]
        if isolated:
            out["isolated_list"] = isolated_list[:100]
        if sig and not (orphans or dups or isolated):
            _write_json(VAULT_CACHE, {"sig": sig, "summary": out, "at": _now_iso()})
        return out
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# --- profil / dowęzłowywanie ----------------------------------------------

def _profile_state() -> dict:
    raw = _read_json(DATA / "profil.json", None)
    exists = isinstance(raw, dict)
    data = {}
    if exists:
        wrapper = raw if isinstance(raw, dict) else {}
        active = wrapper.get("aktualny") or "glowny"
        profiles = wrapper.get("profile") if isinstance(wrapper.get("profile"), dict) else {}
        data = profiles.get(active) if isinstance(profiles.get(active), dict) else {}
    styl = data.get("styl") if isinstance(data.get("styl"), dict) else {}
    return {
        "exists": exists,
        "ton": styl.get("ton") or "rzeczowy",
        "dlugosc": styl.get("dlugosc") or "krotka",
        "emoji": styl.get("emoji") or "rzadko",
        "cele": len((data.get("cele") or {}).get("lista") or []) if isinstance(data.get("cele"), dict) else 0,
        "tabu": len((data.get("tabu") or {}).get("lista") or []) if isinstance(data.get("tabu"), dict) else 0,
        "preferencje": len(data.get("preferencje") or []) if isinstance(data.get("preferencje"), list) else 0,
        "profil_do_sieci": bool((data.get("prywatnosc") or {}).get("profil_do_sieci")),
        "auto_dowezlywanie": bool((data.get("wierzchowanie") or {}).get("auto_dowezlywanie")),
    }


def _wezly_state() -> dict:
    state = _read_json(WEZLY_STATE, {})
    if not isinstance(state, dict):
        state = {}
    profile = _profile_state()
    off = os.environ.get("WEZLY_AUTO", "").strip().lower() in {"0", "off", "nie", "false", "no", "disable", "disabled"}
    cooldown_min = _env_int("WEZLY_AUTO_COOLDOWN_MIN", 15, 1, 1440)
    now = time.time()
    left = max(0, int(cooldown_min * 60 - (now - int(state.get("last_run_ts") or 0)))) if state.get("last_run_ts") else 0
    return {
        "enabled": bool(profile.get("auto_dowezlywanie")) and not off,
        "env_off": off,
        "max_run": _env_int("WEZLY_AUTO_MAX_RUN", 3, 1, 10),
        "max_day": _env_int("WEZLY_AUTO_MAX_DZIEN", 6, 1, 50),
        "cooldown_min": cooldown_min,
        "dzien": state.get("dzien"),
        "utworzone_dzis": state.get("utworzone_dzis", 0),
        "last_run": state.get("last_run") or "",
        "cooldown_left_s": left,
        "ostatnie": [
            {"slug": x.get("slug"), "title": x.get("title"), "type": x.get("type")}
            for x in (state.get("ostatnie") or [])[:5] if isinstance(x, dict)
        ],
        "odrzucone": len(state.get("odrzucone") or []),
    }


# --- .env ------------------------------------------------------------------

def _known_env_keys() -> set[str]:
    global _KNOWN_ENV_CACHE
    if _KNOWN_ENV_CACHE is not None:
        return _KNOWN_ENV_CACHE
    known: set[str] = set()
    example = _read_text(ROOT / ".env.example")
    for line in example.splitlines():
        match = re.match(r"\s*#?\s*(?:export\s+)?([A-Z][A-Z0-9_]+)\s*=", line)
        if match:
            known.add(match.group(1))
    pattern = re.compile(r'(?:environ(?:\.get)?\s*[\(\[]\s*["\']|env_(?:int|float|bool|str)\s*\(\s*["\'])([A-Z][A-Z0-9_]+)')
    for path in AGENT.glob("*.py"):
        try:
            known.update(pattern.findall(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    known.update({"GREGAI_LAN", "GREGAI_TOKEN", "GREGAI_USER_NAME", "GREGAI_CREATOR_NAME"})
    _KNOWN_ENV_CACHE = known
    return known


def _mask_env(key: str, value: str) -> str:
    if re.search(r"KEY|TOKEN|SECRET|PASS|PRIVATE", key, re.I) and value:
        return "***"
    return value


def _config_state(values: bool = True, deep: bool = True) -> dict:
    path = ROOT / ".env"
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""
    parsed: dict[str, str] = {}
    duplicates: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", text)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value[:1] == value[-1:] and value[:1] in ("'", '"'):
            value = value[1:-1]
        if key in parsed:
            duplicates.append({"key": key, "line": lineno})
        parsed[key] = value

    known = _known_env_keys() if deep else set()
    unknown = sorted(k for k in parsed if deep and k not in known and not k.startswith("GREGAI_"))
    errors: list[str] = []
    warnings: list[str] = []

    if not path.is_file():
        errors.append(".env nie istnieje")
    else:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            warnings.append(f".env ma prawa {oct(mode)[2:]}; zalecane 600")
    for item in duplicates:
        warnings.append(f"duplikat {item['key']} (linia {item['line']}); wygrywa ostatni")

    stages = [s.strip().lower() for s in re.split(r"[,\s]+", parsed.get("KORYTO", "")) if s.strip()]
    if stages:
        bad = [s for s in stages if s not in {"anthropic", "darmowe", "lokalnie"}]
        if bad:
            errors.append("KORYTO: nieznane etapy: " + ", ".join(bad))
    local_mode = parsed.get("KORYTO_LOKALNIE", "").strip().lower()
    if local_mode and local_mode not in ("bez_internetu", "zawsze"):
        errors.append("KORYTO_LOKALNIE: dozwolone bez_internetu albo zawsze")
    rozd = parsed.get("ROZDZIELNICA", "").strip()
    if rozd and rozd.lower() not in ("a", "b", "off", "0"):
        errors.append("ROZDZIELNICA: dozwolone A, B, off, 0")
    lan = parsed.get("GREGAI_LAN", "").strip()
    if lan and lan not in ("0", "1"):
        errors.append("GREGAI_LAN: dozwolone 0 albo 1")
    auto = parsed.get("WEZLY_AUTO", "").strip().lower()
    if auto and auto not in {"0", "off", "nie", "false", "no", "disable", "disabled"}:
        warnings.append("WEZLY_AUTO: tylko off ma działanie; włączenie jest w profilu")

    numeric = {
        "KORYTO_BUDZET_S": (int, 10, 3600),
        "KORYTO_BUDZET_WIADOMOSC_S": (int, 30, 7200),
        "KORYTO_BUDZET_DZIEN_USD": (float, 0, 100000),
        "KORYTO_BUDZET_MIESIAC_USD": (float, 0, 100000),
        "CLOUD_DAILY_LIMIT": (int, 0, 1000000),
        "WEZLY_AUTO_MAX_RUN": (int, 1, 10),
        "WEZLY_AUTO_MAX_DZIEN": (int, 1, 50),
        "WEZLY_AUTO_COOLDOWN_MIN": (int, 1, 1440),
        "LOCAL_SYSTEM_MAX": (int, 200, 4000),
        "OLLAMA_QUEUE_TIMEOUT": (int, 1, 3600),
    }
    for key, (kind, low, high) in numeric.items():
        if key not in parsed:
            continue
        try:
            number = kind(parsed[key])
        except ValueError:
            errors.append(f"{key}: oczekiwano liczby, jest {parsed[key]!r}")
            continue
        if not (low <= number <= high):
            errors.append(f"{key}: {number} poza zakresem {low}-{high}")

    out = {
        "ok": not errors,
        "env_exists": path.is_file(),
        "mode": oct(path.stat().st_mode & 0o777)[2:] if path.is_file() else "",
        "keys": len(parsed),
        "duplicates": duplicates,
        "unknown": unknown,
        "errors": errors,
        "warnings": warnings,
    }
    if values:
        out["values"] = {k: _mask_env(k, v) for k, v in sorted(parsed.items())}
    return out


# --- Namysł ----------------------------------------------------------------

def _namysl_state() -> dict:
    settings = _read_json(DATA / "namysl.json", {}) or {}
    try:
        import koryto as koryto_mod
        stages = koryto_mod.namysl_stages()
    except Exception:
        stages = []
    last = []
    entries = _read_json(DATA / "decision_log.json", [])
    if isinstance(entries, list):
        for entry in reversed(entries[-200:]):
            if not isinstance(entry, dict):
                continue
            stage = str(entry.get("stage") or "")
            if "namysl" in stage.lower() or "namysł" in stage.lower():
                last.append({k: entry.get(k) for k in ("ts", "stage", "tool", "took_ms")})
                if len(last) >= 10:
                    break
    return {
        "settings": {"material_do_sieci": bool(settings.get("material_do_sieci")), "tryb": settings.get("tryb") or "zawsze"},
        "model": os.environ.get("NAMYSL_MODEL", ""),
        "stages": stages,
        "last": last,
    }


def _straz_state() -> dict:
    """1.45.7: diagnostyka Straży bez zmiany jej stanu (tylko odczyt plików)."""
    import straz as straz_mod

    ver = _version()
    base = _read_json(straz_mod.BASELINE_PATH, {}) or {}
    anchor = _read_json(straz_mod._ANCHOR_PATH, {}) or {}
    # Kotwica i baza są 0600 użytkownika usługi - człowiek ich nie odczyta.
    # Preferuj metadane z żywej usługi (/api/system_info), a pliki zostaw
    # jako fallback dla instalacji zatrzymanej.
    live: dict = {}
    try:
        info = _http_json("/api/system_info", timeout=2.0)
        if isinstance(info, dict) and isinstance(info.get("straz"), dict):
            live = info["straz"]
    except Exception:
        live = {}
    if isinstance(live.get("baza"), dict):
        base = dict(base)
        if live["baza"].get("wersja"):
            base["wersja"] = live["baza"]["wersja"]
    if isinstance(live.get("kotwica"), dict):
        anchor = dict(anchor)
        if live["kotwica"].get("wersja"):
            anchor["wersja"] = live["kotwica"]["wersja"]
        if live["kotwica"].get("manifest_h"):
            anchor["manifest_h"] = live["kotwica"]["manifest_h"]
        if isinstance(live["kotwica"].get("akceptowane"), dict):
            anchor["pieczec_akceptowane"] = {
                "wersja": live["kotwica"].get("akceptowane_wersja") or live["kotwica"].get("wersja") or "",
                "pliki": live["kotwica"]["akceptowane"],
            }
    base_files = base.get("pliki") if isinstance(base.get("pliki"), dict) else {}
    base_count = len(base_files)
    if isinstance(live.get("baza"), dict) and live["baza"].get("plikow") is not None:
        base_count = int(live["baza"].get("plikow") or 0)
    accepted = anchor.get("pieczec_akceptowane") if isinstance(anchor.get("pieczec_akceptowane"), dict) else {}
    try:
        manifest = straz_mod._manifest()
    except Exception:
        manifest = {}
    mismatch: list[str] = []
    missing: list[str] = []
    accepted_names: list[str] = []
    accepted_map = accepted.get("pliki") if isinstance(accepted.get("pliki"), dict) else {}
    if accepted.get("wersja") != ver:
        accepted_map = {}
    for name, want in manifest.items():
        got = straz_mod._sha(straz_mod.ROOT / name)
        if not got:
            missing.append(name)
        elif got != want:
            if accepted_map.get(name) == got:
                accepted_names.append(name)
            else:
                mismatch.append(name)
    try:
        mtime = datetime.fromtimestamp(straz_mod.BASELINE_PATH.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        mtime = None
    alerts_24h = 0
    cut = time.time() - 86400
    for entry in straz_mod.history(200):
        try:
            when = datetime.strptime(str(entry.get("ts") or "")[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except ValueError:
            continue
        if when >= cut:
            alerts_24h += 1
    muted = sorted(live.get("wyciszone") or straz_mod.muted_types())
    if not manifest:
        pieczec = "manifest_brak"
    elif mismatch or missing:
        pieczec = "mismatch"
    elif accepted_names:
        pieczec = "rebaseline"
    elif (straz_mod.ROOT / "GREGAI.sha256.asc").is_file():
        pieczec = "podpisany"
    else:
        pieczec = "dev"
    return {
        "wlaczona": os.environ.get("STRAZ", "1") != "0",
        "co_s": straz_mod.CO_S,
        "wersja_plik": ver,
        "wersja_baza": str(base.get("wersja") or ""),
        "wersja_kotwica": str(anchor.get("wersja") or ""),
        "zrodlo": "usługa" if (isinstance(live.get("kotwica"), dict) or isinstance(live.get("baza"), dict)) else "pliki",
        "baseline": {"exists": straz_mod.BASELINE_PATH.is_file(), "mtime": mtime,
                     "plikow": base_count, "portow": len(base.get("porty") or [])},
        "kotwica": {"exists": straz_mod._ANCHOR_PATH.is_file() or bool(live),
                    "manifest_h": str(anchor.get("manifest_h") or "")[:16],
                    "akceptowane_pliki": len(accepted.get("pliki") or {})},
        "pieczec": {"stan": pieczec, "plikow_w_manifescie": len(manifest),
                    "mismatch": len(mismatch), "brakujace": len(missing),
                    "zaakceptowane": len(accepted_names),
                    "przyklady": (mismatch + missing + accepted_names)[:5],
                    "manifest_h": str(straz_mod._manifest_hash() or "")[:16]},
        "dedup": {"wpisy": int(live.get("dedup_wpisy")) if isinstance(live.get("dedup_wpisy"), int) else straz_mod.seen_count(),
                  "ttl_h": straz_mod.SEEN_TTL_S // 3600},
        "wyciszone": {"typy": muted, "cooldown_aktywny": bool(muted),
                      "ttl_h": straz_mod.MUTE_TTL_S // 3600},
        "alerty_24h": alerts_24h,
        "zakres": list(straz_mod.ALERTS_SCOPE),
        "wykluczenia": list(straz_mod.ALERTS_EXCLUDE),
    }


# --- state -----------------------------------------------------------------

def _state_payload() -> dict:
    koryto = _koryto_state()
    payload = {
        "schema": 1,
        "generated_at": _now_iso(),
        "version": _version(),
        "root": str(ROOT),
        "service": _service_for(koryto),
        "system": _system_state(),
        "config": {k: v for k, v in _config_state(values=False, deep=False).items()
                   if k in ("ok", "env_exists", "mode", "keys", "errors", "warnings")},
        "koryto": koryto,
        "vault": _vault_state(),
        "profil": _profile_state(),
        "wezly": _wezly_state(),
        "namysl": _namysl_state(),
    }
    return payload


def _diff_values(before: dict, after: dict) -> dict:
    changed, added, removed = {}, {}, {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, "<brak>"), after.get(key, "<brak>")
        if old == new:
            continue
        if isinstance(old, (dict, list)) or isinstance(new, (dict, list)):
            if isinstance(old, dict) and isinstance(new, dict):
                nested = _diff_values(old, new)
                if nested:
                    changed[key] = nested
            else:
                changed[key] = {"before": old, "after": new}
        elif old == "<brak>":
            added[key] = new
        elif new == "<brak>":
            removed[key] = old
        else:
            changed[key] = {"before": old, "after": new}
    return {k: v for k, v in (("changed", changed), ("added", added), ("removed", removed)) if v}


def _comparable(payload: dict) -> dict:
    """Kopia do --diff bez pól, które zmieniają się przy każdym odczycie."""
    import copy
    clean = copy.deepcopy(payload)
    clean.pop("generated_at", None)
    clean.pop("diff", None)
    system = clean.get("system") if isinstance(clean.get("system"), dict) else {}
    for key in ("memory", "loadavg", "uptime_s"):
        system.pop(key, None)
    service = clean.get("service") if isinstance(clean.get("service"), dict) else {}
    for key in ("uptime_s", "uptime"):
        service.pop(key, None)
    wezly = clean.get("wezly") if isinstance(clean.get("wezly"), dict) else {}
    wezly.pop("cooldown_left_s", None)
    providers = ((clean.get("koryto") or {}).get("providers") or {})
    if isinstance(providers, dict):
        for item in providers.values():
            if isinstance(item, dict):
                item.pop("today_calls", None)
    return clean


def _state(flags: list[str]) -> int:
    human = "--human" in flags
    diff = "--diff" in flags
    snapshot = _state_payload()
    payload = snapshot
    if diff:
        before = _read_json(STATE_LAST, None)
        if isinstance(before, dict):
            payload = dict(snapshot)
            payload["diff"] = _diff_values(_comparable(before), _comparable(snapshot)) or {"changed": {}}
        else:
            payload = dict(snapshot)
            payload["diff"] = {"first_run": True}
    _write_json(STATE_LAST, snapshot)
    _emit(_ok(payload), human, "GREGAI state")
    return 0


# --- diag ------------------------------------------------------------------

def _diag_koryto(flags: list[str], human: bool) -> int:
    payload = _ok({"module": "koryto", **_koryto_state()})
    if "--test" in flags:
        tests = []
        try:
            import juggler as juggler_mod
            for name, item in (payload.get("providers") or {}).items():
                if not isinstance(item, dict) or not item.get("key_present") or not item.get("w_korycie"):
                    continue
                started = time.monotonic()
                try:
                    text, who = juggler_mod.chat(
                        "Odpowiedz dokładnie jednym słowem: OK",
                        [], "Odpowiedz dokładnie jednym słowem: OK",
                        timeout=20, only_provider=name, max_tokens=16,
                    )
                    tests.append({"name": name, "ok": bool(text), "latency_ms": int((time.monotonic() - started) * 1000),
                                  "answer": str(text or "")[:80], "provider": who})
                except Exception as exc:
                    tests.append({"name": name, "ok": False,
                                  "latency_ms": int((time.monotonic() - started) * 1000),
                                  "error": f"{type(exc).__name__}: {exc}"[:240]})
        except Exception as exc:
            tests.append({"name": "koryto", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        try:
            import koryto as koryto_mod
            import router as router_mod
            if "lokalnie" in koryto_mod.order() and router_mod.ollama_available():
                started = time.monotonic()
                try:
                    text = router_mod._ollama_chat("Odpowiedz dokładnie jednym słowem: OK", [], "OK",
                                                   timeout=30, num_predict=8)
                    tests.append({"name": "lokalnie", "ok": bool(text),
                                  "latency_ms": int((time.monotonic() - started) * 1000),
                                  "answer": str(text or "")[:80]})
                except Exception as exc:
                    tests.append({"name": "lokalnie", "ok": False,
                                  "latency_ms": int((time.monotonic() - started) * 1000),
                                  "error": f"{type(exc).__name__}: {exc}"[:240]})
        except Exception:
            pass
        payload["tests"] = tests
    _emit(payload, human, "GREGAI diag koryto")
    return 0


def _diag_vault(flags: list[str], human: bool) -> int:
    payload = _ok({
        "module": "vault",
        **_vault_state(orphans="--orphans" in flags, dups="--dups" in flags, isolated="--isolated" in flags, force=True),
    })
    _emit(payload, human, "GREGAI diag vault")
    return 0


def _diag_profil(flags: list[str], human: bool) -> int:
    import profil as profil_mod
    problems: list[str] = []
    warnings: list[str] = []
    raw = _read_json(profil_mod.PATH, None)
    if raw is None:
        payload = {"module": "profil", "ok": True, "exists": False,
                   "note": "brak profilu - onboarding pokaże się przy następnym wejściu"}
        _emit(_ok(payload), human, "GREGAI diag profil")
        return 0
    wrapper = raw if isinstance(raw, dict) else {}
    active = wrapper.get("aktualny") or "glowny"
    profiles = wrapper.get("profile") if isinstance(wrapper.get("profile"), dict) else {}
    data = profiles.get(active)
    if not isinstance(data, dict):
        problems.append("brak aktywnego profilu w JSON")
        data = {}
    default = profil_mod.default_profile()
    missing = sorted(set(default) - set(data))
    extra = sorted(set(data) - set(default))
    if missing:
        warnings.append("brakujące pola (uzupełnią się przy następnym zapisie): " + ", ".join(missing))
    for key in ("tozsamosc", "styl", "cele", "tabu", "inwestowanie", "sysop", "prywatnosc", "wierzchowanie"):
        if key in data and not isinstance(data.get(key), dict):
            problems.append(f"{key}: oczekiwano obiektu")
    for key in ("preferencje", "zainteresowania"):
        if key in data and not isinstance(data.get(key), list):
            problems.append(f"{key}: oczekiwano listy")
    for key in ("profil_do_sieci", "auto_dowezlywanie"):
        section = "prywatnosc" if key == "profil_do_sieci" else "wierzchowanie"
        value = (data.get(section) or {}).get(key)
        if value is not None and not isinstance(value, bool):
            problems.append(f"{section}.{key}: oczekiwano true/false")
    payload = {
        "module": "profil",
        "ok": not problems,
        "exists": True,
        "schema": wrapper.get("schema"),
        "active": active,
        "missing": missing,
        "extra": extra,
        "problems": problems,
        "warnings": warnings,
        "sanitized": profil_mod.get(),
    }
    _emit(_ok(payload), human, "GREGAI diag profil")
    return 0


def _diag_wezly(flags: list[str], human: bool) -> int:
    payload = _ok({"module": "wezly", **_wezly_state()})
    _emit(payload, human, "GREGAI diag wezly")
    return 0


def _diag_config(flags: list[str], human: bool) -> int:
    payload = _ok({"module": "config", **_config_state(values=True)})
    _emit(payload, human, "GREGAI diag config")
    return 0


def _diag_namysl(flags: list[str], human: bool) -> int:
    payload = _ok({"module": "namysl", **_namysl_state()})
    _emit(payload, human, "GREGAI diag namysl")
    return 0


def _diag_straz(flags: list[str], human: bool) -> int:
    payload = _ok({"module": "straz", **_straz_state()})
    _emit(payload, human, "GREGAI diag straz")
    return 0


def _diag(flags: list[str]) -> int:
    human = "--human" in flags
    words = [x for x in flags if not x.startswith("-")]
    module = words[0].lower() if words else "all"
    handlers = {
        "koryto": _diag_koryto,
        "vault": _diag_vault,
        "profil": _diag_profil,
        "wezly": _diag_wezly,
        "config": _diag_config,
        "namysl": _diag_namysl,
        "straz": _diag_straz,
    }
    if module in handlers:
        return handlers[module](flags, human)
    if module == "all":
        payload = _ok({
            "schema": 1,
            "module": "all",
            "state": _state_payload(),
            "vault": _vault_state(),
            "profil": _profile_state(),
            "wezly": _wezly_state(),
            "config": _config_state(values=False),
            "namysl": _namysl_state(),
            "straz": _straz_state(),
        })
        _emit(payload, human, "GREGAI diag all")
        return 0
    _emit(_ok({"ok": False, "error": f"nieznany moduł: {module}",
               "modules": sorted(handlers) + ["all"]}), human)
    return 2


# --- impact ----------------------------------------------------------------

def _python_files() -> list[Path]:
    out = []
    for folder in (AGENT, ROOT / "training"):
        for path in sorted(folder.rglob("*.py")):
            if "__pycache__" in path.parts or ".work" in path.parts:
                continue
            out.append(path)
    return out


def _module_name(path: Path) -> str:
    try:
        rel = path.relative_to(AGENT)
        return rel.with_suffix("").as_posix().replace("/", ".").removesuffix(".__init__")
    except ValueError:
        return path.stem


def _imports_of(path: Path) -> set[str]:
    import ast
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except (SyntaxError, UnicodeError):
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _impact_file(target: str, human: bool) -> int:
    path = (ROOT / target).resolve()
    if not path.exists():
        _emit(_ok({"ok": False, "error": f"nie ma pliku: {target}"}), human)
        return 1
    module = _module_name(path) if path.suffix == ".py" and AGENT in path.parents else path.stem
    importers = []
    for candidate in _python_files():
        if candidate == path:
            continue
        if module in _imports_of(candidate):
            importers.append(str(candidate.relative_to(ROOT)))
    refs = []
    pattern = re.compile(re.escape(path.name), re.IGNORECASE)
    for candidate in list(UI.glob("*")) + [ROOT / "check.sh", ROOT / "gregai"]:
        if not candidate.is_file():
            continue
        try:
            for lineno, line in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if pattern.search(line):
                    refs.append({"file": str(candidate.relative_to(ROOT)), "line": lineno, "text": line.strip()[:200]})
        except OSError:
            continue
    payload = _ok({
        "ok": True,
        "kind": "file",
        "target": str(path.relative_to(ROOT)),
        "module": module,
        "imported_by": importers,
        "references": refs[:100],
    })
    _emit(payload, human, f"GREGAI impact {target}")
    return 0


def _impact_symbol(symbol: str, human: bool) -> int:
    import ast
    definitions, calls = [], []
    for path in _python_files():
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, str(path))
        except (OSError, SyntaxError, UnicodeError):
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                definitions.append({"file": str(path.relative_to(ROOT)), "line": node.lineno, "kind": type(node).__name__})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
                if name == symbol:
                    calls.append({"file": str(path.relative_to(ROOT)), "line": node.lineno,
                                  "text": lines[node.lineno - 1].strip()[:200] if node.lineno <= len(lines) else ""})
    js_refs = []
    for path in sorted(UI.glob("*.js")):
        try:
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if symbol in line:
                    js_refs.append({"file": str(path.relative_to(ROOT)), "line": lineno, "text": line.strip()[:200]})
        except OSError:
            continue
    payload = _ok({"ok": True, "kind": "symbol", "symbol": symbol,
                   "definitions": definitions, "calls": calls[:200], "ui_references": js_refs[:100]})
    _emit(payload, human, f"GREGAI impact {symbol}")
    return 0


def _impact_css(class_name: str, human: bool) -> int:
    name = class_name.lstrip(".")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
        _emit(_ok({"ok": False, "error": "podaj nazwę klasy, np. --css panel"}), human)
        return 2
    css_re = re.compile(r"\." + re.escape(name) + r"(?![\w-])")
    html_re = re.compile(r"class\s*=\s*[\"'][^\"']*\b" + re.escape(name) + r"\b", re.I)
    js_re = re.compile(r"(?:classList\.(?:add|remove|toggle|contains)\s*\(\s*[\"']" + re.escape(name) + r"[\"']|\bclassName\b[^\n]*\b" + re.escape(name) + r"\b)")
    hits = []
    for path in sorted(list(UI.glob("*.css")) + list(UI.glob("*.js")) + list(UI.glob("*.html"))):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            match = False
            if path.suffix == ".css":
                match = bool(css_re.search(line))
            elif path.suffix == ".html":
                match = bool(html_re.search(line))
            else:
                match = bool(js_re.search(line)) or bool(css_re.search(line))
            if match:
                hits.append({"file": str(path.relative_to(ROOT)), "line": lineno, "text": line.strip()[:200]})
    payload = _ok({"ok": True, "kind": "css-class", "class": "." + name,
                   "count": len(hits), "hits": hits[:300]})
    _emit(payload, human, f"GREGAI impact --css .{name}")
    return 0


def _impact(flags: list[str]) -> int:
    human = "--human" in flags
    css = None
    if "--css" in flags:
        idx = flags.index("--css")
        if idx + 1 < len(flags):
            css = flags[idx + 1]
    words = [x for x in flags if not x.startswith("-") and x != css]
    if css:
        return _impact_css(css, human)
    if not words:
        _emit(_ok({"ok": False, "error": "podaj plik, funkcję albo --css <klasa>"}), human)
        return 2
    target = words[0]
    path = (ROOT / target)
    if path.is_file() or (ROOT / target).is_file():
        return _impact_file(target, human)
    return _impact_symbol(target, human)


# --- tokens ----------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def _tokens(flags: list[str]) -> int:
    human = "--human" in flags
    budget_only = "--budget" in flags
    per_phase = "--per-phase" in flags
    today_local = date.today().isoformat()
    journal = _read_json(_journal_path(), {}) or {}
    spend = _load_jsonl(SPEND_LOG)
    local = _load_jsonl(OLLAMA_LOG)

    spend_by_model: dict[str, dict] = {}
    spend_today = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "usd": 0.0, "calls": 0}
    for rec in spend:
        ts = str(rec.get("ts") or "")
        if not ts.startswith(today_local):
            continue
        inp = int(rec.get("wejscie") or 0)
        out = int(rec.get("wyjscie") or 0)
        cw = int(rec.get("cache_w") or 0)
        cr = int(rec.get("cache_r") or 0)
        usd = float(rec.get("usd") or 0)
        model = str(rec.get("model") or "?")
        spend_today["input"] += inp
        spend_today["output"] += out
        spend_today["cache_write"] += cw
        spend_today["cache_read"] += cr
        spend_today["usd"] += usd
        spend_today["calls"] += 1
        slot = spend_by_model.setdefault(model, {"input": 0, "output": 0, "usd": 0.0, "calls": 0})
        slot["input"] += inp
        slot["output"] += out
        slot["usd"] += usd
        slot["calls"] += 1

    local_today = {"tokens": 0, "seconds": 0.0, "calls": 0}
    local_by_model: dict[str, dict] = {}
    for rec in local:
        ts = str(rec.get("ts") or "")
        if not ts.startswith(today_local):
            continue
        tokens = int(rec.get("tokeny") or 0)
        seconds = float(rec.get("sekund") or 0)
        model = str(rec.get("model") or "?")
        local_today["tokens"] += tokens
        local_today["seconds"] += seconds
        local_today["calls"] += 1
        slot = local_by_model.setdefault(model, {"tokens": 0, "seconds": 0.0, "calls": 0})
        slot["tokens"] += tokens
        slot["seconds"] += seconds
        slot["calls"] += 1

    budget = None
    try:
        import juggler as juggler_mod
        budget = juggler_mod.spent_usd()
    except Exception:
        pass

    payload = _ok({
        "ok": True,
        "day": today_local,
        "koryto": {
            "journal": journal,
            "calls": journal.get("wywolania") or {},
            "spend_today": spend_today,
            "by_model": spend_by_model,
        },
        "local": {"today": local_today, "by_model": local_by_model},
        "budget": budget,
    })
    if budget_only:
        payload = _ok({"ok": True, "day": today_local, "budget": budget,
                       "journal": journal})
    if per_phase:
        phases: dict[str, dict] = {}
        try:
            import trace as trace_mod
            for entry in trace_mod.recent(500):
                extra = entry.get("extra") or {}
                for item in (extra.get("namysl_fazy") or []):
                    text = str(item)
                    parts = text.split(":")
                    name = parts[0] if parts else text
                    seconds = 0.0
                    try:
                        seconds = float((parts[2] if len(parts) > 2 else "0").replace("s", ""))
                    except ValueError:
                        pass
                    slot = phases.setdefault(name, {"count": 0, "seconds": 0.0, "providers": {}})
                    slot["count"] += 1
                    slot["seconds"] += seconds
                    provider = parts[1] if len(parts) > 1 else "?"
                    slot["providers"][provider] = slot["providers"].get(provider, 0) + 1
        except Exception:
            pass
        payload["per_phase"] = {"phases": phases,
                                "tokens_available": False,
                                "note": "dziennik decyzji nie zapisuje tokenów per faza"}
    _emit(payload, human, "GREGAI tokens")
    return 0


# --- reset ----------------------------------------------------------------

def _reset(flags: list[str]) -> int:
    human = "--human" in flags
    words = [x for x in flags if not x.startswith("-")]
    what = words[0].lower() if words else ""
    if what not in ("wezly", "cooldown"):
        _emit(_ok({"ok": False, "error": "użyj: reset wezly | reset cooldown"}), human)
        return 2
    state = _read_json(WEZLY_STATE, {})
    if not isinstance(state, dict):
        state = {}
    before = {"utworzone_dzis": state.get("utworzone_dzis", 0),
              "last_run_ts": state.get("last_run_ts", 0),
              "runs": len(state.get("runs") or {})}
    if what == "wezly":
        state["utworzone_dzis"] = 0
        state["last_run_ts"] = 0
        state["runs"] = {}
    else:
        state["last_run_ts"] = 0
        state["runs"] = {}
    try:
        import fsutil as fsutil_mod
        fsutil_mod.atomic_write_text(WEZLY_STATE, json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as exc:
        _emit(_ok({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), human)
        return 1
    payload = _ok({"ok": True, "reset": what, "before": before,
                   "after": {"utworzone_dzis": state.get("utworzone_dzis", 0),
                             "last_run_ts": state.get("last_run_ts", 0)},
                   "note": "liczniki zmienione; węzły i pliki nietknięte"})
    _emit(payload, human, "GREGAI reset")
    return 0


# --- log ------------------------------------------------------------------

def _log(flags: list[str]) -> int:
    human = "--human" in flags
    tail = 50
    filt = ""
    level = "all"
    for i, flag in enumerate(flags):
        if flag == "--tail" and i + 1 < len(flags):
            try:
                tail = max(1, min(1000, int(flags[i + 1])))
            except ValueError:
                tail = 50
        elif flag == "--filter" and i + 1 < len(flags):
            filt = flags[i + 1]
        elif flag == "--level" and i + 1 < len(flags):
            level = flags[i + 1].lower()
    if not _which("journalctl"):
        _emit(_ok({"ok": False, "error": "brak journalctl", "lines": []}), human)
        return 1
    rc, out, err = _run(
        ["journalctl", "-u", "gregai", "-n", str(tail), "--no-pager", "-o", "short-iso"],
        timeout=6,
    )
    if rc != 0:
        _emit(_ok({"ok": False, "error": (err or out or "brak dostępu").strip()[:300],
                   "hint": "spróbuj w terminalu z dostępem do dziennika (sudo journalctl -u gregai)",
                   "lines": []}), human)
        return 1
    patterns = {
        "all": None,
        "err": re.compile(r"error|błąd|blad|exception|traceback|critical|failed|nie udało", re.I),
        "warn": re.compile(r"warn|uwaga|ostrzeż|deprecat", re.I),
    }
    needle = patterns.get(level, patterns["all"])
    lines = []
    for line in out.splitlines():
        if filt and filt.lower() not in line.lower():
            continue
        if needle and not needle.search(line):
            continue
        lines.append(line)
    payload = _ok({"ok": True, "source": "journalctl", "tail": tail, "filter": filt,
                   "level": level, "count": len(lines), "lines": lines})
    if human:
        print("\n".join(lines) if lines else "(brak pasujących linii)")
    else:
        _emit(payload)
    return 0


# --- verify ----------------------------------------------------------------

def _changed_files() -> list[Path]:
    files = []
    try:
        rc, out, _ = _run(["git", "-C", str(ROOT), "status", "--porcelain"], timeout=5)
        if rc == 0:
            for line in out.splitlines():
                if len(line) < 4:
                    continue
                text = line[3:].strip()
                if " -> " in text:
                    text = text.split(" -> ", 1)[1]
                path = ROOT / text
                if path.is_file():
                    files.append(path)
    except Exception:
        pass
    if not files:
        files = [p for p in _python_files()]
    return files


def _quick_check_file(path: Path) -> dict:
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    if path.suffix == ".py":
        import ast
        try:
            ast.parse(path.read_bytes(), rel)
            return {"file": rel, "ok": True, "check": "python-ast"}
        except (SyntaxError, UnicodeError) as exc:
            return {"file": rel, "ok": False, "check": "python-ast", "error": str(exc)}
    if path.suffix == ".sh" or path.name == "gregai":
        rc, _out, err = _run(["bash", "-n", str(path)], timeout=10)
        return {"file": rel, "ok": rc == 0, "check": "bash-n", "error": err.strip()[:300] if rc else ""}
    if path.suffix == ".js":
        if _which("node"):
            rc, _out, err = _run(["node", "--check", str(path)], timeout=15)
            return {"file": rel, "ok": rc == 0, "check": "node --check", "error": err.strip()[:300] if rc else ""}
        return {"file": rel, "ok": True, "check": "js", "skipped": "brak node"}
    if path.suffix == ".css":
        text = _read_text(path)
        depth = 0
        ok = True
        for ch in text:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    ok = False
                    break
        return {"file": rel, "ok": ok and depth == 0, "check": "css-braces"}
    return {"file": rel, "ok": True, "check": "pominięto"}


def _verify(flags: list[str]) -> int:
    human = "--human" in flags
    if "--quick" not in flags and "--diff" not in flags:
        _emit(_ok({"ok": False, "error": "użyj: verify --quick | verify --diff"}), human)
        return 2
    changed = _changed_files()
    checks = [_quick_check_file(p) for p in changed]
    version = _version()
    readme = _read_text(ROOT / "README.md").splitlines()
    changelog = _read_text(ROOT / "CHANGELOG.md").splitlines()
    readme_version = ""
    for line in readme[:10]:
        m = re.match(r"#\s+GREGAI\s+(\S+)", line)
        if m:
            readme_version = m.group(1)
            break
    changelog_version = ""
    for line in changelog[:30]:
        m = re.match(r"##\s+Co nowego w\s+(\S+)", line)
        if m:
            changelog_version = m.group(1)
            break
    docs_ok = readme_version == version and changelog_version == version
    if not docs_ok:
        checks.append({"file": "VERSION/README/CHANGELOG", "ok": False, "check": "wersje",
                       "error": f"VERSION={version}, README={readme_version or '?'}, CHANGELOG={changelog_version or '?'}"})
    payload = _ok({
        "ok": docs_ok and all(item.get("ok", True) for item in checks),
        "mode": "quick",
        "changed": [str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p) for p in changed],
        "checks": checks,
        "docs_version": {"version": version, "readme": readme_version, "changelog": changelog_version},
        "note": "to składnia i wersje, nie pełny check.sh",
    })
    if "--diff" in flags:
        before = _read_json(VERIFY_LAST, {})
        old = set((before or {}).get("changed") or [])
        new = set(payload["changed"])
        payload["diff"] = {"added": sorted(new - old), "removed": sorted(old - new),
                           "kind": "pliki od ostatniego verify"}
    _write_json(VERIFY_LAST, {"changed": payload["changed"], "at": _now_iso(), "ok": payload["ok"]})
    _emit(payload, human, "GREGAI verify")
    return 0 if payload["ok"] else 1


# --- health ----------------------------------------------------------------

_KNOWN_ENV_CACHE: set[str] | None = None
_HEALTH_CACHE = {"at": 0.0, "payload": None}


def health_payload() -> dict:
    now = time.monotonic()
    if _HEALTH_CACHE["payload"] is not None and now - _HEALTH_CACHE["at"] < 2.0:
        return _HEALTH_CACHE["payload"]
    vault = _vault_state()
    koryto = _koryto_state()
    providers = []
    for name, item in (koryto.get("providers") or {}).items():
        if not isinstance(item, dict):
            continue
        providers.append({
            "name": name,
            "enabled": bool(item.get("enabled")),
            "key_present": bool(item.get("key_present")),
            "calls_today": item.get("today_calls"),
            "daily_limit": item.get("daily_limit"),
            "state": (item.get("bezpiecznik") or {}).get("stan", "?"),
            "reason": (item.get("bezpiecznik") or {}).get("powod", ""),
        })
    service = _service_for(koryto)
    payload = {
        "ok": service.get("active", False) and not vault.get("error"),
        "generated_at": _now_iso(),
        "version": _version(),
        "service": service,
        "system": _system_state(),
        "koryto": {
            "order": koryto.get("order", []),
            "local_mode": koryto.get("local_mode", ""),
            "spent_usd": koryto.get("spent_usd"),
            "providers": providers,
        },
        "vault": {k: vault.get(k) for k in ("notes", "edges", "orphans", "duplicates", "isolated", "last_change", "error") if k in vault},
        "wezly": _wezly_state(),
        "profil": _profile_state(),
    }
    _HEALTH_CACHE.update(at=now, payload=payload)
    return payload


# --- dispatch --------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("ops.py: state | diag | impact | tokens | reset | log | verify | health")
        return 2
    cmd, rest = args[0].lower(), args[1:]
    if cmd == "state":
        return _state(rest)
    if cmd in ("diag", "diagnostyka"):
        return _diag(rest)
    if cmd == "impact":
        return _impact(rest)
    if cmd in ("tokens", "tokeny"):
        return _tokens(rest)
    if cmd == "reset":
        return _reset(rest)
    if cmd in ("log", "logs"):
        return _log(rest)
    if cmd == "verify":
        return _verify(rest)
    if cmd == "health":
        _emit(_ok(health_payload()), "--human" in rest, "GREGAI health")
        return 0
    print(json.dumps({"ok": False, "error": f"nieznane polecenie: {cmd}"}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
