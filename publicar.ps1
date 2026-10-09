# Publica una versión nueva de MiComercio.
#
#   powershell -ExecutionPolicy Bypass -File .\publicar.ps1 -Version 1.2.0 -Notas "Qué cambió en esta versión"
#
# Cambia el número de versión, corre las pruebas, guarda los cambios pendientes y sube el código con la
# etiqueta v1.2.0. GitHub genera MiComercio.exe y lo publica (tarda unos minutos); a partir de ese momento
# los programas instalados muestran el botón Update.
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory = $true)][string]$Notas
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)

$archivo = Join-Path $PSScriptRoot "micomercio\__init__.py"
$contenido = [IO.File]::ReadAllText($archivo)
if ($contenido -notmatch '__version__ = "(\d+\.\d+\.\d+)"') { throw "No se encontro la version en micomercio\__init__.py" }
if ([version]$Version -le [version]$Matches[1]) { throw "La version nueva ($Version) debe ser mayor que la actual ($($Matches[1]))." }
git rev-parse -q --verify "refs/tags/v$Version" *> $null
if ($LASTEXITCODE -eq 0) { throw "La etiqueta v$Version ya existe." }

[IO.File]::WriteAllText($archivo, ($contenido -replace '__version__ = "\d+\.\d+\.\d+"', "__version__ = `"$Version`""), $utf8)
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "NOVEDADES.md"), $Notas + "`n", $utf8)

& .\.venv\Scripts\python.exe -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron: no se publica. Revisa los cambios (la version quedo modificada en los archivos)." }

git add -A
git commit -m "Version $Version" -m $Notas
git tag "v$Version"
git push origin HEAD "v$Version"
if ($LASTEXITCODE -ne 0) { throw "No se pudo subir a GitHub." }
Write-Host "Version $Version subida. Segui la publicacion en https://github.com/eliexerguevara/Exa-Pyme/actions"
