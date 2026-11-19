# Adelaide Camera Alerts

A daily map of SA Police's mobile speed camera roads, tailored to two regular drives:

- **Justin:** Hove → Anzac Hwy → Greenhill Rd, Wayville
- **Yvette:** Hove → Seaford

Every morning (4:35am, with a 6:35am catch-up run) a free GitHub Actions job runs these steps:

1. Reads the SAPOL mobile camera page, which covers about a week of daily metro lists plus the country list.
2. Finds each road inside its suburb in OpenStreetMap and marks the whole stretch.
3. Tags each road as **on** a drive (the route runs along it) or **near** a drive (within about 1.2 km).
4. Publishes the phone map app to GitHub Pages.

## The app
- **Day tabs:** Today, Tomorrow and the rest of the week.
- **Filter:** Both, Justin or Yvette. Add `#justin` or `#yvette` to the link to open straight to one person's view.
- **Cards:** list what's on or near each drive. Tap a road to zoom to it.
- **☰:** opens the full list, with J and Y tags.
- **Start drive:** turns on spoken warnings about 25 seconds before a flagged road, and when you turn onto one. On iPhone, keep the app on screen.

## Changing a route
Edit `scraper/routes.json`. Each point can be a road in a suburb, a suburb, or `[lat, lon]`. Push the change and the route is recalculated on the next run.

## Files
| Path | What it does |
|---|---|
| `scraper/scrape.py` | Parses SAPOL (with a headless-browser fallback), looks up roads in OSM via Overpass, builds routes via OSRM, matches roads to routes |
| `scraper/cache/` | Road geometry and route cache, so each road is only looked up once |
| `docs/` | The phone app (Leaflet) and `docs/data/` (written daily) |
| `.github/workflows/daily.yml` | The daily job and the Pages deploy |
| `tests/test_scraper.py` | Offline tests for parsing and matching |

SAPOL lists roads where cameras *may* operate that day, not exact spots or times. Locations © SA Police. Map data © OpenStreetMap contributors. For personal use.
