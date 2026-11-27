# Instala el agente del MCP remoto en esta PC y lo deja corriendo en segundo plano, sin ventana.
# Se ejecuta con doble clic en "Instalar-Agente-Remoto.cmd". Se puede volver a ejecutar para actualizar
# o cambiar la clave; con -Uninstall lo detiene y lo quita del inicio de Windows.
# Solo texto ASCII: Windows PowerShell 5.1 lee mal los .ps1 con tildes si no llevan BOM.
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'ApuriskMcp'),
    [string]$DefaultUrl = 'https://mcp.riskperu.com',
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$startup = [Environment]::GetFolderPath('Startup')
$desktop = [Environment]::GetFolderPath('Desktop')
$launcher = Join-Path $InstallRoot 'iniciar-agente.vbs'
$stopper = Join-Path $InstallRoot 'detener-agente.vbs'
$shortcuts = @(
    (Join-Path $startup 'Agente ApuRisk.lnk'),
    (Join-Path $desktop 'Iniciar agente ApuRisk.lnk'),
    (Join-Path $desktop 'Detener agente ApuRisk.lnk')
)

function Step($text) { Write-Host ''; Write-Host "==> $text" -ForegroundColor Cyan }

function Get-AgentProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe' OR Name = 'apurisk-mcp-agent.exe'" |
        Where-Object { $_.CommandLine -like '*apurisk_mcp.local_agent*' -or $_.Name -eq 'apurisk-mcp-agent.exe' })
}

function Stop-Agent {
    foreach ($process in Get-AgentProcesses) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
}

function New-Shortcut([string]$path, [string]$target, [string]$arguments, [string]$description) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $target
    $link.Arguments = $arguments
    $link.WorkingDirectory = $InstallRoot
    $link.Description = $description
    $link.Save()
}

try {
    Step 'Deteniendo el agente si ya estaba en marcha'
    Stop-Agent

    if ($Uninstall) {
        foreach ($path in $shortcuts + @($launcher, $stopper)) { Remove-Item -Force $path -ErrorAction SilentlyContinue }
        [Environment]::SetEnvironmentVariable('APURISK_MCP_URL', $null, 'User')
        [Environment]::SetEnvironmentVariable('APURISK_MCP_AGENT_TOKEN', $null, 'User')
        Write-Host 'Agente detenido y quitado del inicio de Windows. La clave se borro de este usuario.' -ForegroundColor Green
        exit 0
    }

    Step 'Instalando el servidor MCP de ApuRisk'
    & (Join-Path $source 'install.ps1') -InstallRoot $InstallRoot -SkipClaude
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar el servidor MCP (ver el error de arriba).' }
    $pythonw = Join-Path $InstallRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path $pythonw)) { throw "No se encontro $pythonw." }

    Step 'Configurando la conexion con el servidor remoto'
    $currentUrl = [Environment]::GetEnvironmentVariable('APURISK_MCP_URL', 'User')
    if (-not $currentUrl) { $currentUrl = $DefaultUrl }
    $url = Read-Host "URL del servidor [$currentUrl]"
    if (-not $url) { $url = $currentUrl }
    $url = $url.Trim().TrimEnd('/')
    if (-not $url.StartsWith('https://')) { throw 'La URL debe empezar con https://' }

    $currentToken = [Environment]::GetEnvironmentVariable('APURISK_MCP_AGENT_TOKEN', 'User')
    $prompt = 'Clave del AGENTE (AGENT_TOKEN, no la del cliente)'
    if ($currentToken) { $prompt += ' [Enter = mantener la actual]' }
    $secure = Read-Host $prompt -AsSecureString
    $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    if (-not $token) { $token = $currentToken }
    $token = "$token".Trim()
    if ($token.Length -lt 32) { throw 'La clave del agente debe tener al menos 32 caracteres.' }

    [Environment]::SetEnvironmentVariable('APURISK_MCP_URL', $url, 'User')
    [Environment]::SetEnvironmentVariable('APURISK_MCP_AGENT_TOKEN', $token, 'User')
    $env:APURISK_MCP_URL = $url
    $env:APURISK_MCP_AGENT_TOKEN = $token

    Step 'Creando el arranque oculto y los accesos directos'
    # pythonw.exe no abre consola; el agente escribe en agente.log y no deja correr dos copias.
    Set-Content -Encoding ASCII $launcher @(
        "' Inicia el agente ApuRisk en segundo plano (sin ventana).",
        'CreateObject("WScript.Shell").Run """' + $pythonw + '"" -m apurisk_mcp.local_agent", 0, False'
    )
    Set-Content -Encoding ASCII $stopper @(
        "' Detiene el agente ApuRisk que corre en segundo plano.",
        'Set procesos = GetObject("winmgmts:").ExecQuery("SELECT * FROM Win32_Process WHERE Name = ''pythonw.exe'' AND CommandLine LIKE ''%apurisk_mcp.local_agent%''")',
        'For Each p In procesos : p.Terminate : Next',
        'MsgBox "Agente ApuRisk detenido.", 64, "ApuRisk"'
    )
    $wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
    New-Shortcut $shortcuts[0] $wscript "`"$launcher`"" 'Agente ApuRisk para Claude en Excel (segundo plano)'
    New-Shortcut $shortcuts[1] $wscript "`"$launcher`"" 'Inicia el agente ApuRisk en segundo plano'
    New-Shortcut $shortcuts[2] $wscript "`"$stopper`"" 'Detiene el agente ApuRisk'
    Write-Host "Arranca solo al iniciar sesion en Windows ($startup)."
    Write-Host 'En el escritorio: "Iniciar agente ApuRisk" y "Detener agente ApuRisk".'

    Step 'Iniciando el agente'
    Start-Process $wscript "`"$launcher`""
    $connected = $false
    for ($i = 0; $i -lt 15 -and -not $connected; $i++) {
        Start-Sleep -Seconds 1
        try { $connected = [bool](Invoke-RestMethod "$url/health" -TimeoutSec 5).agentConnected } catch { }
    }
    $log = Join-Path $InstallRoot 'agente.log'
    Write-Host ''
    if ($connected) {
        Write-Host 'Listo. El agente esta conectado al servidor y corre en segundo plano.' -ForegroundColor Green
    } elseif ((Get-AgentProcesses).Count -gt 0) {
        Write-Host "El agente esta en marcha pero el servidor aun no lo ve. Revisa la clave y la red en $log" -ForegroundColor Yellow
    } else {
        Write-Host "El agente no arranco. Revisa $log" -ForegroundColor Red
    }
    Write-Host 'Recuerda: Excel con el add-in ApuRisk debe estar abierto en esta PC para que Claude lo use.'
    exit 0
} catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
