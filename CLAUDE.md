# Tidbyt apps project

**Start by reading [HANDOVER.md](HANDOVER.md).** It covers the apps built so far, the tools,
new-PC setup, hard-won lessons (Gen 1 limits, Starlark gotchas, sandbox/AppData pitfall)
and the next project (**MarketPulse**).

Standing rules from the user:
- Every Tidbyt app goes in **its own subfolder**: `apps/<app_name>/<app_name>.star`.
- Target device is a **Gen 1 Tidbyt**: animations ≤ 15 s total; keep dim colours above ~#303030.
- The Tidbyt API token lives in `%USERPROFILE%\.tidbyt\api_token.txt`. Never copy it into this folder.
- Apps that need fresh data get added to the `apps` array in `tools/push_weather_now.vbs`
  (15-minute scheduled task "Tidbyt - Weather Now").
- Before finishing an app: `pixlet format`, `pixlet lint`, `pixlet check`, and verify the total animation length.
