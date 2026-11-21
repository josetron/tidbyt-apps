# Prompt: make any app installable or portable (single-file Windows .exe and/or Android .apk)

How to use it: open a new session in the app's project, fill in the **Fill in** block below, then paste
everything from the line down. Delete a platform's section if the app doesn't have that platform.

---

## Fill in

- **App name:** `<AppName>` (used for folders, shortcuts and file names; no version in it)
- **Platforms:** `<Windows / Android / Android TV / several>`
- **Where to put the finished files:** `<e.g. Z:\My Apps\<AppName>>`
- **Icon picture:** `<path to the image, or "make one from the app's look">`
- **Where my portable apps usually live:** `<e.g. F:\Portables>`
- **Devices to install on for testing (optional):** `<e.g. Android TV at 192.168.x.x:5555>`
- **Anything special:** `<keys the app needs, a cloud job that uses the same code, etc.>`

---

I want this app turned into **one single file per platform** that I can keep, copy to any device and
either **install** or run **portable**: a Windows `.exe` and/or an Android `.apk`, as listed above.

## 0. How to work with me

- I'm not technical. Explain in plain language, keep it short, and tell me plainly what was tested and
  what wasn't. Never claim something works unless you checked it.
- Before you start, look at how the app runs today (its code, launchers, config files, keys, helper programs,
  cloud jobs) and tell me in a few lines what you'll bundle and anything you can't include.
- **Don't take over my screen** unless I allow it. Ask first; if I say no, test another way (see §10). Never
  click my taskbar or other programs. Don't press buttons on my TV/phone while I may be using it.
  If you open or close anything of mine by mistake, tell me straight away and put it back.
- **Ask before deleting** anything of mine, including older versions of the files you made.
- **Leave nothing behind** after testing (see §10), every time, without being asked.
- Commit and push the source changes when done (never the built files or anything containing keys).

## 1. What the files must contain

- **Everything the app needs on a clean device**, so nothing else has to be installed: the runtime
  (Python, .NET, Node/Electron, Java...), all libraries, helper programs the app calls (command-line tools,
  renderers, plug-ins), data files, templates, fonts, images, and anything else it reads at run time.
- **The same configuration I use today**: settings files, window size/position, per-item settings,
  hidden/disabled items, themes, etc. Find where each lives (config files, `%USERPROFILE%`, `%APPDATA%`,
  `%LOCALAPPDATA%`, the registry, Android SharedPreferences...) and include it.
- **The keys and tokens the app uses**, taken from where they live now.
  - If a key exists only where you can't read it (a GitHub Actions secret, a cloud dashboard), tell me; don't
    leak it with a workaround. If possible make the app fall back gracefully (e.g. download the result the
    cloud already made).
  - **Never** write a key, or any file containing one, inside a git repository (especially a public one).
    Do the build work in a private folder outside the project (e.g. `%LOCALAPPDATA%\<AppName>Build`) and
    write the finished file only to the output folder.
- Bundled settings and keys are a **starting point ("seed")**: on a device's first run, copy each into the
  app's data folder **only if it isn't there already**. Never overwrite a device's own settings.

## 2. Version in the file name

- One version number in the code (e.g. `VERSION = "1.0.0"`), used everywhere: file names, Android
  `versionName` + matching `versionCode` (1.2.3 → 10203), window/setup titles, folder names, the log.
- File names: **`<AppName>-<version>-windows.exe`**, **`<AppName>-<version>-android.apk`**
  (or `-androidtv.apk`).
- Raise the version on **every** rebuild with a change, so old and new can't be confused. After putting a
  new version in the output folder, ask me whether to delete the older files.

## 3. Windows: the first-run setup window

The first time the `.exe` is opened (and it isn't already set up), show a small setup window with the app's
icon and version in the title:

1. **How do you want to use <AppName> on this PC?**
   - **Install it** (shortcuts, listed in Settings → Apps; the downloaded file can be deleted afterwards)
   - **Portable** (its own folder with the program and its data; nothing is installed)
2. **Install folder** + Browse. Default `%LOCALAPPDATA%\Programs\<AppName>` (no administrator rights needed).
   In Portable mode this row becomes **"Create it in"** + Browse, starting at the folder the setup file is
   in, so I can point it at my portables folder.
3. **Data folder** + Browse (install mode): where keys, settings, cache and output go. Default
   `%LOCALAPPDATA%\<AppName>`. If I browse to a general folder (e.g. `E:\My Apps`), use an `<AppName>`
   subfolder inside it. Picking an existing data folder keeps its settings. In Portable mode it shows the
   `Data` folder that will be created, greyed out.
4. A grey line under the folders saying exactly what will happen, e.g. *"Creates the folder
   F:\Portables\<AppName> 1.0.3 with the program to double-click (<AppName>-1.0.3-windows.exe) and its
   Data folder."*
5. Tick boxes: **Desktop shortcut** (on) and **Start with Windows** (off) in **both** modes;
   **Start menu shortcut** (on) in install mode only.
6. Buttons: **Install and start** / **Create and start** (portable), and **Cancel**.

Afterwards, later starts skip this window and go straight to the app.

## 4. Windows: install

- Copy the program into the install folder (only the program file there).
- Shortcuts as ticked: desktop, Start menu, Startup folder (start with Windows). Find the **real Desktop
  folder** with the Windows API (`SHGetFolderPath` / `[Environment]::GetFolderPath('Desktop')`); OneDrive
  often moves it.
- Remember the choices in the **registry**, `HKCU\Software\<AppName>` (install folder, data folder).
  **No `.json`/`.ini` next to the program.**
- Register in **Settings → Apps → Installed apps**: `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\<AppName>`
  with DisplayName, DisplayVersion, Publisher, DisplayIcon, InstallLocation,
  `UninstallString = "<exe>" --uninstall`, NoModify, NoRepair.
- Add **"Uninstall <AppName>"** to the Start menu (runs `--uninstall`).
- **Updating**: running a newer version's file and choosing Install again closes the running older copy
  (only copies inside the install folder, never the setup itself), replaces the old program file, updates
  the shortcuts and the Apps entry, and keeps the data folder.

## 5. Windows: portable

Must look like a normal portable app:

```
<the folder I chose>\
   <AppName> <version>\
      <AppName>-<version>-windows.exe    <- the one file to double-click
      Data\                              <- keys, settings, cache, output (+ a small marker file)
```

- If the app is several files rather than one, use `App\` (the program files) + `Data\` instead.
- **Nothing else** goes in that folder, and **nothing at all** goes in the folder I chose or the folder the
  setup file came from (often my installers folder on a network drive).
- The portable copy recognises itself by a small marker file **inside** `Data\` (e.g. `Data\portable.ini`);
  no registry entries.
- Shortcuts only if ticked (desktop, start with Windows), pointing at the program inside the folder.
- When done: start it, and open the new folder in Explorer **with the program selected**.
- **Updating**: making a newer version in the same place creates `<AppName> <new version>`, copies `Data\`
  from the newest older one (keys and settings carry over), and moves the ticked shortcuts to the new copy.
  The older folder is left for me to delete.
- **Removing**: just delete the folder (and any shortcut I asked for).

## 6. Windows: uninstall (installed copies)

- Asks **"Remove <AppName> from this PC?"**, then **"Also delete its data folder?"** (No keeps keys and
  settings for a later install). Use native Windows message boxes that always come to the front.
- Removes: all shortcuts (desktop, Start menu, Startup, the uninstall entry), the Settings → Apps entry, the
  app's registry key, the data folder if I said yes, and finally the program and its folder.
- A running program can't delete itself: after the final "removed" message has been closed, start a
  hidden delayed command (detached, outside the program's job) that deletes the file and folder.

## 7. Windows: behaviour of the app itself

- If the app is **already running**, a second start shows a message ("already running; look in the
  notification area"), never silently nothing.
- A window position saved on a bigger or second monitor falls back to a visible spot on smaller screens.
- Offer the setups **without the window** too, for scripting and testing:
  `--setup-portable <folder> [--desktop] [--autostart]`,
  `--setup-install <install folder> <data folder> [--no-shortcuts]`, `--uninstall`.
- Pitfalls already met (Python + PyInstaller one-file; check the equivalents for other tools):
  - When the program starts **another copy of itself**, remove PyInstaller's variables (`_PYI*`,
    `_MEIPASS*`) from its environment and set `PYINSTALLER_RESET_ENVIRONMENT=1`, or the new copy reuses the
    first one's temporary unpack folder and crashes when it's deleted ("No such file ... base_library.zip").
  - A file added to the bundle can end up as a folder of the same name; check bundled helper programs are
    really where the code looks for them.
  - Call system tools by **full path** (e.g. `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`).
  - Windowed builds: `stdin=DEVNULL` on every subprocess; write a log file, since there's no console.
  - Paths: read bundled files from the unpack folder; write everything to the data folder, never next to
    the program or into the temporary unpack folder.

## 8. Icon

- Use the icon picture for the `.exe` file, every window (title bar, taskbar, Alt+Tab), the setup window,
  the tray icon if any, the Android launcher icon and, for Android TV, the 320×180 banner.
- Windows `.ico` with 16, 24, 32, 48, 64, 128 and 256 px. If the picture has small text, use a simplified
  crop without it for 16–32 px so it stays readable.
- Show me a preview of all sizes before finishing.

## 9. Android `.apk`

- One signed `.apk` that installs by itself (sideloading), with a sensible `minSdk`.
- Sign with the **same key** as the copy already on my device, so it installs as an update and keeps its
  data. Tell me where that key lives (I need it for future updates).
- **My current device settings become the first-run defaults**: read the real values from my device (e.g.
  install a debuggable build with the same key, read the app's SharedPreferences with `adb shell run-as`,
  then reinstall the normal build) and apply them on first start only where a setting is missing. Leave out
  device-specific values (network addresses, the device's own previous system settings).
- Permissions an app can't give itself (e.g. `WRITE_SECURE_SETTINGS` via `adb shell pm grant`): say so
  plainly; the rest must work without them.
- Android TV: everything usable with the remote (D-pad), plus the banner.
- Install the new version on my device without opening or switching the app on screen, re-grant any
  PC-granted permissions, and confirm version and permissions with `dumpsys package`.

## 10. Testing (yourself, before telling me it's done)

- **Pretend to be a brand-new PC**: run with `USERPROFILE`, `LOCALAPPDATA` and `APPDATA` pointed at empty
  test folders and a `PATH` without developer tools. Prove from the log/output that the app really works;
  say which failures are outside problems (a website not answering) rather than packaging bugs.
- **Install**: only the program in the install folder; shortcuts; Settings → Apps entry; registry key; data
  folder (an `<AppName>` subfolder when a general folder was picked) with the seeded settings; the installed
  copy starts and works; the "already running" message.
- **Portable**: exactly one `<AppName> <version>` folder holding only the program and `Data\` (nothing
  anywhere else); it starts from there and works; shortcuts point at it; an update next to an older
  portable folder carries `Data\` over.
- **Uninstall** both ways (keep data / delete data): everything listed in §6 is gone.
- Use the window-less setup options for these checks. Click through the setup window itself only if I allow
  screen control. Point test shortcuts at a throwaway folder (a test-only desktop override) so nothing lands
  on my real desktop, and confirm it didn't.
- Stop the copy of the app I normally run first (it may hold the same port or files), and **start it again
  afterwards** (but don't restart something I closed myself without asking).
- **Leave nothing behind**: close everything you opened (test copies, dialogs, Explorer windows) and delete
  test folders, temporary unpack folders (`%TEMP%\_MEI*` etc.), build work files that embed keys
  (PyInstaller `build\*.pkg`, `.spec`, staging folders), test registry entries, test shortcuts, temporary
  icons, stray hidden files in the output folder, stale lock files. Then list where you checked, and what
  remains on purpose and why.

## 11. Keep the project working as before

- The unpackaged app (launcher scripts, cloud jobs that use the same code) must run exactly as before;
  change behaviour only when running as the packaged file.
- Add a one-command build (e.g. `tools/build_exe.py <output folder>`; `--copy-to <folder>` for the Android
  build) and describe it in the project's notes/README.

## 12. When you finish, tell me in plain language

- The file names and where they are, and that older versions are waiting for my OK to delete.
- What's inside (runtime, helper programs, data, which settings and which keys).
- How install, portable, update and uninstall work, and what to click.
- What you tested and what you couldn't (e.g. the setup window if I declined screen control, a brand-new
  Android device).
- What I must know: the file contains my keys (keep the folder private); keys that couldn't be included;
  data frozen at build time that needs a rebuild; one-time steps per device; Windows may warn "unknown
  publisher" (More info → Run anyway); anything that only works on this PC.
