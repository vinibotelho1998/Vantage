# Gera o instalador do DBX Stats a partir de um clone limpo.
#
# Funciona em qualquer maquina: usa o Python que encontrar, monta um ambiente
# proprio, baixa o que falta (PyInstaller, pre-requisitos, Inno Setup) e entrega
# um unico arquivo em dist\DBXStats-Setup.exe, que e' o que se manda para outra
# pessoa. Nao instala nada no sistema nem depende de nada estar configurado.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# -SemInstalador para so' gerar a pasta dist\DBXStats (util para testar rapido).
#
# Sem acentos de proposito: o PowerShell 5.1 le .ps1 como ANSI e um caractere
# fora do ASCII quebra o parser inteiro na maquina de quem for compilar.
param([switch]$SemInstalador)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv-build"
$py   = Join-Path $venv "Scripts\python.exe"

function Passo($txt) {
    Write-Host ""
    Write-Host "== $txt" -ForegroundColor Cyan
}
function Ok($txt)   { Write-Host "   ok    $txt" -ForegroundColor Green }
function Info($txt) { Write-Host "   ..    $txt" -ForegroundColor DarkGray }

# ------------------------------------------------------------------ Python
Passo "Procurando Python 3.10 ou mais novo"
$base = $null
foreach ($candidato in @(@("py", "-3"), @("python", ""))) {
    $cmd = Get-Command $candidato[0] -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    if ($candidato[1]) { $versaoPy = & $candidato[0] $candidato[1] --version 2>&1 }
    else { $versaoPy = & $candidato[0] --version 2>&1 }
    if ("$versaoPy" -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) {
        $base = $candidato
        Ok "$versaoPy"
        break
    }
}
if (-not $base) {
    throw "Python 3.10+ nao encontrado. Instale de python.org (marque 'Add to PATH') e rode de novo."
}

# ------------------------------------------------------- Ambiente de build
Passo "Preparando ambiente de build"
if (-not (Test-Path $py)) {
    Info "criando $venv"
    if ($base[1]) { & $base[0] $base[1] -m venv $venv } else { & $base[0] -m venv $venv }
}
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r (Join-Path $root "requirements.txt") --quiet
& $py -m pip install pyinstaller --quiet
Ok "dependencias prontas"

$initPy = Join-Path $root "src\dbxstats\__init__.py"
$versao = (Select-String -Path $initPy -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Ok "versao do app: $versao"

# --------------------------------------------------------------- Empacotar
Passo "Empacotando com PyInstaller (demora alguns minutos)"
Push-Location $root
try {
    & $py -m PyInstaller (Join-Path $PSScriptRoot "DBXStats.spec") `
        --noconfirm --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou (codigo $LASTEXITCODE)" }
} finally {
    Pop-Location
}
$appDir = Join-Path $root "dist\DBXStats"
if (-not (Test-Path (Join-Path $appDir "DBXStats.exe"))) { throw "DBXStats.exe nao foi gerado" }
Ok "app em dist\DBXStats"

if ($SemInstalador) {
    Write-Host ""
    Write-Host "Pronto (sem instalador): $appDir" -ForegroundColor Green
    return
}

# ------------------------------------------------------------ Pre-requisitos
Passo "Baixando pre-requisitos que vao dentro do instalador"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "prepare_prereqs.ps1")

# -------------------------------------------------------------- Inno Setup
# O link direto do site do Inno Setup passa por uma pagina intermediaria e
# devolve HTML no lugar do instalador. O winget resolve isso e ja' vem no
# Windows 10/11, entao e' por ele que a instalacao acontece.
function Find-Iscc {
    @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

Passo "Procurando o Inno Setup"
$iscc = Find-Iscc
if (-not $iscc) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "nao encontrado; instalando via winget"
        & winget install --id JRSoftware.InnoSetup -e --silent `
            --accept-source-agreements --accept-package-agreements | Out-Null
        $iscc = Find-Iscc
    }
}
if (-not $iscc) {
    throw ("Inno Setup 6 nao encontrado. Instale de https://jrsoftware.org/isdl.php " +
           "e rode de novo, ou use 'packaging\build.ps1 -SemInstalador' para gerar " +
           "so' a pasta dist\DBXStats.")
}
Ok (Split-Path $iscc -Parent)

# -------------------------------------------------------------- Instalador
Passo "Compilando o instalador"
& $iscc "/DMyAppVersion=$versao" (Join-Path $PSScriptRoot "DBXStats_Setup.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou (codigo $LASTEXITCODE)" }

$saida = Join-Path $root "dist\DBXStats-Setup.exe"
$tamanho = [math]::Round((Get-Item $saida).Length / 1MB, 1)
Write-Host ""
Write-Host "=====================================================" -ForegroundColor DarkCyan
Write-Host " INSTALADOR PRONTO - versao $versao ($tamanho MB)" -ForegroundColor Green
Write-Host " $saida" -ForegroundColor White
Write-Host "=====================================================" -ForegroundColor DarkCyan
Write-Host " Esse arquivo e' tudo que a outra pessoa precisa." -ForegroundColor Gray
Write-Host " Nao exige Python, nem o repositorio, nem configurar nada." -ForegroundColor Gray
