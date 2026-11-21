"""
Builds the Tidbyt Mirror desktop window as ONE Windows program file:

  python tools/build_exe.py [output folder]        default output folder: Z:\\My Apps\\Tidbyt

  -> TidbytMirror-<version>-windows.exe   (version = VERSION in tools/tidbyt_mirror.py)

Inside the .exe: Python, tkinter, Pillow, pixlet, every app in apps/, the store apps in
.cache/community/apps (run --fetch-store first to update them), and a seed of this PC's
%USERPROFILE%\\.tidbyt\\api_token.txt, mirror_settings.json and .cache/mirror/window.json.
First start on a PC: a setup window asks whether to install it (folder, desktop / Start menu
shortcuts, start with Windows) or run it portable, and where to keep its data; the seed is
copied into that data folder (never over existing files).

THE .EXE CONTAINS THE TIDBYT TOKEN, so it is never written inside this (public) repo: the build
work happens in %LOCALAPPDATA%\\TidbytBuild and the result goes to the output folder only.
Needs: Python 3.12 with tkinter (E:\\Python\\Python312 on this PC); PyInstaller, Pillow and tzdata
are installed into a private virtual environment on the first build.
"""

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TidbytBuild")
HOME = os.path.join(os.path.expanduser("~"), ".tidbyt")
PIXLET = shutil.which("pixlet") or os.path.join(os.path.expanduser("~"), "go", "bin", "pixlet.exe")


def run(*args):
    print(">", " ".join(str(a) for a in args[:4]), "...")
    subprocess.run([str(a) for a in args], check=True)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else r"Z:\My Apps\Tidbyt"
    with open(os.path.join(ROOT, "tools", "tidbyt_mirror.py"), encoding="utf-8") as f:
        version = re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)
    name = "TidbytMirror-%s-windows" % version

    venv = os.path.join(WORK, "venv")
    py = os.path.join(venv, "Scripts", "python.exe")
    if not os.path.exists(py):
        run(sys.executable, "-m", "venv", venv)
        run(py, "-m", "pip", "install", "-q", "pyinstaller", "pillow", "tzdata")

    stage = os.path.join(WORK, "stage")
    shutil.rmtree(stage, ignore_errors=True)
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.webp", "preview")
    shutil.copytree(os.path.join(ROOT, "apps"), os.path.join(stage, "apps"), ignore=ignore)
    shutil.copytree(os.path.join(ROOT, ".cache", "community", "apps"), os.path.join(stage, "community", "apps"),
                    ignore=ignore)
    os.makedirs(os.path.join(stage, "seed"))
    for src in (os.path.join(HOME, "api_token.txt"), os.path.join(HOME, "mirror_settings.json"),
                os.path.join(ROOT, ".cache", "mirror", "window.json")):
        if os.path.exists(src):
            shutil.copy(src, os.path.join(stage, "seed"))
        else:
            print("note: %s not found, left out" % src)
    shutil.copy(PIXLET, os.path.join(stage, "pixlet.exe"))

    tools = os.path.join(ROOT, "tools")
    data = ["apps", "community", "seed", "pixlet.exe"]
    args = [py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", name,
            "--distpath", out_dir, "--workpath", os.path.join(WORK, "build"), "--specpath", WORK,
            "--paths", tools, "--collect-data", "tzdata"]
    for mod in ("movies_snapshot", "stars_snapshot", "gameday_snapshot", "lake_snapshot", "dark_sky_snapshot"):
        args += ["--hidden-import", mod]
    for d in data:  # a folder keeps its name inside the .exe; a single file goes to the top level
        dest = d if os.path.isdir(os.path.join(stage, d)) else "."
        args += ["--add-data", "%s%s%s" % (os.path.join(stage, d), os.pathsep, dest)]
    run(*(args + [os.path.join(tools, "tidbyt_mirror.py")]))
    exe = os.path.join(out_dir, name + ".exe")
    print("built %s (%d MB)" % (exe, os.path.getsize(exe) // (1024 * 1024)))


if __name__ == "__main__":
    main()
