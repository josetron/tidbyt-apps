"""
Tidbyt Mirror: a frameless desktop window that plays the same apps as the Tidbyt.

  pythonw tools/tidbyt_mirror.py          (or double-click tools/tidbyt_mirror.vbs)
  python  tools/tidbyt_mirror.py --menu   keeps the menu bar visible (for testing)

Using the window
  - Drag anywhere on the picture to move it.
  - Drag the bottom-right corner, or turn the mouse wheel, to resize it (always 2:1).
  - Hover over it for the menu: previous / next app, pause, keep on top, close. Esc also closes.
  - Position, size and "keep on top" are remembered in .cache/mirror/window.json.

How it works: the Tidbyt API can list the installations on the device but cannot return their
images, so this renders the apps from this repo with Pixlet, the same way tools/cloud_push.py
does for the device, and plays them in rotation like the Gen 1 does. Apps from the Tidbyt
store are not shown: there is nothing to render them from. Nothing is pushed to the device.
Rendered images go to .cache/mirror/ (git-ignored).

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

W, H = 64, 32
MIN_CELL, MAX_CELL, DEFAULT_CELL = 3, 40, 10  # screen pixels per Tidbyt pixel
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
apps = {a[0]: {"id": a[0], "name": a[1], "version": 0, "note": "", "error": "", "on_device": True} for a in APPS}
lock = threading.Lock()


# ---------------------------------------------------------------------------
# Rendering (background thread)
# ---------------------------------------------------------------------------

def gif_path(iid):
    return os.path.join(OUT, iid + ".gif")


def render(iid, folder, build):
    # GIF, not WebP: Pillow misreads the frame durations of Pixlet's WebP files
    star = os.path.join(ROOT, "apps", folder, folder + ".star")
    tmp = os.path.join(OUT, iid + ".tmp.gif")
    try:
        config, note = build()
        args = [PIXLET, "render", star] + ["%s=%s" % kv for kv in config.items()] + ["--gif", "-o", tmp]
        r = subprocess.run(args, capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
        if r.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:] or "pixlet render failed")
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
    """Which installations the device has (ids only: the API has no images to offer)."""
    token = read_secret("api_token.txt")
    if not token:
        return
    try:
        req = urllib.request.Request(
            "https://api.tidbyt.com/v0/devices/%s/installations" % DEVICE_ID,
            headers={"Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            ids = {i["id"] for i in json.load(r).get("installations", [])}
    except Exception as e:
        log("device list failed: %s" % e)
        return
    with lock:
        for iid, a in apps.items():
            a["on_device"] = iid in ids


def worker():
    due = {a[0]: 0 for a in APPS}
    device_due = 0
    while True:
        if time.time() >= device_due:
            refresh_device()
            device_due = time.time() + 1800
        for iid, _, folder, build, every in APPS:  # one at a time: parallel renders time out
            if time.time() >= due[iid] and apps[iid]["on_device"]:
                render(iid, folder, build)
                due[iid] = time.time() + every
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
        self.paused = False
        self.order = []      # ids that can be shown right now
        self.current = None  # id being shown
        self.frames = []
        self.frame_i = 0
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
        data = {"x": self.root.winfo_x(), "y": self.root.winfo_y(), "cell": self.cell, "on_top": self.on_top}
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
        want = inside or self.keep_menu or self.drag is not None
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

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="Resume" if self.paused else "Pause")

    def close(self):
        self.save_settings()
        self.root.destroy()

    # -- playback ----------------------------------------------------------

    def poll(self):
        """Pick up newly rendered apps."""
        with lock:
            self.order = [a[0] for a in APPS if apps[a[0]]["version"] > 0 and apps[a[0]]["on_device"]]
        if self.current is None and self.order:
            self.show(self.order[0])
        self.root.after(2000, self.poll)

    def step(self, direction):
        if not self.order:
            return
        i = self.order.index(self.current) if self.current in self.order else -1
        self.show(self.order[(i + direction) % len(self.order)])

    def show(self, iid):
        try:
            frames = load_frames(iid)
        except Exception as e:
            log("%s: cannot play: %s" % (iid, e))
            frames = self.frames
        self.current, self.frames, self.frame_i = iid, frames, 0
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
        if self.frame_i >= len(self.frames):  # the animation has played once, like on the device
            if self.paused:
                self.frame_i = 0
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
