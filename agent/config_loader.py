"""
config_loader.py (1.38.9) - konfiguracja GREGAI w plikach: prompts/ i config/.

Zasady:
- tylko standardowa biblioteka (JSON, bez PyYAML),
- brak pliku albo błąd JSON = wartość domyślna z kodu (nigdy crash),
- hot-reload: wątek sprawdza mtime co 5 s i czyści cache; kolejne odczyty
  widzą nową treść bez restartu usługi,
- czyta wyłącznie pliki lokalne (żadnej sieci).

Klucze:
  get("prompts.system_local")      -> prompts/system_local.md (tekst)
  get("system_local")              -> to samo (skrót)
  get("fastpaths")                 -> config/fastpaths.json (dict)
  get("namysl.fazy")               -> config/namysl.json["fazy"]
  get("validation.echo.akcja")     -> zagnieżdżone pole JSON

Nie modyfikuje plików. Nie ma tu żadnej logiki AI.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
CONFIG_DIR = ROOT / "config"
WATCH_INTERVAL_S = 5.0

_CONFIG_NAMES = frozenset({"fastpaths", "social", "namysl", "validation", "tools", "commands"})


class ConfigLoader:
    """Czytnik prompts/*.md i config/*.json z cache po mtime i fallbackiem."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else ROOT
        self.prompts_dir = self.root / "prompts"
        self.config_dir = self.root / "config"
        self._lock = threading.RLock()
        self._cache: dict[Path, tuple[float, object]] = {}
        self._last_error: dict[Path, str] = {}
        self._watcher_started = False

    # --- mapowanie klucza na plik ------------------------------------------
    def _path_for(self, key: str) -> tuple[Path, str]:
        text = str(key or "").strip()
        if not text:
            return self.prompts_dir / "", ""
        # Jawne ścieżki (np. "prompts/system_local.md") - zostawiamy.
        if text.startswith("prompts/") or text.startswith("config/"):
            return self.root / text, ""
        if text.startswith("prompts."):
            rest = text[len("prompts."):]
            return self.prompts_dir / (rest if rest.endswith(".md") else rest + ".md"), ""
        first, _, rest = text.partition(".")
        if first in _CONFIG_NAMES:
            return self.config_dir / f"{first}.json", rest
        # Krótkie nazwy plików: "system_local" -> prompts/system_local.md.
        if text.endswith(".md"):
            return self.prompts_dir / text, ""
        if (self.prompts_dir / f"{text}.md").exists():
            return self.prompts_dir / f"{text}.md", ""
        # Dowolny plik JSON w config/ z polem po kropce: "b.pole.x".
        if "." in text:
            first, _, rest = text.partition(".")
            if (self.config_dir / f"{first}.json").exists():
                return self.config_dir / f"{first}.json", rest
        return self.config_dir / f"{text}.json", ""

    @staticmethod
    def _dig(data, field: str, default):
        if not field:
            return data
        cur = data
        for part in field.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # --- odczyt ------------------------------------------------------------
    def _read(self, path: Path, default):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return default
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == mtime:
                return hit[1]
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return default
        try:
            if path.suffix.lower() == ".json":
                value = json.loads(raw)
            else:
                value = raw
        except ValueError as e:
            with self._lock:
                self._last_error[path] = f"{type(e).__name__}: {e}"
            return default
        with self._lock:
            self._cache[path] = (mtime, value)
            self._last_error.pop(path, None)
        return value

    def get(self, key: str, default=None):
        path, field = self._path_for(key)
        data = self._read(path, default)
        return self._dig(data, field, default)

    def text(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return value if isinstance(value, str) else default

    # --- hot-reload --------------------------------------------------------
    def reload_if_changed(self, force: bool = False) -> list[str]:
        """Czyści cache zmienionych plików. Zwraca listę zmienionych ścieżek."""
        changed: list[str] = []
        with self._lock:
            items = list(self._cache.items())
        for path, (old_mtime, _value) in items:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if force or mtime != old_mtime:
                with self._lock:
                    self._cache.pop(path, None)
                changed.append(str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path))
        for path in changed:
            print(f"Przeładowano: {path}", flush=True)
        return changed

    def status(self) -> dict:
        with self._lock:
            return {
                "pliki": sorted(str(p.relative_to(self.root)) for p in self._cache if p.is_relative_to(self.root)),
                "bledy": {str(p.relative_to(self.root)): e for p, e in self._last_error.items() if p.is_relative_to(self.root)},
                "watcher": self._watcher_started,
            }

    def start_watcher(self, interval_s: float = WATCH_INTERVAL_S) -> None:
        if self._watcher_started:
            return
        self._watcher_started = True

        def loop():
            while True:
                time.sleep(max(1.0, float(interval_s)))
                try:
                    self.reload_if_changed()
                except Exception:
                    pass

        threading.Thread(target=loop, name="gregai-config-watch", daemon=True).start()


_LOADER = ConfigLoader()


def get(key: str, default=None):
    return _LOADER.get(key, default)


def text(key: str, default: str = "") -> str:
    return _LOADER.text(key, default)


def reload_if_changed(force: bool = False) -> list[str]:
    return _LOADER.reload_if_changed(force=force)


def start_watcher(interval_s: float = WATCH_INTERVAL_S) -> None:
    _LOADER.start_watcher(interval_s)


def status() -> dict:
    return _LOADER.status()
