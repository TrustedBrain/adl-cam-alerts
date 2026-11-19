"""Offline tests: list parsing, name handling and route matching. Run: python3 tests/test_scraper.py"""
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import scrape as S  # noqa: E402

# Layout seen on the SAPOL page: a date index, then one section per day, then the country list.
HTML = """<html><body><nav>Home | Fixed camera locations</nav>
<h1>Mobile camera locations</h1>
<ul><li><a>20/11/2026</a></li><li><a>21/11/2026</a></li></ul>
<h2>Metropolitan traffic camera locations</h2>
<h3>Friday, 20 November 2026</h3>
<ul><li>peacock rd, adelaide</li><li>south tce, adelaide</li><li>cross rd, myrtle bank</li>
<li>o'halloran hill rd, o'halloran hill</li><li>mckinna rd, christie downs</li></ul>
<h3>Saturday, 21 November 2026</h3>
<ul><li>brighton rd, hove</li><li>anzac hwy, plympton</li><li>southern exp, lonsdale</li></ul>
<h2>Country traffic camera locations</h2>
<p>This week's locations: Monday, 16 November 2026 to Sunday, 29 November 2026</p>
<ul><li>augusta hwy, port wakefield</li><li>barrier hwy, burra</li></ul>
<footer>Fixed camera locations</footer>
</body></html>"""

days, clabel, country = S.parse_sapol(HTML)
assert sorted(days) == [dt.date(2026, 11, 20), dt.date(2026, 11, 21)], days
assert ("Peacock Rd", "Adelaide") in days[dt.date(2026, 11, 20)]
assert ("O'Halloran Hill Rd", "O'Halloran Hill") in days[dt.date(2026, 11, 20)]
assert ("McKinna Rd", "Christie Downs") in days[dt.date(2026, 11, 20)]
assert len(days[dt.date(2026, 11, 21)]) == 3
assert clabel.startswith("Monday, 16 November 2026"), clabel
assert ("Barrier Hwy", "Burra") in country and len(country) == 2
print("parse ok:", {str(k): len(v) for k, v in days.items()}, "country", len(country))

# dd/mm/yyyy section headings also work
d2, _, _ = S.parse_sapol("<h3>20/11/2026</h3><li>cross rd, myrtle bank</li>")
assert d2 == {dt.date(2026, 11, 20): [("Cross Rd", "Myrtle Bank")]}

assert S.osm_name("Southern Exp") == "Southern Expressway"
assert S.osm_name("Port River Exp") == "Port River Expressway"
assert S.osm_name("Anzac Hwy") == "Anzac Highway"
assert S.osm_name("Mt Barker Rd") == "Mount Barker Road"
assert S.osm_name("North South Motorway") == "North South Motorway"
f = S.name_filter("O'Halloran Hill Rd")
assert "\\" not in f and re.search(f.split('~"', 2)[2].split('",i')[0], "O'Halloran Hill Road", re.I)
assert re.fullmatch(S.rx("St. Bernards Rd"), "St. Bernards Rd") and not re.fullmatch(S.rx("St. Bernards Rd"), "Stx Bernards Rd")
print("names ok")

# Matching: a route running east along a road vs a parallel street 400 m away vs one 3 km away
M = 1 / 111320
road = [[-34.96, 138.55], [-34.96, 138.56]]
route = S.densify([[-34.96, 138.54], [-34.96, 138.57]])
assert S.match(route, [road]) == "on"
assert S.match(route, [[[-34.96 - 400 * M, 138.55], [-34.96 - 400 * M, 138.56]]]) == "near"
assert S.match(route, [[[-34.96 - 3000 * M, 138.55], [-34.96 - 3000 * M, 138.56]]]) is None
# crossing road (route only touches it at the intersection) is "near", not "on"
assert S.match(route, [[[-34.95, 138.555], [-34.97, 138.555]]]) == "near"
assert S.match(route, []) is None
print("matching ok")
print("all scraper tests passed")
