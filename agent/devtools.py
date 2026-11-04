"""Narzędzia deweloperskie wywoływane z rozmowy (bez terminala).

Wszystko tutaj jest tylko do odczytu albo uruchamia istniejące, lokalne
testy. Żadna funkcja nie zmienia plików systemowych, .env ani kodu.
Polecenia idą przez sysop.run_cmd: bez shella, z limitem czasu, maskowaniem
sekretów i obcięciem wyjścia.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _run(argv: list[str], timeout: int = 120) -> dict:
    import sysop
    return sysop.run_cmd(argv, timeout=timeout, tail=True)


def _result(speech: str, ok: bool, **extra) -> dict:
    out = {"speech": speech, "card": None, "ok": ok}
    out.update(extra)
    return out


def _output(result: dict) -> str:
    parts = [str(result.get("out") or "").strip(), str(result.get("err") or "").strip()]
    text = "\n".join(p for p in parts if p)
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def run_eval(live: bool = False) -> dict:
    """Uruchom gregai eval. Domyślnie offline i bez zapisu historii."""
    argv = [_python(), str(ROOT / "agent" / "ewaluacja.py"), "--bez-zapisu"]
    if live:
        argv += ["--zywo", "--k", "3"]
    res = _run(argv, timeout=900 if live else 180)
    body = _output(res) or "(brak wyjścia)"
    label = "na żywo" if live else "offline"
    ok = res.get("rc") == 0
    return _result(f"Ewaluacja GREGAI ({label}), kod {res.get('rc')}:\n{body}", ok)


def _env_value(key: str) -> str:
    """Wartość klucza z .env. Duplikat: wygrywa OSTATNI wpis - tak samo jak
    env_loader.load_env() i install.sh/envval (1.32.29, audyt #12)."""
    path = ROOT / ".env"
    value = ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(rf"\s*(?:export\s+)?{re.escape(key)}\s*=\s*(.*)", line)
            if match:
                value = match.group(1).strip().strip("\"'")
    except OSError:
        pass
    return value


def _quick_checks() -> list[str]:
    """Krótka kontrola bez sudo, gdy pełny check.sh nie może się wykonać."""
    lines = []

    venv = ROOT / ".venv" / "bin" / "python"
    lines.append("[OK]   .venv działa" if venv.is_file() else "[BŁĄD] .venv brak")

    service = _run(["systemctl", "is-active", "gregai"], timeout=10)
    state = str(service.get("out") or "").strip() or "nieznany"
    lines.append(f"[OK]   usługa gregai: {state}" if service.get("rc") == 0 else f"[BŁĄD] usługa gregai: {state}")

    port = _run(["ss", "-ltnH", "sport", "= :7777"], timeout=10)
    listeners = [line.split()[3] for line in str(port.get("out") or "").splitlines() if len(line.split()) >= 4]
    lan = _env_value("GREGAI_LAN") == "1"
    if listeners and all(addr.startswith(("127.0.0.1:", "[::1]:")) for addr in listeners):
        lines.append("[OK]   port 7777 słucha tylko lokalnie: " + ", ".join(listeners))
    elif listeners and lan:
        lines.append("[OK]   port 7777 w sieci (GREGAI_LAN=1, wymagany token): " + ", ".join(listeners))
    else:
        lines.append("[BŁĄD] port 7777: " + (", ".join(listeners) if listeners else "brak nasłuchu"))

    warp = _run(["warp-cli", "--accept-tos", "status"], timeout=10)
    warp_text = (str(warp.get("out") or "") + " " + str(warp.get("err") or "")).strip()
    lines.append("[OK]   WARP: połączony" if "Connected" in warp_text else f"[BŁĄD] WARP: {warp_text.splitlines()[0] if warp_text else 'brak statusu'}")

    ollama = _run(["systemctl", "is-active", "ollama"], timeout=10)
    ollama_state = str(ollama.get("out") or "").strip() or "nieznany"
    lines.append(f"[OK]   Ollama: {ollama_state}" if ollama.get("rc") == 0 else f"[BŁĄD] Ollama: {ollama_state}")

    env_file = ROOT / ".env"
    if env_file.is_file():
        lines.append(f"[OK]   .env istnieje (prawa {oct(env_file.stat().st_mode & 0o777)[2:]})")
    else:
        lines.append("[BŁĄD] .env brak")
    return lines


def run_check() -> dict:
    """Uruchom check.sh bez podnoszenia uprawnień.

    check.sh sam wymaga sudo do pełnego audytu. Z przeglądarki nie ma
    terminala do wpisania hasła, więc bez wcześniejszego sudo -n narzędzie
    zwróci jego własny komunikat i krótką kontrolę dostępną bez sudo.
    """
    res = _run(["bash", str(ROOT / "check.sh")], timeout=180)
    body = _output(res) or "(brak wyjścia)"
    ok = res.get("rc") == 0
    prefix = "check.sh - kontrola GREGAI" if ok else "check.sh - kontrola GREGAI niepełna (wymaga sudo w terminalu)"
    if not ok:
        body += "\n\nKrótka kontrola bez sudo:\n" + "\n".join(_quick_checks())
    return _result(f"{prefix}, kod {res.get('rc')}:\n{body}", ok)


def env_status() -> dict:
    """Stan venv, wersji pakietów runtime i lokalnej Ollamy."""
    lines = []
    ok = True
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file():
        res = _run([str(venv_python), "--version"], timeout=10)
        version = (_output(res) or "(brak wersji)").splitlines()[0]
        lines.append(f"[OK]   .venv: {version}")
    else:
        ok = False
        lines.append("[BŁĄD] .venv: brak (uruchom install.sh)")

    probe = (
        "import importlib.metadata as m, json\n"
        "out = {}\n"
        "for name in ('httpx', 'huawei-lte-api'):\n"
        "    try:\n"
        "        out[name] = m.version(name)\n"
        "    except Exception:\n"
        "        out[name] = None\n"
        "print(json.dumps(out))\n"
    )
    res = _run([_python(), "-c", probe], timeout=15)
    versions = {}
    try:
        versions = json.loads(str(res.get("out") or "").strip() or "{}")
    except ValueError:
        pass
    for name in ("httpx", "huawei-lte-api"):
        version = versions.get(name)
        if version:
            lines.append(f"[OK]   {name}: {version}")
        else:
            lines.append(f"[BŁĄD] {name}: brak")

    ollama = _run(["systemctl", "is-active", "ollama"], timeout=10)
    state = (str(ollama.get("out") or "").strip() or str(ollama.get("err") or "").strip() or "nieznany")
    if ollama.get("rc") == 0:
        lines.append(f"[OK]   Ollama: {state}")
    else:
        ok = False
        lines.append(f"[BŁĄD] Ollama: {state}")

    models = _run(["ollama", "list"], timeout=15)
    if models.get("rc") == 0:
        names = [line.split()[0] for line in str(models.get("out") or "").splitlines()[1:] if line.strip()]
        lines.append("[OK]   modele Ollama: " + (", ".join(names) if names else "brak modeli"))
    else:
        lines.append("[UWAGA] modele Ollama: nie można odczytać listy")
    return _result("\n".join(lines), ok)


def service_status() -> dict:
    """Stan usługi gregai i ostatnie linie jej dziennika. Tylko odczyt."""
    active = _run(["systemctl", "is-active", "gregai"], timeout=10)
    state = (str(active.get("out") or "").strip() or str(active.get("err") or "").strip() or "nieznany")
    show = _run([
        "systemctl", "show", "gregai", "--no-pager",
        "-p", "ActiveState,SubState,WorkingDirectory,ExecMainStartTimestamp",
    ], timeout=10)
    details = _output(show)
    logs = _run(["journalctl", "-u", "gregai", "-n", "30", "--no-pager"], timeout=20)
    log_text = _output(logs) or "(brak wpisów lub brak dostępu do dziennika)"
    ok = active.get("rc") == 0
    tag = "[OK]" if ok else "[BŁĄD]"
    speech = (
        f"{tag} usługa gregai: {state}\n"
        f"{details}\n"
        f"Ostatnie 30 linii dziennika:\n{log_text}"
    )
    return _result(speech, ok)


def _version_lines() -> list[str]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace").splitlines()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace").splitlines()
    readme_version = ""
    for line in readme[:10]:
        match = re.match(r"#\s+GREGAI\s+(\S+)", line)
        if match:
            readme_version = match.group(1)
            break
    changelog_version = ""
    for line in changelog[:20]:
        match = re.match(r"##\s+Co nowego w\s+(\S+)", line)
        if match:
            changelog_version = match.group(1)
            break
    problems = []
    if readme_version != version:
        problems.append(f"README.md: wersja {readme_version or 'brak'}, VERSION {version}")
    if changelog_version != version:
        problems.append(f"CHANGELOG.md: najnowsza sekcja {changelog_version or 'brak'}, VERSION {version}")
    return problems


def _control_lines() -> list[str]:
    check = (ROOT / "check.sh").read_text(encoding="utf-8", errors="replace")
    banner = re.search(r"==\s*GREGAI:\s*(\d+)\s+kontrol", check)
    numbers = [int(n) for n in re.findall(r"^\s*(?:ok|bad)\s+(\d+)\b", check, re.MULTILINE)]
    if not banner or not numbers:
        return ["check.sh: nie można ustalić liczby kontroli"]
    declared = int(banner.group(1))
    actual = max(numbers)
    if declared != actual:
        return [f"check.sh: banner mówi {declared}, ostatnia kontrola ma numer {actual}"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(\d+)\s+kontroli", readme)
    if match and int(match.group(1)) != declared:
        return [f"README.md: {match.group(1)} kontroli, check.sh: {declared}"]
    return []


def _reference_lines() -> list[str]:
    problems = []
    known_scripts = {
        "install.sh", "aktualizuj.sh", "check.sh", "weryfikuj.sh", "wydaj.sh", "gregai",
        "run.sh", "run_planner.sh", "run_student.sh",
    }
    for name in ("README.md", "FUNDAMENT.md"):
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        for ref in sorted(set(re.findall(r"(?:agent|training)/[\w.-]+\.(?:py|sh)\b|[\w.-]+\.sh\b", text))):
            if ref.startswith(("agent/", "training/")):
                target = ROOT / ref
            elif ref in known_scripts:
                target = ROOT / ref
            else:
                continue
            if not target.exists():
                problems.append(f"{name}: wskazuje nieistniejący plik {ref}")
    return problems


def docs_check() -> dict:
    """Sprawdź spójność README, FUNDAMENT, CHANGELOG i check.sh."""
    lines = _version_lines() + _control_lines() + _reference_lines()
    if lines:
        speech = "Wykryte rozbieżności dokumentacji:\n" + "\n".join(f"- {line}" for line in lines)
        return _result(speech, False)
    return _result(
        "Dokumentacja spójna: wersja w VERSION/README/CHANGELOG, liczba kontroli "
        "w check.sh/README oraz odwołania do plików w README/FUNDAMENT.",
        True,
    )
