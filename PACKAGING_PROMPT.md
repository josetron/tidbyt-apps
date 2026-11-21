# Prompt: package my app as single-file installers (Windows .exe + Android .apk)

Copy everything below the line into a new session in the app's project. Fill in the `<...>` fields first.
Delete the Android part if the app has no Android version (or the Windows part if it has no Windows one).

---

I want this app saved as **one single file per platform** that I can copy to any device and install:
a **Windows `.exe`** and an **Android `.apk`**. Put the finished files in: **`<output folder, e.g. Z:\My Apps\<AppName>>`**.

I'm not technical: explain things in plain language, test everything yourself, and tell me plainly what
was tested and what wasn't.

## 1. What the files must contain

- **Everything the app needs to run on a clean device**, with nothing else to install: the language runtime
  (e.g. Python), all libraries and packages, helper programs the app calls (command-line tools, renderers,
  plug-ins), data files, templates, fonts, images, and anything else the app reads at run time.
- **The same configuration I use today on this PC/device**: settings files, window size/position and other
  layout choices, per-item settings, hidden/disabled items, chosen themes, etc. Find where each is stored
  (config files, `%USERPROFILE%`, `%APPDATA%`, registry, Android SharedPreferences...) and include it.
- **The keys and tokens the app uses** (API keys, access tokens), taken from where they live now.
  - If a key only exists somewhere you can't read (e.g. a GitHub Actions secret or a cloud dashboard),
    don't invent a workaround that leaks it: tell me, and if possible make the app fall back gracefully
    (for example, fetch the already-made result from the cloud instead).
  - **Never** write a key, or a file containing one, inside a git repository, especially a public one.
    Do the build work in a private folder outside the project (e.g. `%LOCALAPPDATA%\<AppName>Build`) and
    write the finished file only to the output folder. Never commit the built `.exe`/`.apk`.
  - Clean up afterwards: delete build staging folders and any temporary unpack folders that hold the keys.
- On a new device, the bundled settings and keys are a **starting point** ("seed"): copy each into place on
  the first run **only if it isn't there already**. Never overwrite a device's own existing settings.

## 2. Version in the file name

- Add **one version number** to the code (e.g. `VERSION = "1.0.0"`) and use it everywhere: the Windows
  file name, the Android `versionName` (plus a matching `versionCode`, e.g. 1.2.3 → 10203), the app's
  window/setup title and its log.
- File names: **`<AppName>-<version>-windows.exe`** and **`<AppName>-<version>-android.apk`**
  (or `-androidtv.apk` for a TV app).
- Raise the version every time you rebuild with a change, so old and new files can't be confused. When a
  new version is in the output folder, ask me whether to delete the older files.

## 3. Windows `.exe`: first-run setup (install or portable)

The first time the `.exe` is opened on a PC, show a small setup window that asks:

1. **Install it** or **Portable**:
   - *Install*: copies the program into an install folder and adds shortcuts. Afterwards I can delete
     the downloaded file.
   - *Portable*: runs from where the file is; nothing is installed, no shortcuts, no registry entries.
2. **Install folder** (with a Browse button). Default: `%LOCALAPPDATA%\Programs\<AppName>`, which needs no
   administrator rights. Greyed out in Portable mode.
3. **Data folder** (with a Browse button): where the app keeps keys, settings, cached data and output.
   Default: `%LOCALAPPDATA%\<AppName>` when installed, or a `<AppName> data` folder next to the file when
   portable. Picking an existing data folder keeps its settings (that's how an update or reinstall keeps
   everything).
4. Tick boxes (install mode only): **Desktop shortcut** (on), **Start menu shortcut** (on),
   **Start with Windows** (off).
5. Button: **Install and start** (or **Start** in Portable mode), and **Cancel**.

Details that must be right:

- Save the choices in a small file next to the program (e.g. `<AppName>.json` with the data folder and
  portable flag), so later starts skip the setup window and go straight to the app.
- Find the **real Desktop folder** with the Windows API (SHGetFolderPath / `[Environment]::GetFolderPath`):
  OneDrive often moves it, so `%USERPROFILE%\Desktop` is not reliable.
- Running a newer version's `.exe` acts as an **update**: same defaults, it replaces the older program
  file in the install folder, updates the shortcuts and keeps the data folder. Close a running older copy
  first (only copies in the install folder, never the setup process itself).
- If the app is **already running**, a second start must show a message saying so ("look in the
  notification area"), not silently do nothing.
- If the app keeps a window position, make sure a position saved on a bigger or second monitor falls back
  to a visible spot on a smaller screen.

## 4. Windows uninstall

- Register the installed copy under **Windows Settings → Apps → Installed apps** (per-user registry key
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\<AppName>` with DisplayName, DisplayVersion,
  Publisher, DisplayIcon, InstallLocation, `UninstallString = "<exe>" --uninstall`, NoModify, NoRepair).
- Add an **"Uninstall <AppName>"** entry to the Start menu that runs the same `--uninstall`.
- Uninstall asks **"Remove <AppName> from this PC?"**, then **"Also delete its data folder?"** (No keeps
  keys and settings for a later install). Use native Windows message boxes that always come to the front.
- It removes: the shortcuts (desktop, Start menu, startup), the uninstall entry, the settings file next to
  the program, the data folder if I said yes, and finally the program file and its folder. A running
  program can't delete itself, so start a hidden delayed command for that **after** the final "removed"
  message has been closed, so the program has really exited when it runs.

## 5. App icon

- Use **`<path to my icon image>`** for: the `.exe` file, its windows (title bar, taskbar, Alt+Tab), the
  tray/notification icon if there is one, and the Android launcher icon (and the TV banner, 320×180, for
  an Android TV app).
- Make a multi-size Windows `.ico` (16, 24, 32, 48, 64, 128, 256). If the picture has small text, use a
  simplified crop (without the text) for the 16–32 px sizes so they stay readable.
- Show me a preview sheet of all icon sizes before finishing.

## 6. Android `.apk`

- One signed `.apk` that installs by itself (sideloading) on phones/TVs, with a sensible `minSdk` so
  it also installs on older devices.
- Use the **same signing key** as the copy already installed on my device, so the new one installs as an
  update and keeps its data. Tell me where that key lives and that I need it to make future updates.
- **Bake my current device settings in as first-run defaults.** Read the real current values from my
  device (for example, temporarily install a debuggable build with the same key and read the app's
  SharedPreferences with `adb shell run-as`, then reinstall the normal build). Apply them on first start
  only when a setting is missing, so an existing device is never changed. Leave out device-specific
  values (network addresses, the device's previous system settings).
- If a feature needs a permission an app can't give itself (e.g. `WRITE_SECURE_SETTINGS` granted with
  `adb shell pm grant`), say so plainly: the rest of the app must work without it.
- Install the new version on my existing device and confirm with `dumpsys package` that the version and
  permissions are right.

## 7. Testing (do it yourself, before telling me it's done)

- **Pretend to be a brand-new PC**: run the `.exe` with `USERPROFILE`, `LOCALAPPDATA` and `APPDATA` pointed
  at empty test folders and a `PATH` that doesn't include the developer tools (Python, git, the app's helper
  programs). Check the log or output to prove the app really works: every feature or item that should run
  does, and say which failures are outside problems (a website not answering) rather than packaging bugs.
- Click through the setup window yourself: **Install** (check program file, desktop + Start menu
  shortcuts, the Settings → Apps entry, the data folder with the seeded settings) and **Portable**.
- Run the **uninstall** both ways (keep data / delete data) and check that everything is gone.
- Check the "already running" message.
- Stop the copy of the app I normally run before testing (it may hold the same port or lock files), and
  **start it again afterwards**.
- Don't press buttons on my TV/phone while I may be using it; ask first or use screenshots only.
- Don't click on my taskbar or on other programs while testing; if you open or close something of mine by
  mistake, tell me straight away.
- **Leave nothing behind.** Close everything you opened (test copies, their windows and dialogs, anything
  started by a mis-click) and delete every leftover: test folders, temporary unpack folders (`%TEMP%\_MEI*`),
  build work folders and files that embed keys (PyInstaller `build\*.pkg`, `.spec`), test registry entries,
  test shortcuts, stale lock files. Restart anything of mine you stopped. Then list the places you checked,
  and tell me what remains on purpose and why. Do this every time, without being asked.

## 8. Keep the project's normal way of running

- The source code must still run exactly as before when not packaged (e.g. a script started by a launcher,
  a cloud job that uses the same code). Change paths only when running as the packaged file.
- Add a build script (e.g. `tools/build_exe.py`, and a `--copy-to <folder>` option for the Android build)
  so a future rebuild is one command, and describe it in the project's notes/README.
- Commit and push the source changes (never the built files or anything with keys).

## 9. When you finish, tell me in plain language

- The file names and where they are.
- What's inside (runtime, helper programs, data, which settings and which keys).
- How the first-run setup, update and uninstall work.
- What you tested and what you couldn't (for example, a brand-new Android device).
- Anything I must know: the file contains my keys (keep the folder private); keys that couldn't be included;
  data frozen at build time that needs a rebuild to change; one-time steps per device; Windows SmartScreen
  may warn "unknown publisher" (More info → Run anyway); anything that only works on this PC.
