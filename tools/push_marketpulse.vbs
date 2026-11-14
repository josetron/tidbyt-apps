' Pushes MarketPulse + MarketPulse Stocks with no visible window.
' Called every 5 minutes by the "Tidbyt - MarketPulse" scheduled task; push_marketpulse.ps1
' itself decides (by New York time) whether this run fetches and pushes.
Dim shell, rc
Set shell = CreateObject("WScript.Shell")
rc = shell.Run("""C:\Program Files\PowerShell\7\pwsh.exe"" -NoProfile -NonInteractive -ExecutionPolicy Bypass" & _
               " -File ""G:\My Drive\Web Dev\Tidbyt\tools\push_marketpulse.ps1""", 0, True)
WScript.Quit rc
