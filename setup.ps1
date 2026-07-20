$ErrorActionPreference = "Stop"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Elevando para administrador..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
    )
    return
}

$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$prereqDir = Join-Path $root "prereqs"
$venv = Join-Path $root ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
$falhas = @()

function Passo($n, $txt) {
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor DarkCyan
    Write-Host " [$n] $txt" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor DarkCyan
}
function Ok($t)    { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Info($t)  { Write-Host "  ->     $t" -ForegroundColor Gray }
function Falha($t) { Write-Host "  [ERRO] $t" -ForegroundColor Red; $script:falhas += $t }

Write-Host ""
Write-Host "  DBX STATS - INSTALACAO AUTOMATICA" -ForegroundColor White
Write-Host "  Pasta: $root" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. Python
Passo 1 "Verificando Python"

function Find-Python {
    foreach ($c in @("py", "python")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $out = if ($c -eq "py") { & $c -3 --version 2>&1 } else { & $c --version 2>&1 }
            if ("$out" -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) { return $c }
        } catch { }
    }
    return $null
}

$py = Find-Python
if ($py) {
    Ok "Python encontrado ($py)"
} else {
    Info "Python nao encontrado - instalando via winget..."
    try {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements --silent | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
        $py = Find-Python
        if ($py) { Ok "Python instalado" } else { Falha "Python instalado mas nao detectado - reabra o setup" }
    } catch {
        Falha "Nao consegui instalar o Python: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------- 2. Pre-requisitos
Passo 2 "Baixando pre-requisitos"

New-Item -ItemType Directory -Path $prereqDir -Force | Out-Null
$downloads = @(
    @{ Nome = "VC++ Redist";      Url = "https://aka.ms/vs/17/release/vc_redist.x64.exe";                    Arq = "vc_redist.x64.exe" }
    @{ Nome = ".NET Desktop 8";   Url = "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe";      Arq = "windowsdesktop-runtime-8.0-x64.exe" }
    @{ Nome = ".NET Desktop 6";   Url = "https://aka.ms/dotnet/6.0/windowsdesktop-runtime-win-x64.exe";      Arq = "windowsdesktop-runtime-6.0-x64.exe" }
    @{ Nome = "PawnIO";           Url = "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe"; Arq = "PawnIO_setup.exe" }
)

foreach ($d in $downloads) {
    $destino = Join-Path $prereqDir $d.Arq
    if (Test-Path $destino) { Ok "$($d.Nome) ja baixado"; continue }
    try {
        Info "Baixando $($d.Nome)..."
        Invoke-WebRequest -Uri $d.Url -OutFile $destino -UseBasicParsing
        Ok "$($d.Nome) baixado"
    } catch {
        Falha "Download de $($d.Nome) falhou: $($_.Exception.Message)"
    }
}

# --------------------------------------------------------- 3. Instalar prereqs
Passo 3 "Instalando pre-requisitos (silencioso)"

$instaladores = @(
    @{ Nome = "VC++ Redist";    Arq = "vc_redist.x64.exe";                  Args = @("/install", "/quiet", "/norestart") }
    @{ Nome = ".NET Desktop 8"; Arq = "windowsdesktop-runtime-8.0-x64.exe"; Args = @("/install", "/quiet", "/norestart") }
    @{ Nome = ".NET Desktop 6"; Arq = "windowsdesktop-runtime-6.0-x64.exe"; Args = @("/install", "/quiet", "/norestart") }
    @{ Nome = "PawnIO";         Arq = "PawnIO_setup.exe";                   Args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") }
)

foreach ($i in $instaladores) {
    $exe = Join-Path $prereqDir $i.Arq
    if (-not (Test-Path $exe)) { Falha "$($i.Nome): instalador ausente"; continue }
    try {
        Info "Instalando $($i.Nome)..."
        $p = Start-Process $exe -ArgumentList $i.Args -Wait -PassThru
        switch ($p.ExitCode) {
            0     { Ok "$($i.Nome) instalado" }
            3010  { Ok "$($i.Nome) instalado (requer reiniciar)" }
            1638  { Ok "$($i.Nome) ja estava instalado" }
            default {
                Write-Host "  [!]    $($i.Nome) retornou codigo $($p.ExitCode) - pode precisar instalar manualmente em prereqs\" -ForegroundColor Yellow
            }
        }
    } catch {
        Falha "$($i.Nome): $($_.Exception.Message)"
    }
}

# ------------------------------------------------------------ 4. Ambiente Python
Passo 4 "Criando ambiente Python e instalando dependencias"

if ($py) {
    try {
        if (-not (Test-Path $venvPy)) {
            Info "Criando .venv..."
            if ($py -eq "py") { & py -3 -m venv $venv } else { & python -m venv $venv }
        } else {
            Ok ".venv ja existe"
        }

        if (Test-Path $venvPy) {
            Info "Atualizando pip..."
            & $venvPy -m pip install --upgrade pip --quiet
            $req = Join-Path $root "requirements.txt"
            if (Test-Path $req) {
                Info "Instalando dependencias (pode demorar)..."
                & $venvPy -m pip install -r $req --quiet
                Ok "Dependencias instaladas"
            } else {
                Falha "requirements.txt nao encontrado"
            }
        } else {
            Falha "Falha ao criar o .venv"
        }
    } catch {
        Falha "Ambiente Python: $($_.Exception.Message)"
    }
} else {
    Falha "Sem Python - etapa pulada"
}

# --------------------------------------------------------------- 5. Atalho
Passo 5 "Criando atalho na area de trabalho"

try {
    $runBat = Join-Path $root "run.bat"
    if (Test-Path $runBat) {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut((Join-Path $desktop "DBX Stats.lnk"))
        $lnk.TargetPath = $runBat
        $lnk.WorkingDirectory = $root
        $icone = Join-Path $root "assets\icon.ico"
        if (Test-Path $icone) { $lnk.IconLocation = $icone }
        $lnk.Save()
        Ok "Atalho 'DBX Stats' criado"
    } else {
        Falha "run.bat nao encontrado"
    }
} catch {
    Falha "Atalho: $($_.Exception.Message)"
}

# --------------------------------------------------------------- Resumo
Write-Host ""
Write-Host "=============================================" -ForegroundColor DarkCyan
if ($falhas.Count -eq 0) {
    Write-Host " INSTALACAO CONCLUIDA COM SUCESSO" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor DarkCyan
    Write-Host ""
    Write-Host " Abra pelo atalho 'DBX Stats' na area de trabalho." -ForegroundColor White
    Write-Host " (o app se eleva sozinho - precisa de admin para sensores e FPS)" -ForegroundColor DarkGray
} else {
    Write-Host " CONCLUIDO COM $($falhas.Count) PROBLEMA(S)" -ForegroundColor Yellow
    Write-Host "=============================================" -ForegroundColor DarkCyan
    foreach ($f in $falhas) { Write-Host "  - $f" -ForegroundColor Red }
    Write-Host ""
    Write-Host " Os instaladores estao em: $prereqDir" -ForegroundColor White
}
Write-Host ""
Read-Host "Pressione ENTER para fechar"
