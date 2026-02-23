$ErrorActionPreference = "Stop"

Write-Host "Removing __pycache__ and temporary pyc files..."
$removed = 0
$failed = 0

Get-ChildItem -Path . -Recurse -File -Filter "*.pyc.*" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $path = $_.FullName
        try {
            Remove-Item -Force $path -ErrorAction Stop
            $removed += 1
        } catch {
            $failed += 1
            Write-Host "Failed to remove file: $path"
        }
    }

Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $path = $_.FullName
        try {
            Remove-Item -Recurse -Force $path -ErrorAction Stop
            $removed += 1
        } catch {
            $failed += 1
            Write-Host "Failed to remove directory: $path"
        }
    }

Write-Host "Cache cleanup complete. removed=$removed failed=$failed"
