param(
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

$conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Host "Porta $Port ocupada (PID $($conn.OwningProcess)) - matando..."
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match "^\s*[^#]" -and $_ -match "=" } | ForEach-Object {
        $parts = $_ -split "=", 2
        $key   = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"

$uvicorn = Join-Path $ProjectRoot ".venv\Scripts\uvicorn.exe"

$uvicornArgs = @(
    "src.main:create_app",
    "--factory",
    "--host", "0.0.0.0",
    "--port", "$Port"
)
if ($Reload) { $uvicornArgs += "--reload" }

Write-Host "Iniciando servidor em http://localhost:$Port ..."
& $uvicorn @uvicornArgs
