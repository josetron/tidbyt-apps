"""
Builds the data snapshot for the Dark Sky Tonight app (apps/dark_sky).

  python tools/dark_sky_snapshot.py <out.json> [zip] [unix-time]     (no key, standard library only)

Tonight's stargazing outlook for a US ZIP code; the default is Dripping Springs, Texas (a Dark
Sky Community). Other ZIPs are looked up with Open-Meteo's geocoder, and times are shown in that
place's own time zone. The score knows clouds and moonlight, not light pollution.
- Astronomy is computed here, with Paul Schlyter's low-precision method ("How to compute planetary
  positions"): good to a few arc-minutes for the sun and planets and a fraction of a degree for
  the moon, which is plenty for twilight times, moonrise/set, phase and "is it up".
- Cloud cover comes from Open-Meteo's hourly forecast (no key).
"Tonight" is the dark night in progress, or the next one: from astronomical dusk (sun 18 degrees
below the horizon) to astronomical dawn. Every 5 minutes of it gets a quality from 0 to 1:
clear sky and no moon (or a thin or low one) score high.

Output: {"date", "dusk", "dawn", "score" 0-10, "label", "best": [from, to] or null, "reason",
         "clouds", "bar": [60 x 0-100], "moon": {...}, "planets": [...], "milky_way": [from, to] or null}
"""

import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_ZIP = "78620"  # Dripping Springs, TX, as in the weather apps
DEFAULT_PLACE = (30.19, -98.09, "DRIPPING SPRINGS")
ZIP_URL = "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&countryCode=US"
CLOUD_URL = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&hourly=cloud_cover"
             "&timezone=auto&forecast_days=3&past_days=1")
STEP = 5  # minutes
DARK = -18.0  # astronomical twilight
BAR = 60
MILKY_WAY_CORE = (266.4, -29.0)  # RA, Dec of the galactic centre, degrees

# Schlyter's orbital elements: N, i, w, a, e, M as (value, rate per day)
PLANETS = {
    "MERCURY": ((48.3313, 3.24587e-5), (7.0047, 5.00e-8), (29.1241, 1.01444e-5), (0.387098, 0), (0.205635, 5.59e-10), (168.6562, 4.0923344368)),
    "VENUS": ((76.6799, 2.46590e-5), (3.3946, 2.75e-8), (54.8910, 1.38374e-5), (0.723330, 0), (0.006773, -1.302e-9), (48.0052, 1.6021302244)),
    "MARS": ((49.5574, 2.11081e-5), (1.8497, -1.78e-8), (286.5016, 2.92961e-5), (1.523688, 0), (0.093405, 2.516e-9), (18.6021, 0.5240207766)),
    "JUPITER": ((100.4542, 2.76854e-5), (1.3030, -1.557e-7), (273.8777, 1.64505e-5), (5.20256, 0), (0.048498, 4.469e-9), (19.8950, 0.0830853001)),
    "SATURN": ((113.6634, 2.38980e-5), (2.4886, -1.081e-7), (339.3939, 2.97661e-5), (9.55475, 0), (0.055546, -9.499e-9), (316.9670, 0.0334442282)),
}

rad, deg = math.radians, math.degrees


def sind(x):
    return math.sin(rad(x))


def cosd(x):
    return math.cos(rad(x))


def rev(x):
    return x % 360.0


def day_number(t):
    # days since 2000 Jan 0.0 UT
    return (t - datetime(1999, 12, 31, tzinfo=timezone.utc)).total_seconds() / 86400.0


def kepler(M, e):
    E = M + deg(e * sind(M) * (1 + e * cosd(M)))
    for _ in range(10):
        E1 = E - (E - deg(e * sind(E)) - M) / (1 - e * cosd(E))
        if abs(E1 - E) < 1e-6:
            break
        E = E1
    return E


def sun_ecliptic(d):
    w = 282.9404 + 4.70935e-5 * d
    e = 0.016709 - 1.151e-9 * d
    M = rev(356.0470 + 0.9856002585 * d)
    E = kepler(M, e)
    xv, yv = cosd(E) - e, math.sqrt(1 - e * e) * sind(E)
    v, r = deg(math.atan2(yv, xv)), math.hypot(xv, yv)
    lon = rev(v + w)
    return lon, r, M, w


def to_equatorial(x, y, z, d):
    ecl = 23.4393 - 3.563e-7 * d
    xe, ye, ze = x, y * cosd(ecl) - z * sind(ecl), y * sind(ecl) + z * cosd(ecl)
    return rev(deg(math.atan2(ye, xe))), deg(math.atan2(ze, math.hypot(xe, ye)))


def sun_radec(d):
    lon, r, _, _ = sun_ecliptic(d)
    return to_equatorial(r * cosd(lon), r * sind(lon), 0.0, d)


def planet_radec(name, d):
    (N, i, w, a, e, M) = [v0 + rate * d for v0, rate in PLANETS[name]]
    M = rev(M)
    E = kepler(M, e)
    xv, yv = a * (cosd(E) - e), a * math.sqrt(1 - e * e) * sind(E)
    v, r = deg(math.atan2(yv, xv)), math.hypot(xv, yv)
    xh = r * (cosd(N) * cosd(v + w) - sind(N) * sind(v + w) * cosd(i))
    yh = r * (sind(N) * cosd(v + w) + cosd(N) * sind(v + w) * cosd(i))
    zh = r * sind(v + w) * sind(i)
    slon, sr, _, _ = sun_ecliptic(d)
    return to_equatorial(xh + sr * cosd(slon), yh + sr * sind(slon), zh, d)


def moon(d):
    """Geocentric RA, Dec, distance (Earth radii), ecliptic longitude and latitude."""
    N = rev(125.1228 - 0.0529538083 * d)
    i, w = 5.1454, rev(318.0634 + 0.1643573223 * d)
    a, e, M = 60.2666, 0.054900, rev(115.3654 + 13.0649929509 * d)
    E = kepler(M, e)
    xv, yv = a * (cosd(E) - e), a * math.sqrt(1 - e * e) * sind(E)
    v, r = deg(math.atan2(yv, xv)), math.hypot(xv, yv)
    xh = r * (cosd(N) * cosd(v + w) - sind(N) * sind(v + w) * cosd(i))
    yh = r * (sind(N) * cosd(v + w) + cosd(N) * sind(v + w) * cosd(i))
    zh = r * sind(v + w) * sind(i)
    lon, lat = deg(math.atan2(yh, xh)), deg(math.atan2(zh, math.hypot(xh, yh)))

    _, _, Ms, ws = sun_ecliptic(d)
    Ls, Lm = rev(Ms + ws), rev(M + w + N)
    D, F = rev(Lm - Ls), rev(Lm - N)
    lon += (-1.274 * sind(M - 2 * D) + 0.658 * sind(2 * D) - 0.186 * sind(Ms) - 0.059 * sind(2 * M - 2 * D)
            - 0.057 * sind(M - 2 * D + Ms) + 0.053 * sind(M + 2 * D) + 0.046 * sind(2 * D - Ms)
            + 0.041 * sind(M - Ms) - 0.035 * sind(D) - 0.031 * sind(M + Ms) - 0.015 * sind(2 * F - 2 * D)
            + 0.011 * sind(M - 4 * D))
    lat += (-0.173 * sind(F - 2 * D) - 0.055 * sind(M - F - 2 * D) - 0.046 * sind(M + F - 2 * D)
            + 0.033 * sind(F + 2 * D) + 0.017 * sind(2 * M + F))
    r += -0.58 * cosd(M - 2 * D) - 0.46 * cosd(2 * D)
    x, y, z = r * cosd(lon) * cosd(lat), r * sind(lon) * cosd(lat), r * sind(lat)
    ra, dec = to_equatorial(x, y, z, d)
    return ra, dec, r, rev(lon), lat


def local_sidereal(t, d, lon):
    _, _, Ms, ws = sun_ecliptic(d)
    ut = t.hour + t.minute / 60 + t.second / 3600
    return rev(Ms + ws + 180 + ut * 15 + lon)


def sky_at(t, lat, lon):
    def altitude(ra, dec, lst):
        ha = lst - ra
        return deg(math.asin(sind(lat) * sind(dec) + cosd(lat) * cosd(dec) * cosd(ha)))

    d = day_number(t)
    lst = local_sidereal(t, d, lon)
    sra, sdec = sun_radec(d)
    mra, mdec, mr, mlon, mlat = moon(d)
    malt = altitude(mra, mdec, lst)
    malt -= deg(math.asin(1 / mr)) * cosd(malt)  # parallax: topocentric altitude
    slon = sun_ecliptic(d)[0]
    elong = deg(math.acos(cosd(slon - mlon) * cosd(mlat)))
    return {
        "sun": altitude(sra, sdec, lst),
        "moon": malt,
        "illum": (1 - cosd(elong)) / 2,
        "waxing": rev(mlon - slon) < 180,
        "planets": {n: altitude(*planet_radec(n, d), lst) for n in PLANETS},
        "core": altitude(MILKY_WAY_CORE[0], MILKY_WAY_CORE[1], lst),
    }


# ---------------------------------------------------------------------------

def get_json(url, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tidbyt-dark-sky/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)


def place_for(zip_code):
    """(lat, lon, name) for a US ZIP code."""
    if zip_code == DEFAULT_ZIP:
        return DEFAULT_PLACE
    found = (get_json(ZIP_URL % zip_code).get("results") or [])
    if not found:
        raise ValueError("unknown ZIP code %s" % zip_code)
    p = found[0]
    return p["latitude"], p["longitude"], p["name"].upper()


def clouds_by_hour(lat, lon):
    data = get_json(CLOUD_URL % (lat, lon))
    offset = data.get("utc_offset_seconds", -6 * 3600)
    out = {}
    for stamp, cover in zip(data["hourly"]["time"], data["hourly"]["cloud_cover"]):
        local = datetime.fromisoformat(stamp)
        utc = (local - timedelta(seconds=offset)).replace(tzinfo=timezone.utc)
        out[int(utc.timestamp()) // 3600] = cover if cover is not None else 50
    return out, offset


def clock(t, offset):
    lt = t + timedelta(seconds=offset)
    h = lt.hour % 12 or 12
    return "%d:%02d%s" % (h, lt.minute, "A" if lt.hour < 12 else "P")


def quality(s, cloud):
    moon_light = 0.0
    if s["moon"] > 0:
        moon_light = s["illum"] * (0.35 + 0.65 * min(1.0, s["moon"] / 30.0))
    return max(0.0, (1 - cloud / 100.0) ** 1.5 * (1 - 0.85 * moon_light))


def runs(flags):
    """(start, end) index pairs of consecutive True values."""
    out, start = [], None
    for k, f in enumerate(flags + [False]):
        if f and start is None:
            start = k
        elif not f and start is not None:
            out.append((start, k - 1))
            start = None
    return out


def build(now=None, zip_code=DEFAULT_ZIP):
    zip_code = (zip_code or DEFAULT_ZIP).strip()[:5]
    lat, lon, place = place_for(zip_code)
    now = now or datetime.now(timezone.utc).replace(second=0, microsecond=0)
    now = now - timedelta(minutes=now.minute % STEP)
    clouds, offset = clouds_by_hour(lat, lon)

    # find tonight: the dark spell in progress, or the next one
    times = [now - timedelta(hours=14) + timedelta(minutes=STEP * k) for k in range(int(40 * 60 / STEP))]
    sun = [sky_at(t, lat, lon)["sun"] for t in times]
    spells = runs([a < DARK for a in sun])
    spell = next(((a, b) for a, b in spells if times[b] >= now), None)
    if spell is None:
        raise RuntimeError("no dark night found")
    night = times[spell[0]:spell[1] + 1]
    dusk, dawn = night[0], night[-1] + timedelta(minutes=STEP)
    skies = [sky_at(t, lat, lon) for t in night]
    cover = [clouds.get(int(t.timestamp()) // 3600, 50) for t in night]
    q = [quality(s, c) for s, c in zip(skies, cover)]

    # best hour sets the score; the best window is the longest stretch of good sky
    per_hour = 60 // STEP
    best_hour = max(sum(q[k:k + per_hour]) / per_hour for k in range(max(1, len(q) - per_hour + 1)))
    score = int(round(10 * best_hour))
    label = "GREAT" if score >= 8 else "GOOD" if score >= 6 else "FAIR" if score >= 4 else "POOR"
    good = []
    for floor in (0.8, 0.6, 0.4):  # the darkest stretch that lasts at least an hour
        good = [r for r in runs([v >= floor for v in q]) if r[1] - r[0] >= per_hour - 1]
        if good:
            break
    best = None
    if good and score >= 4:
        a, b = max(good, key=lambda r: r[1] - r[0])
        best = [clock(night[a], offset), clock(night[b] + timedelta(minutes=STEP), offset)]

    avg_cloud = int(round(sum(cover) / len(cover)))
    moon_up = [s["moon"] > 0 for s in skies]
    illum = skies[len(skies) // 2]["illum"]
    reason = ""
    if score < 6:
        moon_share = sum(moon_up) / len(moon_up)
        reason = "CLOUDY" if avg_cloud >= 50 else ("BRIGHT MOON" if illum > 0.5 and moon_share > 0.5 else "HAZE / MOON")

    # moon: the event that matters during the dark hours
    rise = next((night[k] for k in range(1, len(night)) if moon_up[k] and not moon_up[k - 1]), None)
    sets = next((night[k] for k in range(1, len(night)) if moon_up[k - 1] and not moon_up[k]), None)
    if all(moon_up):
        moon_event = "UP ALL NIGHT"
    elif not any(moon_up):
        moon_event = "DOWN ALL NIGHT"
    elif sets and (not rise or sets < rise):
        moon_event = "SETS " + clock(sets, offset)
    else:
        moon_event = "RISES " + clock(rise, offset)

    # planets 10+ degrees up while the sky is dark enough (Mercury and Venus: in twilight too)
    span = [now - timedelta(hours=14) + timedelta(minutes=STEP * k) for k in range(spell[0] - 18, spell[1] + 19)]
    twilight = [sky_at(t, lat, lon) for t in span]
    planets = []
    for name in ("VENUS", "JUPITER", "SATURN", "MARS", "MERCURY"):
        limit = -6 if name in ("VENUS", "MERCURY") else DARK
        if any(s["sun"] < limit and s["planets"][name] > 10 for s in twilight):
            planets.append(name)

    core = [s["core"] > 10 and not m for s, m in zip(skies, moon_up)]
    core_runs = [r for r in runs(core) if r[1] - r[0] >= 5]
    milky_way = None
    if core_runs:
        a, b = max(core_runs, key=lambda r: r[1] - r[0])
        milky_way = [clock(night[a], offset), clock(night[b] + timedelta(minutes=STEP), offset)]

    bar = []
    for k in range(BAR):
        j = min(len(q) - 1, int(k * len(q) / BAR))
        bar.append(int(round(100 * q[j])))

    local_dusk = dusk + timedelta(seconds=offset)
    return {
        "fetched_at": int(time.time()),
        "zip": zip_code,
        "place": place,
        "date": local_dusk.strftime("%a %m/%d").upper().replace(" 0", " ").replace("/0", "/"),
        "dark_now": now >= dusk,
        "dusk": clock(dusk, offset),
        "dawn": clock(dawn, offset),
        "score": score,
        "label": label,
        "best": best,
        "reason": reason,
        "clouds": avg_cloud,
        "bar": bar,
        "moon": {"illum": int(round(100 * illum)), "waxing": skies[len(skies) // 2]["waxing"], "event": moon_event},
        "planets": planets,
        "milky_way": milky_way,
    }


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3, 4):
        sys.exit(__doc__)
    when = datetime.fromtimestamp(int(sys.argv[3]), timezone.utc) if len(sys.argv) == 4 else None
    snap = build(when, sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_ZIP)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    print(json.dumps({k: v for k, v in snap.items() if k != "bar"}, indent=1))
