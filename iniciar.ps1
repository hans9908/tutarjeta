param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$studioUrl = 'http://127.0.0.1:8877'

function Test-StudioReady {
    try {
        $studioHealth = Invoke-RestMethod -Uri "$studioUrl/api/health" -TimeoutSec 2 -Proxy $null
        return ($studioHealth.application -eq 'TarjetasStudio' -and $studioHealth.status -eq 'ok')
    } catch { return $false }
}

if (-not (Test-StudioReady)) {
    if (-not (Test-Path -LiteralPath 'web/dist/index.html')) {
        Write-Host 'Compilando la interfaz Vue...'
        & npm install --prefix web
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de la interfaz.' }
        & npm run build --prefix web
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo compilar la interfaz.' }
    }
    $studioPython = (Get-Command python -ErrorAction Stop).Source
    & $studioPython -c 'import qrcode, PIL'
    if ($LASTEXITCODE -ne 0) {
        & $studioPython -m pip install -r backend/requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias del generador.' }
    }
    $studioLogDirectory = Join-Path $PSScriptRoot 'data'
    New-Item -ItemType Directory -Force -Path $studioLogDirectory | Out-Null
    $env:PORT = '8877'
    $studioProcess = Start-Process -FilePath $studioPython -ArgumentList @('-u','-m','backend.server') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $studioLogDirectory 'server.stdout.log') -RedirectStandardError (Join-Path $studioLogDirectory 'server.stderr.log') -PassThru
    $studioReady = $false
    for ($studioAttempt = 0; $studioAttempt -lt 20; $studioAttempt++) {
        if (Test-StudioReady) { $studioReady = $true; break }
        $studioProcess.Refresh()
        if ($studioProcess.HasExited) { break }
        Start-Sleep -Milliseconds 300
    }
    if (-not $studioReady) {
        throw "No se pudo iniciar Tarjetas Studio. Revisa data\server.stderr.log. Puede haber otro programa usando el puerto 8877."
    }
}
# Open only after the API and the compiled interface are reachable.
$studioPage = Invoke-WebRequest -Uri "$studioUrl/" -UseBasicParsing -TimeoutSec 5 -Proxy $null
if ($studioPage.StatusCode -ne 200 -or $studioPage.Content -notmatch 'Tarjetas Studio') {
    throw 'El servidor responde pero no se encuentra la interfaz compilada.'
}
Write-Host "Tarjetas Studio lista en $studioUrl"
Write-Host 'La aplicacion sigue funcionando aunque cierres esta ventana.'
if (-not $NoBrowser) { Start-Process $studioUrl }
