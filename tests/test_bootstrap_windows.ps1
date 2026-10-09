# Cross-platform bootstrap flow tests with fake downloads/executables.
# Run with pwsh -NoProfile -File tests/test_bootstrap_windows.ps1
# Native Windows BAT execution/browser startup still require a Windows machine.
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Archive
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/bootstrap_windows.ps1'
$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
if ($IsWindows) { throw 'This fixture uses Linux shell executables. Run this smoke test with PowerShell on Linux.' }
$root = Join-Path ([IO.Path]::GetTempPath()) ('janani-bootstrap-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$global:jananiFixtureDownloads = 0
$global:jananiFixtureFailDownload = $false
function Start-Sleep { param($Seconds) }
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    $global:jananiFixtureDownloads++
    if ($global:jananiFixtureFailDownload) { throw 'Fixture: blocked network' }
    if ($Uri -like '*versions-with-downloads.json') {
        $data = @{ channels = @{ Stable = @{ version = '123.0.0.1'; downloads = @{
            chrome = @(@{ platform = 'win64'; url = 'https://storage.googleapis.com/chrome-for-testing-public/123.0.0.1/win64/chrome-win64.zip' });
            chromedriver = @(@{ platform = 'win64'; url = 'https://storage.googleapis.com/chrome-for-testing-public/123.0.0.1/win64/chromedriver-win64.zip' })
        } } } }
        $data | ConvertTo-Json -Depth 8 | Set-Content $OutFile
    } elseif ($Uri -like '*get-pip.py') {
        Set-Content $OutFile '# Fixture only'
    } else {
        $zipSource = Join-Path $root ([Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $zipSource | Out-Null
        if ($Uri -like '*embed*') {
            Set-Content (Join-Path $zipSource 'python.exe') "#!/bin/sh`nexit 0" -Encoding utf8NoBOM
            Set-Content (Join-Path $zipSource 'python312._pth') '# Fixture'
        } else {
            $name = if ($Uri -like '*chromedriver*') { 'chromedriver' } else { 'chrome' }
            $directory = Join-Path $zipSource "$name-win64"
            New-Item -ItemType Directory -Path $directory | Out-Null
            Set-Content (Join-Path $directory "$name.exe") "#!/bin/sh`nexit 0" -Encoding utf8NoBOM
        }
        Compress-Archive -Path (Join-Path $zipSource '*') -DestinationPath $OutFile
    }
}
function Expand-Archive {
    param($LiteralPath, $DestinationPath, [switch]$Force)
    Microsoft.PowerShell.Archive\Expand-Archive -LiteralPath $LiteralPath -DestinationPath $DestinationPath -Force
    Get-ChildItem $DestinationPath -Recurse -Filter '*.exe' | ForEach-Object { & chmod +x $_.FullName }
}
function New-Fixture([string]$Name) {
    $project = Join-Path $root $Name
    New-Item -ItemType Directory -Path (Join-Path $project 'scripts') -Force | Out-Null
    Set-Content (Join-Path $project 'requirements.txt') 'requests'
    # Bypass only the OS gate, so the unchanged setup flow can run on Linux.
    $body = (Get-Content -Raw $source).Replace('if ([Environment]::OSVersion.Version.Major -lt 10)', 'if ($false)')
    Set-Content (Join-Path $project 'scripts/bootstrap_windows.ps1') $body
    return $project
}
function Assert([bool]$Condition, [string]$Message) { if (!$Condition) { throw $Message } }
$project = New-Fixture 'first-run'
& (Join-Path $project 'scripts/bootstrap_windows.ps1')
Assert ($LASTEXITCODE -eq 0) 'First-time setup failed'
Assert ($global:jananiFixtureDownloads -eq 5) 'Expected exactly five download requests'
Assert (Test-Path (Join-Path $project '.janani-runtime/current/ready.json')) 'Runtime was not published'
$pth = Get-Content -Raw (Join-Path $project '.janani-runtime/current/python/python312._pth')
Assert ($pth.Contains('Lib\site-packages') -and $pth.Contains('import site')) 'Embedded Python module paths were not configured'
& (Join-Path $project 'scripts/bootstrap_windows.ps1')
Assert ($LASTEXITCODE -eq 0) 'Cached setup failed'
Assert ($global:jananiFixtureDownloads -eq 5) 'Cached runtime must not download anything'
$failed = New-Fixture 'failed-run'
$global:jananiFixtureFailDownload = $true
& (Join-Path $failed 'scripts/bootstrap_windows.ps1')
Assert ($LASTEXITCODE -eq 2) 'Blocked downloads must return setup failure'
Assert (!(Test-Path (Join-Path $failed '.janani-runtime/current/ready.json'))) 'Failed setup published a runtime'
Write-Output 'PASS: syntax, first setup, cached reuse, module paths, and blocked-download failure. No Windows binaries were executed.'
