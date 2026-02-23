param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/4] Validating Python imports..."
& $Python -c "import importlib.util as u,sys;mods=['PySide6','RealtimeSTT','openai','google.genai','torch','torchaudio'];missing=[m for m in mods if u.find_spec(m) is None];print('OK' if not missing else 'MISSING:'+','.join(missing));sys.exit(0 if not missing else 1)"

Write-Host "[2/4] Validating settings.json schema..."
& $Python -c "import json,sys;from pathlib import Path;p=Path('settings.json');d=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {};required=['translator_type','source_lang','target_lang','llm'];missing=[k for k in required if k not in d];print('OK' if not missing else 'MISSING:'+','.join(missing));sys.exit(0 if not missing else 1)"

Write-Host "[3/4] Checking syntax..."
$syntaxScript = @'
import ast
import sys
from pathlib import Path

bad = []
for f in Path(".").rglob("*.py"):
    if ".venv" in f.parts:
        continue
    try:
        ast.parse(f.read_text(encoding="utf-8"))
    except Exception as exc:
        bad.append((str(f), str(exc)))

print("OK" if not bad else "BAD")
for path, err in bad:
    print(f"{path}: {err}")
sys.exit(0 if not bad else 1)
'@
$syntaxScript | & $Python -

Write-Host "[4/4] Checking temporary pyc leftovers..."
$tmpPyc = Get-ChildItem -Path . -Recurse -File -Filter "*.pyc.*" -ErrorAction SilentlyContinue
if ($tmpPyc.Count -gt 0) {
    Write-Host "Found $($tmpPyc.Count) temporary pyc files. Consider removing them."
} else {
    Write-Host "OK"
}

Write-Host "Preflight finished."
