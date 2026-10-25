param(
    [Parameter(Mandatory=$true)][string]$Baseline,
    [Parameter(Mandatory=$true)][string]$Candidate,
    [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference = 'Stop'
$Baseline = (Resolve-Path $Baseline).Path
$Candidate = (Resolve-Path $Candidate).Path
$Python = (Resolve-Path $Python).Path
$scratch = Join-Path $env:RUNNER_TEMP 'CurveMole migration test'
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:CURVEMOLE_SMOKE_TEST = '1'
$env:CURVEMOLE_PACKAGING_SMOKE = '1'
$env:MPLCONFIGDIR = Join-Path $scratch 'matplotlib'

function Build-Bundle([string]$root, [string]$onefile) {
    Push-Location $root
    try {
        New-Item -ItemType Directory -Force -Path generated-icons | Out-Null
        & $Python -c "from PIL import Image; Image.open('src/curvemole/resources/curvemole.png').save('generated-icons/curvemole.ico', sizes=[(32,32),(64,64),(256,256)])"
        if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
        $env:CURVEMOLE_ICON = Join-Path $root 'generated-icons/curvemole.ico'
        $env:CURVEMOLE_ONEFILE = $onefile
        & $Python -m PyInstaller --noconfirm --clean packaging/curvemole.spec
        if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    } finally { Pop-Location }
}

function Run-Checked([string]$file, [string[]]$arguments, [int]$timeout = 180000) {
    $options = @{FilePath=$file; PassThru=$true}
    if ($arguments.Count -gt 0) { $options.ArgumentList = $arguments }
    $process = Start-Process @options
    if (-not $process.WaitForExit($timeout)) {
        Stop-Process -Id $process.Id -Force
        throw "Timed out: $file"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "$file exited with $($process.ExitCode)" }
}

Build-Bundle $Baseline '1'
Build-Bundle $Candidate '0'
$oldOutput = Join-Path $scratch 'old setup'
$newOutput = Join-Path $scratch 'new setup'
New-Item -ItemType Directory -Force -Path $oldOutput,$newOutput | Out-Null
& $iscc '/DMyAppVersion=0.0.1' "/DSourceExe=$Baseline\dist\CurveMole.exe" "/DRootDir=$Baseline" "/DOutputDir=$oldOutput" "$Baseline\packaging\windows\curvemole.iss"
if ($LASTEXITCODE -ne 0) { throw 'Baseline installer compilation failed' }
& $iscc '/DMyAppVersion=0.0.2' "/DSourceDir=$Candidate\dist\CurveMole" "/DRootDir=$Candidate" "/DOutputDir=$newOutput" "$Candidate\packaging\windows\curvemole.iss"
if ($LASTEXITCODE -ne 0) { throw 'Candidate installer compilation failed' }
$installDir = Join-Path $scratch 'installed app'
$oldSetup = (Get-ChildItem $oldOutput -Filter '*setup.exe').FullName
$newSetup = (Get-ChildItem $newOutput -Filter '*setup.exe').FullName
Run-Checked $oldSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$installDir`"")
# Postinstall launches use smoke mode; wait for their entire bootloader process tree.
Get-Process -Name CurveMole -ErrorAction SilentlyContinue | Wait-Process -Timeout 180
$exe = Join-Path $installDir 'CurveMole.exe'
Run-Checked $exe @()
$before = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
$sentinel = Join-Path $installDir 'user-project-sentinel.txt'
[System.IO.File]::WriteAllText($sentinel, 'User data must survive the update')
$settingsKey = 'HKCU:\Software\CurveMole\CurveMole'
New-Item -Path $settingsKey -Force | Out-Null
New-ItemProperty -Path $settingsKey -Name 'migration_test' -Value 'preserve-me' -Force | Out-Null
# Do not supply /DIR: Inno must discover the previous installation itself.
Run-Checked $newSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
Get-Process -Name CurveMole -ErrorAction SilentlyContinue | Wait-Process -Timeout 180
if (-not (Test-Path (Join-Path $installDir '_internal'))) { throw 'Onedir dependencies are missing' }
if (-not (Test-Path (Join-Path $installDir 'curvemole-installed.marker'))) { throw 'Installation identity lost' }
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -eq $before) { throw 'Executable was not updated' }
if ([System.IO.File]::ReadAllText($sentinel) -ne 'User data must survive the update') { throw 'User file changed' }
if ((Get-ItemProperty $settingsKey).migration_test -ne 'preserve-me') { throw 'Settings lost' }
Run-Checked $exe @()
# Compare full frozen smoke-process times (includes exit), not source import timings.
$env:CURVEMOLE_PACKAGING_SMOKE = '0'
$results = @()
for ($i = 0; $i -lt 5; $i++) {
    $labels = if ($i % 2 -eq 0) { @('onefile','onedir') } else { @('onedir','onefile') }
    foreach ($label in $labels) {
        $binary = if ($label -eq 'onefile') { "$Baseline\dist\CurveMole.exe" } else { $exe }
        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        Run-Checked $binary @()
        $timer.Stop()
        $results += [PSCustomObject]@{format=$label; sample=$i; process_seconds=$timer.Elapsed.TotalSeconds}
    }
}
$results | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Candidate 'windows-startup.json')
Write-Output 'Installed onefile-to-onedir upgrade passed; user file and settings preserved.'
