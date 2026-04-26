# HomePulse — start Vite dev server from repo root (Windows PowerShell).
# Usage:  .\scripts\start_frontend.ps1
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "frontend")
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing npm dependencies..."
    npm install
}
npm run dev
