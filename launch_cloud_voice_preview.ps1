param([switch]$SetupOnly)
$ErrorActionPreference = 'Stop'
$previewRoot = $PSScriptRoot
$probeScript = Join-Path $previewRoot 'program\preview_python_check.py'
if (-not (Test-Path $probeScript)) { throw 'Preview files are incomplete. Extract the entire ZIP first.' }

function Find-PreviewPython {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.12', '-3.11')) {
            try {
                $rawValue = & $launcher.Source $version -I $probeScript 2>$null
                if ($LASTEXITCODE -eq 0 -and $rawValue) {
                    $value = ConvertFrom-Json -InputObject ([string]$rawValue)
                    if (Test-Path ([string]$value)) { return [string]$value }
                }
            } catch { }
        }
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe')
    )
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps') { $candidates += $command.Source }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            $rawValue = & $candidate -I $probeScript 2>$null
            if ($LASTEXITCODE -eq 0 -and $rawValue) {
                $value = ConvertFrom-Json -InputObject ([string]$rawValue)
                if (Test-Path ([string]$value)) { return [string]$value }
            }
        } catch { }
    }
    return $null
}

try {
    $basePython = Find-PreviewPython
    if (-not $basePython) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Python 3.12 and winget were not found. No installed Studio files were changed.' }
        Write-Host 'Preparing 64-bit Python 3.12 for the independent preview...'
        & $winget.Source install --exact --id Python.Python.3.12 --source winget --scope user --accept-package-agreements --accept-source-agreements --silent
        if ($LASTEXITCODE -ne 0) { throw 'Python preparation failed.' }
        $basePython = Find-PreviewPython
        if (-not $basePython) { throw 'Python was installed but could not be validated. Close this window and run the preview again.' }
    }
    $runtimeDir = Join-Path $previewRoot '.preview_runtime'
    $runtimePython = Join-Path $runtimeDir 'Scripts\python.exe'
    $healthy = $false
    if ((Test-Path $runtimePython) -and (Test-Path (Join-Path $runtimeDir 'pyvenv.cfg'))) {
        try {
            & $runtimePython -I $probeScript *> $null
            $healthy = $LASTEXITCODE -eq 0
        } catch { $healthy = $false }
    }
    if (-not $healthy) {
        if (Test-Path $runtimeDir) {
            $backupDir = $runtimeDir + '.failed_' + [DateTime]::UtcNow.ToString('yyyyMMddHHmmss')
            Move-Item -LiteralPath $runtimeDir -Destination $backupDir
        }
        & $basePython -m venv $runtimeDir
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the independent Python environment.' }
    }
    $requirements = Join-Path $previewRoot 'preview_requirements.txt'
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash.Substring(0,16)
    $marker = Join-Path $runtimeDir ('setup_' + $digest + '.ok')
    if (-not (Test-Path $marker)) {
        Write-Host 'Preparing Kaggle client dependencies. No TTS model is installed on this PC.'
        & $runtimePython -m pip install --only-binary=:all: -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Client dependency installation did not finish.' }
        & $runtimePython -m kaggle --version
        if ($LASTEXITCODE -ne 0) { throw 'Kaggle client import check failed.' }
        & $runtimePython (Join-Path $previewRoot 'program\cloud_voice_preview.py') --setup-only
        if ($LASTEXITCODE -ne 0) { throw 'Media tool setup did not finish.' }
        Set-Content -LiteralPath $marker -Value 'ready' -Encoding ASCII
    }
    if ($SetupOnly) {
        Write-Host 'Independent preview setup completed.'
        exit 0
    }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'YangNing Voice Cloud Preview.lnk'
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = Join-Path $previewRoot 'START_CLOUD_VOICE_PREVIEW.bat'
        $shortcut.WorkingDirectory = $previewRoot
        $shortcut.Description = 'YangNing independent cloud voice preview'
        $shortcut.Save()
    } catch { Write-Host 'Desktop shortcut was not created; START_CLOUD_VOICE_PREVIEW.bat remains available.' }
    & $runtimePython (Join-Path $previewRoot 'program\cloud_voice_preview.py')
    if ($LASTEXITCODE -ne 0) { throw 'Preview launch failed. See the preceding error.' }
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message)
    exit 1
}
