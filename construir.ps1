# Genera dist\MiComercio.exe de forma reproducible.
# Uso (PowerShell, desde la carpeta del proyecto):   .\construir.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creando el entorno virtual..."
    python -m venv .venv
}
Write-Host "Instalando dependencias..."
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias." }

Write-Host "Ejecutando las pruebas..."
& $py -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron: no se genera el ejecutable." }

Write-Host "Generando el icono..."
& $py herramientas\generar_icono.py
if ($LASTEXITCODE -ne 0) { throw "No se pudo generar el icono." }

Write-Host "Empaquetando con PyInstaller..."
& $py -m PyInstaller MiComercio.spec --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo." }

Write-Host "Probando el ejecutable (autoprueba sobre una base temporal)..."
$resultado = Join-Path $env:TEMP "micomercio_autoprueba.txt"
$proceso = Start-Process -FilePath ".\dist\MiComercio.exe" -ArgumentList "--autoprueba", "`"$resultado`"" -Wait -PassThru
if ($proceso.ExitCode -ne 0) {
    if (Test-Path $resultado) { Get-Content $resultado }
    throw "El ejecutable no paso la autoprueba."
}

$exe = Get-Item ".\dist\MiComercio.exe"
Write-Host ("Listo: {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB))
