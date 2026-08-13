# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas", "country_converter", "requests"]
# ///
"""Build the JSON data files for the USDA World Agricultural Production explorer.

Source: USDA FAS Production, Supply and Distribution (PSD) bulk download
        https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip

Usage:  uv run scripts/build_data.py [--no-download]

Outputs:
    data/index.json               commodity + entity catalogue
    data/commodity/<slug>.json    one file per commodity, all metrics
"""
from __future__ import annotations

import argparse
import email.utils
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import country_converter as coco
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from entities import (AGGREGATE_MEMBERS, CONTINENTS, EU15, EU25_ADD, EU28_ADD,
                      HISTORIC, MANUAL, SUPRANATIONAL)

EU_MEMBER_CODES = [c for c in EU15 + EU25_ADD + EU28_ADD if c != "UK"]

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CSV = Path(__file__).parent / "psd_alldata.csv"
URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip"

# The three attributes the explorer exposes.
METRICS = {"028": "production", "184": "yield", "004": "area"}

# Dissolution / merger aggregates: whenever the parent is reported, its members
# are *inside* it, so they must be dropped from any total. (Verified against the
# file: e.g. Czech Republic 1990 cattle = 924 sits inside Czechoslovakia = 1504.)
# The EU aggregates are deliberately NOT in this list — PSD reports member
# states separately only for years before they acceded, so they are additive.
SUPPRESS = {k: v for k, v in AGGREGATE_MEMBERS.items() if k not in ("E2", "E3", "E4")}

CATEGORY_BY_PREFIX = [
    ("001", "Livestock"), ("011", "Meat"), ("022", "Dairy"), ("023", "Dairy"),
    ("024", "Dairy"), ("041", "Grains"), ("042", "Grains"), ("043", "Grains"),
    ("044", "Grains"), ("045", "Grains"), ("057", "Fruit & nuts"),
    ("0585", "Fruit & nuts"), ("0612", "Sugar"), ("0711", "Coffee"),
    ("081", "Oilseed meals"), ("222", "Oilseeds"), ("223", "Oilseeds"),
    ("2631", "Cotton"), ("42", "Vegetable oils"),
]

NICE_NAME = {
    "Animal Numbers, Cattle": "Cattle (herd size)",
    "Animal Numbers, Swine": "Pigs (herd size)",
    "Meat, Beef and Veal": "Beef and veal",
    "Meat, Swine": "Pigmeat",
    "Meat, Chicken": "Chicken meat",
    "Poultry, Meat, Broiler": "Broiler meat (discontinued 2016)",
    "Dairy, Milk, Fluid": "Milk",
    "Dairy, Milk, Nonfat Dry": "Nonfat dry milk",
    "Dairy, Dry Whole Milk Powder": "Whole milk powder",
    "Dairy, Butter": "Butter",
    "Dairy, Cheese": "Cheese",
    "Corn": "Corn (maize)",
    "Rice, Milled": "Rice (milled)",
    "Mixed Grain": "Mixed grain",
    "Oranges, Fresh": "Oranges",
    "Tangerines/Mandarins, Fresh": "Tangerines and mandarins",
    "Lemons/Limes, Fresh": "Lemons and limes",
    "Grapefruit, Fresh": "Grapefruit",
    "Apples, Fresh": "Apples",
    "Grapes, Fresh Table": "Table grapes",
    "Almonds, Shelled Basis": "Almonds (shelled)",
    "Walnuts, Inshell Basis": "Walnuts (in shell)",
    "Pistachios, Inshell Basis": "Pistachios (in shell)",
    "Pears, Fresh": "Pears",
    "Cherries (Sweet&Sour), Fresh": "Cherries",
    "Peaches & Nectarines, Fresh": "Peaches and nectarines",
    "Orange Juice": "Orange juice",
    "Sugar, Centrifugal": "Sugar",
    "Coffee, Green": "Coffee (green)",
    "Meal, Soybean": "Soybean meal",
    "Meal, Peanut": "Peanut meal",
    "Meal, Cottonseed": "Cottonseed meal",
    "Meal, Sunflowerseed": "Sunflowerseed meal",
    "Meal, Rapeseed": "Rapeseed meal",
    "Meal, Copra": "Copra meal",
    "Meal, Palm Kernel": "Palm kernel meal",
    "Meal, Fish": "Fishmeal",
    "Oilseed, Peanut": "Peanuts",
    "Oilseed, Soybean": "Soybeans",
    "Oilseed, Cottonseed": "Cottonseed",
    "Oilseed, Sunflowerseed": "Sunflower seed",
    "Oilseed, Rapeseed": "Rapeseed",
    "Oilseed, Copra": "Copra",
    "Oilseed, Palm Kernel": "Palm kernels",
    "Oil, Soybean": "Soybean oil",
    "Oil, Cottonseed": "Cottonseed oil",
    "Oil, Peanut": "Peanut oil",
    "Oil, Olive": "Olive oil",
    "Oil, Sunflowerseed": "Sunflower oil",
    "Oil, Rapeseed": "Rapeseed oil",
    "Oil, Coconut": "Coconut oil",
    "Oil, Palm": "Palm oil",
    "Oil, Palm Kernel": "Palm kernel oil",
}

# "(Local)" series are alternate local-marketing-year duplicates for two
# countries only; they would confuse the picker without adding coverage.
EXCLUDE_COMMODITIES = {"Oilseed, Soybean (Local)", "Oil, Soybean (Local)",
                       "Meal, Soybean (Local)"}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s


def category_for(code: str) -> str:
    for prefix, cat in CATEGORY_BY_PREFIX:
        if code.startswith(prefix):
            return cat
    return "Other"


def source_last_modified() -> str | None:
    """Month and year the PSD bulk file was last published, from its own headers.

    Returned as e.g. "July 2026". None if the header is missing or unparseable —
    the footer then omits the line rather than showing a guessed date.
    """
    try:
        r = requests.head(URL, timeout=30, allow_redirects=True)
        stamp = r.headers.get("Last-Modified")
        if not stamp:
            return None
        return email.utils.parsedate_to_datetime(stamp).strftime("%B %Y")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  could not read Last-Modified ({exc}); omitting the date")
        return None


def download() -> None:
    print(f"downloading {URL}")
    r = requests.get(URL, timeout=180)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        CSV.write_bytes(z.read(name))
    print(f"wrote {CSV} ({CSV.stat().st_size / 1e6:.0f} MB)")


def load() -> pd.DataFrame:
    # keep_default_na=False matters: country code "NA" is Netherlands Antilles,
    # not a missing value.
    df = pd.read_csv(
        CSV, keep_default_na=False, na_values=[""],
        usecols=["Commodity_Code", "Commodity_Description", "Country_Code",
                 "Country_Name", "Market_Year", "Attribute_ID",
                 "Unit_Description", "Value"],
        dtype={"Commodity_Code": str, "Attribute_ID": str, "Country_Code": str},
    )
    df = df[df.Attribute_ID.isin(METRICS)]
    df = df[~df.Commodity_Description.isin(EXCLUDE_COMMODITIES)]
    df["metric"] = df.Attribute_ID.map(METRICS)
    df = df[df.Value.notna()]
    return df


def build_entity_table(df: pd.DataFrame) -> pd.DataFrame:
    codes = df[["Country_Code", "Country_Name"]].drop_duplicates()
    cc = coco.CountryConverter()
    names = codes.Country_Name.tolist()
    iso3 = cc.convert(names, to="ISO3", not_found=None)
    # continent_7 keeps North and South America separate; plain "continent"
    # merges them into "America".
    cont = cc.convert(names, to="continent_7", not_found=None)
    codes["iso3"] = [None if (v is None or v == n) else v
                     for v, n in zip(iso3, names)]
    codes["continent"] = [None if (v is None or v == n) else v
                          for v, n in zip(cont, names)]
    codes["name"] = codes.Country_Name

    for code, (nice, i3, con) in MANUAL.items():
        m = codes.Country_Code == code
        if not m.any():
            continue
        codes.loc[m, "name"] = nice
        codes.loc[m, "iso3"] = i3
        codes.loc[m, "continent"] = con

    unresolved = codes[codes.continent.isna() & (codes.Country_Code != "ZZ")]
    if len(unresolved):
        raise SystemExit(f"unmapped entities:\n{unresolved}")

    def kind(row):
        if row.Country_Code in SUPRANATIONAL:
            return "region"
        if row.Country_Code in HISTORIC:
            return "historic"
        return "country"

    codes["kind"] = codes.apply(kind, axis=1)
    # Numeric ISO code, used to join onto the world-atlas TopoJSON features.
    num = cc.convert([i or "not found" for i in codes.iso3], src="ISO3",
                     to="ISOnumeric", not_found=None)
    # world-atlas ids are zero-padded to three digits ("076", not "76").
    codes["map_id"] = [None if (v is None or not str(v).isdigit())
                       else f"{int(v):03d}" for v in num]
    # PSD's long names are truncated to 30 chars; tidy a few for display.
    codes["name"] = codes.name.str.replace("Bahamas, The", "Bahamas") \
        .str.replace("Gambia, The", "Gambia") \
        .str.replace("Korea, South", "South Korea") \
        .str.replace("Korea, North", "North Korea") \
        .str.replace("Congo (Kinshasa)", "Democratic Republic of Congo") \
        .str.replace("Congo (Brazzaville)", "Congo")
    return codes.set_index("Country_Code")


def suppress_double_counting(df: pd.DataFrame) -> pd.DataFrame:
    """Drop member rows for any commodity-year where their parent is reported."""
    drop_idx = []
    for parent, members in SUPPRESS.items():
        par = df[df.Country_Code == parent][
            ["Commodity_Code", "Market_Year", "metric"]].drop_duplicates()
        if par.empty:
            continue
        par["_parent"] = True
        kids = df[df.Country_Code.isin(members)]
        merged = kids.merge(par, on=["Commodity_Code", "Market_Year", "metric"],
                            how="left")
        merged.index = kids.index
        drop_idx.extend(merged.index[merged._parent.notna()].tolist())
    dropped = df.loc[sorted(set(drop_idx))]
    if len(dropped):
        print(f"  suppressed {len(dropped)} member rows inside historic "
              f"aggregates ({sorted(dropped.Country_Code.unique())})")
    return df.drop(index=sorted(set(drop_idx)))


# Fallback for commodities that publish yield but no area, so k cannot be
# derived from the data (copra, palm kernel). Keyed by (production, yield) unit.
UNIT_FACTOR = {
    ("(1000 MT)", "(MT/HA)"): 1.0,
    ("1000 480 lb. Bales", "(KG/HA)"): 1000 * 480 * 0.45359237 / 1000,
}


def to_ranges(years: list[int]) -> list[list[int]]:
    """Collapse a sorted year list into [start, end] runs."""
    out: list[list[int]] = []
    for y in years:
        y = int(y)
        if out and y == out[-1][1] + 1:
            out[-1][1] = y
        else:
            out.append([y, y])
    return out


def available_any(sub: pd.DataFrame) -> list[str]:
    """The metric columns present on this frame, for a notna() check."""
    return [m for m in ("production", "yield", "area") if m in sub.columns]


def yield_factor(w: pd.DataFrame, prod_unit: str, yield_unit: str) -> float | None:
    """Derive the constant k with yield = k * production / area, from the data.

    Grains report production in 1000 MT, area in 1000 HA and yield in MT/HA, so
    k == 1. Cotton reports 1000 480-lb bales against KG/HA, so k == 217.72.
    Deriving it rather than hardcoding keeps aggregate yields honest if USDA
    ever changes a unit.
    """
    sub = w[(w["production"] > 0) & (w["area"] > 0) & (w["yield"] > 0)]
    if len(sub) >= 20:
        return float((sub["yield"] * sub["area"] / sub["production"]).median())
    return UNIT_FACTOR.get((prod_unit, yield_unit))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    if not args.no_download or not CSV.exists():
        download()

    print("loading")
    df = load()
    ent = build_entity_table(df)
    print(f"  {len(df):,} observations, {len(ent)} entities")

    print("removing double counting")
    df = suppress_double_counting(df)

    file_max_year = int(df.Market_Year.max())
    print(f"  newest marketing year in file: {file_max_year}")

    units = (df.groupby(["Commodity_Description", "metric"])
               .Unit_Description.agg(lambda s: s.mode().iat[0]).unstack())

    (DATA / "commodity").mkdir(parents=True, exist_ok=True)
    for f in (DATA / "commodity").glob("*.json"):
        f.unlink()

    catalogue = []
    used_entities: set[str] = set()

    for (code, name), g in df.groupby(["Commodity_Code", "Commodity_Description"]):
        wide = g.pivot_table(index=["Country_Code", "Market_Year"],
                             columns="metric", values="Value").reset_index()
        for m in METRICS.values():
            if m not in wide:
                wide[m] = pd.NA
        wide[["production", "yield", "area"]] = wide[
            ["production", "yield", "area"]].astype("Float64")

        # Years in which an EU member's output is folded into the EU aggregate
        # rather than reported separately. This is why, for example, UK wheat
        # only starts in 2016: PSD restated the EU series as EU-27 from then and
        # began reporting the UK on its own. The handover year differs by
        # commodity, so derive it instead of assuming Brexit everywhere.
        eu_years = set(wide.loc[wide.Country_Code.isin(["E2", "E3", "E4"]),
                                "Market_Year"])
        eu_folded = {}
        for code in EU_MEMBER_CODES + ["UK"]:
            sub = wide[wide.Country_Code == code]
            own = set(sub.loc[sub[available_any(sub)].notna().any(axis=1),
                              "Market_Year"]) if len(sub) else set()
            if not own:
                continue          # never reported separately, so nothing to explain
            missing = sorted(eu_years - own)
            if missing:
                eu_folded[code] = to_ranges(missing)

        def unit(m):
            u = units.loc[name, m] if m in units.columns else None
            return str(u) if pd.notna(u) else ""

        k = yield_factor(wide, unit("production"), unit("yield"))
        cont = wide.Country_Code.map(ent.continent)

        # --- aggregates -----------------------------------------------------
        aggs = []
        groups = [("World", wide)] + [(c, wide[cont == c]) for c in CONTINENTS]
        for label, sub in groups:
            if sub.empty:
                continue
            a = sub.groupby("Market_Year")[["production", "area"]].sum(min_count=1)
            if k is not None:
                # Aggregate yield is total production over total area, not a mean
                # of national yields. Where area is unpublished (copra, palm
                # kernel) back it out from the reported yield so those producers
                # still count. Numerator and denominator must cover exactly the
                # same rows, so drop any row we cannot place an area against.
                s = sub.copy()
                implied = (s["production"] * k / s["yield"]).where(s["yield"] > 0)
                s["_area"] = s["area"].fillna(implied)
                s = s[s._area.notna() & s.production.notna() & (s._area > 0)]
                den = s.groupby("Market_Year")._area.sum(min_count=1)
                num = s.groupby("Market_Year").production.sum(min_count=1)
                a["yield"] = (num * k / den).where(den > 0)
            else:
                a["yield"] = pd.NA
            a = a.reset_index()
            a["Country_Code"] = "@" + label
            aggs.append(a)

        wide = pd.concat([wide] + aggs, ignore_index=True)

        years = [int(y) for y in sorted(wide.Market_Year.unique())]
        yidx = {y: i for i, y in enumerate(years)}
        available = [m for m in ("production", "yield", "area")
                     if wide[m].notna().any()]

        series = {}
        for ccode, sub in wide.groupby("Country_Code"):
            label = ("@" + ccode[1:]) if ccode.startswith("@") else ccode
            out = {}
            for m in available:
                col = [None] * len(years)
                has = False
                for y, v in zip(sub.Market_Year, sub[m]):
                    if pd.notna(v):
                        col[yidx[y]] = round(float(v), 4)
                        has = True
                if has:
                    out[m] = col
            if out:
                series[label] = out
                used_entities.add(label)

        # Default: the six largest producers in the most recent year with data.
        prod = wide[~wide.Country_Code.str.startswith("@") & wide.production.notna()]
        defaults = []
        if len(prod):
            last = prod.Market_Year.max()
            top = (prod[prod.Market_Year == last]
                   .nlargest(6, "production").Country_Code.tolist())
            defaults = top

        # USDA's newest marketing year is a forecast and the one before it a
        # provisional estimate still open to revision. Only flag them where the
        # series actually runs up to the current vintage — a discontinued series
        # (Broiler meat, last reported 2016) ends in settled history, not a
        # forecast.
        last = years[-1]
        live = last >= file_max_year - 1
        year_projection = last if live else None
        year_provisional = (last - 1) if live else None

        slug = slugify(name)
        payload = {
            "name": NICE_NAME.get(name, name),
            "psd_name": name,
            "years": years,
            "year_provisional": year_provisional,
            "year_projection": year_projection,
            "eu_folded": eu_folded,
            "metrics": available,
            "units": {m: str(units.loc[name, m]) for m in available
                      if pd.notna(units.loc[name, m])},
            "series": series,
        }
        (DATA / "commodity" / f"{slug}.json").write_text(
            json.dumps(payload, separators=(",", ":"), allow_nan=False))

        catalogue.append({
            "slug": slug,
            "name": NICE_NAME.get(name, name),
            "psd_name": name,
            "category": category_for(code),
            "metrics": available,
            "units": payload["units"],
            "year_start": years[0],
            "year_end": years[-1],
            "year_provisional": year_provisional,
            "year_projection": year_projection,
            "defaults": defaults,
        })

    # World first, then continents; the rest sorted by display name. Sorting
    # matters because the renames above (e.g. "Korea, South" -> "South Korea")
    # break the source file's own ordering.
    entities = [{"code": "@World", "name": "World", "kind": "aggregate"}] + [
        {"code": "@" + c, "name": c, "kind": "aggregate"} for c in CONTINENTS]
    named = []
    for ccode, row in ent.iterrows():
        if ccode not in used_entities:
            continue
        # pandas leaves NaN in object columns; JSON has no NaN literal.
        def clean(v):
            return v if isinstance(v, str) else None

        named.append({"code": ccode, "name": row["name"], "kind": row.kind,
                      "iso3": clean(row.iso3),
                      "continent": clean(row.continent),
                      "map_id": clean(row.map_id)})
    named.sort(key=lambda e: e["name"].lower())
    entities.extend(named)

    catalogue.sort(key=lambda c: (c["category"], c["name"]))
    index = {
        "source": "USDA Foreign Agricultural Service, Production, Supply and "
                  "Distribution (PSD)",
        "source_url": "https://apps.fas.usda.gov/psdonline/app/index.html",
        "source_updated": source_last_modified(),
        "metrics": [
            {"key": "production", "name": "Production"},
            {"key": "yield", "name": "Yield"},
            {"key": "area", "name": "Area harvested"},
        ],
        "commodities": catalogue,
        "entities": entities,
        # For grains, oilseeds and cotton, PSD reports the EU as one entity
        # instead of its members. The map hatches these polygons rather than
        # painting each with the EU-wide total.
        "eu_member_map_ids": sorted(
            {ent.map_id[c] for c in EU_MEMBER_CODES if c in ent.index
             and isinstance(ent.map_id[c], str)}),
    }
    (DATA / "index.json").write_text(json.dumps(index, separators=(",", ":"), allow_nan=False))

    total = sum(f.stat().st_size for f in (DATA / "commodity").glob("*.json"))
    print(f"wrote {len(catalogue)} commodities, {len(entities)} entities, "
          f"{total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
