#!/usr/bin/env bash
# Szybka weryfikacja czystej kopii: bez sudo, usług, sieci i modeli.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

python3 - <<'PY'
import ast
from pathlib import Path

errors = []
for folder in (Path("agent"), Path("training")):
    for path in sorted(folder.rglob("*.py")):
        if "__pycache__" in path.parts or ".work" in path.parts:
            continue
        try:
            ast.parse(path.read_bytes(), str(path))
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f"{path}: {exc}")
if errors:
    raise SystemExit("Błędy składni Pythona:\n" + "\n".join(errors))
print("OK: składnia Pythona")
PY

for script in install.sh uninstall.sh aktualizuj.sh check.sh weryfikuj.sh wydaj.sh gregai; do
    if [ -f "$script" ]; then
        bash -n "$script"
    fi
done
echo "OK: składnia skryptów bash"

if command -v node >/dev/null 2>&1; then
    while IFS= read -r -d '' script; do
        node --check "$script"
    done < <(find ui -type f -name '*.js' -print0)
    echo "OK: składnia JavaScript"
else
    echo "POMINIĘTO: node nie jest zainstalowany, składnia JavaScript niesprawdzona"
fi

bash "$ROOT/gregai" eval --bez-zapisu
