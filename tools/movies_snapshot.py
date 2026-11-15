"""
Builds the data snapshot for the Now Playing app (apps/now_playing).

  python tools/movies_snapshot.py <out.json>        (needs TMDB_API_KEY in the environment)

- Movie list and posters: TMDB "now playing" for US theaters (free API key).
  This product uses the TMDB API but is not endorsed or certified by TMDB.
- Ratings: IMDb's free daily dataset title.ratings.tsv.gz (personal, non-commercial use),
  matched by IMDb ID. It is downloaded at most once a day (IMDB_RATINGS caches it).
- Posters are fetched small, cropped to 2:3 and downscaled to 21x32 with Pillow, which looks far
  better than Pixlet's own scaling, then stored as base64 PNG (about 1-2 KB each).

Output: {"fetched_at": unix, "movies": [{title, release, runtime, cert, genres, imdb, votes, poster, backdrop}]}
"""

import base64
import gzip
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

TMDB = "https://api.themoviedb.org/3"
POSTER_URL = "https://image.tmdb.org/t/p/w185%s"
RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
POSTER_W, POSTER_H = 21, 32
BACKDROP_W, BACKDROP_H = 80, 40  # a little larger than the screen so it can pan
BACKDROP_URL = "https://image.tmdb.org/t/p/w300%s"
MAX_MOVIES = 12


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "tidbyt-now-playing/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def tmdb(path, **params):
    # Accepts either TMDB credential: the short v3 "API Key" or the long "Read Access Token"
    key = os.environ["TMDB_API_KEY"].strip()
    headers = {"User-Agent": "tidbyt-now-playing/1.0", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    else:
        params["api_key"] = key
    req = urllib.request.Request("%s%s?%s" % (TMDB, path, urllib.parse.urlencode(params)), headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def now_playing():
    seen, movies = set(), []
    for page in (1, 2, 3):
        data = tmdb("/movie/now_playing", region="US", language="en-US", page=page)
        for m in data.get("results", []):
            if m["id"] in seen or not m.get("poster_path"):
                continue
            seen.add(m["id"])
            movies.append(m)
        if page >= data.get("total_pages", 1):
            break
    # the most talked-about current releases, then newest first
    movies.sort(key=lambda m: m.get("popularity", 0), reverse=True)
    movies = movies[:MAX_MOVIES]
    movies.sort(key=lambda m: m.get("release_date", ""), reverse=True)
    return movies


def details(movie_id):
    d = tmdb("/movie/%d" % movie_id, language="en-US", append_to_response="external_ids,release_dates")
    cert = ""
    for country in d.get("release_dates", {}).get("results", []):
        if country.get("iso_3166_1") == "US":
            for rd in sorted(country.get("release_dates", []), key=lambda r: r.get("type", 9)):
                if rd.get("certification"):
                    cert = rd["certification"]
                    break
    return {
        "imdb_id": (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id") or "",
        "runtime": d.get("runtime") or 0,
        "cert": cert,
        "genres": [g["name"] for g in d.get("genres", [])][:2],
        "backdrop_path": d.get("backdrop_path") or "",
    }


def imdb_ratings(ids, cache_path):
    """Looks up the wanted IMDb IDs in the daily ratings file (downloaded at most once a day)."""
    fresh = os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < 20 * 3600
    if not fresh:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        data = get(RATINGS_URL, timeout=60)
        with open(cache_path, "wb") as f:
            f.write(data)
    wanted, found = set(i for i in ids if i), {}
    with gzip.open(cache_path, "rt", encoding="utf-8") as f:
        next(f)  # header: tconst averageRating numVotes
        for line in f:
            tconst, _, rest = line.partition("\t")
            if tconst in wanted:
                rating, votes = rest.strip().split("\t")
                found[tconst] = (float(rating), int(votes))
                if len(found) == len(wanted):
                    break
    return found


def shrink(data, w, h, top_bias=0.5, gamma=0.8):
    """Crop to w:h and shrink for LEDs: blur slightly, average each cell (no ringing),
    boost colour and contrast, and lift the darks (Gen 1 LEDs swallow dark tones)."""
    from PIL import Image, ImageEnhance, ImageFilter

    im = Image.open(io.BytesIO(data)).convert("RGB")
    iw, ih = im.size
    target = w / h
    if iw / ih > target:
        nw = int(ih * target)
        im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
    else:
        nh = int(iw / target)
        y = int((ih - nh) * top_bias)
        im = im.crop((0, y, iw, y + nh))
    im = im.filter(ImageFilter.GaussianBlur(im.width / w * 0.35)).resize((w, h), Image.BOX)
    im = ImageEnhance.Color(im).enhance(1.45)
    im = ImageEnhance.Contrast(im).enhance(1.25)
    lut = [int(255 * ((i / 255) ** gamma)) for i in range(256)]
    return im.point(lut * 3)


def b64(im, fmt, **kw):
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def poster_png(poster_path):
    return b64(shrink(get(POSTER_URL % poster_path), POSTER_W, POSTER_H), "PNG", optimize=True)


def backdrop_jpg(backdrop_path):
    if not backdrop_path:
        return ""
    im = shrink(get(BACKDROP_URL % backdrop_path), BACKDROP_W, BACKDROP_H, top_bias=0.4, gamma=0.85)
    return b64(im, "JPEG", quality=90)


def build(cache_dir):
    movies = now_playing()
    extra = {m["id"]: details(m["id"]) for m in movies}
    ratings = imdb_ratings([e["imdb_id"] for e in extra.values()], os.path.join(cache_dir, "title.ratings.tsv.gz"))
    out = []
    for m in movies:
        e = extra[m["id"]]
        rating, votes = ratings.get(e["imdb_id"], (None, 0))
        out.append({
            "title": m["title"],
            "release": m.get("release_date", ""),
            "runtime": e["runtime"],
            "cert": e["cert"],
            "genres": e["genres"],
            "imdb": rating,
            "votes": votes,
            "poster": poster_png(m["poster_path"]),
            "backdrop": backdrop_jpg(e["backdrop_path"]),
        })
    return {"fetched_at": int(time.time()), "movies": out}


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.environ.get("TMDB_API_KEY"):
        sys.exit(__doc__)
    snap = build(os.environ.get("IMDB_CACHE", os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), ".imdb")))
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    for m in snap["movies"]:
        print("%-40s %s  IMDb %s (%s votes)  %s %s min" % (m["title"][:40], m["release"], m["imdb"], m["votes"], m["cert"] or "-", m["runtime"]))
