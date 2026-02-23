param(
    [string]$Python = "python",
    [switch]$Clean,
    [switch]$ForceInstallRuntime
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [string]$Title,
        [scriptblock]$Action
    )

    Write-Host $Title
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($Title). exit=$LASTEXITCODE"
    }
}

if ($Clean) {
    Write-Host "Cleaning previous build outputs..."
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

$runtimeImportsOk = $false
& $Python -c "import PySide6,RealtimeSTT,openai,google.genai,torch,torchaudio" *> $null
if ($LASTEXITCODE -eq 0) {
    $runtimeImportsOk = $true
}

if ($ForceInstallRuntime -or -not $runtimeImportsOk) {
    Invoke-Checked "Installing runtime dependencies..." {
        & $Python -m pip install -r requirements.txt
    }
} else {
    Write-Host "Runtime dependencies already importable. Skipping runtime dependency install."
}

$hasPyInstaller = $false
& $Python -c "import PyInstaller" *> $null
if ($LASTEXITCODE -eq 0) {
    $hasPyInstaller = $true
    Write-Host "PyInstaller already installed. Skipping build dependency install."
} else {
    Invoke-Checked "Installing build dependencies..." {
        & $Python -m pip install -r requirements-build.txt
    }
}

Invoke-Checked "Checking PyInstaller import..." {
    & $Python -c "import PyInstaller"
}

Write-Host "Running PyInstaller..."
$args = @("-m", "PyInstaller", "speaki.spec", "--noconfirm")
if ($Clean) { $args += "--clean" }
& $Python @args
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed. exit=$LASTEXITCODE"
}

Write-Host "Build complete. Output: dist\\speaki\\"
