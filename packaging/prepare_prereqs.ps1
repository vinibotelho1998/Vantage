$ErrorActionPreference = "Stop"

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$repoRoot = Split-Path -Parent $scriptDir
$prereqDir = Join-Path $repoRoot "prereqs"
New-Item -ItemType Directory -Path $prereqDir -Force | Out-Null

$files = @(
    @{ Url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"; Out = (Join-Path $prereqDir "vc_redist.x64.exe") },
    @{ Url = "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe"; Out = (Join-Path $prereqDir "windowsdesktop-runtime-8.0-x64.exe") },
    @{ Url = "https://aka.ms/dotnet/6.0/windowsdesktop-runtime-win-x64.exe"; Out = (Join-Path $prereqDir "windowsdesktop-runtime-6.0-x64.exe") },
    @{ Url = "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe"; Out = (Join-Path $prereqDir "PawnIO_setup.exe") }
)

foreach ($f in $files) {
    if (Test-Path $f.Out) {
        Write-Host ("Ja existe: " + $f.Out)
        continue
    }

    Write-Host ("Baixando: " + $f.Url)
    Invoke-WebRequest -Uri $f.Url -OutFile $f.Out -UseBasicParsing
}

Write-Host "Dependencias prontas."
