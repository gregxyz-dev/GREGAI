#!/usr/bin/env bash
# Zbuduj, podpisz i sprawdź paczkę wydania. Nie zmienia wersji, historii ani gita.
# 1.39.0: manifest GREGAI.sha256 jest podpisany kluczem GPG wydawcy
# (GREGAI.sha256.asc); klucz publiczny (GREGAI.klucz.asc) jedzie w paczce.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"
VERSION="$(tr -d '[:space:]' < VERSION)"
case "$VERSION" in
    ''|*[!0-9A-Za-z.-]*) echo "Nieprawidłowy VERSION: $VERSION" >&2; exit 2 ;;
esac
ZIP="$ROOT/../GREGAI-$VERSION.zip"
[ ! -e "$ZIP" ] || { echo "Paczka już istnieje: $ZIP" >&2; exit 2; }
grep -Fq "# GREGAI $VERSION" README.md || { echo "README.md nie ma nagłówka '# GREGAI $VERSION'" >&2; exit 2; }
grep -Fq "## Co nowego w $VERSION" CHANGELOG.md || { echo "CHANGELOG.md nie ma sekcji 'Co nowego w $VERSION'" >&2; exit 2; }

command -v gpg >/dev/null || { echo "Brak gpg: podpisany manifest wymaga gnupg (sudo apt install gnupg)." >&2; exit 2; }

# --- Klucz wydawcy (generacja przy pierwszym wydaniu) -------------------------
# GREGAI_GPG_KEY wymusza konkretny klucz. Bez tego bierzemy pierwszy klucz
# sekretny z keyringu wydawcy; gdy go nie ma, tworzymy ed25519 bez hasła
# (klucz zostaje w ~/.gnupg wydawcy, usługa ma ten katalog w InaccessiblePaths).
GPG_KEY_ID="${GREGAI_GPG_KEY:-}"
if [ -z "$GPG_KEY_ID" ]; then
  GPG_KEY_ID="$(gpg --batch --list-secret-keys --with-colons 2>/dev/null | awk -F: '$1=="sec"{print $5; exit}' || true)"
fi
if [ -z "$GPG_KEY_ID" ]; then
  echo "Brak klucza GPG wydawcy - tworzę jednorazowy klucz GREGAI (ed25519, bez hasła)."
  gpg --batch --pinentry-mode loopback --passphrase '' \
    --quick-generate-key "GREGAI release signing <gregai@localhost>" ed25519 sign 0
  GPG_KEY_ID="$(gpg --batch --list-secret-keys --with-colons 2>/dev/null | awk -F: '$1=="sec"{print $5; exit}')"
fi
[ -n "$GPG_KEY_ID" ] || { echo "Nie udało się ustalić klucza GPG wydawcy." >&2; exit 2; }
gpg --batch --armor --export "$GPG_KEY_ID" > GREGAI.klucz.asc
echo "Klucz wydawcy: $GPG_KEY_ID (publiczny: GREGAI.klucz.asc)"

bash "$ROOT/weryfikuj.sh"

# Manifest: wszystkie pliki paczki POZA samym manifestem i jego podpisem.
# Podpis nie może być w manifeście ( Manifest -> podpis -> Manifest).
python3 - "$ROOT" <<'PY'
import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1])

def included(path: Path) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts
    if not path.is_file() or path.name in {"GREGAI.sha256", "GREGAI.sha256.asc"}:
        return False
    if any(part in {".git", "__pycache__", ".venv"} for part in parts):
        return False
    if parts[0] in {"data", "memory", "backups"}:
        return False
    if parts[0] == "notatki" and (len(parts) < 2 or parts[1] not in {"wiedza", "szkola"}):
        return False
    if parts[:2] == ("training", ".work"):
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.suffix in {".pyc", ".pyo", ".gguf"}:
        return False
    return True

files = sorted((p for p in root.rglob("*") if included(p)), key=lambda p: str(p.relative_to(root)).encode())
lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}" for p in files]
(root / "GREGAI.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Manifest: {len(files)} plików")
PY

gpg --batch --yes --local-user "$GPG_KEY_ID" --armor \
  --detach-sign --output "$ROOT/GREGAI.sha256.asc" "$ROOT/GREGAI.sha256"

# Zip: pliki z manifestu + manifest + podpis. Python zamiast `zip` (nie każdy
# system go ma), ścieżki spoza projektu są odcinane.
python3 - "$ROOT" "$ZIP" <<'PY'
from pathlib import Path
import sys
import zipfile

root, zip_path = Path(sys.argv[1]), Path(sys.argv[2])
names = []
for line in (root / "GREGAI.sha256").read_text(encoding="utf-8").splitlines():
    _, _, name = line.partition("  ")
    if name:
        names.append(name)
try:
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(root / name, name)
        archive.write(root / "GREGAI.sha256", "GREGAI.sha256")
        archive.write(root / "GREGAI.sha256.asc", "GREGAI.sha256.asc")
except BaseException:
    zip_path.unlink(missing_ok=True)
    raise
print(f"Zbudowano: {zip_path}")
PY

# Weryfikacja na świeżym rozpakowaniu: sumy, podpis (w osobnym, tymczasowym
# keyringu z kluczem publicznym z paczki) i szybkie kontrole.
STAGE="$(mktemp -d)"
GNUPG_TMP="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$GNUPG_TMP"' EXIT
python3 - "$ZIP" "$STAGE" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
(
    cd "$STAGE"
    sha256sum --quiet -c GREGAI.sha256
    chmod 700 "$GNUPG_TMP"
    GNUPGHOME="$GNUPG_TMP" gpg --batch --quiet --import GREGAI.klucz.asc
    GNUPGHOME="$GNUPG_TMP" gpg --batch --quiet --verify GREGAI.sha256.asc GREGAI.sha256
    bash weryfikuj.sh
)
echo "Wydanie $VERSION gotowe i podpisane: $ZIP"
echo "Podpis: $ROOT/GREGAI.sha256.asc (klucz publiczny: GREGAI.klucz.asc)"
