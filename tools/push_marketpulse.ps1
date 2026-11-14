<#
Fetches market data once and pushes both MarketPulse apps to the Tidbyt.

Run every 5 minutes by the "Tidbyt - MarketPulse" scheduled task (via push_marketpulse.vbs).
It decides by New York time whether this run should do any work:
  Mon-Fri 09:30-16:00          every run (5 min)
  Mon-Fri 04:00-09:30, 16:00-20:00   every 15 min (pre/post market)
  otherwise                     once an hour
Use -Force to skip that check (manual runs), -Foreground to show the apps right away.

- One Yahoo Finance request covers every symbol. A good response is saved as
  %USERPROFILE%\.tidbyt\marketpulse_snapshot.json. If the fetch fails, the last good snapshot
  is rendered instead, so the apps show STALE rather than going blank.
- The apps get the data as the `snapshot` config value and never fetch themselves
  (Pixlet can't catch an HTTP timeout).
- MarketPulse Stocks shows 3 of its 6 stocks per push; page 0/1 alternates each push.
- Logs to %USERPROFILE%\.tidbyt\push.log.
#>
param(
    [switch] $Force,
    [switch] $Foreground,
    [string] $DeviceId = "urgently-principal-smashing-hippo-90b",
    [string] $Pixlet = "C:\Pixlet\pixlet.exe"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandArgumentPassing = "Standard"   # pass the JSON's quotes through to pixlet intact

$root = Split-Path $PSScriptRoot -Parent
$stateDir = Join-Path $env:USERPROFILE ".tidbyt"
$logFile = Join-Path $stateDir "push.log"
$tokenFile = Join-Path $stateDir "api_token.txt"
$snapFile = Join-Path $stateDir "marketpulse_snapshot.json"
$pageFile = Join-Path $stateDir "marketpulse_page.txt"
New-Item -ItemType Directory -Force $stateDir | Out-Null

$symbols = "SPY", "QQQ", "DIA", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "HPQ"
$apps = @(
    @{ Path = "apps\marketpulse\marketpulse.star"; Id = "marketpulse"; Paged = $false },
    @{ Path = "apps\marketpulse_stocks\marketpulse_stocks.star"; Id = "marketpulsestocks"; Paged = $true }
)

function Write-Log([string] $msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} [marketpulse] {1}" -f (Get-Date), $msg
    Add-Content -Path $logFile -Value $line
    Write-Output $line
}

function Test-ShouldRun {
    $ny = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Eastern Standard Time")
    $mins = $ny.Hour * 60 + $ny.Minute
    $weekday = $ny.DayOfWeek -ne "Saturday" -and $ny.DayOfWeek -ne "Sunday"
    if ($weekday -and $mins -ge 570 -and $mins -lt 960) { return $true }                         # regular session
    if ($weekday -and $mins -ge 240 -and $mins -lt 1200) { return ($ny.Minute % 15) -lt 5 }      # pre/post
    return $ny.Minute -lt 5                                                                       # hourly
}

function Get-Snapshot {
    $url = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=$($symbols -join ',')&range=1d&interval=5m"
    $headers = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }
    for ($i = 1; $i -le 3; $i++) {
        try {
            $r = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 25
            $quotes = [ordered]@{}
            foreach ($res in $r.spark.result) {
                $resp = $res.response | Select-Object -First 1
                if (-not $resp) { continue }
                $m = $resp.meta
                $prev = if ($m.chartPreviousClose) { $m.chartPreviousClose } else { $m.previousClose }
                if (-not $m.regularMarketPrice -or -not $prev) { continue }
                $periods = [ordered]@{}
                foreach ($name in "pre", "regular", "post") {
                    $p = $m.currentTradingPeriod.$name
                    if ($p -and $p.start) { $periods[$name] = @([long]$p.start, [long]$p.end) }
                }
                $closes = @($resp.indicators.quote[0].close | Where-Object { $null -ne $_ } | ForEach-Object { [math]::Round([double]$_, 2) })
                $quotes[$res.symbol] = [ordered]@{
                    price = [double]$m.regularMarketPrice; prev = [double]$prev
                    time = [long]$m.regularMarketTime; closes = $closes; periods = $periods
                }
            }
            if ($quotes.Count -ge 3) {
                return [ordered]@{ fetched_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); quotes = $quotes }
            }
            Write-Log "fetch attempt ${i}: only $($quotes.Count) quotes"
        }
        catch { Write-Log "fetch attempt ${i} failed: $($_.Exception.Message)" }
        if ($i -lt 3) { Start-Sleep -Seconds 10 }
    }
    return $null
}

$worst = 0
try {
    if (-not $Force -and -not (Test-ShouldRun)) { exit 0 }
    if (-not (Test-Path $tokenFile)) { throw "Token file missing: $tokenFile" }
    $token = (Get-Content $tokenFile -Raw).Trim()

    $snap = Get-Snapshot
    if ($snap) {
        $json = $snap | ConvertTo-Json -Compress -Depth 8
        Set-Content -Path $snapFile -Value $json -NoNewline
        Write-Log ("fetched {0} quotes" -f $snap.quotes.Count)
    }
    elseif (Test-Path $snapFile) {
        $json = (Get-Content $snapFile -Raw).Trim()
        Write-Log "fetch failed; rendering the last good snapshot (apps will show STALE)"
    }
    else { throw "no market data and no saved snapshot" }

    $page = 0
    if (Test-Path $pageFile) { $page = (1 - [int](Get-Content $pageFile -Raw).Trim()) }

    foreach ($app in $apps) {
        $star = Join-Path $root $app.Path
        $out = Join-Path $stateDir "$($app.Id).webp"
        $cfg = @("snapshot=$json")
        if ($app.Paged) { $cfg += "page=$page" }
        $result = & $Pixlet render $star @cfg -o $out --silent 2>&1
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $out)) {
            Write-Log "$($app.Id): render failed: $(($result | Out-String).Trim() -replace '\s+', ' ')"
            $worst = 1; continue
        }
        $pushArgs = @("push", "--api-token", $token, "--installation-id", $app.Id)
        if (-not $Foreground) { $pushArgs += "--background" }
        $result = & $Pixlet @pushArgs $DeviceId $out 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "$($app.Id): push failed: $(($result | Out-String).Trim() -replace '\s+', ' ')"
            $worst = 1; continue
        }
        $note = if ($app.Paged) { ", page $page" } else { "" }
        Write-Log ("{0}: pushed OK ({1:N0} bytes{2})" -f $app.Id, (Get-Item $out).Length, $note)
    }
    Set-Content -Path $pageFile -Value $page
}
catch {
    Write-Log "error: $($_.Exception.Message)"
    $worst = 1
}
finally {
    if (Test-Path $logFile) {
        $lines = Get-Content $logFile
        if ($lines.Count -gt 500) { $lines | Select-Object -Last 500 | Set-Content $logFile }
    }
}
exit $worst
