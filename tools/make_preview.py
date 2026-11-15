"""
Builds a preview-only copy of Now Playing with the sample snapshot embedded, because the
Pixlet emulator can't take the large `snapshot` config value. The output is git-ignored.

  python tools/make_preview.py   ->  apps/now_playing/preview/now_playing_preview.star
  (then: pixlet serve apps/now_playing/preview/now_playing_preview.star)
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = os.path.join(ROOT, "apps", "now_playing")
s = open(os.path.join(app, "now_playing.star"), encoding="utf-8").read()
snap = json.dumps(json.load(open(os.path.join(app, "fixtures", "sample_snapshot.json"), encoding="utf-8")), separators=(",", ":"))
s = s.replace('    raw = config.str("snapshot")', '    raw = config.str("snapshot") or PREVIEW_SNAPSHOT', 1)
s = s.replace("def main(config):", "PREVIEW_SNAPSHOT = %s\n\ndef main(config):" % json.dumps(snap), 1)
os.makedirs(os.path.join(app, "preview"), exist_ok=True)
out = os.path.join(app, "preview", "now_playing_preview.star")
open(out, "w", encoding="utf-8", newline="\n").write(s)
print("wrote", out)
