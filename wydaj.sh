#!/usr/bin/env bash
# Zbuduj i sprawdź paczkę wydania. Nie zmienia wersji, historii ani gita.
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

bash "$ROOT/weryfikuj.sh"

python3 - "$ROOT" "$ZIP" <<'PY'
import hashlib
from pathlib import Path
import sys
import zipfile

root = Path(sys.argv[1])
zip_path = Path(sys.argv[2])

def included(path: Path) -> bool:
    rel = path.relative_to(root)
    parts = rel.parts
    if not path.is_file() or path.name == "GREGAI.sha256":
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
manifest = root / "GREGAI.sha256"
manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
try:
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, str(path.relative_to(root)))
        archive.write(manifest, manifest.name)
except BaseException:
    zip_path.unlink(missing_ok=True)
    raise
print(f"Zbudowano: {zip_path}")
PY

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
python3 - "$ZIP" "$STAGE" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
(
    cd "$STAGE"
    sha256sum --quiet -c GREGAI.sha256
    bash weryfikuj.sh
)
echo "Wydanie $VERSION gotowe: $ZIP"
