' Pushes the auto-refreshing apps (weather + Pixel Museum) to the Tidbyt with no visible window.
' Called every 15 minutes by the "Tidbyt - Weather Now" scheduled task.
' Each app is pushed by push_app.ps1 (render with retries, then background push).
Dim shell, root, apps, i, rc, worst
Set shell = CreateObject("WScript.Shell")
root = "G:\My Drive\Web Dev\Tidbyt"

' Pairs of: app path (relative to root), installation ID on the device
apps = Array( _
    "apps\weather_now\weather_now.star", "weathernow", _
    "apps\weather_forecast\weather_forecast.star", "weatherforecast", _
    "apps\pixel_museum\pixel_museum.star", "pixelmuseum" _
)

worst = 0
For i = 0 To UBound(apps) Step 2
    rc = shell.Run("""C:\Program Files\PowerShell\7\pwsh.exe"" -NoProfile -NonInteractive -ExecutionPolicy Bypass" & _
                   " -File """ & root & "\tools\push_app.ps1""" & _
                   " -App """ & root & "\" & apps(i) & """" & _
                   " -InstallationId " & apps(i + 1), 0, True)
    If rc > worst Then worst = rc
Next

' Non-zero if any app failed, so Task Scheduler's "Last Run Result" shows it
WScript.Quit worst
