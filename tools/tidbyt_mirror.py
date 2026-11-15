"""
Tidbyt Mirror: a frameless desktop window that plays the same apps as the Tidbyt.

  pythonw tools/tidbyt_mirror.py          (or double-click tools/tidbyt_mirror.vbs)
  python  tools/tidbyt_mirror.py --menu   keeps the menu bar visible (for testing)

Using the window
  - Drag anywhere on the picture to move it.
  - Drag the bottom-right corner, or turn the mouse wheel, to resize it (always 2:1).
  - Hover over it for the menu: previous / next app, pause, keep on top, close. It disappears
    3 seconds after the mouse leaves. Esc also closes the window.
  - Position, size and "keep on top" are remembered in .cache/mirror/window.json.

  python  tools/tidbyt_mirror.py --fetch-store   downloads the store apps installed on the device

How it works: the Tidbyt API can list the installations on the device but cannot return their
images, so this renders the apps with Pixlet and plays them in the device's order.
  - The apps from this repo are rendered the same way tools/cloud_push.py does for the device.
  - Store apps come from Tidbyt's open-source community repository (github.com/tidbyt/community),
    kept in .cache/community/ by --fetch-store. They run with DEFAULT settings plus the location
    below, because the API does not expose the settings chosen in the phone app. Apps that are
    not open source (clock, news, photo, spotify...) or need an API key are left out.
    The "Store" button in the menu turns them on and off.
Nothing is pushed to the device. Rendered images go to .cache/mirror/ (git-ignored).

Needs: pixlet on PATH, Python with tkinter and Pillow. Optional: the Tidbyt token in
%USERPROFILE%\\.tidbyt\\api_token.txt (to show only apps that are installed on the device) and
a TMDB key in %USERPROFILE%\\.tidbyt\\tmdb_api_key.txt (Now Playing; without it, sample movies).
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageTk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".cache", "mirror")
HOME = os.path.join(os.path.expanduser("~"), ".tidbyt")
DEVICE_ID = "urgently-principal-smashing-hippo-90b"
LOCK_PORT = 8765  # only used to make sure one mirror runs at a time
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


def read_secret(name):
    try:
        with open(os.path.join(HOME, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ---------------------------------------------------------------------------
# Snapshot builders (same data the cloud job passes to the apps)
# ---------------------------------------------------------------------------

def fixture(app):
    with open(os.path.join(ROOT, "apps", app, "fixtures", "sample_snapshot.json"), encoding="utf-8") as f:
        return json.load(f)


def movies_config():
    key = read_secret("tmdb_api_key.txt") or os.environ.get("TMDB_API_KEY", "")
    note = ""
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

def gif_path(iid):
    return os.path.join(OUT, iid.replace(":", "_") + ".gif")


def render(iid, star, build):
    # GIF, not WebP: Pillow misreads the frame durations of Pixlet's WebP files
    tmp = gif_path(iid)[:-4] + ".tmp.gif"
    try:
        config, note = build()
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
        with lock:
            apps[iid]["error"] = str(e)[:200]
        log("%s: %s" % (iid, e))


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
    due = {}
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


class Mirror:
    def __init__(self, keep_menu):
        self.keep_menu = keep_menu
        self.settings_path = os.path.join(OUT, "window.json")
        s = self.load_settings()
        self.cell = min(MAX_CELL, max(MIN_CELL, int(s.get("cell", DEFAULT_CELL))))
        self.on_top = bool(s.get("on_top", False))
        self.store = bool(s.get("store", True))
        self.paused = False
        self.order = []      # ids that can be shown right now
        self.current = None  # id being shown
        self.frames = []
        self.frame_i = 0
        self.show_until = 0
        self.tick_job = None
        self.mask = None
        self.mask_cell = 0
        self.photo = None
        self.drag = None

        root = self.root = tk.Tk()
        root.title("Tidbyt Mirror")
        root.overrideredirect(True)  # frameless
        root.configure(bg="#000000")
        root.attributes("-topmost", self.on_top)
        x, y = int(s.get("x", 200)), int(s.get("y", 200))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        if not (-W * self.cell + 60 < x < sw - 60 and 0 <= y < sh - 60):  # saved on a monitor that is gone
            x, y = 200, 200
        root.geometry("%dx%d+%d+%d" % (W * self.cell, H * self.cell, x, y))

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
        self.store_btn = button("", self.toggle_store, side="right")
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
                "store": self.store}
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # -- window behaviour --------------------------------------------------

    def show_in_taskbar(self):
        """A frameless Tk window has no taskbar button on Windows unless asked for."""
        if os.name != "nt":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            self.root.update_idletasks()
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)           # GWL_EXSTYLE
            style = (style & ~0x00000080) | 0x00040000         # not a tool window; an app window
            user32.SetWindowLongW(hwnd, -20, style)
            self.root.withdraw()
            self.root.after(20, self.root.deiconify)
        except Exception as e:
            log("taskbar button not set: %s" % e)

    def watch_pointer(self):
        """Show the menu while the mouse is over the window (Enter/Leave events flicker on child widgets)."""
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

    def move_start(self, e):
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def move_drag(self, e):
        if self.drag:
            self.root.geometry("+%d+%d" % (e.x_root - self.drag[0], e.y_root - self.drag[1]))

    def resize_start(self, e):
        self.drag = None

    def resize_drag(self, e):
        width = e.x_root - self.root.winfo_x()
        self.set_cell(round(width / W))

    def set_cell(self, cell, save=False):
        cell = min(MAX_CELL, max(MIN_CELL, int(cell)))
        if cell == self.cell:
            return
        self.cell = cell
        self.root.geometry("%dx%d" % (W * cell, H * cell))
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
        self.store_btn.configure(text="Store ✓" if self.store else "Store", fg=BAR_FG if self.store else BAR_DIM)

    def toggle_store(self):
        self.store = not self.store
        self.update_top_label()
        self.save_settings()
        self.poll_once()
        if self.current not in self.order:
            self.step(1)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")

    def close(self):
        self.save_settings()
        self.root.destroy()

    # -- playback ----------------------------------------------------------

    def poll_once(self):
        with lock:
            self.order = [k for k in order if apps[k]["version"] > 0 and apps[k]["on_device"]
                          and (self.store or not apps[k]["store"])]

    def poll(self):
        """Pick up newly rendered apps."""
        self.poll_once()
        if self.current is None and self.order:
            self.show(self.order[0])
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
        n = self.order.index(iid) + 1 if iid in self.order else 0
        note = "last good image" if a["error"] else a["note"]
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
                self.mask, self.mask_cell = dot_mask(self.cell), self.cell
            big = ImageChops.multiply(big, self.mask)
        self.photo = ImageTk.PhotoImage(big)
        self.screen.configure(image=self.photo, text="")


def main():
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
    Mirror(keep_menu="--menu" in sys.argv).root.mainloop()


if __name__ == "__main__":
    main()
