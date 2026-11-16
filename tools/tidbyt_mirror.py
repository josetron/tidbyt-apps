"""
Tidbyt Mirror: a frameless desktop window that plays the same apps as the Tidbyt.

  pythonw tools/tidbyt_mirror.py          (or double-click tools/tidbyt_mirror.vbs)
  python  tools/tidbyt_mirror.py --menu   keeps the menu bar visible (for testing)

Using the window
  - Drag anywhere on the picture to move it.
  - Drag the bottom-right corner, or turn the mouse wheel, to resize it (always 2:1).
  - Hover over it for the menu: previous / next app, pause, opacity slider, Apps, Settings,
    keep on top, close. It disappears
    3 seconds after the mouse leaves. Esc also closes the window.
  - Position, size and "keep on top" are remembered in .cache/mirror/window.json.
  - "Frame" in the menu adds or removes the wooden frame around the screen; the small slider
    beside it sets the wood's shade, from dark walnut to light oak.
  - "Tray" in the menu moves the window's button from the taskbar to the notification area
    (system tray): click the tray icon to hide or show the window, right-click it for a menu.
  - "Apps" in the menu lists every app: untick one to leave it out of the rotation, "Show" jumps
    to it, "Settings" opens its options.
  - "Settings" in the menu opens the options of the app on screen (the same fields the phone
    app's Edit screen has). They are saved in %USERPROFILE%\\.tidbyt\\mirror_settings.json, outside
    this (public) repo because they can be personal, and only affect the mirror, not the device.

  python  tools/tidbyt_mirror.py --fetch-store   downloads the store apps installed on the device
  python  tools/tidbyt_mirror.py --feed <dir>    renders every app once into <dir> with a manifest.json
                                                 (no window; used by GitHub Actions for the Android TV app)
  python  tools/tidbyt_mirror.py --feed-one <id> re-renders one app in the published feed (used after the
                                                 TV app saves a setting; see "TV settings" below)

TV settings: the Android TV app (android_tv/) cannot render apps, so when a setting is changed on the TV
it sends it to this program over the home network (port 8766). This program then publishes the setting
to the mirror-settings branch on GitHub (PUBLIC), where the cloud job reads it, and refreshes that app's
picture in the mirror-feed branch. So the PC only has to be on while a setting is being changed.

How it works: the Tidbyt API can list the installations on the device but cannot return their
images, so this renders the apps with Pixlet and plays them in the device's order.
  - The apps from this repo are rendered the same way tools/cloud_push.py does for the device.
  - Store apps come from Tidbyt's open-source community repository (github.com/tidbyt/community),
    kept in .cache/community/ by --fetch-store. They run with DEFAULT settings plus the location
    below, because the API does not expose the settings chosen in the phone app. Apps that are
    not open source (clock, news, photo, spotify...) or need an API key are left out.
    "Only my apps" in the Apps list leaves them all out.
Nothing is pushed to the device. Rendered images go to .cache/mirror/ (git-ignored).

Needs: pixlet on PATH, Python with tkinter and Pillow. Optional: the Tidbyt token in
%USERPROFILE%\\.tidbyt\\api_token.txt (to show only apps that are installed on the device) and
a TMDB key in %USERPROFILE%\\.tidbyt\\tmdb_api_key.txt (Now Playing; without it, sample movies).
"""

import json
import os
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:  # the window needs these; the headless --feed mode (GitHub Actions) does not
    import tkinter as tk
    from tkinter import ttk
    from PIL import Image, ImageChops, ImageDraw, ImageTk
except ImportError:
    tk = ttk = Image = ImageChops = ImageDraw = ImageTk = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".cache", "mirror")
HOME = os.path.join(os.path.expanduser("~"), ".tidbyt")
DEVICE_ID = "urgently-principal-smashing-hippo-90b"
LOCK_PORT = 8765  # only used to make sure one mirror runs at a time
RELAY_PORT = 8766  # the Android TV app sends setting changes here (home network only)
PIXLET = os.environ.get("PIXLET", "pixlet")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # keep pixlet from flashing a console window

COMMUNITY = os.path.join(ROOT, ".cache", "community")
COMMUNITY_URL = "https://github.com/tidbyt/community.git"
STORE_EVERY = 1800  # seconds between refreshes of a store app
STORE_CONFIG = {    # passed to every store app; apps ignore what they don't use
    "$tz": "America/Chicago",
    "location": json.dumps({"lat": "30.19", "lng": "-98.09", "locality": "Dripping Springs", "timezone": "America/Chicago"}),
}
# Store apps that only show a "set your API key / not configured" card with default settings
STORE_SKIP = {"air-quality", "avatars-in-pixels", "birdbyt", "last-fm", "multiple-images", "time-and-weather"}
SHOW_MS = 15000  # the Tidbyt gives each app about this long

W, H = 64, 32
MIN_CELL, MAX_CELL, DEFAULT_CELL = 3, 40, 10  # screen pixels per Tidbyt pixel
MENU_LINGER_S = 3  # the menu disappears this long after the mouse leaves the window
STATIC_MS = 15000  # how long a still image (Mona Lisa) stays up

BAR_BG = "#11161c"
BAR_FG = "#c8d0d8"
BAR_DIM = "#7d8794"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


SECRET_ENV = {"api_token.txt": "TIDBYT_API_TOKEN", "tmdb_api_key.txt": "TMDB_API_KEY"}  # GitHub Actions secrets
FEED = False  # True in --feed mode: publish-safe renders (no personal settings, no sample data)


def read_secret(name):
    try:
        with open(os.path.join(HOME, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return os.environ.get(SECRET_ENV.get(name, ""), "").strip()


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ---------------------------------------------------------------------------
# Snapshot builders (same data the cloud job passes to the apps)
# ---------------------------------------------------------------------------

def fixture(app):
    with open(os.path.join(ROOT, "apps", app, "fixtures", "sample_snapshot.json"), encoding="utf-8") as f:
        return json.load(f)


def movies_config():
    key = read_secret("tmdb_api_key.txt")
    note = ""
    if FEED and not key:
        raise RuntimeError("no TMDB key: Now Playing is left out of the feed")
    if key:
        os.environ["TMDB_API_KEY"] = key
        import movies_snapshot
        snap = movies_snapshot.build(os.path.join(ROOT, ".cache", "imdb"))
    else:
        snap, note = fixture("now_playing"), "sample movies"
    movies = snap["movies"]
    start = (int(time.time()) // 3600 * 2) % len(movies)
    page = dict(snap, movies=(movies + movies)[start:start + 2])
    return {"snapshot": json.dumps(page, separators=(",", ":")), "page": "0"}, note


def stars_config():
    import stars_snapshot
    snap = stars_snapshot.build()
    players = snap["players"]
    one = dict(snap, players=[players[(int(time.time()) // 3600) % len(players)]])
    return {"snapshot": json.dumps(one, separators=(",", ":")), "page": "0"}, ""


def gameday_config():
    import gameday_snapshot
    return {"snapshot": json.dumps(gameday_snapshot.build(), separators=(",", ":"))}, ""


def lake_config():
    import lake_snapshot
    return {"snapshot": json.dumps(lake_snapshot.build(), separators=(",", ":"))}, ""


def no_config():
    return {}, ""


# (installation id on the device, name, app folder, config builder, refresh every N seconds)
APPS = [
    ("weathernow", "Weather Now", "weather_now", no_config, 900),
    ("weatherforecast", "Weather Forecast", "weather_forecast", no_config, 900),
    ("monalisa", "Mona Lisa", "mona_lisa", no_config, 86400),
    ("pixelmuseum", "Pixel Museum", "pixel_museum", no_config, 900),
    ("marketpulse", "MarketPulse", "marketpulse", no_config, 300),
    ("marketpulsestocks", "MarketPulse Stocks", "marketpulse_stocks", no_config, 300),
    ("pixelaquarium", "Pixel Aquarium", "pixel_aquarium", no_config, 900),
    ("nowplaying", "Now Playing", "now_playing", movies_config, 3600),
    ("astrosnews", "Astros News", "astros_news", no_config, 900),
    ("astrosstars", "Astros Stars", "astros_stars", stars_config, 3600),
    ("astrosgameday", "Astros GameDay", "astros_gameday", gameday_config, 300),
    ("laketravis", "Lake Travis", "lake_travis", lake_config, 21600),
]

# Shared between the render thread (writes) and the window (reads)
apps = {a[0]: {"id": a[0], "name": a[1], "version": 0, "note": "", "error": "", "on_device": True, "store": False}
        for a in APPS}
order = [a[0] for a in APPS]  # playing order: the device's own order once it is known
jobs = {a[0]: (os.path.join(ROOT, "apps", a[2], a[2] + ".star"), a[3], a[4]) for a in APPS}  # id -> (star, config builder, every)
lock = threading.Lock()


# ---------------------------------------------------------------------------
# Store apps (Tidbyt's community repository)
# ---------------------------------------------------------------------------

def store_dir(app_id):
    return os.path.join(COMMUNITY, "apps", app_id.replace("-", ""))


def store_star(app_id):
    d = store_dir(app_id)
    try:
        stars = sorted(f for f in os.listdir(d) if f.endswith(".star"))
    except OSError:
        return None
    return os.path.join(d, stars[0]) if stars else None


def store_name(app_id):
    try:
        with open(os.path.join(store_dir(app_id), "manifest.yaml"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("name:"):
                    return line[5:].strip().strip(chr(34) + chr(39))
    except OSError:
        pass
    return app_id


def store_config():
    return dict(STORE_CONFIG), "default settings"


def device_installations():
    token = read_secret("api_token.txt")
    if not token:
        return None
    req = urllib.request.Request(
        "https://api.tidbyt.com/v0/devices/%s/installations" % DEVICE_ID,
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("installations", [])


def fetch_store():
    """Downloads (or updates) the community code of the store apps installed on the device."""
    installs = device_installations()
    if installs is None:
        sys.exit("No Tidbyt token in %s" % os.path.join(HOME, "api_token.txt"))
    ids = sorted({i["appID"] for i in installs if i.get("appID")})

    def git(*args, cwd=COMMUNITY):
        return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)

    if not os.path.isdir(os.path.join(COMMUNITY, ".git")):
        os.makedirs(os.path.dirname(COMMUNITY), exist_ok=True)
        r = git("clone", "--depth", "1", "--filter=blob:none", "--sparse", COMMUNITY_URL, COMMUNITY, cwd=ROOT)
        if r.returncode != 0:
            sys.exit(r.stderr.strip())
    else:
        git("pull", "--depth", "1")
    available = set(git("ls-tree", "--name-only", "HEAD", "apps/").stdout.replace("apps/", "").split())
    wanted = [i for i in ids if i.replace("-", "") in available]
    r = git("sparse-checkout", "set", "--no-cone", *["/apps/%s/" % i.replace("-", "") for i in wanted])
    if r.returncode != 0:
        sys.exit(r.stderr.strip())
    print("%d store apps on the device, %d downloaded" % (len(ids), len(wanted)))
    print("not open source:", ", ".join(i for i in ids if i not in wanted) or "-")


# ---------------------------------------------------------------------------
# Rendering (background thread)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-app settings (the mirror's own; the device's are not readable)
# ---------------------------------------------------------------------------

SETTINGS_FILE = os.path.join(HOME, "mirror_settings.json")
due = {}  # app id -> time of its next render; the settings form resets it to refresh an app now


def load_app_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_app_settings(data):
    os.makedirs(HOME, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def normalize_datetime(text):
    """Apps want a full timestamp (2023-03-29T08:30:00-05:00). Accepts what people type instead:
    2023-03-29, 3/29/2023, with an optional time such as 08:30 or 8:30 PM (local time)."""
    text = text.strip()
    if not text or re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text):
        return text
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d",
                "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.upper(), fmt).astimezone().isoformat(timespec="seconds")
        except ValueError:
            pass
    return text


def fetch_schema(star):
    """The app's settings fields. Pixlet only exposes them through its emulator, so this starts
    `pixlet serve` on a spare port, reads /api/v1/schema and stops it again."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([PIXLET, "serve", "--port", str(port), star], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    try:
        for _ in range(40):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/api/v1/schema" % port, timeout=5) as r:
                    return json.load(r).get("schema") or []
            except Exception:
                if proc.poll() is not None:
                    break
        raise RuntimeError("could not read the app's settings")
    finally:
        proc.kill()


# ---------------------------------------------------------------------------
# Settings published for the Android TV app (PUBLIC: the mirror-settings branch on GitHub)
# ---------------------------------------------------------------------------

SETTINGS_REPO = os.path.join(ROOT, ".cache", "settings_repo")  # working copy of the mirror-settings branch
FEED_REPO = os.path.join(ROOT, ".cache", "feed_repo")          # working copy of the mirror-feed branch
_published = None


def repo_slug():
    """owner/name of the GitHub repository."""
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug:
        return slug
    try:
        url = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout.strip()
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "josetron/tidbyt-apps"


def published_settings():
    """{app id: {field: value}} as published for the TV. On this PC the local working copy is the
    freshest; in GitHub Actions it is downloaded from the branch."""
    global _published
    if _published is None:
        _published = {}
        try:
            local = os.path.join(SETTINGS_REPO, "settings.json")
            if os.path.exists(local) and not os.environ.get("GITHUB_ACTIONS"):
                with open(local, encoding="utf-8") as f:
                    _published = json.load(f)
            else:
                url = "https://raw.githubusercontent.com/%s/mirror-settings/settings.json" % repo_slug()
                with urllib.request.urlopen(url, timeout=20) as r:
                    _published = json.load(r)
        except Exception:
            _published = {}
        if not isinstance(_published, dict):
            _published = {}
    return _published


def git(path, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    cmd = ["git", "-C", path, "-c", "credential.helper=", "-c", "credential.helper=manager",
           "-c", "user.name=Tidbyt Mirror", "-c", "user.email=tidbyt-mirror@users.noreply.github.com"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, creationflags=NO_WINDOW)


def branch_checkout(path, branch):
    """A working copy of one branch at its latest commit (created empty if the branch is new)."""
    url = "https://github.com/%s.git" % repo_slug()
    if not os.path.isdir(os.path.join(path, ".git")):
        os.makedirs(path, exist_ok=True)
        git(path, "init", "-q", "-b", branch)
        git(path, "remote", "add", "origin", url)
    if git(path, "fetch", "--depth", "1", "origin", branch).returncode == 0:
        git(path, "reset", "-q", "--hard", "FETCH_HEAD")
        git(path, "clean", "-fdq")


def branch_push(path, branch, message):
    git(path, "add", "-A")
    if git(path, "diff", "--cached", "--quiet").returncode == 0:
        return True  # nothing changed
    git(path, "commit", "-q", "-m", message)
    r = git(path, "push", "origin", "HEAD:" + branch)
    if r.returncode != 0:
        log("push to %s failed: %s" % (branch, (r.stderr or r.stdout).strip()[-200:]))
    return r.returncode == 0


def publish_settings(key, values):
    """Saves one app's settings to the mirror-settings branch (empty values = back to defaults)."""
    global _published
    branch_checkout(SETTINGS_REPO, "mirror-settings")
    path = os.path.join(SETTINGS_REPO, "settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if values:
        data[key] = values
    else:
        data.pop(key, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    _published = data
    return branch_push(SETTINGS_REPO, "mirror-settings", "Settings for %s" % key)


def feed_one(key):
    """Re-renders one app with the published settings and updates it in the mirror-feed branch,
    so the TV shows a changed setting within a minute instead of at the next cloud run."""
    global OUT, FEED
    import hashlib
    branch_checkout(FEED_REPO, "mirror-feed")
    OUT, FEED = FEED_REPO, True
    refresh_device()
    if key not in jobs:
        log("feed-one: unknown app %s" % key)
        return False
    star, build, _ = jobs[key]
    render(key, star, build)
    if apps[key]["version"] == 0:
        return False
    manifest_path = os.path.join(FEED_REPO, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {"apps": []}
    with open(gif_path(key), "rb") as f:
        digest = hashlib.sha1(f.read()).hexdigest()[:12]
    entry = {"id": key, "name": apps[key]["name"], "file": os.path.basename(gif_path(key)),
             "version": digest, "store": apps[key]["store"]}
    found = False
    for i, old in enumerate(manifest.get("apps", [])):
        if old.get("id") == key:
            manifest["apps"][i], found = entry, True
    if not found:
        manifest.setdefault("apps", []).append(entry)
    manifest["generated"] = int(time.time())
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return branch_push(FEED_REPO, "mirror-feed", "Picture for %s" % key)


# ---------------------------------------------------------------------------
# Relay for the Android TV app (home network): app options out, changed settings in
# ---------------------------------------------------------------------------

relay_schemas = {}  # app id -> the app's settings schema, as last sent to the TV
LOCATION_PARTS = (("locality", "place name"), ("lat", "latitude"), ("lng", "longitude"), ("timezone", "time zone"))


def tv_fields(key):
    """The app's options in the simple shape the TV understands: text, onoff or choice rows.
    A location becomes four text rows ("location|lat"...), put back together on save."""
    schema = fetch_schema(jobs[key][0])
    relay_schemas[key] = schema
    saved = published_settings().get(key, {})
    fields = []
    for field in schema:
        kind, fid = field.get("type"), field.get("id")
        if not fid:
            continue
        name = field.get("name", fid)
        current = saved.get(fid, field.get("default", ""))
        if kind == "onoff":
            fields.append({"id": fid, "name": name, "type": "onoff", "value": str(current).lower()})
        elif kind == "dropdown":
            options = [{"label": o.get("display") or o.get("text") or o.get("value", ""), "value": o.get("value", "")}
                       for o in field.get("options") or []]
            fields.append({"id": fid, "name": name, "type": "choice", "options": options, "value": str(current)})
        elif kind == "location":
            try:
                loc = json.loads(current) if current else json.loads(STORE_CONFIG["location"])
            except ValueError:
                loc = {}
            for part, label in LOCATION_PARTS:
                fields.append({"id": "%s|%s" % (fid, part), "name": "%s: %s" % (name, label), "type": "text",
                               "value": str(loc.get(part, ""))})
        elif kind in ("text", "datetime", "color"):
            hint = {"datetime": "for example 2023-03-29 or 2023-03-29 08:30", "color": "#RRGGBB"}.get(kind, "")
            fields.append({"id": fid, "name": name, "type": "text", "value": str(current), "hint": hint})
    return fields


def tv_save(key, raw):
    """Turns what the TV sent back into the app's config values and publishes them."""
    schema = relay_schemas.get(key) or fetch_schema(jobs[key][0])
    kinds = {f.get("id"): f.get("type") for f in schema}
    values, groups = {}, {}
    for fid, value in raw.items():
        value = str(value).strip()[:500]
        if "|" in fid:
            base, part = fid.split("|", 1)
            if kinds.get(base) == "location":
                groups.setdefault(base, {})[part] = value
        elif kinds.get(fid) == "datetime":
            if value:
                values[fid] = normalize_datetime(value)
        elif kinds.get(fid) in ("text", "color", "onoff", "dropdown") and value != "":
            values[fid] = value
    for base, loc in groups.items():
        if loc.get("lat") and loc.get("lng"):
            values[base] = json.dumps(loc)

    data = load_app_settings()  # the Windows mirror uses the same settings from now on
    if values:
        data[key] = values
    else:
        data.pop(key, None)
    save_app_settings(data)
    due[key] = 0

    ok = publish_settings(key, values)
    if ok:  # refresh the TV's picture in the background (a separate process: it renders in feed mode)
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--feed-one", key], creationflags=NO_WINDOW)
    return ok


class RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/ping":
                self.reply(200, {"ok": True, "service": "tidbyt-mirror"})
            elif url.path == "/schema":
                key = (query.get("id") or [""])[0]
                if key not in jobs:
                    self.reply(404, {"ok": False, "error": "This app is not known to the PC mirror."})
                else:
                    self.reply(200, {"ok": True, "name": apps[key]["name"], "fields": tv_fields(key)})
            else:
                self.reply(404, {"ok": False, "error": "not found"})
        except Exception as e:
            log("relay: %s" % e)
            self.reply(500, {"ok": False, "error": str(e)[:200]})

    def do_POST(self):
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100000)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            key, raw = body.get("id"), body.get("values")
            if self.path != "/settings" or key not in jobs or not isinstance(raw, dict):
                self.reply(400, {"ok": False, "error": "bad request"})
                return
            ok = tv_save(key, raw)
            log("relay: settings for %s %s" % (key, "published" if ok else "NOT published"))
            self.reply(200 if ok else 500, {"ok": ok, "error": "" if ok else "Could not publish to GitHub."})
        except Exception as e:
            log("relay: %s" % e)
            self.reply(500, {"ok": False, "error": str(e)[:200]})


def start_relay():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", RELAY_PORT), RelayHandler)
    except OSError as e:
        log("TV settings relay not started: %s" % e)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log("TV settings relay listening on port %d" % RELAY_PORT)


def gif_path(iid):
    return os.path.join(OUT, iid.replace(":", "_") + ".gif")


def render(iid, star, build):
    # GIF, not WebP: Pillow misreads the frame durations of Pixlet's WebP files
    tmp = gif_path(iid)[:-4] + ".tmp.gif"
    try:
        config, note = build()
        # the public feed only uses settings published on purpose from the TV; never this PC's private ones
        mine = published_settings().get(iid, {}) if FEED else load_app_settings().get(iid, {})
        for k, v in mine.items():
            if k != "snapshot":
                config[k] = v
        if mine and note == "default settings":
            note = ""
        args = [PIXLET, "render", star] + ["%s=%s" % kv for kv in config.items()] + ["--gif", "-o", tmp]
        r = subprocess.run(args, capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
        if r.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:] or "pixlet render failed")
        if os.path.getsize(tmp) < 20:  # the app chose to show nothing right now
            os.remove(tmp)
            raise RuntimeError("nothing to show")
        os.replace(tmp, gif_path(iid))
        with lock:
            apps[iid]["version"] += 1
            apps[iid]["note"], apps[iid]["error"] = note, ""
        log("%s: rendered" % iid)
    except Exception as e:  # keep the last good image and say why it is old
        lines = [line.strip() for line in str(e).splitlines() if line.strip()]
        with lock:
            apps[iid]["error"] = (lines[-1] if lines else "render failed")[:200]
        log("%s: %s" % (iid, e))
    with lock:
        apps[iid]["tries"] = apps[iid].get("tries", 0) + 1


def refresh_device():
    """Reads the device's installation list: which of our apps are on it, in which order, and
    which store apps to add (ids only: the API has no images or settings to offer)."""
    try:
        installs = device_installations()
    except Exception as e:
        log("device list failed: %s" % e)
        return
    if installs is None:
        return
    new_order, seen = [], set()
    with lock:
        for inst in installs:
            app_id = inst.get("appID")
            key = "store:" + app_id if app_id else inst["id"]
            if key in seen:
                continue  # the same store app installed twice plays once here
            seen.add(key)
            if app_id:
                star = None if app_id in STORE_SKIP else store_star(app_id)
                if not star:
                    continue
                if key not in apps:
                    apps[key] = {"id": key, "name": store_name(app_id), "version": 0, "note": "", "error": "",
                                 "on_device": True, "store": True}
                    jobs[key] = (star, store_config, STORE_EVERY)
            elif key not in apps:
                continue  # pushed by something else: no source to render
            new_order.append(key)
        for key, a in apps.items():
            a["on_device"] = key in seen
        order[:] = new_order + [k for k in apps if k not in new_order]


def worker():
    device_due = 0
    while True:
        if time.time() >= device_due:
            refresh_device()
            device_due = time.time() + 1800
        with lock:
            todo = [k for k in order if apps[k]["on_device"]]
        todo.sort(key=lambda k: apps[k]["store"])  # our own apps first, so the window starts quickly
        for key in todo:  # one at a time: parallel renders time out
            if time.time() >= due.get(key, 0):
                star, build, every = jobs[key]
                render(key, star, build)
                due[key] = time.time() + every
        time.sleep(5)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

def tray_icon_file():
    """A small LED-matrix icon for the notification area, made once with Pillow."""
    path = os.path.join(OUT, "tray.ico")
    if not os.path.exists(path):
        size, dots = 64, ["#ff7a1a", "#f4f4f4", "#33dd66", "#4da6ff"]
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((2, 12, size - 3, size - 13), radius=8, fill="#101418", outline="#5a6470", width=2)
        for row in range(2):
            for col in range(4):
                x, y = 10 + col * 12, 22 + row * 12
                d.ellipse((x, y, x + 8, y + 8), fill=dots[(col + row) % len(dots)])
        im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
    return path


class TrayIcon:
    """An icon in the Windows notification area, made with Shell_NotifyIcon through ctypes (no
    extra packages). It lives on its own thread with a hidden message window; clicks are put on
    `events` ("click" = left button, "menu" = right button) for the Tk thread to pick up."""

    def __init__(self, icon_path, tip, events):
        self.icon_path, self.tip, self.events = icon_path, tip, events
        self.hwnd = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.hwnd:
            import ctypes
            ctypes.windll.user32.PostMessageW(self.hwnd, 0x8000 + 2, 0, 0)
            self.thread.join(2)

    def run(self):
        import ctypes
        from ctypes import wintypes

        user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        TRAY_MSG, QUIT_MSG = 0x8000 + 1, 0x8000 + 2  # WM_APP + n

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HANDLE),
                        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HANDLE)]

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                           wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]

        nid = NOTIFYICONDATAW()

        def proc(hwnd, msg, wparam, lparam):
            if msg == TRAY_MSG:
                if lparam == 0x0202:    # WM_LBUTTONUP
                    self.events.put("click")
                elif lparam == 0x0205:  # WM_RBUTTONUP
                    self.events.put("menu")
                return 0
            if msg == QUIT_MSG:
                shell32.Shell_NotifyIconW(2, ctypes.byref(nid))  # NIM_DELETE
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self.proc = WNDPROC(proc)  # keep a reference: Windows calls it for as long as the window lives
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW()
        cls.lpfnWndProc, cls.hInstance, cls.lpszClassName = self.proc, hinst, "TidbytMirrorTray%d" % id(self)
        if not user32.RegisterClassW(ctypes.byref(cls)):
            log("tray icon: could not register the window class")
            return
        hwnd = user32.CreateWindowExW(0, cls.lpszClassName, "Tidbyt Mirror tray", 0, 0, 0, 0, 0, None, None, hinst, None)
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID = hwnd, 1
        nid.uFlags = 0x1 | 0x2 | 0x4  # NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon = user32.LoadImageW(None, self.icon_path, 1, 0, 0, 0x10 | 0x40)  # IMAGE_ICON, from file, default size
        nid.szTip = self.tip
        if not shell32.Shell_NotifyIconW(0, ctypes.byref(nid)):  # NIM_ADD
            log("tray icon: Windows refused the icon")
        self.hwnd = hwnd
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = None


def load_frames(iid):
    """[(64x32 RGB image, milliseconds)] for one app."""
    frames = []
    with Image.open(gif_path(iid)) as im:
        for i in range(getattr(im, "n_frames", 1)):
            im.seek(i)
            frames.append((im.convert("RGB"), max(20, im.info.get("duration", 100))))
    if len(frames) == 1:
        frames = [(frames[0][0], STATIC_MS)]
    return frames


def dot_mask(cell):
    """LED look: white round dots on black, one per Tidbyt pixel, multiplied over the picture."""
    big = Image.new("L", (cell * 4, cell * 4), 0)
    edge = cell * 4 * 0.07
    ImageDraw.Draw(big).ellipse((edge, edge, cell * 4 - 1 - edge, cell * 4 - 1 - edge), fill=255)
    tile = big.resize((cell, cell), Image.LANCZOS)
    mask = Image.new("L", (W * cell, H * cell))
    for y in range(H):
        for x in range(W):
            mask.paste(tile, (x * cell, y * cell))
    return mask.convert("RGB")


OFF_BELOW = 28              # a pixel whose brightest channel is under this is an unlit LED
OFF_COLOR = (46, 48, 52)    # what an unlit LED looks like on the real panel: a faint grey dot
OFF_SIZE = 0.5              # its diameter, as a share of the pixel pitch (lit LEDs bloom larger)


def off_layer(cell):
    """The panel with every LED off: small faint grey dots on black. Shown only where a pixel
    is unlit, so lit dots keep their exact colour and brightness."""
    big = Image.new("L", (cell * 4, cell * 4), 0)
    edge = cell * 4 * (1 - OFF_SIZE) / 2
    ImageDraw.Draw(big).ellipse((edge, edge, cell * 4 - 1 - edge, cell * 4 - 1 - edge), fill=255)
    tile = big.resize((cell, cell), Image.LANCZOS)
    mask = Image.new("L", (W * cell, H * cell))
    for y in range(H):
        for x in range(W):
            mask.paste(tile, (x * cell, y * cell))
    layer = Image.new("RGB", mask.size, OFF_COLOR)
    return ImageChops.multiply(layer, mask.convert("RGB"))


WOOD_DARK = (43, 29, 20)    # the frame's shade slider runs from this dark walnut...
WOOD_LIGHT = (176, 126, 80) # ...to this light oak


def wood_color(level):
    """Frame colour for a slider position of 0 (darkest) to 100 (lightest)."""
    t = min(100, max(0, level)) / 100.0
    return tuple(round(a + (b - a) * t) for a, b in zip(WOOD_DARK, WOOD_LIGHT))


FRAME_WOOD = 2.2            # wood thickness, in Tidbyt pixels
FRAME_GAP = 0.8             # black bezel between the wood and the first LEDs, in Tidbyt pixels
CORNER_KEY = (1, 2, 3)      # painted in the frame's rounded-off corners; Windows shows it as see-through


def frame_margin(cell):
    return max(4, round(cell * FRAME_WOOD)) + max(1, round(cell * FRAME_GAP))


def frame_image(cell, level):
    """The wooden frame with rounded corners and a black opening for the screen; the picture is
    pasted into it."""
    wood, margin = max(4, round(cell * FRAME_WOOD)), frame_margin(cell)
    w, h = W * cell + 2 * margin, H * cell + 2 * margin

    base = wood_color(level)
    contrast = 1 + level / 60.0  # lighter wood shows its grain and edges more

    def tint(amount):
        return tuple(max(0, min(255, round(c + amount * contrast))) for c in base)

    im = Image.new("RGB", (w, h), CORNER_KEY)
    d = ImageDraw.Draw(im)
    radius = max(3, round(cell * 1.2))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=base)
    rnd = random.Random(7)  # the same grain every time
    for y in range(radius, h - radius):  # faint horizontal grain
        if rnd.random() < 0.5:
            x0 = rnd.randint(0, w // 2)
            d.line((x0, y, min(w - 1, x0 + rnd.randint(w // 4, w)), y), fill=tint(rnd.randint(-7, 6)))
    for y in list(range(2, radius)) + list(range(h - radius, h - 2)):  # grain on the top and bottom rails
        if rnd.random() < 0.5:
            d.line((radius, y, w - 1 - radius, y), fill=tint(rnd.randint(-7, 6)))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=tint(-14))       # outer edge
    d.rectangle((wood - 1, wood - 1, w - wood, h - wood), fill=tint(-20))              # shadow inside the wood
    d.rectangle((wood, wood, w - 1 - wood, h - 1 - wood), fill=(0, 0, 0))               # the panel
    return im


class Mirror:
    def __init__(self, keep_menu):
        self.keep_menu = keep_menu
        self.settings_path = os.path.join(OUT, "window.json")
        s = self.load_settings()
        self.cell = min(MAX_CELL, max(MIN_CELL, int(s.get("cell", DEFAULT_CELL))))
        self.on_top = bool(s.get("on_top", False))
        self.hidden = set(s.get("hidden", []))  # app ids left out of the rotation
        self.framed = bool(s.get("frame", True))  # wooden frame around the screen
        self.wood = min(100, max(0, int(s.get("wood", 35))))  # frame shade: 0 dark walnut, 100 light oak
        self.frame_img = None
        self.frame_cell = 0
        self.tray_mode = bool(s.get("tray", False))  # icon in the notification area instead of the taskbar
        self.tray = None
        self.tray_events = queue.Queue()
        self.apps_win = None
        self.alpha = min(100, max(20, int(s.get("alpha", 100))))  # window opacity in percent
        self.paused = False
        self.order = []      # ids that can be shown right now
        self.current = None  # id being shown
        self.frames = []
        self.frame_i = 0
        self.show_until = 0
        self.shown_version = 0
        self.settings_win = None
        self.reload_key = None
        self.reload_tries = 0
        self.tick_job = None
        self.mask = None
        self.mask_cell = 0
        self.photo = None
        self.drag = None

        root = self.root = tk.Tk()
        root.title("Tidbyt Mirror")
        root.overrideredirect(True)  # frameless
        root.configure(bg="#000000")
        try:
            root.attributes("-transparentcolor", "#%02x%02x%02x" % CORNER_KEY)
        except tk.TclError:
            pass  # not Windows: the corners stay square
        root.attributes("-topmost", self.on_top)
        x, y = int(s.get("x", 200)), int(s.get("y", 200))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        if not (-W * self.cell + 60 < x < sw - 60 and 0 <= y < sh - 60):  # saved on a monitor that is gone
            x, y = 200, 200
        root.geometry("%dx%d+%d+%d" % (self.window_size() + (x, y)))

        self.screen = tk.Label(root, bd=0, bg="#000000", fg=BAR_DIM, text="Rendering the first app...")
        self.screen.place(x=0, y=0, relwidth=1, relheight=1)

        # menu bar: only on screen while the mouse is over the window
        bar = self.bar = tk.Frame(root, bg=BAR_BG)

        def button(text, command, side="left"):
            b = tk.Label(bar, text=text, bg=BAR_BG, fg=BAR_FG, padx=7, pady=2, cursor="hand2", font=("Segoe UI", 9))
            b.bind("<Button-1>", lambda e: command())
            b.bind("<Enter>", lambda e: b.configure(bg="#27313b"))
            b.bind("<Leave>", lambda e: b.configure(bg=BAR_BG))
            b.pack(side=side)
            return b

        button("◀", lambda: self.step(-1))
        button("▶", lambda: self.step(1))
        self.pause_btn = button("Pause", self.toggle_pause)
        button("✕", self.close, side="right")
        self.top_btn = button("", self.toggle_top, side="right")
        self.tray_btn = button("", self.toggle_tray, side="right")
        # frame shade slider, right next to the Frame switch (packed first, so it sits to its right)
        self.wood_scale = tk.Scale(
            bar, from_=0, to=100, orient="horizontal", showvalue=False, length=50, width=9, sliderlength=12,
            bg=BAR_BG, fg=BAR_FG, troughcolor="#6b4a2e", activebackground=BAR_FG, highlightthickness=0, bd=0,
            command=self.set_wood,
        )
        self.wood_scale.set(self.wood)
        self.wood_scale.bind("<ButtonRelease-1>", lambda e: self.save_settings())
        self.wood_scale.pack(side="right", padx=(0, 4))
        self.frame_btn = button("", self.toggle_frame, side="right")
        button("Settings", self.open_settings, side="right")
        button("Apps", self.open_apps, side="right")

        # transparency slider: 20 % (mostly see-through) to 100 % (solid)
        self.alpha_scale = tk.Scale(
            bar, from_=20, to=100, orient="horizontal", showvalue=False, length=70, width=9, sliderlength=12,
            bg=BAR_BG, fg=BAR_FG, troughcolor="#3f4b57", activebackground=BAR_FG, highlightthickness=0, bd=0,
            command=self.set_alpha,
        )
        self.alpha_scale.set(self.alpha)
        self.alpha_scale.bind("<ButtonRelease-1>", lambda e: self.save_settings())
        self.alpha_scale.pack(side="right", padx=(2, 6))
        tk.Label(bar, text="Opacity", bg=BAR_BG, fg=BAR_DIM, font=("Segoe UI", 9)).pack(side="right")
        self.title = tk.Label(bar, text="", bg=BAR_BG, fg=BAR_FG, font=("Segoe UI", 9), anchor="w")
        self.title.pack(side="left", fill="x", expand=True, padx=6)
        self.update_top_label()

        # resize handle: a small triangle in the bottom-right corner
        self.grip = tk.Canvas(root, width=16, height=16, bg="#000000", highlightthickness=0, cursor="size_nw_se")
        self.grip.create_polygon(16, 0, 16, 16, 0, 16, fill=BAR_FG)
        self.grip.bind("<ButtonPress-1>", self.resize_start)
        self.grip.bind("<B1-Motion>", self.resize_drag)
        self.grip.bind("<ButtonRelease-1>", lambda e: self.save_settings())

        for widget in (self.screen, self.title):  # drag the picture (or the title) to move the window
            widget.bind("<ButtonPress-1>", self.move_start)
            widget.bind("<B1-Motion>", self.move_drag)
            widget.bind("<ButtonRelease-1>", lambda e: self.save_settings())
        root.bind("<MouseWheel>", lambda e: self.set_cell(self.cell + (1 if e.delta > 0 else -1), save=True))
        root.bind("<Escape>", lambda e: self.close())
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.menu_shown = False
        self.last_hover = 0
        self.show_in_taskbar()
        self.watch_pointer()
        self.poll()

    # -- settings ----------------------------------------------------------

    def load_settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        data = {"x": self.root.winfo_x(), "y": self.root.winfo_y(), "cell": self.cell, "on_top": self.on_top,
                "hidden": sorted(self.hidden), "alpha": self.alpha, "tray": self.tray_mode,
                "frame": self.framed, "wood": self.wood}
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # -- window behaviour --------------------------------------------------

    def show_in_taskbar(self):
        """Puts the window's button in the taskbar, or (tray mode) takes it out and shows an icon
        in the notification area instead. A frameless Tk window has no taskbar button by itself."""
        if os.name != "nt":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            self.root.update_idletasks()
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)           # GWL_EXSTYLE
            if self.tray_mode:
                style = (style & ~0x00040000) | 0x00000080     # a tool window: no taskbar button
            else:
                style = (style & ~0x00000080) | 0x00040000     # an app window: taskbar button
            user32.SetWindowLongW(hwnd, -20, style)
            self.root.withdraw()                               # the change applies when it is shown again
            self.root.after(20, self.root.deiconify)
        except Exception as e:
            log("taskbar button not set: %s" % e)
        if self.tray_mode and self.tray is None:
            try:
                self.tray = TrayIcon(tray_icon_file(), "Tidbyt Mirror", self.tray_events)
            except Exception as e:
                log("tray icon failed: %s" % e)
        elif not self.tray_mode and self.tray is not None:
            self.tray.stop()
            self.tray = None

    def toggle_tray(self):
        self.tray_mode = not self.tray_mode
        self.update_top_label()
        self.save_settings()
        self.show_in_taskbar()

    def toggle_visible(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
        else:
            self.root.withdraw()

    def tray_menu(self):
        hidden = self.root.state() == "withdrawn"
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Show window" if hidden else "Hide window", command=self.toggle_visible)
        menu.add_command(label="Apps...", command=self.open_apps)
        menu.add_command(label="Back to the taskbar", command=self.toggle_tray)
        menu.add_separator()
        menu.add_command(label="Close Tidbyt Mirror", command=self.close)
        x, y = self.root.winfo_pointerxy()
        try:
            menu.tk_popup(x, y - 5)
        finally:
            menu.grab_release()

    def handle_tray_events(self):
        try:
            while True:
                event = self.tray_events.get_nowait()
                if event == "click":
                    self.toggle_visible()
                elif event == "menu":
                    self.tray_menu()
        except queue.Empty:
            pass

    def watch_pointer(self):
        """Show the menu while the mouse is over the window (Enter/Leave events flicker on child widgets)."""
        self.handle_tray_events()
        px, py = self.root.winfo_pointerxy()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        inside = x <= px < x + self.root.winfo_width() and y <= py < y + self.root.winfo_height()
        if inside or self.keep_menu:
            self.last_hover = time.time()
        want = time.time() - self.last_hover < MENU_LINGER_S  # stays a moment after the mouse leaves
        if want != self.menu_shown:
            self.menu_shown = want
            if want:
                self.bar.place(x=0, y=0, relwidth=1)
                self.grip.place(relx=1.0, rely=1.0, anchor="se")
            else:
                self.bar.place_forget()
                self.grip.place_forget()
        self.root.after(120, self.watch_pointer)

    def window_size(self):
        margin = frame_margin(self.cell) if self.framed else 0
        return W * self.cell + 2 * margin, H * self.cell + 2 * margin

    def set_wood(self, value):
        self.wood = min(100, max(0, int(float(value))))
        if self.framed:
            self.draw()

    def toggle_frame(self):
        self.framed = not self.framed
        self.update_top_label()
        self.root.geometry("%dx%d" % self.window_size())
        self.draw()
        self.save_settings()

    def move_start(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def move_drag(self, e):
        if self.drag:
            self.root.geometry("+%d+%d" % (e.x_root - self.drag[0], e.y_root - self.drag[1]))

    def resize_start(self, e):
        self.drag = None

    def resize_drag(self, e):
        width = e.x_root - self.root.winfo_x()
        extra = 2 * (FRAME_WOOD + FRAME_GAP) if self.framed else 0  # the frame's share, in Tidbyt pixels
        self.set_cell(round(width / (W + extra)))

    def set_cell(self, cell, save=False):
        cell = min(MAX_CELL, max(MIN_CELL, int(cell)))
        if cell == self.cell:
            return
        self.cell = cell
        self.root.geometry("%dx%d" % self.window_size())
        self.draw()
        if save:
            self.save_settings()

    def toggle_top(self):
        self.on_top = not self.on_top
        self.root.attributes("-topmost", self.on_top)
        self.update_top_label()
        self.save_settings()

    def update_top_label(self):
        self.top_btn.configure(text="On top ✓" if self.on_top else "On top", fg=BAR_FG if self.on_top else BAR_DIM)
        self.tray_btn.configure(text="Tray ✓" if self.tray_mode else "Tray", fg=BAR_FG if self.tray_mode else BAR_DIM)
        self.frame_btn.configure(text="Frame ✓" if self.framed else "Frame", fg=BAR_FG if self.framed else BAR_DIM)

    def set_alpha(self, value):
        self.alpha = min(100, max(20, int(float(value))))
        self.root.attributes("-alpha", self.alpha / 100.0)

    # -- apps list ---------------------------------------------------------

    def open_apps(self):
        """A window listing every app: tick = in the rotation, Show = jump to it, Settings = its options."""
        if self.apps_win is not None:
            self.apps_win.lift()
            return
        win = self.apps_win = tk.Toplevel(self.root)
        win.title("Tidbyt Mirror apps")
        win.attributes("-topmost", True)
        win.geometry("460x560+%d+%d" % (self.root.winfo_x() + 30, self.root.winfo_y() + 50))

        def closed():
            self.apps_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", closed)

        with lock:
            rows = [dict(apps[k]) for k in order if apps[k]["on_device"]]
        variables = {}

        def apply():
            self.hidden = {k for k, v in variables.items() if not v.get()}
            self.save_settings()
            self.poll_once()
            if self.current not in self.order and self.order:
                self.step(1)

        def set_all(choose):
            for row in rows:
                variables[row["id"]].set(choose(row))
            apply()

        top = ttk.Frame(win, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Ticked apps play in the mirror.").pack(side="left")
        ttk.Button(top, text="Only my apps", command=lambda: set_all(lambda r: not r["store"])).pack(side="right", padx=2)
        ttk.Button(top, text="All", command=lambda: set_all(lambda r: True)).pack(side="right", padx=2)

        canvas = tk.Canvas(win, highlightthickness=0)
        bar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, padding=(10, 0))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        inner.columnconfigure(0, weight=1)

        for n, row in enumerate(rows):
            key = row["id"]
            var = variables[key] = tk.BooleanVar(value=key not in self.hidden)
            label = row["name"] + ("" if row["store"] else "  (mine)")
            if row["version"] == 0:
                label += "  - not working yet" if row["error"] else "  - rendering..."
            ttk.Checkbutton(inner, text=label, variable=var, command=apply).grid(row=n, column=0, sticky="w")
            ttk.Button(inner, text="Show", width=6, command=lambda k=key: self.jump_to(k)).grid(row=n, column=1, padx=2, pady=1)
            ttk.Button(inner, text="Settings", width=9,
                       command=lambda k=key: self.open_settings(k)).grid(row=n, column=2, padx=2, pady=1)

    def jump_to(self, key):
        with lock:
            ready = apps[key]["version"] > 0
        if ready:
            self.show(key)

    # -- settings form -----------------------------------------------------

    def open_settings(self, key=None):
        if self.settings_win is not None:
            self.settings_win.lift()
            return
        if key is None:
            key = self.current
        elif key != self.current:
            self.jump_to(key)  # put the app being edited on screen
        if key is None:
            return
        with lock:
            name = apps[key]["name"]
        was_paused = self.paused
        if not self.paused:
            self.toggle_pause()  # hold this app on screen while it is being edited

        win = self.settings_win = tk.Toplevel(self.root)
        win.title("%s settings" % name)
        win.attributes("-topmost", True)
        win.geometry("+%d+%d" % (self.root.winfo_x() + 30, self.root.winfo_y() + 50))
        win.minsize(380, 120)
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        status = ttk.Label(body, text="Reading this app's settings...")
        status.pack(anchor="w")

        def closed():
            self.settings_win = None
            win.destroy()
            if not was_paused and self.paused:
                self.toggle_pause()

        win.protocol("WM_DELETE_WINDOW", closed)
        result = {}

        def load():
            try:
                result["schema"] = fetch_schema(jobs[key][0])
            except Exception as e:
                result["error"] = str(e)

        threading.Thread(target=load, daemon=True).start()

        def wait():
            if self.settings_win is not win:
                return
            if "error" in result:
                status.configure(text=result["error"])
            elif "schema" in result:
                status.destroy()
                self.build_settings_form(win, body, key, result["schema"], closed)
            else:
                win.after(200, wait)

        wait()

    def build_settings_form(self, win, body, key, schema, closed):
        saved = load_app_settings().get(key, {})
        getters = {}  # field id -> function returning the value to save ("" = use the app's default)
        easy = ("text", "datetime", "color", "onoff", "dropdown", "location")
        if not [f for f in schema if f.get("type") in easy]:
            ttk.Label(body, text="This app has no settings that can be changed here.").pack(anchor="w")

        for field in schema:
            kind, fid = field.get("type"), field.get("id")
            if not fid:
                continue
            ttk.Label(body, text=field.get("name", fid), font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 0))
            if field.get("description"):
                ttk.Label(body, text=field["description"], foreground="#666666", wraplength=420).pack(anchor="w")
            current = saved.get(fid, field.get("default", ""))

            if kind == "onoff":
                var = tk.BooleanVar(value=str(current).lower() == "true")
                ttk.Checkbutton(body, text="On", variable=var).pack(anchor="w")
                getters[fid] = lambda var=var: "true" if var.get() else "false"
            elif kind == "dropdown":
                options = field.get("options") or []
                shown = [o.get("display") or o.get("text") or o.get("value", "") for o in options]
                values = [o.get("value", "") for o in options]
                box = ttk.Combobox(body, values=shown, state="readonly", width=44)
                if current in values:
                    box.current(values.index(current))
                box.pack(anchor="w")
                getters[fid] = lambda box=box, values=values: values[box.current()] if box.current() >= 0 else ""
            elif kind == "location":
                try:
                    loc = json.loads(current) if current else json.loads(STORE_CONFIG["location"])
                except ValueError:
                    loc = {}
                grid = ttk.Frame(body)
                grid.pack(anchor="w")
                entries = {}
                for row, (part, label) in enumerate((("locality", "Place name"), ("lat", "Latitude"),
                                                     ("lng", "Longitude"), ("timezone", "Time zone"))):
                    ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8))
                    entry = ttk.Entry(grid, width=32)
                    entry.insert(0, str(loc.get(part, "")))
                    entry.grid(row=row, column=1, pady=1)
                    entries[part] = entry

                def location_value(entries=entries):
                    loc = {part: e.get().strip() for part, e in entries.items()}
                    return json.dumps(loc) if loc["lat"] and loc["lng"] else ""

                getters[fid] = location_value
            elif kind in ("text", "datetime", "color"):
                entry = ttk.Entry(body, width=47)
                entry.insert(0, str(current))
                entry.pack(anchor="w")
                if kind == "datetime":
                    ttk.Label(body, text="For example 2023-03-29, or 2023-03-29 08:30 with a time",
                              foreground="#666666").pack(anchor="w")
                    getters[fid] = lambda entry=entry: normalize_datetime(entry.get())
                else:
                    if kind == "color":
                        ttk.Label(body, text="Format: #RRGGBB", foreground="#666666").pack(anchor="w")
                    getters[fid] = lambda entry=entry: entry.get().strip()
            else:
                ttk.Label(body, text="(This kind of setting needs the phone app; not available here.)",
                          foreground="#666666").pack(anchor="w")

        def store(values):
            data = load_app_settings()
            if values:
                data[key] = values
            else:
                data.pop(key, None)
            try:
                save_app_settings(data)
            except OSError as e:
                log("settings not saved: %s" % e)
            due[key] = 0  # render this app again right away
            with lock:
                self.reload_tries = apps[key].get("tries", 0)
            self.reload_key = key
            closed()

        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(14, 0))
        ttk.Button(buttons, text="Use defaults", command=lambda: store({})).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=closed).pack(side="left", padx=4)
        ttk.Button(buttons, text="Save", command=lambda: store(
            {fid: v for fid, v in ((fid, get()) for fid, get in getters.items()) if v != ""})).pack(side="left", padx=4)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")

    def close(self):
        self.save_settings()
        if self.tray is not None:
            self.tray.stop()  # take the icon out of the notification area
            self.tray = None
        self.root.destroy()

    # -- playback ----------------------------------------------------------

    def poll_once(self):
        with lock:
            self.order = [k for k in order if apps[k]["version"] > 0 and apps[k]["on_device"]
                          and k not in self.hidden]

    def poll(self):
        """Pick up newly rendered apps."""
        self.poll_once()
        if self.current is None and self.order:
            self.show(self.order[0])
        elif self.current is not None:
            with lock:
                tries = apps[self.current].get("tries", 0)
            if self.reload_key == self.current and tries != self.reload_tries:
                self.reload_key = None
                self.show(self.current)  # just re-rendered with new settings: show the result (or the error)
        self.root.after(2000, self.poll)

    def step(self, direction):
        if not self.order:
            return
        if self.current in self.order:
            i = self.order.index(self.current)
        else:  # the current app left the list (store apps switched off): carry on from where it was
            with lock:
                before = order[:order.index(self.current)] if self.current in order else []
            i = len([k for k in self.order if k in before]) - (1 if direction > 0 else 0)
        self.show(self.order[(i + direction) % len(self.order)])

    def show(self, iid):
        try:
            frames = load_frames(iid)
        except Exception as e:
            log("%s: cannot play: %s" % (iid, e))
            frames = self.frames
        self.current, self.frames, self.frame_i = iid, frames, 0
        total = sum(ms for _, ms in frames)
        self.show_until = time.time() + min(30000, max(total, SHOW_MS)) / 1000.0  # short animations loop
        with lock:
            a = dict(apps[iid])
        self.shown_version = a["version"]
        n = self.order.index(iid) + 1 if iid in self.order else 0
        note = a["note"]
        if a["error"]:  # e.g. a setting the app could not use; the picture is the last good one
            note = "problem: " + a["error"][-70:]
        self.title.configure(text="%s   %d/%d%s" % (a["name"], n, len(self.order), "   (" + note + ")" if note else ""))
        if self.tick_job:
            self.root.after_cancel(self.tick_job)
        self.tick()

    def tick(self):
        if not self.frames:
            return
        if self.frame_i >= len(self.frames):
            if self.paused or time.time() < self.show_until - 0.3:
                self.frame_i = 0  # short animations loop until the app's time is up, like on the device
            else:
                self.tick_job = None
                self.step(1)
                return
        self.draw()
        delay = self.frames[self.frame_i][1]
        self.frame_i += 1
        self.tick_job = self.root.after(delay, self.tick)

    def draw(self):
        if not self.frames:
            return
        frame = self.frames[min(self.frame_i, len(self.frames) - 1)][0]
        big = frame.resize((W * self.cell, H * self.cell), Image.NEAREST)
        if self.cell >= 4:
            if self.mask_cell != self.cell:
                self.mask, self.off, self.mask_cell = dot_mask(self.cell), off_layer(self.cell), self.cell
            big = ImageChops.multiply(big, self.mask)

            # unlit LEDs show as faint grey dots, like the real panel; lit ones are left untouched
            r, g, b = frame.split()
            brightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
            unlit = brightest.point(lambda v: 255 if v < OFF_BELOW else 0).resize(big.size, Image.NEAREST)
            big = Image.composite(self.off, big, unlit)
        if self.framed:
            if self.frame_cell != (self.cell, self.wood):
                self.frame_img, self.frame_cell = frame_image(self.cell, self.wood), (self.cell, self.wood)
            margin = frame_margin(self.cell)
            framed = self.frame_img.copy()
            framed.paste(big, (margin, margin))
            big = framed
        self.photo = ImageTk.PhotoImage(big)
        self.screen.configure(image=self.photo, text="")


def build_feed(out_dir):
    """Renders every app on the device once into out_dir and writes manifest.json: the public
    picture feed the Android TV app plays (android_tv/). Returns the number of apps written."""
    global OUT, FEED
    import hashlib
    OUT, FEED = os.path.abspath(out_dir), True
    os.makedirs(OUT, exist_ok=True)
    try:
        fetch_store()
    except SystemExit as e:  # no token or no git: carry on with the apps from this repo
        log("store apps not fetched: %s" % e)
    refresh_device()
    with lock:
        todo = [k for k in order if apps[k]["on_device"]]
    entries = []
    for key in todo:
        star, build, _ = jobs[key]
        render(key, star, build)
        if apps[key]["version"] > 0:
            with open(gif_path(key), "rb") as f:
                digest = hashlib.sha1(f.read()).hexdigest()[:12]
            entries.append({"id": key, "name": apps[key]["name"], "file": os.path.basename(gif_path(key)),
                            "version": digest, "store": apps[key]["store"]})
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": int(time.time()), "apps": entries}, f, indent=1)
    log("feed: %d apps in %s" % (len(entries), OUT))
    return len(entries)


def main():
    if "--feed-one" in sys.argv:
        os.makedirs(OUT, exist_ok=True)
        if sys.stdout is None:
            sys.stdout = sys.stderr = open(os.path.join(OUT, "feed_one.log"), "w", encoding="utf-8")
        sys.exit(0 if feed_one(sys.argv[sys.argv.index("--feed-one") + 1]) else 1)
    if "--feed" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--feed") + 1]
        sys.exit(0 if build_feed(out_dir) else 1)
    os.makedirs(OUT, exist_ok=True)
    if "--fetch-store" in sys.argv:
        fetch_store()
        return
    if sys.stdout is None:  # started with pythonw (no console): log to a file instead
        sys.stdout = sys.stderr = open(os.path.join(OUT, "mirror.log"), "w", encoding="utf-8")
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        guard.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        log("Tidbyt Mirror is already running")
        return
    threading.Thread(target=worker, daemon=True).start()
    start_relay()
    Mirror(keep_menu="--menu" in sys.argv).root.mainloop()


if __name__ == "__main__":
    main()
