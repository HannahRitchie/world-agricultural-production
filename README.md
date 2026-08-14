# USDA World Agricultural Production — data explorer

An OWID-style data explorer over the USDA Foreign Agricultural Service's
**Production, Supply and Distribution (PSD)** database.

The page opens with "How is food production changing across the world?" and a short
introduction (`.page-head`), then the tool itself. That header is the only `<h1>`; the chart's own heading is an `<h2>` with
`id="chart-title"`, which is what `updateTitle()` and the PNG export target. Anything
selecting the chart title by tag would pick up the page title instead.

Four views:

| View | Shows |
|---|---|
| **Chart** | Time-series lines for the selected countries |
| **Map** | Choropleth for a single year |
| **Columns** | The same time series as columns, one country or region at a time |
| **Table** | Every country and region reported for the food, in one year |

The three chart views have a **Download PNG** button at the bottom right. The
export is rebuilt as one standalone SVG — title, subtitle, plot, legend and footer,
and nothing else — then rasterised at 3x, so a 1240px window yields a ~2900px
image. Dropdowns, tabs, the sidebar and the slider are all absent, and the map's
"selected country" outlines are dropped too, since selection is interactive state
with no meaning in a static image.

Controls:

- **Food** — a searchable dropdown, 60 commodities grouped by category.
- **Country / region** — an always-open sidebar to the left of the chart, with
  its own search. The current selection is pinned to the top of the list so it
  stays visible among ~200 entities. Clicking a country on the map, or a bar in
  the ranking, toggles it too.
- **Metric** — limited to **Production**, **Yield** and **Area harvested**.
  Metrics a commodity does not report are greyed out.

The Chart plots every selected country. **Columns plots one at a time** — a
column chart of several series grouped across six decades is unreadable, and one
series is what the view is good at — so the sidebar switches to radio buttons
there. The single-entity choice is held separately from the multi-selection, so
flipping to Columns and back leaves the Chart's selection intact.

Picking anything from the sidebar clears the search box and restores the full
list, so a one-row filtered list is never a dead end; the new pick appears in the
pinned "Selected" group at the top. Countries are listed alphabetically — which
needs an explicit sort in the build, because renaming entities for display
("Korea, South" to "South Korea") breaks the source file's own ordering.

**The selection survives a change of food.** Switching from wheat to soybeans
keeps your countries, dropping only those the new food does not report; it falls
back to top producers only if that would leave the chart empty, and not if you had
deliberately cleared the list.

On the map, hovering a legend bin dims everything outside that range, and clicking
a country adds it to the selection and switches to the Chart so you land on its
time series.

Whenever World is displayed, a note says what it sums — "World sums the 79
countries and regions with reported output in 2026" — counting contributors rather
than the many countries USDA lists at zero (145 entities appear for wheat; 79 grow
any). Below 20 it adds "the major producers, not every country". For the yield
metric it says "production-weighted yield" instead, since that aggregate is a ratio
rather than a sum.

The Table is a full reference
view — it always lists every country and region with data for the food, and
*highlights* the selection rather than filtering to it. World, the continents and
the EU are italicised there so a value-sorted list is not misread as a pure
country ranking.

Chart and Columns share the dual-handle year range, with the start year to the
left of the track and the end year to the right, both following their handles.
Map and Table use the single-year slider with a play button.

**The two time-series views scope their timeline differently, on purpose.** The
Chart spans every year the food has data, so series of different lengths stay
comparable on one axis — you can see that the UK's wheat line starts decades after
China's. Columns plots a single entity, so its timeline covers only that entity's
own years: picking the UK gives 2016–2026 rather than 1960–2026 with five blank
decades. Swapping entity re-derives it, and Ukraine (reported from 1987, after the
USSR) gets 1987–2026.

This is implemented by *clipping* the stored range to the view's limits rather
than reassigning it, so a trip through Columns never silently rewrites the
Chart's range. Internal gaps are left visible — UK apples still shows its
1977–1981 and 2009–2015 holes, because collapsing them would distort the time
axis. Only leading and trailing emptiness is trimmed.

```
usda-food/
├── index.html                  the explorer (self-contained; d3 + topojson from CDN)
├── data/
│   ├── index.json              commodity + entity catalogue (36 KB)
│   ├── commodity/<slug>.json   one file per commodity, all three metrics (≤170 KB)
│   ├── countries-110m.json     world-atlas TopoJSON for the map
│   └── fonts.css               webfonts as base64, for PNG export (182 KB, lazy)
└── scripts/
    ├── build_data.py           the pipeline
    ├── build_fonts.py          regenerates data/fonts.css
    ├── entities.py             aggregate/member definitions and manual country mappings
    ├── make_static_chart.py    renders the 4x2 publishing PNG in static-charts/
    ├── check_views.py          screenshots every view + control combination
    └── check_regressions.py    asserts view switching, metric fallback, deep links,
                                vintage marking, EU-folding notes, full table
```

## Static chart for publishing

`scripts/make_static_chart.py` renders a 2508x1311 small-multiples figure of
**World** yield (top row) and production (bottom row) for corn, wheat, rice and
soybeans, into `static-charts/`:

```bash
uv run scripts/make_static_chart.py                        # lines, 1960-
uv run scripts/make_static_chart.py --kind column --start 2000
uv run scripts/make_static_chart.py --kind column --start 2000 --format both
```

`--format png|svg|both`. SVG text is converted to outlines by default, so the file
renders identically anywhere, including where Inter and Lato are not installed.
Add `--svg-text` to keep live `<text>` instead — smaller and editable in
Illustrator or Figma, but it needs those fonts wherever it is opened.

Each crop carries a soft hue, held constant down its column so the yield and
production panels read as a pair. Those hues do **not** pass the palette
validator's separation gates — worst normal-vision dE 12.1 against a floor of 15 —
because low chroma is precisely what those gates measure. That is a considered
exception rather than an oversight: every panel holds a single series named by its
own title, so colour never carries identity here, only association between the two
panels of a column. The same four hues would not be safe in a chart where the
crops share one plot.

The metric leads the hierarchy: "Yield" and "Production" are set in display
weight with the unit alongside, while crop names recede to muted text on the top
row only.

The forecast year is drawn as an open dashed bar (or dashed line with a hollow
marker), matching the explorer's treatment. Which year that is comes from
`year_projection` in the commodity files, so it follows each monthly release.

Each panel holds a single series, so no categorical palette is needed: the column
headings carry identity and one validated ink serves every panel. y-axes are shared
within each row so the four crops compare directly. The script reuses
`data/fonts.css`, instancing Inter's variable font at weight 700 — matplotlib would
otherwise render "bold" as regular without warning.

## Checks

`uv run scripts/validate_data.py` reconciles every published figure against the
raw PSD CSV — 293,298 country values, 4,779 World aggregates, continent closure,
the yield identity and every unit string. It is an independent re-derivation, not
a re-run of the build, and it takes a few minutes.

It also reports two caveats that are properties of the source rather than defects:

- **23 of 60 commodities have output in fewer than 20 countries.** USDA tracks the
  producers that matter rather than every country, so these are mostly still close
  to a world total — the median top-3 share is 84%, and pistachios (5 countries) is
  95% in three. The explorer states the count whenever World is shown, so a reader
  can judge. Note that PSD milk being 69% of FAO's figure is *definitional*, not a
  coverage gap: PSD is cow milk in major countries, FAO is all milk species
  worldwide.
- **16 commodity-years where the countries reporting area cover under 80% of
  production** — all early oil palm, as low as 12% in 1968. The aggregate yield
  there describes the countries that report area, not the world.

With the server running:

```bash
uv run --with playwright python scripts/check_regressions.py   # 130 assertions
uv run --with playwright python scripts/check_views.py         # screenshots → scripts/_shots/
```

`check_regressions.py` covers the bugs that actually bit during the build: a
fixed-height view collapsing after the table view left an inline height behind,
the metric dropdown not falling back when a commodity lacks yield/area, URL state
not restoring, that a discontinued series is *not* marked as a forecast while a
fruit commodity's 2025 *is*, and that the EU-folding note reports the right
handover year for each commodity. Both scripts fail on any console error.

## Running it

```bash
lsof -ti :8888 | xargs kill -9 2>/dev/null || true
uv run python -m http.server 8888
```

Then open <http://localhost:8888/index.html>. A server is required — the page
`fetch()`es local JSON, which browsers block on `file://`.

## Rebuilding the data

```bash
uv run scripts/build_data.py              # downloads the latest PSD bulk file
uv run scripts/build_data.py --no-download # reuse scripts/psd_alldata.csv
```

Source: `https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip`
(~10 MB zipped, ~200 MB CSV, 2.1 M rows). The CSV is gitignored.

The build also reads the file's `Last-Modified` header and stores it as
`source_updated` in `index.json`, which drives the footer's "Last updated"
line. A rebuild refreshes it automatically; if the header is missing the field is
omitted and the footer drops the line rather than showing a guessed date. The
check suite reads the same field rather than hardcoding a month, so a monthly
rebuild needs no test edits.

PSD is revised monthly. Rerunning the build is the whole update: it re-downloads,
rewrites `data/`, and refreshes the footer date. Current build: **60 commodities,
220 entities, 1960–2026**, 2.9 MB of JSON, from the **August 2026** release.

## Fonts in the export

`data/fonts.css` holds the Inter and Lato latin subsets as base64 `@font-face`
rules, regenerated with `uv run scripts/build_fonts.py` (only needed if the fonts
change). A standalone SVG cannot reach fonts.googleapis.com, so without embedding
them every label in an exported PNG would fall back to a generic sans-serif and
the image would not match the page. The file is fetched lazily on the first
download, so it costs nothing on page load.

## Coverage

All 60 commodities report Production. Only 18 report Yield and 17 report Area
harvested — these are the field crops (grains, oilseeds, cotton, oil palm).
The metric dropdown greys out metrics a commodity does not report and falls
back to Production.

## Data decisions worth knowing

These are the non-obvious parts, each verified against the file rather than
assumed.

**Years are marketing years**, labelled by the year the marketing year begins;
the month it begins varies by country and crop.

**The last two years are not settled data, and the explorer marks them.** The
newest marketing year is a USDA forecast and the one before it a provisional
estimate still open to revision. On the line chart the forecast segment is
**dashed with an open marker**, the provisional and forecast years sit in tinted
bands, and a legend under the chart names both years. In the map, ranking and
table views a badge next to the year slider reads "Provisional" or "USDA
forecast". Tooltips carry the same flag.

The footer states it too — "Note: Years are marketing years, labelled by the
beginning year. 2025 is a provisional estimate and 2026 is a USDA forecast (which
is updated monthly)." — with the years substituted per food, so it reads 2024/2025
on the fruit and nut series and drops the sentence entirely for the discontinued
one.

Which years these are is computed per commodity at build time, not hardcoded,
because the vintage differs across the database:

| Commodity group | Last year | Provisional | Forecast |
|---|---|---|---|
| Grains, oilseeds, cotton, dairy, meat (45 commodities) | 2026 | 2025 | 2026 |
| Fruit, nuts, juice, fishmeal (14 commodities) | 2025 | 2024 | 2025 |
| Broiler meat — discontinued series | 2016 | – | – |

The fruit and nut commodities run a year behind, so marking 2025 as provisional
there would be wrong — it is their forecast year. And a discontinued series ends
in settled history, so it gets no marking at all: the build only flags a
commodity whose last year reaches the current vintage.

**`Yield` is exactly `Production / Area`** in PSD's own units. The build derives
the unit constant `k` in `yield = k × production / area` empirically per
commodity (median over all country-years) rather than hardcoding it. Two
commodities are why that matters:

| Commodity | k | Why |
|---|---|---|
| Grains, oilseeds, oil palm | `1.0000` | 1000 MT over 1000 HA gives MT/HA |
| Cotton | `217.7358` | 1000 480-lb bales over 1000 HA gives KG/HA |
| **Rice (milled)** | **`1.5351`** | production is **milled**, but area and yield are on a **rough (paddy)** basis — k is the milling conversion (milled ≈ 65% of paddy) |

Rice is the trap: `production / area` gives 3.14 t/ha for the world in 2025, while
USDA publishes 4.82. Hardcoding `k = 1` would have silently produced a wrong
aggregate rice yield. Anyone comparing a rice yield here against a rice production
figure should note they are on different bases.

**World and continental aggregates are computed here — PSD's bulk file has no
World row.** Production and area are summed; **yield is total production over
total area**, never an average of national yields. Continents use
`country_converter`'s 7-continent classification, so they sum exactly to World.

**Double counting is suppressed for dissolution/merger aggregates only.** PSD
mixes present-day countries with historic entities, and in transition years both
a union and its constituents appear, with the constituent *inside* the union
(Czech Republic 1990 cattle = 924 sits inside Czechoslovakia = 1504). So members
of USSR, Czechoslovakia, Yugoslavia, Serbia and Montenegro, Belgium-Luxembourg,
Germany and Yemen are dropped for any commodity-year where the parent is
reported — 291 rows in total.

**The EU is deliberately *not* suppressed.** PSD reports EU member states
separately only for years *before* they acceded, so those rows are additive, not
duplicative. This is visible in the data: every EU-15/member overlap ends exactly
at that member's accession year (Denmark, Ireland and the UK end 1971; Greece
1980; Austria, Finland and Sweden 1994), and the only EU/member overlaps are
Romania to 2007 and the UK from 2016. Suppressing them would have *undercounted*
the world total.

**On the map, EU members are hatched, not shaded.** For grains, oilseeds and
cotton, PSD reports the EU as a single entity with no member-state breakdown.
Painting 27 countries with the EU-wide total would be misleading, so they get a
hatch pattern and a tooltip saying the value is an EU total.

**Two commodities (copra, palm kernels) publish yield but no area.** Their
aggregate yield is a production-weighted mean via area implied from each
country's own yield, which is why `k` matters. Countries with a zero yield are
excluded from both numerator and denominator so the aggregate is not dragged to
zero.

**Netherlands Antilles has the country code `NA`**, so the CSV must be read with
`keep_default_na=False` or that country becomes a null.

**EU member states have gaps, and the explorer says so.** This is the single most
confusing thing in PSD. Ask why the UK wheat series starts in 2016 and the answer
is that it does not begin there at all — USDA folded UK wheat into the EU
aggregate until it restated the series as EU-27, and only then began reporting the
UK separately. The handover year is *per commodity*, not Brexit everywhere: UK
cheese is reported separately to 1996, folded into the EU total 1997–2015, then
separate again; UK rapeseed breaks at 1991; UK apples at 2009. For wheat there is
no separate UK series at all before 2016, because PSD's "EU-15" is a
constant-composition aggregate carried back to 1960 that already contains UK
output.

The build derives these folded year ranges per commodity per member
(`eu_folded` in each commodity file) by comparing each member's own coverage
against the years an EU aggregate is present. The chart and column views then
print a note naming them, so a gap is never left to be misread as zero
production.

**27 of 195 countries have no map polygon** at 110m resolution (Singapore,
Malta, Mauritius, Hong Kong and other micro-states and territories). They appear
in the chart, ranking and table but not the map.

**"Other" is a USDA residual**, not a country. It is included in World totals but
has no continent, so continental totals can fall marginally short of World for a
few commodities. It is listed under "Other & former states" in the picker.

**The three "(Local)" series** (soybean, soybean oil, soybean meal on local
marketing years, 2 countries each) are excluded — they duplicate the main series
without adding coverage.

## Validation

World wheat production 2020/21 comes out at 772.8 Mt against a continent sum of
772.8 Mt (exact), with China 134.3, EU 126.7, India 107.9, Russia 85.4 and the
US 49.5 Mt. World cotton yield reproduces per-country values under the bale
conversion (US 2020 = 957 kg/ha, matching the source row). World yields trend
sensibly over the long run — wheat 1.08 → 3.80 t/ha, corn 1.95 → 6.07 t/ha.

## URL state

State is in the query string, so any view is linkable:

```
?tab=bar&food=oilseed-soybean&metric=area&year=2000&entities=BR~AR~US
```

`tab`, `food`, `metric`, `year` (map/ranking/table), `time=YYYY..YYYY` (chart),
`entities` (`~`-separated codes; aggregates are prefixed `@`). Add `embed=1` to
stop the page writing to the URL.

## Licensing and attribution

This work is released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — see `LICENSE`. You are
free to share and adapt it, including commercially, provided you give credit.

Third-party components keep their own terms:

- **Data**: USDA Foreign Agricultural Service, Production, Supply and Distribution
  (PSD). A work of the US federal government, so not subject to copyright in the
  United States. Please cite USDA FAS when reusing it.
- **Fonts**: `data/fonts.css` embeds latin subsets of
  [Inter](https://github.com/rsms/inter) and
  [Lato](https://fonts.google.com/specimen/Lato), both licensed under the
  [SIL Open Font License 1.1](https://openfontlicense.org/). They are
  redistributed here under that licence so that exported PNGs keep the right
  typefaces.
- **Map geometry**: [world-atlas](https://github.com/topojson/world-atlas)
  (ISC licence), derived from Natural Earth (public domain).
