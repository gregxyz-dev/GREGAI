"""
env_loader.py

Minimalny loader .env, bez zewnętrznych zależności. Wczytuje KEY=VALUE
z pliku .env w katalogu głównym projektu do os.environ (nie nadpisuje
zmiennych już ustawionych w środowisku systemowym).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import fsutil

ENV_PATH = Path(__file__).parent.parent / ".env"


def _parse_env_lines() -> list[tuple[str, str]]:
    """Pary (klucz, wartość) z .env, bez dotykania os.environ - wspólna
    logika parsowania dla load_env() poniżej."""
    try:
        # utf-8-sig: .env zapisany w edytorze z BOM nie psuje pierwszego klucza;
        # errors="replace": komentarz w innym kodowaniu (np. cp1250 z Windowsa) nie
        # może przewrócić startu serwera.
        text = ENV_PATH.read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        return []
    except OSError as e:
        # Najczęściej: .env należy do roota (skrypt odpalony przez sudo). Bez ostrzeżenia
        # usługa startowałaby po cichu bez tokenu i kluczy.
        print(f"UWAGA: nie mogę wczytać .env ({type(e).__name__}); sprawdź właściciela i prawa pliku (chmod 600, właściciel: użytkownik usługi)")
        return []
    # Bajty zerowe (plik zapisany jako UTF-16 albo dopełniony zerami po zaniku zasilania)
    # przewracałyby os.environ (ValueError: embedded null byte) przy imporcie serwera.
    text = text.replace("\x00", "")
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):  # `export KLUCZ=wartość` jak w powłoce
            key = key[len("export "):].strip()
        value = value.strip()
        # Cudzysłowy zdejmujemy tylko jako PARĘ obejmującą całą wartość ("a b" ->
        # a b). Pojedynczy cudzysłów na końcu hasła (abc") jest jego częścią.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            pairs.append((key, value))
    return pairs


# Projekt nazywał się SIECAI do 2026-10-09. Stary .env (przeniesiony ze
# starego laptopa) może mieć jeszcze klucze SIECAI_*: wczytujemy je jako
# GREGAI_*, chyba że .env ma już nową nazwę. install.sh i tak zmienia
# nazwy kluczy w .env na stałe; to jest siatka bezpieczeństwa.
OLD_PREFIX, NEW_PREFIX = "SIECAI_", "GREGAI_"


def _renamed(key: str) -> str:
    return NEW_PREFIX + key[len(OLD_PREFIX):] if key.startswith(OLD_PREFIX) else key


def load_env():
    """Ten sam klucz kilka razy w .env: wygrywa OSTATNI wpis - tak samo jak
    w install.sh i check.sh (grep | tail -1), żeby serwer i skrypty zawsze
    widziały tę samą wartość (np. dopisany na końcu GREGAI_LAN=0)."""
    pairs = _parse_env_lines()
    new_keys = {k for k, _ in pairs if k.startswith(NEW_PREFIX)}
    values: dict[str, str] = {}
    for key, value in pairs:
        if key.startswith(OLD_PREFIX):
            if _renamed(key) in new_keys:
                continue  # nowa nazwa w .env wygrywa ze starą
            key = _renamed(key)
        values[key] = value
    for key, value in values.items():
        if key not in os.environ:
            try:
                os.environ[key] = value
            except ValueError:  # klucz albo wartość, której system nie przyjmie; sam klucz w komunikacie
                print(f"UWAGA: pomijam wpis .env o nieprawidłowym kluczu albo wartości ({key[:40]!r})")


def _env_number(name: str, default, cast, minimum, maximum):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        print(f"UWAGA: {name}={raw!r} nie jest liczbą - używam {default}")
        return default
    if value != value:  # NaN
        print(f"UWAGA: {name}={raw!r} nie jest liczbą - używam {default}")
        return default
    if minimum is not None and value < minimum:
        print(f"UWAGA: {name}={raw!r} jest poniżej {minimum} - używam {minimum}")
        return minimum
    if maximum is not None and value > maximum:
        print(f"UWAGA: {name}={raw!r} jest powyżej {maximum} - używam {maximum}")
        return maximum
    return value


def env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    """Liczba całkowita z os.environ. Pusta, błędna (np. "8k") albo spoza zakresu
    wartość w .env NIE przewraca startu serwera: dostajemy wartość domyślną lub
    brzegową i ostrzeżenie w logu."""
    return _env_number(name, default, int, minimum, maximum)


def env_float(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    return _env_number(name, default, float, minimum, maximum)


def set_env_vars(updates: dict[str, str], comments: dict[str, str] | None = None) -> dict[str, str]:
    """Zapisuje KILKA par KEY=wartość do .env w JEDNYM atomowym zapisie (ta
    sama logika co training/export.py:update_env, tyle że dla wielu kluczy
    naraz, żeby np. GREGAI_LAN i nowy GREGAI_TOKEN trafiły do pliku razem,
    nie dwoma osobnymi zapisami). Dla każdego klucza: czynny (pierwszy) wpis
    jest podmieniany, jego ewentualne duplikaty znikają; gdy czynnego wpisu
    nie ma, zakomentowany przykład `# KEY=...` zamienia się w czynny; gdy
    nie ma żadnego z dwóch - nowy blok (z `comments[KEY]`, jeśli podano,
    inaczej jedną ogólną linią) trafia na koniec pliku. Resztę .env (sekrety
    użytkownika, kolejność, komentarze) zostawia bajt w bajt. Brakujący plik
    .env jest tworzony od zera (prawa 600, patrz fsutil.atomic_write_text).

    Zwraca {KEY: "podmieniono"/"dopisano"} - do komunikatu dla użytkownika,
    nie do logiki (wołający i tak wie, co ustawił)."""
    # Bajty, nie tekst UTF-8: .env w innym kodowaniu (komentarz z polskimi znakami
    # zapisany w cp1250) nie może wywrócić zapisu, a reszta pliku ma zostać bajt w bajt
    # (tak samo jak training/export.py:update_env, z tego samego powodu).
    text = ENV_PATH.read_bytes().decode("utf-8", "surrogateescape") if ENV_PATH.exists() else ""
    comments = comments or {}
    lines = text.split("\n")
    actions: dict[str, str] = {}
    to_append: list[tuple[str, str]] = []
    for key, value in updates.items():
        line = f"{key}={value}"
        # Te same kształty linii, które czyta load_env() wyżej (`export KLUCZ=`, spacje wokół `=`).
        active = re.compile(rf"^[ \t]*(export[ \t]+)?{re.escape(key)}[ \t]*=")
        commented = re.compile(rf"^[ \t]*#[ \t]*{re.escape(key)}[ \t]*=")
        done = False
        new_lines = []
        for current in lines:
            if active.match(current):
                if not done:
                    new_lines.append(line)
                    done = True
                continue  # ewentualne duplikaty tego klucza niżej w pliku znikają
            new_lines.append(current)
        lines = new_lines
        if not done:
            for i, current in enumerate(lines):
                if commented.match(current):
                    lines[i] = line
                    done = True
                    break
        actions[key] = "podmieniono" if done else "dopisano"
        if not done:
            to_append.append((key, line))
    new_text = "\n".join(lines)
    if to_append:
        new_text = new_text.rstrip("\n") + "\n"
        for key, line in to_append:
            comment = comments.get(key, f"# {key}: ustawione przez GREGAI.\n")
            new_text += "\n" + comment + line + "\n"
    if new_text != text:
        fsutil.atomic_write_text(ENV_PATH, new_text, errors="surrogateescape")
    return actions
