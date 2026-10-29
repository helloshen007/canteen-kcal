$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
function Run-Docker {
    param([string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed. Check the message above.' }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Install and start Docker Desktop first: https://www.docker.com/products/docker-desktop/'
    exit 1
}
Run-Docker -Arguments @('info', '--format', '{{.OSType}}')
$ram = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
if ($ram -lt 15GB) {
    throw 'Local vision models need approximately 16 GB system RAM. No paid service will be enabled automatically.'
}
$compose = @('compose', '-p', 'canteen-free', '-f', 'compose.yaml', '-f', 'deploy/free/compose.yaml')
Write-Host 'Starting local-only models. First setup downloads several GB; no hosting subscription or paid API is used.'
Run-Docker -Arguments ($compose + @('up', '--build', '-d'))
Run-Docker -Arguments ($compose + @('run', '--rm', 'worker', 'python', '-m', 'web.prepare_models'))
Run-Docker -Arguments ($compose + @('exec', '-T', 'ollama', 'ollama', 'pull', 'qwen2.5vl:3b'))
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8090/api/health'
        if ($health.status -eq 'ok') { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) { throw 'Local application is not ready. Run docker compose logs for details.' }
# Obtain an official Windows build and verify GitHub's published artifact digest.
$headers = @{ 'User-Agent' = 'canteen-kcal-public-launcher'; 'Accept' = 'application/vnd.github+json' }
$release = Invoke-RestMethod 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest' -Headers $headers
$asset = $release.assets | Where-Object { $_.name -eq 'cloudflared-windows-amd64.exe' } | Select-Object -First 1
if (-not $asset -or $asset.digest -notmatch '^sha256:[a-f0-9]{64}$') {
    throw 'Official artifact digest is unavailable. Refusing to execute an unverified tunnel client.'
}
$tools = Join-Path $env:LOCALAPPDATA 'canteen-kcal/tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$binary = Join-Path $tools 'cloudflared.exe'
$expected = $asset.digest.Substring(7)
if (-not (Test-Path $binary) -or (Get-FileHash $binary -Algorithm SHA256).Hash.ToLower() -ne $expected) {
    Invoke-WebRequest $asset.browser_download_url -OutFile "$binary.download" -UseBasicParsing
    if ((Get-FileHash "$binary.download" -Algorithm SHA256).Hash.ToLower() -ne $expected) {
        Remove-Item "$binary.download"
        throw 'Tunnel client checksum mismatch.'
    }
    Move-Item -Force "$binary.download" $binary
}
Write-Host 'Keep this window and the computer running. Share the actual https://...trycloudflare.com URL printed below.'
Write-Host 'A link is usable only after an external browser can open it. Closing this tunnel removes the temporary link.'
& $binary tunnel --url http://127.0.0.1:8090 --protocol http2
if ($LASTEXITCODE -ne 0) { throw 'The free public tunnel could not connect on this network.' }
