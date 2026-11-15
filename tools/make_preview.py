"""
Builds preview-only copies of the snapshot apps (Now Playing, Astros Stars) with their sample
snapshot embedded, because the Pixlet emulator can't take the large `snapshot` config value.
The output is git-ignored.

  python tools/make_preview.py   ->  apps/<app>/preview/<app>_preview.star
  (then: pixlet serve apps/<app>/preview/<app>_preview.star)
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for name in ("now_playing", "astros_stars"):
    app = os.path.join(ROOT, "apps", name)
    s = open(os.path.join(app, name + ".star"), encoding="utf-8").read()
    snap = json.dumps(json.load(open(os.path.join(app, "fixtures", "sample_snapshot.json"), encoding="utf-8")), separators=(",", ":"))
    s = s.replace('    raw = config.str("snapshot")', '    raw = config.str("snapshot") or PREVIEW_SNAPSHOT', 1)
    s = s.replace("def main(config):", "PREVIEW_SNAPSHOT = %s\n\ndef main(config):" % json.dumps(snap), 1)
    os.makedirs(os.path.join(app, "preview"), exist_ok=True)
    out = os.path.join(app, "preview", name + "_preview.star")
    open(out, "w", encoding="utf-8", newline="\n").write(s)
    print("wrote", out)
