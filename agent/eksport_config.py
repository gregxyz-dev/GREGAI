"""
eksport_config.py (1.38.9) - generuje read-only snapshoty konfiguracji.

  config/tools.json   <- agent/capabilities.py (CAPABILITIES)
  prompts/persona.md  <- agent/persona.py (_STUDENT_PROMPT)

Nie jest to źródło prawdy i nie jest importowane przez GREGAI w runtime.
Uruchom po zmianie CAPABILITIES/persona:

    cd agent && python3 eksport_config.py

`--check` porównuje pliki z kodem i kończy się kodem 1, gdy są nieaktualne.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from env_loader import load_env

load_env()

import capabilities as cap_mod
import persona as persona_mod

ROOT = Path(__file__).resolve().parent.parent
TOOLS_PATH = ROOT / "config" / "tools.json"
PERSONA_PATH = ROOT / "prompts" / "persona.md"


def _safe_text(text: str, creator_first: bool = False) -> str:
    """Zamienia prywatne imiona na placeholdery w snapshotach do paczki."""
    out = str(text or "")
    pairs = [
        (persona_mod.USER_NAME_GENITIVE, "{UZYTKOWNIKA}"),
        (persona_mod.USER_NAME, "{UZYTKOWNIK}"),
        (persona_mod.CREATOR, "{CREATOR}"),
    ]
    if creator_first:
        pairs = [(persona_mod.CREATOR, "{CREATOR}")] + pairs[:-1]
    for value, placeholder in pairs:
        if value:
            out = out.replace(value, placeholder)
    return out


def tools_snapshot() -> dict:
    # Narzędzia SYSOP są dynamiczne (zależą od SYSOP_ENABLED/active_tools),
    # więc snapshot w paczce zawiera tylko stabilny trzon. Installed UI może
    # dołożyć dynamiczne wpisy z capabilities.py; plik jest read-only.
    dynamic: set[str] = set()
    try:
        import sysop as sysop_mod
        if sysop_mod.enabled():
            dynamic = set(sysop_mod.active_tools())
    except Exception:
        dynamic = set()
    tools = []
    for key, cap in cap_mod.CAPABILITIES.items():
        if key in dynamic:
            continue
        tools.append({
            "key": key,
            "short": _safe_text(cap.short or ""),
            "prompt": _safe_text(cap.prompt or ""),
            "user_only": bool(cap.user_only),
            "call": cap.call is not None,
            "keywords": [getattr(pattern, "pattern", str(pattern)) for pattern in (cap.keywords or [])],
        })
    return {
        "_readonly": True,
        "zrodlo": "agent/capabilities.py",
        "opis": "Snapshot trzonu narzędzi do UI//debug (bez dynamicznych SYSOP). Nie edytuj ręcznie.",
        "tools": tools,
    }


def persona_export() -> str:
    return (
        "<!-- Eksport read-only. Źródło: agent/persona.py (_STUDENT_PROMPT).\n"
        "     Zmiana tego pliku NIE zmienia zachowania GREGAI; zmień persona.py\n"
        "     i wytrenuj ucznia ponownie (training/run_student.sh). -->\n\n"
        + _safe_text(persona_mod.student_system_prompt(), creator_first=True).strip() + "\n"
    )


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    tools_text = _dump(tools_snapshot())
    persona_text = persona_export()
    stale = []
    for path, text in ((TOOLS_PATH, tools_text), (PERSONA_PATH, persona_text)):
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old != text:
            stale.append(path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    if check:
        for path in stale:
            print(f"Nieaktualny: {path.relative_to(ROOT)}")
        return 1 if stale else 0
    for path in stale:
        print(f"Zapisano: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
