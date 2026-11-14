# Tidbyt Apps: Handover

How to pick this project up on another PC: what exists, how it fits together, how to
set up a new machine, the lessons learned, and what to build next.

_Last updated: 2026-11-13 (moved to GitHub Actions)._

---

## 1. At a glance

| | |
|---|---|
| **Device** | First-generation Tidbyt (64×32 LED). Device ID `urgently-principal-smashing-hippo-90b` |
| **Toolchain** | Pixlet v0.34.0 (official Tidbyt CLI, apps written in Starlark) |
| **Project folder** | `G:\My Drive\Web Dev\Tidbyt` (Google Drive, so it syncs between PCs) |
| **Rule** | **Every app lives in its own subfolder:** `apps/<app_name>/<app_name>.star` |
| **Auto-refresh** | **GitHub Actions** in the public repo https://github.com/josetron/tidbyt-apps. No PC needed (see §4) |
| **Latest** | **MarketPulse** + **MarketPulse Stocks** (see §7); everything moved to GitHub Actions on 2026-11-13 |

---

## 2. Apps built so far

| Folder | Installation ID on device | Auto-refreshed | What it does |
|---|---|---|---|
| `apps/hello_world` | (not pushed) | no | Starter app, a greeting with a `who` setting |
| `apps/weather_now` | `weathernow` | yes | Current conditions for ZIP 78620 (Dripping Springs, TX): animated pixel-art icon, big temp, hi/lo, rotating detail line (city, condition, feels-like, humidity, wind, rain %, UV) at 2 s each |
| `apps/weather_forecast` | `weatherforecast` | yes | Location title card → 3-day forecast with mini animated icons → 24 h temperature/rain chart that draws itself |
| `apps/mona_lisa` | `monalisa` | no (static) | The user's pixel-art Mona Lisa mockup converted to 64×32 (`mockup.webp` → `mona_lisa_64x32.png`) |
| `apps/pixel_museum` | `pixelmuseum` | yes | Gallery of 10 public-domain paintings as pixel art; 3 per showing (4 s each), transitions fade / slide / wipe / pixel-dissolve / random; each refresh moves to the next 3 |
| `apps/marketpulse` | `marketpulse` | yes | SPY/QQQ/DIA (labelled ETFs): overview with arrows, %/price and sparklines, then a detail chart. See `apps/marketpulse/DESIGN.md` |
| `apps/marketpulse_stocks` | `marketpulsestocks` | yes | 6 stocks with pixel-art logos (AAPL, MSFT, NVDA, AMZN, GOOGL, HPQ; configurable), 3 cards × 5 s per refresh, alternating sets |

Every app passes `pixlet lint` and `pixlet check`. Weather and museum apps have a `manifest.yaml`
(author is a placeholder, "Tidbyt Dev", to be replaced before any community publishing).

**Data sources:** weather and ZIP geocoding both come from **Open-Meteo**, with no API key
(`api.open-meteo.com`, `geocoding-api.open-meteo.com`). Paintings came from Wikimedia
Commons (public domain), with the downloaded originals in `apps/pixel_museum/source/`.

### Debug/preview tricks built into the apps
- Weather Now: `?demo_code=95&demo_time=day` forces an icon (WMO code) and day or night.
  Codes: 0 clear, 2 partly, 3 overcast, 45 fog, 53 drizzle, 63 rain, 73 snow, 95 storm.
- Pixel Museum: `?start=3` starts at a given artwork; `?transition=wipe` and so on.

---

## 3. Tools (`tools/`)

| File | Purpose |
|---|---|
| `push_app.ps1` | Renders one app (3 tries, 20 s apart) and pushes it with `--background`. Skips the push if rendering fails, so the device keeps its last good image. Reads the token from `%USERPROFILE%\.tidbyt\api_token.txt`; logs to `%USERPROFILE%\.tidbyt\push.log` |
| `push_weather_now.vbs` | Hidden-window launcher run by the scheduled task. **Holds the list of auto-pushed apps** (`apps` array: path, installation ID). Add new apps there |
| `push_marketpulse.ps1` / `.vbs` | MarketPulse fetch + push, run every 5 min by the **"Tidbyt - MarketPulse"** task. It skips runs outside the market-hours schedule (5 min / 15 min / hourly ET). Saves the last-good snapshot to `%USERPROFILE%\.tidbyt\marketpulse_snapshot.json`. Manual: `-Force -Foreground` |
| `pixelate.py` | Converts images to 64×32 pixel art and regenerates the `ARTWORKS` block in `pixel_museum.star`. Driven by `apps/pixel_museum/artworks.json` (focus/zoom crop, modes `photo` / `pixelart` / `fit`). Needs `pip install pillow`. Run: `python tools/pixelate.py apps/pixel_museum` |

`.claude/launch.json` defines emulator servers for Claude's browser preview
(`hello_world` :8080, `weather_now` :8081, `mona_lisa` :8082, `pixel_museum` :8083,
`weather_forecast` :8084, `marketpulse` :8085, `marketpulse_stocks` :8086). Manually: `pixlet serve --watch apps/<app>/<app>.star`, then open http://localhost:8080.

---

## 4. Auto-refresh: GitHub Actions (since 2026-11-13)

The Tidbyt apps are pushed from GitHub's servers, so no PC has to stay on.
- **Repo:** https://github.com/josetron/tidbyt-apps (public). The project folder is its git working copy;
  **commit and push changes to `main`** or the cloud keeps running the old code.
- **Workflow:** `.github/workflows/tidbyt.yml` runs `tools/cloud_push.py`. Pixlet 0.34.0 is downloaded by
  `.github/actions/pixlet`.
  - Market: every 5 min on weekdays 04:00–20:00 ET, hourly otherwise.
  - Weather + Pixel Museum: every 15 min.
  - GitHub may start scheduled runs a few minutes late.
- **Secrets** (repo Settings → Secrets → Actions): `TIDBYT_API_TOKEN`, `TIDBYT_DEVICE_ID`.
- **Run now:** Actions tab → Tidbyt → Run workflow (market / weather / both), or
  `gh workflow run tidbyt.yml -f group=both`.
- The MarketPulse last-good snapshot is kept in the Actions cache. The stocks page alternates by run number.
- **Keepalive:** the hourly job re-enables the workflow, because GitHub disables schedules after 60 days without commits.
- **gh on this PC:** sign-in is stored in `%USERPROFILE%\.config\gh` (set `GH_CONFIG_DIR` to that), because
  Claude's shells can't read AppData or Credential Manager. gh is at `C:\Program Files\GitHub CLI\gh.exe`.
- **Old PC tasks** "Tidbyt - Weather Now" and "Tidbyt - MarketPulse" are **disabled**, not deleted. Their scripts
  (`push_app.ps1`, `push_*.vbs`, `push_marketpulse.ps1`) remain as a local fallback.
  **Never enable them while the workflow runs**, or the device gets double pushes.

## 4b. Setting up a new PC (only needed to develop; the cloud does the pushing)

1. **Install Pixlet:** download `pixlet_0.34.0_windows_amd64.tar.gz` from
   https://github.com/tidbyt/pixlet/releases, extract `pixlet.exe` to `C:\Pixlet\`, and add
   that folder to the user `Path`. Check with `pixlet version`.
2. **Python + Pillow** (only for `pixelate.py`): `pip install pillow`.
3. **PowerShell 7** (`pwsh`) is used by the push script: `winget install Microsoft.PowerShell`.
4. **API token:** in the Tidbyt phone app go to device → Settings → General → **Get API Key**.
   Save **only the token** to `C:\Users\<you>\.tidbyt\api_token.txt`. **Never put it in this
   Drive folder.** The token is not in this document on purpose.
   - If the user name isn't `josec`, update the paths in `push_weather_now.vbs` if needed.
     It uses the `G:\My Drive\...` root, so Google Drive for desktop must mount as `G:`.
5. **Scheduled task** (run once in PowerShell, as the user, not elevated):
   ```powershell
   $action = New-ScheduledTaskAction -Execute "C:\WINDOWS\system32\wscript.exe" -Argument '//B //NoLogo "G:\My Drive\Web Dev\Tidbyt\tools\push_weather_now.vbs"'
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
   $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
   Register-ScheduledTask -TaskName "Tidbyt - Weather Now" -Action $action -Trigger $trigger -Settings $settings
   ```
   Then test it with `Start-ScheduledTask -TaskName "Tidbyt - Weather Now"` and check `~\.tidbyt\push.log`.
   **Only one PC should run this task.** Disable it on the old PC so both don't push.
6. The task only runs while that PC is **on and logged in**. Closing the lid (sleep) stops it.

---

## 5. Hard-won lessons (read before building)

**Gen 1 display**
- **15-second cap.** An app's whole animation must stay under 15 s
  (`pixlet render --max_duration` defaults to 15000 ms). Verify it: render a GIF and sum the
  frame durations. Budget the frames: `frames × delay ≤ 15000`.
- **Very dark colours vanish** on Gen 1 LEDs. Keep "dim" UI colours brighter than about `#303030`.
- Pixlet's WebP is lossy, and near-black noise (values 1–24) appears in the browser
  preview but is invisible on the device. Ignore it.
- Keep pushes small (these apps are 30–80 KB).
- WebP merges identical frames, so frame counts in the `.webp` differ from the real
  frame count. Use `--gif` output to inspect frames.

**Starlark/Pixlet gotchas**
- Strings aren't iterable: use `s.elems()`.
- `%` formatting has **no width or zero-pad** (`%02x` fails). Build hex by hand (see `hex2()` in pixel_museum).
- Adjacent string literals don't concatenate. Join them with `+`.
- No `while`, no `try/except`. An `http.get` timeout **crashes** the app (it can't be caught);
  `push_app.ps1` retries for this reason. Open-Meteo occasionally takes several seconds.
- Useful facts found by testing: `render.Box` **clips** its child (centred); **negative
  padding works** (shifts content), which is how `crop()` in pixel_museum cuts regions;
  `animation.Transformation` translate works; `render.Animation` loops shorter children
  (frame index modulo); `render.Image` accepts SVG text, which the weather apps use to
  draw their icons procedurally.
- `pixlet lint` flags formatting: run `pixlet format <file>` first. `pixlet check` needs
  `manifest.yaml`, and its `summary` must start with a capital letter (max 27 chars).

**Claude Code environment**
- Claude's sandboxed shells **redirect writes to `%LOCALAPPDATA%`** into a private copy that
  Windows can't see, even with the sandbox disabled. That's why the token and log live in
  `%USERPROFILE%\.tidbyt\`. Shared state must not go in AppData.
- To test the scheduled task for real, run `Start-ScheduledTask` from the **user's terminal
  panel** (outside the sandbox), not from Claude's shell.
- `conhost --headless` didn't launch anything from Task Scheduler. Use the `wscript` + `.vbs`
  launcher (no window flash).
- Running many renders in parallel caused API timeouts. Render 2 at a time at most.

---

## 6. Typical workflow for a new app

1. `mkdir apps/<name>`, write `<name>.star` (+ `manifest.yaml`).
2. `pixlet serve --watch apps/<name>/<name>.star` to preview (or add an entry to `.claude/launch.json`).
3. `pixlet format`, `pixlet lint`, `pixlet check`, and render a GIF to check frames and total duration.
4. First push in the foreground so it shows right away:
   `pixlet push --api-token <token> --installation-id <id> urgently-principal-smashing-hippo-90b <name>.webp`
5. If the data changes, add `"apps\<name>\<name>.star", "<id>"` to the `apps` array in
   `tools/push_weather_now.vbs`. It refreshes every 15 min from then on.

---

## 7. MarketPulse (live since 2026-11-13)

Two apps, both 14.4–15 s. The full design and refresh rules are in **`apps/marketpulse/DESIGN.md`**.
- `marketpulse`: SPY/QQQ/DIA (always labelled as ETFs), overview + detail chart.
- `marketpulsestocks`: AAPL, MSFT, NVDA, AMZN, GOOGL, HPQ with pixel-art logos, 3 cards × 5 s per push, alternating sets.
- **Data:** Yahoo Finance spark endpoint (unofficial, no key, needs a browser User-Agent). The push script fetches;
  the apps only render the `snapshot` config, because Yahoo has taken 12 s and Pixlet can't catch timeouts.
  STALE shows when data is over 15 min old during a session.
- **Scheduled task "Tidbyt - MarketPulse"** (every 5 min) → `tools/push_marketpulse.vbs`. On a new PC, register it
  like the weather task (§4), pointing at that .vbs, with `-RepetitionInterval (New-TimeSpan -Minutes 5)` and
  `-ExecutionTimeLimit (New-TimeSpan -Minutes 4)`.
- Claude's sandboxed shells can't see PowerShell 7. Run pwsh scripts and `Register-ScheduledTask` with the sandbox disabled.

Show prices and movement only. No buy/sell suggestions.
