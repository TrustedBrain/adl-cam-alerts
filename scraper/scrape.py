#!/usr/bin/env python3
"""Daily SA mobile speed camera scraper.

1. Pulls SA Police's mobile camera page (about a week of daily metro lists plus the country list).
2. Finds each road inside its suburb in OpenStreetMap (Overpass), cached in scraper/cache/geo.json.
3. Works out Justin's and Yvette's regular routes (OSRM), cached in scraper/cache/routes.json.
4. Tags each camera road as "on" (shares road with a route) or "near" (within 1.2 km).
5. Writes docs/data/data.json and docs/data/geo.json for the map app.
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scraper" / "cache"
OUT = ROOT / "docs" / "data"
DEBUG = ROOT / "scraper" / "debug"
ADL = ZoneInfo("Australia/Adelaide")
SAPOL_URL = "https://speedcameras.sa.gov.au/home/mobile_camera_locations"
UA = {"User-Agent": "Mozilla/5.0 (personal camera map; github.com/TrustedBrain/adl-cam-alerts)"}
CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/131.0.0.0 Safari/537.36")
BROWSER_HEADERS = {"User-Agent": CHROME_UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Language": "en-AU,en;q=0.9", "Cache-Control": "no-cache"}
FLEURIEU_HOME = "https://fleurieunews.com.au/"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
OSRM = "https://router.project-osrm.org/route/v1/driving/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
_last_nom = [0.0]
SA_BBOX = "(-38.1,129.0,-25.9,141.1)"

ON_SHARED_M = 120     # route must run along the camera road for at least this far to count as "on"
ON_TOL_M = 30         # ...within this distance of it
NEAR_M = 1200         # otherwise, anything this close counts as "near"

MONTHS = "January February March April May June July August September October November December".split()
DAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
DATE_LONG = re.compile(r"^(?:(%s),?\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(%s)\s+(\d{4})$" % ("|".join(DAYS), "|".join(MONTHS)), re.I)
DATE_MDY = re.compile(r"(%s),?\s+(%s)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?" % ("|".join(DAYS), "|".join(MONTHS)), re.I)
DATE_SHORT = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
ROAD_LINE = re.compile(r"^[A-Za-z0-9'’.\- ]{2,50},\s*[A-Za-z'’.\- ]{2,40}$")

ABBR = {"rd": "Road", "st": "Street", "tce": "Terrace", "ave": "Avenue", "av": "Avenue", "hwy": "Highway",
        "dr": "Drive", "pde": "Parade", "exp": "Expressway", "expy": "Expressway", "bvd": "Boulevard",
        "blvd": "Boulevard", "cres": "Crescent", "cr": "Crescent", "pl": "Place", "ct": "Court", "gr": "Grove",
        "cct": "Circuit", "pkwy": "Parkway", "esp": "Esplanade", "wy": "Way", "ln": "Lane", "cl": "Close",
        "hts": "Heights", "mwy": "Motorway", "fwy": "Freeway", "sq": "Square", "rdwy": "Roadway", "ch": "Chase"}
PREFIX = {"nth": "North", "sth": "South", "mt": "Mount", "st": "Saint"}


def log(*a):
    print(*a, flush=True)


def adl_today():
    return dt.datetime.now(ADL).date()


def title(s):
    out = []
    for w in s.lower().split():
        if w in ("of", "the"):
            out.append(w)
        elif "'" in w or "’" in w:
            out.append("'".join(p.capitalize() for p in re.split("['’]", w)))
        elif "-" in w:
            out.append("-".join(p.capitalize() for p in w.split("-")))
        else:
            out.append(w.capitalize())
    s = " ".join(out)
    return re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), s)


# ---------------------------------------------------------------- SAPOL page

def fetch_html(url):
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=40)
    r.raise_for_status()
    return r.text


def fetch_impersonate(url):
    """Same request with a real Chrome TLS fingerprint (gets past some bot filters)."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "curl_cffi"], check=True)
        from curl_cffi import requests as creq
    r = creq.get(url, impersonate="chrome", timeout=40, headers={"Accept-Language": "en-AU,en;q=0.9"})
    r.raise_for_status()
    return r.text


def fetch_rendered(url):
    """Headless browser fallback for when the page builds its lists with JavaScript."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
        from playwright.sync_api import sync_playwright
    subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True,
                   stdout=subprocess.DEVNULL)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=CHROME_UA, locale="en-AU", timezone_id="Australia/Adelaide")
        pg.goto(url, wait_until="networkidle", timeout=90000)
        pg.wait_for_timeout(3000)
        html = pg.content()
        b.close()
    return html


def page_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    lines = []
    for raw in soup.get_text("\n").split("\n"):
        s = re.sub(r"\s+", " ", raw).strip(" \t-•·*")
        if s:
            lines.append(s)
    return lines


def parse_date(s):
    m = DATE_LONG.match(s)
    if m:
        return dt.date(int(m.group(4)), MONTHS.index(m.group(3).capitalize()) + 1, int(m.group(2)))
    m = DATE_SHORT.match(s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def parse_sapol(html):
    """Returns ({date: [(road, suburb)]}, country_label, [(road, suburb)])."""
    days, country, country_label = {}, [], ""
    cur, section = None, "metro"
    for s in page_lines(html):
        low = s.lower()
        if "country" in low and "camera" in low and len(s) < 60:
            section, cur = "country", None
            continue
        if section == "metro" and ("fixed" in low and "camera" in low and len(s) < 60):
            cur = None
            continue
        if section == "country":
            if "locations" in low and (" to " in low or "week" in low) and len(s) < 120:
                country_label = s.split(":", 1)[-1].strip()
                continue
            if "fixed" in low and "camera" in low and len(s) < 60:
                section = "done"
                continue
        if section == "metro":
            d = parse_date(s)
            if d:
                cur = d
                days.setdefault(cur, [])
                continue
        if ROAD_LINE.match(s):
            road, suburb = [x.strip() for x in s.split(",", 1)]
            if section == "metro" and cur:
                days[cur].append((title(road), title(suburb)))
            elif section == "country":
                country.append((title(road), title(suburb)))
    days = {d: sorted(set(v), key=lambda x: (x[1], x[0])) for d, v in days.items() if v}
    return days, country_label, sorted(set(country), key=lambda x: (x[1], x[0]))


def snippet(html, n=400):
    t = " ".join(page_lines(html))
    return t[:n]


def infer_date(m, today):
    month = MONTHS.index(m.group(2).capitalize()) + 1
    day = int(m.group(3))
    if m.group(4):
        return dt.date(int(m.group(4)), month, day)
    for y in (today.year, today.year + 1, today.year - 1):
        try:
            d = dt.date(y, month, day)
        except ValueError:
            continue
        if abs((d - today).days) < 200 and DAYS[d.weekday()].lower() == m.group(1).lower():
            return d
    return None


def fleurieu_lists(today):
    """Fallback: The Fleurieu App posts each day's SAPOL metro list as a news story."""
    home = fetch_rendered(FLEURIEU_HOME)
    soup = BeautifulSoup(home, "html.parser")
    links = {}
    for a in soup.find_all("a", href=True):
        txt = " ".join(a.get_text(" ").split())
        if "/NewsStory/" in a["href"] and "camera" in (txt + a["href"]).lower():
            links[requests.compat.urljoin(FLEURIEU_HOME, a["href"])] = txt
    log(f"Fleurieu: {len(links)} camera stories on the home page")
    days = {}
    for url, txt in list(links.items())[:8]:
        html = fetch_html(url)
        lines = page_lines(html)
        head = " ".join(lines[:40])
        m = DATE_MDY.search(txt) or DATE_MDY.search(head)
        d = infer_date(m, today) if m else None
        if not d or d < today - dt.timedelta(days=1) or d in days:
            continue
        roads = sorted({tuple(title(x) for x in [p.strip() for p in s_.split(",", 1)]) for s_ in lines if ROAD_LINE.match(s_)},
                       key=lambda x: (x[1], x[0]))
        if len(roads) >= 5:
            days[d] = roads
            log(f"  {d}: {len(roads)} roads from {url}")
    return days


LISTS_FILE = ROOT / "scraper" / "lists.json"


def file_lists(today):
    """Lists saved into the repo by the daily Claude task (it can reach the list when GitHub's servers can't)."""
    j = load(LISTS_FILE, {})
    days = {}
    for k, v in (j.get("days") or {}).items():
        d = dt.date.fromisoformat(k)
        if d >= today - dt.timedelta(days=1) and v:
            days[d] = sorted({(title(r), title(s_)) for r, s_ in v}, key=lambda x: (x[1], x[0]))
    country = sorted({(title(r), title(s_)) for r, s_ in (j.get("country") or {}).get("roads", [])}, key=lambda x: (x[1], x[0]))
    return days, (j.get("country") or {}).get("label", ""), country, j.get("source", "saved list")


def get_lists(today):
    tried = []
    DEBUG.mkdir(parents=True, exist_ok=True)
    refused = 0
    for how, fn in (("plain", fetch_html), ("chrome-tls", fetch_impersonate), ("browser", fetch_rendered)):
        if how == "browser" and refused == 2:
            tried.append("browser: skipped (site refuses this server)")
            continue
        try:
            html = fn(SAPOL_URL)
        except Exception as e:
            tried.append(f"{how}: {str(e)[:120]}")
            log(f"SAPOL ({how}) failed: {str(e)[:200]}")
            refused += "403" in str(e)
            continue
        (DEBUG / f"sapol-{how}.html").write_text(html)
        days, clabel, country = parse_sapol(html)
        log(f"SAPOL ({how}): {len(days)} days -> {[str(d) for d in sorted(days)]}, country {len(country)}")
        if days:
            return days, clabel, country, "SA Police"
        log(f"  page text: {snippet(html)}")
        tried.append(f"{how}: no dated lists found")
    days, clabel, country, src = file_lists(today)
    if today in days:
        log(f"Using saved lists ({src}): {[str(d) for d in sorted(days)]}")
        return days, clabel, country, src
    tried.append("saved lists: nothing for today")
    try:
        days = fleurieu_lists(today)
        if days:
            return days, "", [], "The Fleurieu App (repost of the SA Police list)"
        tried.append("fleurieu: nothing current")
    except Exception as e:
        tried.append(f"fleurieu: {str(e)[:120]}")
        log(f"Fleurieu failed: {e}")
    raise RuntimeError("Could not read the camera list: " + "; ".join(tried))


# ---------------------------------------------------------------- OpenStreetMap

def overpass(q):
    last = None
    for attempt in range(1):
        for url in OVERPASS[:2]:
            try:
                r = requests.post(url, data={"data": q}, headers=UA, timeout=30)
                if r.status_code == 200:
                    return r.json()
                last = f"{url} {r.status_code}"
            except Exception as e:
                last = f"{url} {str(e)[:80]}"
            time.sleep(1)
    raise RuntimeError(f"Overpass failed: {last}")


def osm_name(road):
    words = road.split()
    if len(words) > 1 and words[0].lower() in PREFIX and words[0].lower() != "st":
        words[0] = PREFIX[words[0].lower()]
    if words and words[-1].lower().strip(".") in ABBR:
        words[-1] = ABBR[words[-1].lower().strip(".")]
    return " ".join(words)


def rx(s):
    """Regex for a name, written without backslashes (they'd need double-escaping inside Overpass strings)."""
    out = []
    for ch in re.sub(r"[’']", "'", s):
        if ch == "'":
            out.append("['’]?")
        elif ch == " ":
            out.append("[ -]?")
        elif ch in ".+*?$(){}|-=!<>:":
            out.append(f"[{ch}]")
        elif ch in '"\\[]^':
            out.append(".")
        else:
            out.append(ch)
    return "".join(out)


def name_filter(road):
    full = osm_name(road)
    alts = {rx(full), rx(road)}
    return '[~"^(name|alt_name|official_name|old_name)$"~"^(%s)$",i]' % "|".join(sorted(alts))


def lines_from(res):
    out = []
    for el in res.get("elements", []):
        g = el.get("geometry")
        if el.get("type") == "way" and g and len(g) > 1:
            out.append([[round(p["lat"], 6), round(p["lon"], 6)] for p in g])
    return out


def qs(s):
    return s.replace('"', "").replace("’", "'")


def nominatim(params):
    wait = 1.1 - (time.time() - _last_nom[0])
    if wait > 0:
        time.sleep(wait)
    _last_nom[0] = time.time()
    p = {"format": "jsonv2", "countrycodes": "au", **params}
    r = requests.get(NOMINATIM, params=p, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def geo_lines(g):
    if not g:
        return []
    if g["type"] == "LineString":
        return [[[round(y, 6), round(x, 6)] for x, y in g["coordinates"]]]
    if g["type"] == "MultiLineString":
        return [[[round(y, 6), round(x, 6)] for x, y in ln] for ln in g["coordinates"]]
    return []


def nominatim_road(road, suburb):
    full = osm_name(road)
    res = nominatim({"street": full, "city": suburb, "state": "South Australia", "polygon_geojson": 1,
                     "dedupe": 0, "limit": 40, "layer": "address"})
    lines = []
    for x in res:
        if x.get("category", x.get("class")) != "highway":
            continue
        nm = (x.get("name") or "").lower()
        if nm and nm != full.lower() and nm != road.lower():
            continue
        lines += geo_lines(x.get("geojson"))
    return lines


def find_road(road, suburb):
    try:
        lines = nominatim_road(road, suburb)
        if lines:
            return lines, "nominatim"
    except Exception as e:
        log(f"  nominatim error {road}, {suburb}: {str(e)[:120]}")
    return find_road_overpass(road, suburb)


def find_road_overpass(road, suburb):
    """Exact-name lookups first (fast, indexed); regex only as a fallback."""
    full, sub = qs(osm_name(road)), qs(suburb)
    q1 = f"""[out:json][timeout:25];
area["name"="{sub}"]["boundary"="administrative"]->.s;
way(area.s)["highway"]["name"="{full}"]{SA_BBOX};
out geom;"""
    lines = lines_from(overpass(q1))
    if lines:
        return lines, "suburb"
    q2 = f"""[out:json][timeout:25];
node["place"]["name"="{sub}"]{SA_BBOX}->.p;
way(around.p:3000)["highway"]["name"="{full}"];
out geom;"""
    lines = lines_from(overpass(q2))
    if lines:
        return lines, "near-suburb"
    q3 = f"""[out:json][timeout:25];
node["place"]["name"~"^{rx(suburb)}$",i]{SA_BBOX}->.p;
way(around.p:3500)["highway"]{name_filter(road)};
out geom;"""
    lines = lines_from(overpass(q3))
    return (lines, "fuzzy") if lines else ([], "not found")


def resolve_point(pt):
    if isinstance(pt, list):
        return pt
    if "place" in pt:
        res = nominatim({"city": pt["place"], "state": "South Australia", "limit": 1})
        if not res:
            raise RuntimeError(f"place not found: {pt}")
        return [float(res[0]["lat"]), float(res[0]["lon"])]
    lines, _ = find_road(pt["road"], pt["suburb"])
    if not lines:
        raise RuntimeError(f"route point not found: {pt}")
    pts = [p for ln in lines for p in ln]
    cy = sum(p[0] for p in pts) / len(pts)
    cx = sum(p[1] for p in pts) / len(pts)
    return min(pts, key=lambda p: (p[0] - cy) ** 2 + (p[1] - cx) ** 2)  # point on the road nearest its middle


def build_routes(cfg, cache):
    out = {}
    for key, r in cfg.items():
        if key.startswith("_"):
            continue
        sig = hashlib.sha1(json.dumps(r["points"], sort_keys=True).encode()).hexdigest()
        c = cache.get(key)
        if c and c.get("sig") == sig and c.get("coords"):
            coords = c["coords"]
        else:
            pts = [resolve_point(p) for p in r["points"]]
            url = OSRM + ";".join(f"{p[1]},{p[0]}" for p in pts) + "?overview=full&geometries=geojson"
            res = requests.get(url, headers=UA, timeout=60).json()
            if res.get("code") != "Ok":
                raise RuntimeError(f"OSRM failed for {key}: {res.get('code')}")
            coords = [[round(y, 6), round(x, 6)] for x, y in res["routes"][0]["geometry"]["coordinates"]]
            cache[key] = {"sig": sig, "coords": coords, "km": round(res["routes"][0]["distance"] / 1000, 1)}
            log(f"route {key}: {cache[key]['km']} km")
        out[key] = {"name": r["name"], "label": r["label"], "color": r["color"], "coords": coords}
    return out


# ---------------------------------------------------------------- matching

LAT0 = -34.95
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110540


def xy(p):
    return (p[1] * KX, p[0] * KY)


def seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def densify(coords, step=15):
    pts = [xy(c) for c in coords]
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(d // step))
        for i in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
    return out


def match(route_pts, lines):
    """'on' if the route runs along the road, 'near' if within NEAR_M, else None."""
    segs = [(xy(a), xy(b)) for ln in lines for a, b in zip(ln, ln[1:])]
    if not segs:
        return None
    xs = [p[0] for s in segs for p in s]; ys = [p[1] for s in segs for p in s]
    x0, x1, y0, y1 = min(xs) - NEAR_M, max(xs) + NEAR_M, min(ys) - NEAR_M, max(ys) + NEAR_M
    best, shared, prev = 1e12, 0.0, None
    for p in route_pts:
        if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1):
            prev = None
            continue
        d = min(seg_dist(p, a, b) for a, b in segs)
        best = min(best, d)
        if d <= ON_TOL_M and prev is not None:
            shared += math.hypot(p[0] - prev[0], p[1] - prev[1])
        prev = p if d <= ON_TOL_M else None
    if shared >= ON_SHARED_M:
        return "on"
    return "near" if best <= NEAR_M else None


# ---------------------------------------------------------------- main

def load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def rid(road, suburb):
    return re.sub(r"[^a-z0-9]+", "-", f"{road} {suburb}".lower()).strip("-")


def main():
    today = adl_today()
    OUT.mkdir(parents=True, exist_ok=True)
    geo_cache = load(CACHE / "geo.json", {})
    route_cache = load(CACHE / "routes.json", {})
    prev = load(OUT / "data.json", {})

    try:
        days, clabel, country, source = get_lists(today)
    except Exception as e:
        log(f"ERROR {e}")
        if prev:
            prev["stale"] = True
            prev["error"] = str(e)[:300]
            prev["checked"] = dt.datetime.now(ADL).isoformat(timespec="minutes")
            (OUT / "data.json").write_text(json.dumps(prev, indent=1))
        sys.exit(1)

    days = {d: v for d, v in days.items() if d >= today - dt.timedelta(days=1)}
    try:
        routes = build_routes(load(ROOT / "scraper" / "routes.json", {}), route_cache)
    except Exception as e:
        log(f"Route error: {e}")
        routes = prev.get("routes") or {}
        if not routes:
            raise
    dense = {k: densify(r["coords"]) for k, r in routes.items()}

    wanted = {(r, s) for v in days.values() for r, s in v} | set(country)
    misses = []
    for road, suburb in sorted(wanted):
        k = f"{road}|{suburb}"
        c = geo_cache.get(k)
        if c is not None and (c["lines"] or c.get("t", 0) > time.time() - 7 * 86400):
            continue  # cached (failed lookups are retried weekly)
        try:
            lines, how = find_road(road, suburb)
        except Exception as e:
            log(f"  lookup error {k}: {e}")
            continue
        geo_cache[k] = {"lines": lines, "how": how, "t": int(time.time())}
        log(f"  {k}: {how} ({len(lines)} ways)")
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "geo.json").write_text(json.dumps(geo_cache, separators=(",", ":"), sort_keys=True))

    geo, summary = {}, {}

    def entry(road, suburb):
        k = f"{road}|{suburb}"
        lines = (geo_cache.get(k) or {}).get("lines") or []
        i = rid(road, suburb)
        if lines:
            geo[i] = lines
        else:
            misses.append(k)
        m = {key: match(dense[key], lines) for key in routes}
        return {"id": i, "road": road, "suburb": suburb, "placed": bool(lines), "match": m}

    out_days = []
    for d in sorted(days):
        roads = [entry(r, s) for r, s in days[d]]
        out_days.append({"date": d.isoformat(), "label": f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}",
                         "roads": roads})
        summary[d.isoformat()] = {k: [f"{x['road']}, {x['suburb']}" for x in roads if x["match"][k] == "on"]
                                  for k in routes}

    data = {
        "generated": dt.datetime.now(ADL).isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "source": source,
        "stale": today.isoformat() not in {d["date"] for d in out_days},
        "days": out_days,
        "country": {"label": clabel, "roads": [entry(r, s) for r, s in country]},
        "routes": routes,
        "summary": summary,
    }
    (OUT / "data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    (OUT / "geo.json").write_text(json.dumps(geo, separators=(",", ":")))
    (CACHE / "geo.json").write_text(json.dumps(geo_cache, separators=(",", ":"), sort_keys=True))
    (CACHE / "routes.json").write_text(json.dumps(route_cache, separators=(",", ":"), sort_keys=True))
    log(f"Wrote {len(out_days)} days, {len(geo)} placed roads, {len(set(misses))} not placed: {sorted(set(misses))[:20]}")
    log("Summary: " + json.dumps(summary.get(today.isoformat(), {})))


if __name__ == "__main__":
    main()
