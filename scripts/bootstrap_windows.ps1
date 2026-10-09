# Local runtime for run_daily.bat. Windows 10/11; no admin or system installs.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$project = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $project '.janani-runtime'
$runtime = Join-Path $runtimeRoot 'current'
$platform = if ([Environment]::Is64BitOperatingSystem) { 'win64' } else { 'win32' }
$pythonArch = if ($platform -eq 'win64') { 'amd64' } else { 'win32' }
$pythonVersion = '3.12.10'

function Download-File([string]$Url, [string]$Destination) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 120
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Write-Output "[SETUP] Download failed; retry $attempt of 3: $Url"
            Start-Sleep -Seconds 2
        }
    }
}

function Test-Runtime([string]$Directory) {
    $python = Join-Path $Directory 'python\python.exe'
    $chrome = Join-Path $Directory "browser\chrome-$platform\chrome.exe"
    $driver = Join-Path $Directory "browser\chromedriver-$platform\chromedriver.exe"
    if (!(Test-Path $python) -or !(Test-Path $chrome) -or !(Test-Path $driver) -or !(Test-Path (Join-Path $Directory 'ready.json'))) { return $false }
    & $python -c 'import requests, selenium, ssl; from selenium import webdriver' 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

try {
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw 'The automatic runtime requires Windows 10/11. Current Chrome does not support Windows 7/8/8.1.'
    }
    if (Test-Runtime $runtime) {
        Write-Output '[SETUP] Local Python, packages, Chrome and ChromeDriver are ready.'
        exit 0
    }
    if (!(Test-Path (Join-Path $project 'requirements.txt'))) { throw 'requirements.txt is missing. Copy the complete Janani project.' }
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    # Only one process may create/replace the shared runtime at a time.
    $lock = [IO.File]::Open((Join-Path $runtimeRoot 'setup.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    if (Test-Runtime $runtime) { exit 0 }
    $stage = Join-Path $runtimeRoot ('stage-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    Write-Output '[SETUP] First-time setup: downloading a local runtime. Internet is required; this can take several minutes.'
    Download-File "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-$pythonArch.zip" (Join-Path $stage 'python.zip')
    Expand-Archive -LiteralPath (Join-Path $stage 'python.zip') -DestinationPath (Join-Path $stage 'python')
    # Embedded Python uses an isolated relative module path. Packages stay local.
    $pth = Join-Path $stage 'python\python312._pth'
    Set-Content -LiteralPath $pth -Encoding ASCII -Value @('python312.zip', '.', 'Lib\site-packages', 'import site')
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'python\Lib\site-packages') | Out-Null
    Download-File 'https://bootstrap.pypa.io/get-pip.py' (Join-Path $stage 'get-pip.py')
    $python = Join-Path $stage 'python\python.exe'
    & $python (Join-Path $stage 'get-pip.py') --no-warn-script-location --disable-pip-version-check --no-cache-dir --target (Join-Path $stage 'python\Lib\site-packages')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install local pip. Check internet/proxy access to pypi.org and files.pythonhosted.org.' }
    & $python -m pip install --disable-pip-version-check --no-warn-script-location --no-cache-dir --only-binary=:all: --target (Join-Path $stage 'python\Lib\site-packages') -r (Join-Path $project 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install requests/Selenium and their dependencies.' }
    Write-Output '[SETUP] Downloading a matched Chrome and ChromeDriver pair.'
    Download-File 'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json' (Join-Path $stage 'chrome-versions.json')
    $stable = (Get-Content -Raw -LiteralPath (Join-Path $stage 'chrome-versions.json') | ConvertFrom-Json).channels.Stable
    foreach ($component in @('chrome', 'chromedriver')) {
        $download = @($stable.downloads.$component | Where-Object { $_.platform -eq $platform })
        if ($download.Count -ne 1) { throw "No unique stable $component download for $platform." }
        $url = [Uri]$download[0].url
        if ($url.Scheme -ne 'https' -or $url.Host -ne 'storage.googleapis.com' -or !$url.AbsolutePath.StartsWith("/chrome-for-testing-public/$($stable.version)/$platform/")) { throw 'Unexpected or mismatched browser download URL in the Chrome manifest.' }
        $zip = Join-Path $stage "$component.zip"
        Download-File $url.AbsoluteUri $zip
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $stage 'browser') -Force
    }
    @{ python = $pythonVersion; chrome = $stable.version; platform = $platform; installedAt = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'ready.json') -Encoding UTF8
    if (!(Test-Runtime $stage)) { throw 'Downloaded runtime failed its import/file checks.' }
    & (Join-Path $stage "browser\chromedriver-$platform\chromedriver.exe") --version
    if ($LASTEXITCODE -ne 0) { throw 'Downloaded ChromeDriver could not run on this computer.' }
    # Keep a previous runtime for recovery; publish only after checks pass.
    if (Test-Path $runtime) { Move-Item -LiteralPath $runtime -Destination (Join-Path $runtimeRoot ('previous-' + [Guid]::NewGuid().ToString('N'))) }
    Move-Item -LiteralPath $stage -Destination $runtime
    Write-Output '[SETUP] Complete. No system Python/Chrome install or administrator access was needed.'
    exit 0
} catch {
    Write-Output ('[SETUP ERROR] ' + $_.Exception.Message)
    Write-Output '[SETUP ERROR] Nothing was uploaded. Check network access and folder write permissions, then retry run_daily.bat.'
    exit 2
} finally {
    if ($lock) { $lock.Dispose() }
}
