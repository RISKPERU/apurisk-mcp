# Instala el servidor MCP de ApuRisk y su skill para Claude Code en este equipo.
# Se ejecuta con doble clic en "Instalar-ApuRisk-MCP.cmd". Se puede volver a ejecutar para actualizar.
# Solo texto ASCII: Windows PowerShell 5.1 lee mal los .ps1 con tildes si no llevan BOM.
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ApuriskMcp'),
    [string]$SkillsRoot = (Join-Path $env:USERPROFILE '.claude\skills'),
    [switch]$SkipClaude
)

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot

function Step($text) { Write-Host ''; Write-Host "==> $text" -ForegroundColor Cyan }

function Test-Python([string]$exe, [string[]]$extra = @()) {
    try {
        $out = & $exe @extra -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq '1')
    } catch { return $false }
}

# Devuelve @(ejecutable, argumentos...) de un Python 3.10+ o $null.
function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { if (Test-Python 'py' @('-3')) { return @('py', '-3') } }
    $candidates = @(Get-Command python -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    $candidates += Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    foreach ($candidate in $candidates) { if ($candidate -and (Test-Python $candidate)) { return @($candidate) } }
    return $null
}

try {
    Step 'Buscando Python 3.10 o superior'
    $python = Find-Python
    if (-not $python) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host 'No se encontro Python. Instalando Python 3.12 con winget (solo para tu usuario)...'
            winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
            $python = Find-Python
        }
    }
    if (-not $python) { throw 'No se encontro Python 3.10 o superior. Instalalo desde https://www.python.org/downloads/ (marca "Add python.exe to PATH") y vuelve a ejecutar este instalador.' }
    Write-Host ('Python: ' + ($python -join ' '))

    Step "Copiando archivos a $InstallRoot"
    $app = Join-Path $InstallRoot 'app'
    if (Test-Path $app) { Remove-Item -Recurse -Force $app }
    New-Item -ItemType Directory -Force $app | Out-Null
    foreach ($item in 'src', 'skills', 'pyproject.toml', 'README.md') {
        Copy-Item -Recurse -Force (Join-Path $source $item) $app
    }
    Get-ChildItem $app -Recurse -Include '__pycache__', '*.egg-info' -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

    Step 'Creando el entorno de Python e instalando dependencias (puede tardar un minuto)'
    $venv = Join-Path $InstallRoot '.venv'
    $pythonArgs = @($python | Select-Object -Skip 1)
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    # Al actualizar se reutiliza el entorno: si Claude Code tiene el servidor en marcha, Windows no deja recrear python.exe.
    if (-not (Test-Path $venvPython)) {
        & $python[0] @pythonArgs -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de Python.' }
        & $venvPython -m pip install --quiet --upgrade pip
    }
    & $venvPython -m pip install --quiet --upgrade $app
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar el servidor. Si Claude Code esta abierto, cierralo y vuelve a ejecutar el instalador (revisa tambien la conexion a internet).' }
    $server = Join-Path $venv 'Scripts\apurisk-mcp.exe'
    if (-not (Test-Path $server)) { throw 'La instalacion no genero apurisk-mcp.exe.' }

    Step 'Instalando el skill de ApuRisk para Claude'
    $skillTarget = Join-Path $SkillsRoot 'apurisk'
    New-Item -ItemType Directory -Force $SkillsRoot | Out-Null
    if (Test-Path $skillTarget) { Remove-Item -Recurse -Force $skillTarget }
    Copy-Item -Recurse -Force (Join-Path $app 'skills\apurisk') $skillTarget
    Write-Host "Skill en $skillTarget"

    $registered = $false
    if ($SkipClaude) {
        Write-Host 'Registro en Claude Code omitido.'
    } else {
        Step 'Registrando el servidor en Claude Code'
        if (Get-Command claude -ErrorAction SilentlyContinue) {
            & claude mcp remove apurisk --scope user 2>&1 | Out-Null
            & claude mcp add apurisk $server --scope user
            if ($LASTEXITCODE -eq 0) { $registered = $true } else { Write-Warning 'Claude Code no pudo registrar el servidor.' }
        } else {
            Write-Warning 'No se encontro el comando "claude" (Claude Code). Instalalo y vuelve a ejecutar este instalador.'
        }
    }

    Step 'Comprobando el servidor'
    $check = & $venvPython -c "from apurisk_mcp.server import mcp; import asyncio; print(len(asyncio.run(mcp.list_tools())))"
    if ($LASTEXITCODE -ne 0) { throw 'El servidor no arranca.' }
    Write-Host "Servidor listo con $check herramientas."

    Write-Host ''
    if ($registered) {
        Write-Host 'Listo. Cierra y vuelve a abrir Claude Code para usar ApuRisk.' -ForegroundColor Green
    } else {
        Write-Host "Servidor y skill instalados, pero falta registrarlo en Claude Code. Cuando lo tengas, ejecuta:" -ForegroundColor Yellow
        Write-Host "  claude mcp add apurisk `"$server`" --scope user"
    }
    Write-Host ''
    Write-Host 'Recuerda: tambien necesitas el add-in ApuRisk (version con puerta de automatizacion) cargado en Excel.'
    exit 0
} catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
