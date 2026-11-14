<#
Renders a Pixlet app and pushes it to a Tidbyt in the background.

Used by the "Tidbyt - Weather Now" scheduled task, but works for any app:
  pwsh -File push_app.ps1 -App "..\apps\weather_now\weather_now.star" -InstallationId weathernow

- The API token is read from %USERPROFILE%\.tidbyt\api_token.txt (never stored in this repo).
- If rendering fails (e.g. the weather API is slow), it retries, then gives up WITHOUT
  pushing, so the device keeps showing the last good image.
- Pushes with --background so the device updates the app quietly in its rotation
  instead of interrupting whatever is on screen.
- Logs to %USERPROFILE%\.tidbyt\push.log (trimmed to the last 500 lines).
#>
param(
    [Parameter(Mandatory)] [string] $App,
    [Parameter(Mandatory)] [string] $InstallationId,
    [string] $DeviceId = "urgently-principal-smashing-hippo-90b",
    [string] $Pixlet = "C:\Pixlet\pixlet.exe",
    [int] $Attempts = 3,
    [int] $RetryDelaySeconds = 20
)

$ErrorActionPreference = "Stop"
# Kept in the user profile (not AppData), so it is the same folder no matter
# which app or sandbox launches this script.
$stateDir = Join-Path $env:USERPROFILE ".tidbyt"
$logFile = Join-Path $stateDir "push.log"
$tokenFile = Join-Path $stateDir "api_token.txt"
New-Item -ItemType Directory -Force $stateDir | Out-Null

function Write-Log([string] $msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} [{1}] {2}" -f (Get-Date), $InstallationId, $msg
    Add-Content -Path $logFile -Value $line
    Write-Output $line
}

try {
    if (-not (Test-Path $App)) { throw "App not found: $App" }
    if (-not (Test-Path $tokenFile)) { throw "Token file missing: $tokenFile" }
    $token = (Get-Content $tokenFile -Raw).Trim()
    $out = Join-Path $stateDir "$InstallationId.webp"

    $rendered = $false
    for ($i = 1; $i -le $Attempts; $i++) {
        $result = & $Pixlet render $App -o $out --silent 2>&1
        if ($LASTEXITCODE -eq 0 -and (Test-Path $out)) { $rendered = $true; break }
        Write-Log "render attempt $i failed: $(($result | Out-String).Trim() -replace '\s+', ' ')"
        if ($i -lt $Attempts) { Start-Sleep -Seconds $RetryDelaySeconds }
    }
    if (-not $rendered) {
        Write-Log "giving up this round; device keeps its last image"
        exit 1
    }

    $result = & $Pixlet push --api-token $token --installation-id $InstallationId --background $DeviceId $out 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log "push failed: $(($result | Out-String).Trim() -replace '\s+', ' ')"
        exit 1
    }
    Write-Log ("pushed OK ({0:N0} bytes)" -f (Get-Item $out).Length)
}
catch {
    Write-Log "error: $($_.Exception.Message)"
    exit 1
}
finally {
    if (Test-Path $logFile) {
        $lines = Get-Content $logFile
        if ($lines.Count -gt 500) { $lines | Select-Object -Last 500 | Set-Content $logFile }
    }
}
