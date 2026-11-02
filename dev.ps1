# Starts the API and the web app in two PowerShell windows.
# No Docker and no make needed. Usage:  .\dev.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root'; `$env:PYTHONPATH = 'backend\src'; .\.venv\Scripts\python.exe -m uvicorn fairpool.main:app --reload --port 8000"
)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\frontend'; npm run dev"
)

Write-Host "API  -> http://localhost:8000/health"
Write-Host "Web  -> http://localhost:5173"
Write-Host "Two windows opened. Close them to stop the app."
