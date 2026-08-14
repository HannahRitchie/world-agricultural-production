"""Regression pass: view switching, metric availability, deep links, data vintage.

Run with the port-8888 server up:
    uv run --with playwright python scripts/check_regressions.py
"""
import json
import os
import pathlib
import struct
import tempfile

from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(__file__), "_shots")
os.makedirs(OUT, exist_ok=True)
BASE = "http://localhost:8888/index.html"
INDEX = json.loads((pathlib.Path(__file__).parent.parent / "data" / "index.json").read_text())
NAME = {c["slug"]: c["name"] for c in INDEX["commodities"]}
# Derived from the build, not hardcoded, so a monthly PSD rebuild does not need
# this file edited: the vintage years and publication date move every release.
UPDATED = INDEX["source_updated"]
VINTAGE = {c["slug"]: (c["year_provisional"], c["year_projection"])
           for c in INDEX["commodities"]}


def vintage_sentence(slug):
    prov, proj = VINTAGE[slug]
    if proj is None:
        return ""
    return (f" {prov} is a provisional estimate and {proj} is a USDA forecast "
            f"(which is updated monthly).")

errors, fails = [], []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def pick_food(pg, slug):
    """Drive the searchable food dropdown the way a user would."""
    pg.click("#food-btn")
    pg.wait_for_timeout(200)
    pg.fill("#food-search", NAME[slug])
    pg.wait_for_timeout(250)
    # Exact text: searching "Copra" also matches "Copra meal".
    pg.click(f'#food-list .opt-item:text-is("{NAME[slug]}")')
    pg.wait_for_timeout(1100)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1240, "height": 1000})
    pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}")
          if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

    def svg_h():
        return pg.eval_on_selector("#viz svg", "s=>+s.getAttribute('height')") \
            if pg.query_selector("#viz svg") else 0

    pg.goto(BASE)
    pg.wait_for_timeout(2500)

    print("view round-trip (the collapsed-chart regression):")
    for order in [["table", "chart"], ["columns", "chart"], ["map", "chart"],
                  ["table", "columns"], ["table", "map"]]:
        for v in order:
            pg.click(f'.tab[data-view="{v}"]')
            pg.wait_for_timeout(600)
        h = svg_h()
        check(h > 300, f"{'→'.join(order)}: svg height {h} (>300)")

    print("\nsearchable food dropdown:")
    pg.click('.tab[data-view="chart"]'); pg.wait_for_timeout(500)
    pg.click("#food-btn"); pg.wait_for_timeout(200)
    pg.fill("#food-search", "palm"); pg.wait_for_timeout(300)
    hits = pg.eval_on_selector_all("#food-list .opt-item", "os=>os.map(o=>o.textContent)")
    check(hits == ["Palm kernel meal", "Palm kernels", "Palm oil", "Palm kernel oil"]
          or set(hits) == {"Palm kernel meal", "Palm kernels", "Palm oil", "Palm kernel oil"},
          f"search 'palm' → {hits}")
    pg.fill("#food-search", "zzzz"); pg.wait_for_timeout(300)
    check("No foods match" in pg.inner_text("#food-list"), "empty search shows a message")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check(not pg.eval_on_selector("#food-panel", "e=>e.classList.contains('open')"),
          "Escape closes the panel")

    print("\nsidebar country selector:")
    pg.goto(BASE); pg.wait_for_timeout(2500)
    check(pg.is_visible("#ent-list"), "sidebar list is visible without opening anything")
    n0 = pg.eval_on_selector_all("#ent-list input:checked", "e=>e.length")
    check(n0 == 6, f"defaults pre-checked in the sidebar (got {n0})")
    check("6 selected" in pg.inner_text("#ent-count"), "count reflects the selection")
    lines0 = pg.eval_on_selector_all("#viz path[stroke-width='2']", "e=>e.length")
    pg.fill("#ent-search", "brazil"); pg.wait_for_timeout(350)
    pg.click("#ent-list .opt-item input"); pg.wait_for_timeout(700)
    lines1 = pg.eval_on_selector_all("#viz path[stroke-width='2']", "e=>e.length")
    check(lines1 > lines0, f"adding a country adds a series ({lines0} → {lines1})")
    pg.click("#ent-clear"); pg.wait_for_timeout(600)
    check("Choose one or more countries" in pg.inner_text("#viz"),
          "clearing all prompts for a selection")

    print("\nprovisional / forecast marking:")
    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&time=2010..2026")
    pg.wait_for_timeout(2500)
    dashed = pg.eval_on_selector_all("#viz path[stroke-dasharray='4,3']", "e=>e.length")
    check(dashed == 6, f"one dashed forecast segment per series (got {dashed})")
    open_dots = pg.eval_on_selector_all(
        "#viz circle[fill='#fff']", "e=>e.length")
    check(open_dots == 6, f"one open marker per series at the forecast year (got {open_dots})")
    bands = pg.eval_on_selector_all("#viz rect[fill='#f4f6f8'],#viz rect[fill='#eaeef2']", "e=>e.length")
    check(bands == 2, f"provisional + forecast bands drawn (got {bands})")
    leg = pg.inner_text(".vintage-legend").replace("\n", " ")
    check("2025 provisional" in leg and "2026 USDA forecast" in leg,
          f"vintage legend = {leg!r}")
    pg.screenshot(path=f"{OUT}/11-forecast-chart.png")

    print("\ndiscontinued series must NOT be marked as a forecast:")
    pg.goto(BASE + "?tab=chart&food=poultry-meat-broiler&metric=production")
    pg.wait_for_timeout(2500)
    dashed = pg.eval_on_selector_all("#viz path[stroke-dasharray='4,3']", "e=>e.length")
    bands = pg.eval_on_selector_all("#viz rect[fill='#f4f6f8'],#viz rect[fill='#eaeef2']", "e=>e.length")
    legs = pg.eval_on_selector_all(".vintage-legend", "e=>e.length")
    check(dashed == 0 and bands == 0 and legs == 0,
          f"broiler meat (ends 2016): dashed={dashed} bands={bands} legend={legs}")

    print("\nyear badge in the single-year views:")
    for year, expect in [(2026, "USDA FORECAST"), (2025, "PROVISIONAL"), (2010, "")]:
        pg.goto(BASE + f"?tab=map&food=wheat&metric=production&year={year}")
        pg.wait_for_timeout(2200)
        badge = pg.inner_text("#year-badge").strip().upper()
        check(badge == expect, f"{year} badge = {badge!r} (expected {expect!r})")

    print("\nfruit commodity: 2025 is the forecast, not provisional:")
    pg.goto(BASE + "?tab=map&food=apples-fresh&metric=production&year=2025")
    pg.wait_for_timeout(2200)
    check(pg.inner_text("#year-badge").strip().upper() == "USDA FORECAST",
          f"apples 2025 badge = {pg.inner_text('#year-badge')!r}")

    print("\nmetric availability:")
    pg.goto(BASE); pg.wait_for_timeout(2400)
    for food, expect in [("dairy-cheese", ["production"]),
                         ("oilseed-copra", ["production", "yield"]),
                         ("wheat", ["production", "yield", "area"])]:
        pick_food(pg, food)
        enabled = pg.eval_on_selector_all(
            "#sel-metric option", "os=>os.filter(o=>!o.disabled).map(o=>o.value)")
        check(enabled == expect, f"{food}: enabled={enabled} expected={expect}")

    pg.select_option("#sel-metric", "area"); pg.wait_for_timeout(700)
    pick_food(pg, "dairy-butter")
    check(pg.eval_on_selector("#sel-metric", "e=>e.value") == "production",
          "area → butter falls back to production")

    print("\ndeep link restore:")
    pg.goto(BASE + "?tab=chart&food=oilseed-soybean&metric=area&time=1990..2010&entities=BR~AR~US")
    pg.wait_for_timeout(2500)
    check(pg.inner_text("#chart-title") == "Area harvested for soybeans",
          f"h1 = {pg.inner_text('#chart-title')!r}")
    check(pg.inner_text("#food-btn") == "Soybeans", "food button restored")
    check(pg.eval_on_selector("#sel-metric", "e=>e.value") == "area", "metric restored")
    check("3 selected" in pg.inner_text("#ent-count"), "entities restored")
    labels = pg.eval_on_selector_all("#viz .line-label", "e=>e.map(x=>x.textContent)")
    check(sorted(labels) == ["Argentina", "Brazil", "United States"],
          f"one right-edge label per series: {labels}")
    pg.screenshot(path=f"{OUT}/12-deeplink-bar.png")

    print("\ncolumn chart is a time series, not a single year:")
    pg.goto(BASE + "?tab=columns&food=wheat&metric=production&time=2000..2026&entities=CH")
    pg.wait_for_timeout(2400)
    check(pg.eval_on_selector("#dual-wrap", "e=>e.classList.contains('show')"),
          "columns view uses the dual year range")
    check(not pg.is_visible("#play"), "no play button in the columns view")
    check(pg.inner_text("#chart-title") == "Wheat production", "no year in the columns title")
    hollow = pg.eval_on_selector_all("#viz rect[stroke-dasharray='3,2']", "e=>e.length")
    check(hollow == 1, f"one hollow forecast column (got {hollow})")

    print("\ncolumns shows exactly one entity:")
    pg.goto(BASE)
    pg.wait_for_timeout(2500)
    n_chart = pg.eval_on_selector_all("#ent-list input:checked", "e=>e.length")
    pg.click('.tab[data-view="columns"]')
    pg.wait_for_timeout(1100)
    check(pg.eval_on_selector("#ent-list input", "e=>e.type") == "radio",
          "sidebar offers radios in the columns view")
    check(pg.eval_on_selector_all("#ent-list input:checked", "e=>e.length") == 1,
          "exactly one entity is checked")
    labels = pg.eval_on_selector_all("#viz .line-label", "e=>e.map(x=>x.textContent)")
    check(len(labels) == 1, f"exactly one series plotted: {labels}")
    check(not pg.is_visible("#ent-clear"), "'Clear all' hidden where one is required")
    check("one at a time" in pg.inner_text("#ent-count"), "footer explains the limit")
    check(pg.url.count("~") == 0, f"url carries a single entity: {pg.url.split('?')[-1]}")
    # switching back must not have destroyed the multi-selection
    pg.click('.tab[data-view="chart"]')
    pg.wait_for_timeout(1000)
    back = pg.eval_on_selector_all("#ent-list input:checked", "e=>e.length")
    check(back == n_chart == 6,
          f"chart selection survives a trip through columns ({n_chart} → {back})")

    print("\npicking from the list clears the search, so nobody gets stuck:")
    pg.fill("#ent-search", "brazil")
    pg.wait_for_timeout(350)
    check(pg.eval_on_selector_all("#ent-list .opt-item", "e=>e.length") == 1,
          "search narrows the list to one row")
    pg.click("#ent-list .opt-item input")
    pg.wait_for_timeout(700)
    check(pg.eval_on_selector("#ent-search", "e=>e.value") == "",
          "search box is cleared after picking")
    rows = pg.eval_on_selector_all("#ent-list .opt-item", "e=>e.length")
    check(rows > 100, f"full list is back ({rows} rows)")
    top = pg.eval_on_selector_all("#ent-list .opt-item", "e=>e.slice(0,7).map(x=>x.textContent)")
    check("Brazil" in top, f"the new pick is pinned near the top: {top}")
    # and the same in single-select mode
    pg.click('.tab[data-view="columns"]')
    pg.wait_for_timeout(1000)
    pg.fill("#ent-search", "ukraine")
    pg.wait_for_timeout(350)
    pg.click("#ent-list .opt-item input")
    pg.wait_for_timeout(800)
    check(pg.eval_on_selector("#ent-search", "e=>e.value") == "",
          "search also clears in the columns view")
    check(pg.eval_on_selector_all("#viz .line-label", "e=>e.map(x=>x.textContent)") == ["Ukraine"],
          "picking in columns swaps the plotted entity")
    pg.click("#ent-clear") if pg.is_visible("#ent-clear") else None

    print("\ntable lists every country and region for the food:")
    pg.goto(BASE + "?tab=table&food=wheat&metric=production&year=2024")
    pg.wait_for_timeout(2400)
    names = pg.eval_on_selector_all("tbody tr td:first-child", "e=>e.map(x=>x.textContent)")
    check("World" in names, "World is in the table")
    check(all(c in names for c in ["Africa", "Asia", "Europe", "North America",
                                   "Oceania", "South America"]),
          "all six continents are in the table")
    check("European Union" in names, "EU is in the table")
    check(len(names) > 100, f"table is unfiltered ({len(names)} rows)")
    aggs = pg.eval_on_selector_all("td.agg", "e=>e.length")
    check(aggs == 8, f"aggregates marked apart from countries (got {aggs})")

    print("\nEU-folded years are explained:")
    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&entities=UK")
    pg.wait_for_timeout(2400)
    note = " ".join(pg.eval_on_selector_all(".legend-note", "e=>e.map(x=>x.textContent)"))
    check("United Kingdom from 1960 to 2015" in note, f"UK note = {note!r}")
    pg.goto(BASE + "?tab=chart&food=dairy-cheese&metric=production&entities=UK")
    pg.wait_for_timeout(2400)
    note = " ".join(pg.eval_on_selector_all(".legend-note", "e=>e.map(x=>x.textContent)"))
    check("United Kingdom from 1997 to 2015" in note,
          f"cheese has a different handover year: {note!r}")

    print("\nyear range labels bracket the slider and track the handles:")
    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&time=1960..2026")
    pg.wait_for_timeout(2400)
    check(pg.inner_text("#range-start-label") == "1960", "start year on the left")
    check(pg.inner_text("#range-end-label") == "2026", "end year on the right")
    check(not pg.is_visible("#year-label"), "combined label hidden in range mode")
    pg.eval_on_selector("#range-start-input",
                        "e=>{e.value=1990;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    pg.wait_for_timeout(500)
    check(pg.inner_text("#range-start-label") == "1990", "start label follows its handle")
    pg.eval_on_selector("#range-end-input",
                        "e=>{e.value=2010;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    pg.wait_for_timeout(500)
    check(pg.inner_text("#range-end-label") == "2010", "end label follows its handle")
    # left/right ordering on screen, not just in the DOM
    xs = pg.evaluate("""() => {
        const a = document.getElementById('range-start-label').getBoundingClientRect();
        const t = document.getElementById('dual-wrap').getBoundingClientRect();
        const b = document.getElementById('range-end-label').getBoundingClientRect();
        return [a.right <= t.left + 1, t.right <= b.left + 1];
    }""")
    check(all(xs), f"start left of track, end right of it: {xs}")

    print("\nmap legend is centred and highlights its bin on hover:")
    pg.goto(BASE + "?tab=map&food=wheat&metric=production&year=2024")
    pg.wait_for_timeout(2400)
    check(pg.eval_on_selector(".legend", "e=>getComputedStyle(e).justifyContent") == "center",
          "legend is centred")
    bins = pg.eval_on_selector_all(".legend-item.is-bin", "e=>e.length")
    check(bins == 7, f"7 hoverable bins (got {bins})")
    pg.hover(".legend-item.is-bin:nth-child(7)")
    pg.wait_for_timeout(400)
    ops = pg.eval_on_selector_all("#viz path", "e=>e.map(x=>x.getAttribute('opacity'))")
    check(ops.count("1") > 0 and ops.count("0.15") > 0,
          f"hover splits the map into in-bin and dimmed ({ops.count('1')} lit, {ops.count('0.15')} dimmed)")
    pg.mouse.move(620, 320)
    pg.wait_for_timeout(400)
    ops = pg.eval_on_selector_all("#viz path", "e=>e.map(x=>x.getAttribute('opacity'))")
    check(set(ops) == {"1"}, "leaving the legend restores the map")

    print("\nclicking a country on the map opens its line chart:")
    pg.goto(BASE + "?tab=map&food=wheat&metric=production&year=2024&entities=%40World")
    pg.wait_for_timeout(2400)
    pg.eval_on_selector_all("#viz path", """ps=>{
        const t = ps.find(p => p.__data__ && p.__data__.id === '076');
        t.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    }""")
    pg.wait_for_timeout(1200)
    check(pg.inner_text(".tab.active") == "Chart", "switched to the chart view")
    labels = pg.eval_on_selector_all("#viz .line-label", "e=>e.map(x=>x.textContent)")
    check("Brazil" in labels, f"the clicked country is plotted: {labels}")
    check("World" in labels, "the existing selection is kept")

    print("\nchanging food keeps the country selection:")
    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&entities=CH~IN~US")
    pg.wait_for_timeout(2500)
    pick_food(pg, "oilseed-soybean")
    labels = pg.eval_on_selector_all("#viz .line-label", "e=>e.map(x=>x.textContent)")
    check(sorted(labels) == ["China", "India", "United States"],
          f"same three countries after switching food: {labels}")
    pick_food(pg, "oil-olive")
    labels = pg.eval_on_selector_all("#viz .line-label", "e=>e.map(x=>x.textContent)")
    check("India" not in labels and labels,
          f"countries the new food does not report are dropped: {labels}")

    print("\nnaming and ordering:")
    pg.goto(BASE)
    pg.wait_for_timeout(2400)
    pg.click("#food-btn"); pg.wait_for_timeout(200)
    pg.fill("#food-search", "maize"); pg.wait_for_timeout(300)
    check(pg.eval_on_selector_all("#food-list .opt-item", "e=>e.map(x=>x.textContent)") == ["Corn (maize)"],
          "corn is searchable as maize")
    pg.keyboard.press("Escape")
    names = pg.evaluate("""() => {
        const out = [];
        let on = false;
        for (const el of document.querySelectorAll('#ent-list > *')) {
            if (el.classList.contains('opt-group')) { on = el.textContent === 'Countries'; continue; }
            if (on) out.push(el.textContent);
        }
        return out;
    }""")
    check(names == sorted(names, key=str.lower) and len(names) > 50,
          f"countries listed alphabetically ({len(names)}): {names[:6]}")

    print("\ncolumns timeline covers only the entity's own years:")

    def range_state(pg):
        return (pg.inner_text("#range-start-label"), pg.inner_text("#range-end-label"),
                pg.eval_on_selector("#range-start-input", "e=>e.min"),
                pg.eval_on_selector("#range-start-input", "e=>e.max"))

    # UK wheat is reported separately only from 2016; the rest is EU-folded.
    pg.goto(BASE + "?tab=columns&food=wheat&metric=production&entities=UK")
    pg.wait_for_timeout(2500)
    a, b_, lo, hi = range_state(pg)
    check((a, b_) == ("2016", "2026"), f"labels bracket the UK's own years: {a}-{b_}")
    check((lo, hi) == ("2016", "2026"), f"slider bounds match too: {lo}-{hi}")
    ticks = pg.eval_on_selector_all(
        "#viz .axis text", "es=>es.map(x=>x.textContent).filter(t=>/^[0-9]{4}$/.test(t))")
    check(ticks[0] == "2016", f"axis starts at 2016, no blank decades: {ticks[:3]}")

    # swapping the entity re-derives the timeline
    pg.fill("#ent-search", "world"); pg.wait_for_timeout(300)
    pg.click("#ent-list .opt-item input"); pg.wait_for_timeout(900)
    check(range_state(pg)[:2] == ("1960", "2026"),
          f"World gets the full span back: {range_state(pg)[:2]}")
    pg.fill("#ent-search", "united king"); pg.wait_for_timeout(300)
    pg.click("#ent-list .opt-item input"); pg.wait_for_timeout(900)
    check(range_state(pg)[:2] == ("2016", "2026"), "and narrows again for the UK")

    # the line chart is untouched: short and long series stay comparable there
    pg.click('.tab[data-view="chart"]'); pg.wait_for_timeout(1000)
    check(range_state(pg)[:2] == ("1960", "2026"),
          f"chart keeps the food's full span: {range_state(pg)[:2]}")

    # narrowing inside the columns view still works
    pg.click('.tab[data-view="columns"]'); pg.wait_for_timeout(900)
    pg.eval_on_selector("#range-start-input",
                        "e=>{e.value=2020;e.dispatchEvent(new Event('input',{bubbles:true}))}")
    pg.wait_for_timeout(700)
    check(range_state(pg)[:2] == ("2020", "2026"), "can still narrow within those years")

    # a series starting mid-history for a different reason (USSR, not the EU)
    pg.goto(BASE + "?tab=columns&food=wheat&metric=production&entities=UP")
    pg.wait_for_timeout(2500)
    check(range_state(pg)[:2] == ("1987", "2026"),
          f"Ukraine starts 1987, not 1960: {range_state(pg)[:2]}")

    print("\nWorld coverage note:")

    def world_note(pg):
        got = [t for t in pg.eval_on_selector_all(".legend-note", "e=>e.map(x=>x.textContent)")
               if "World" in t and ("sums" in t or "weighted" in t)]
        return got[0] if got else ""

    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&entities=%40World")
    pg.wait_for_timeout(2400)
    check(world_note(pg) == "World sums the 79 countries and regions with reported "
                            "output in 2026.", f"wheat: {world_note(pg)!r}")
    # counts contributors, not the many countries USDA lists at zero
    n_series = pg.evaluate("Object.keys(COMMODITY.series).filter(c=>!c.startsWith('@')"
                           "&&COMMODITY.series[c].production).length")
    check(n_series > 79, f"zero-output entities excluded ({n_series} listed, 79 counted)")

    pg.goto(BASE + "?tab=chart&food=wheat&metric=yield&entities=%40World")
    pg.wait_for_timeout(2400)
    check("production-weighted yield" in world_note(pg),
          f"yield is described as a ratio, not a sum: {world_note(pg)!r}")

    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&entities=CH~IN")
    pg.wait_for_timeout(2400)
    check(world_note(pg) == "", "no note when World is not plotted")

    for food, expect_n in (("pistachios-inshell-basis", 5), ("dairy-milk-fluid", 18)):
        pg.goto(BASE + f"?tab=columns&food={food}&metric=production&entities=%40World")
        pg.wait_for_timeout(2400)
        note = world_note(pg)
        check(f"the {expect_n} countries" in note and "major producers" in note,
              f"{food}: {note!r}")

    pg.goto(BASE + "?tab=table&food=corn&metric=production&year=2026")
    pg.wait_for_timeout(2400)
    check("115 countries" in world_note(pg), f"table/corn: {world_note(pg)!r}")

    print("\nfooter: source line, then note, then last-updated:")
    pg.goto(BASE)
    pg.wait_for_timeout(2500)
    src = pg.inner_text(".foot-source")
    check(src.startswith("Data source: USDA Foreign Agricultural Service"),
          f"source line = {src!r}")
    check(pg.eval_on_selector(".foot-source a", "e=>e.href").startswith(
        "https://apps.fas.usda.gov/psdonline"), "source links to PSD Online")
    note = pg.inner_text("#vintage-note")
    check(note == ("Note: Years are marketing years, labelled by the beginning year."
                   + vintage_sentence("wheat")), f"note = {note!r}")
    check(pg.inner_text("#updated-note") == f"Last updated: {UPDATED}.",
          f"updated = {pg.inner_text('#updated-note')!r}")
    # the vintage years follow the food rather than being hardcoded
    pick_food(pg, "apples-fresh")
    note = pg.inner_text("#vintage-note")
    prov, proj = VINTAGE["apples-fresh"]
    check(f"{prov} is a provisional estimate and {proj} is a USDA forecast" in note,
          f"apples run a year behind ({prov}/{proj}): {note!r}")
    # a discontinued series has neither, so the sentence is dropped
    pick_food(pg, "poultry-meat-broiler")
    note = pg.inner_text("#vintage-note")
    check(note == "Note: Years are marketing years, labelled by the beginning year.",
          f"discontinued series omits the vintage sentence: {note!r}")
    check(pg.inner_text("#updated-note") == f"Last updated: {UPDATED}.",
          "last-updated still shown")

    print("\npage title and introduction:")
    pg.goto(BASE)
    pg.wait_for_timeout(2500)
    check(pg.eval_on_selector_all("h1", "e=>e.length") == 1,
          "exactly one h1 on the page")
    check(pg.inner_text(".page-title") == "How is food production changing across the world?",
          f"page title = {pg.inner_text('.page-title')!r}")
    paras = pg.eval_on_selector_all(".page-intro", "es=>es.map(e=>e.textContent.trim())")
    check(len(paras) == 2, f"two intro paragraphs (got {len(paras)})")
    check("USDA" in paras[0] and len(paras[0]) > 200,
          f"first paragraph describes the data ({len(paras[0])} chars)")
    check(paras[1].startswith("Select a crop or animal product"),
          f"second paragraph tells you how to use it: {paras[1][:40]!r}")
    # the page title must not move when the chart title does
    pg.click('.tab[data-view="map"]')
    pg.wait_for_timeout(1000)
    check(pg.inner_text("#chart-title").startswith("Wheat production, "),
          "chart title still tracks the view")
    check(pg.inner_text(".page-title") == "How is food production changing across the world?",
          "page title is unaffected by the view")
    # geometry: the header sits above the tool
    above = pg.evaluate("""() => {
        const h = document.querySelector('.page-head').getBoundingClientRect();
        const c = document.querySelector('#chart-title').getBoundingClientRect();
        return c.top >= h.bottom - 1;
    }""")
    check(above, "header sits above the chart block")

    print("\nPNG export:")
    pg.goto(BASE + "?tab=chart&food=wheat&metric=production&time=1960..2026")
    pg.wait_for_timeout(2600)
    check(pg.is_visible("#dl-btn"), "download button present on the chart")
    place = pg.evaluate("""() => {
        const s = document.getElementById('slider-row').getBoundingClientRect();
        const t = document.getElementById('chart-tools').getBoundingClientRect();
        const c = document.querySelector('.chart-col').getBoundingClientRect();
        return {below: t.top >= s.bottom - 1, right: t.right <= c.right + 1
                    && (t.right - c.right) > -40};
    }""")
    check(place["below"], "download button sits below the timeline")
    check(place["right"], "download button is right-aligned")

    markup = pg.evaluate("async () => buildExportSvg(await loadFontCss()).markup")
    wanted = ["Wheat production", "Total quantity produced",
              "Data source: USDA Foreign Agricultural Service",
              f"Last updated: {UPDATED}.",
              f"{VINTAGE['wheat'][0]} is a provisional estimate"]
    for w in wanted:
        check(w in markup, f"export includes {w!r}")
    # chrome must not leak into the image
    for junk in ["Search countries", "Download PNG", "Clear all", "one at a time",
                 "combo-btn", "<select", "opt-item",
                 "Estimates of yield, production, and harvested area"]:   # intro stays off the image
        check(junk not in markup, f"export excludes {junk!r}")
    check("@font-face" in markup and "base64" in markup,
          "fonts embedded, so exported text is not a fallback face")

    with tempfile.TemporaryDirectory() as tmp:
        for q, tag, expect_name in [
            ("?tab=chart&food=wheat&metric=production&time=1960..2026", "chart",
             "usda-wheat-production-1960-2026.png"),
            ("?tab=columns&food=wheat&metric=production&entities=UK", "columns",
             "usda-wheat-production-2016-2026.png"),
            ("?tab=map&food=wheat&metric=production&year=2024", "map",
             "usda-wheat-production-2024.png"),
        ]:
            pg.goto(BASE + q)
            pg.wait_for_timeout(2600)
            with pg.expect_download(timeout=30000) as dl:
                pg.click("#dl-btn")
            d = dl.value
            check(d.suggested_filename == expect_name,
                  f"{tag}: filename {d.suggested_filename!r}")
            path = os.path.join(tmp, f"{tag}.png")
            d.save_as(path)
            with open(path, "rb") as fh:
                head = fh.read(24)
            check(head[:8] == b"\x89PNG\r\n\x1a\n", f"{tag}: is a real PNG")
            w, h = struct.unpack(">II", head[16:24])
            check(w > 2000 and h > 1000, f"{tag}: high resolution {w}x{h}")

    pg.goto(BASE + "?tab=table&food=wheat")
    pg.wait_for_timeout(2300)
    check(not pg.is_visible("#dl-btn"), "no download button on the table view")

    print("\nplay button advances the year:")
    pg.goto(BASE + "?tab=map&food=corn&year=2000")
    pg.wait_for_timeout(2200)
    pg.click("#play"); pg.wait_for_timeout(1600); pg.click("#play")
    y = pg.inner_text("#year-label")
    check(int(y) > 2000, f"year advanced to {y}")

    b.close()

print(f"\n=== console errors: {len(errors)}")
for e in errors[:20]:
    print(" ", e)
print(f"=== failures: {len(fails)}")
for f in fails:
    print("  -", f)
