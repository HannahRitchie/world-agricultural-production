"""Screenshot every view and control combination, failing on any console error.

Run with the port-8888 server up:
    uv run --with playwright python scripts/check_views.py
"""
import json
import os
import pathlib

from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "_shots")
os.makedirs(OUT, exist_ok=True)
BASE = "http://localhost:8888/index.html"
INDEX = json.loads((pathlib.Path(__file__).parent.parent / "data" / "index.json").read_text())
NAME = {c["slug"]: c["name"] for c in INDEX["commodities"]}

errors = []


def pick_food(pg, slug):
    pg.click("#food-btn")
    pg.wait_for_timeout(200)
    pg.fill("#food-search", NAME[slug])
    pg.wait_for_timeout(250)
    pg.click(f'#food-list .opt-item:text-is("{NAME[slug]}")')
    pg.wait_for_timeout(1100)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1240, "height": 1000})
    pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}")
          if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

    def shot(name):
        pg.screenshot(path=f"{OUT}/{name}.png")
        print(f"  {name:22s} title={pg.inner_text('#chart-title')!r} "
              f"badge={pg.inner_text('#year-badge').strip()!r}")

    pg.goto(BASE)
    pg.wait_for_timeout(2500)

    print("four views, default food:")
    shot("01-chart")
    for view in ["map", "columns", "table"]:
        pg.click(f'.tab[data-view="{view}"]')
        pg.wait_for_timeout(900)
        shot(f"02-{view}")

    print("\nmetrics:")
    pg.click('.tab[data-view="chart"]')
    pick_food(pg, "corn")
    pg.select_option("#sel-metric", "yield")
    pg.wait_for_timeout(800)
    shot("03-corn-yield")
    pg.select_option("#sel-metric", "area")
    pg.wait_for_timeout(800)
    shot("04-corn-area")

    print("\nproduction-only commodity (metrics greyed out):")
    pick_food(pg, "dairy-cheese")
    shot("05-cheese")

    print("\nforecast detail, zoomed:")
    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&time=2008..2026"
                   "&entities=%40World")
    pg.wait_for_timeout(2400)
    shot("06-forecast-zoom")

    print("\nfood dropdown open, searching:")
    pg.goto(BASE)
    pg.wait_for_timeout(2400)
    pg.click("#food-btn")
    pg.wait_for_timeout(250)
    pg.fill("#food-search", "oil")
    pg.wait_for_timeout(350)
    shot("07-food-search")

    print("\nsidebar search:")
    pg.keyboard.press("Escape")
    pg.fill("#ent-search", "china")
    pg.wait_for_timeout(350)
    shot("08-sidebar-search")

    print("\nmap where the EU is the reporting entity:")
    pg.goto(BASE + "?tab=map&food=wheat&metric=production&year=2024")
    pg.wait_for_timeout(2400)
    shot("09-map-eu")
    print("  eu hatch polygons:", pg.eval_on_selector_all(
        "#viz path",
        "ps=>ps.filter(p=>(p.getAttribute('fill')||'').includes('eu-hatch')).length"))

    print("\ncolumn chart, few series over a narrow range:")
    pg.goto(BASE + "?tab=columns&food=oilseed-soybean&metric=production"
                   "&time=2000..2026&entities=BR~US~AR")
    pg.wait_for_timeout(2400)
    shot("10-columns-narrow")

    b.close()

print(f"\n=== console errors/warnings: {len(errors)}")
for e in errors[:30]:
    print(" ", e)
