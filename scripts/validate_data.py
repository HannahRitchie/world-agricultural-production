# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas"]
# ///
"""Re-derive every published figure from the raw PSD CSV and compare.

This is an independent check of the whole explorer, not a re-run of the build:
it reads scripts/psd_alldata.csv and data/commodity/*.json and reconciles them
across all commodities, metrics and entities.

Checks
  1  country values      every entity-year in the JSON matches the source row
  2  units               each commodity's unit strings match the source
  3  World aggregates    sum of reporting entities, historic parents suppressed
  4  continent closure   continents sum to World (bar the "Other" residual)
  5  yield identity      yield == k x production / area, k derived per commodity
  6  magnitudes          no negative, no absurd values

Usage:  uv run scripts/validate_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from entities import AGGREGATE_MEMBERS, CONTINENTS

ROOT = Path(__file__).resolve().parent.parent
CSV = Path(__file__).parent / "psd_alldata.csv"
DATA = ROOT / "data"
METRICS = {"028": "production", "184": "yield", "004": "area"}
SUPPRESS = {k: v for k, v in AGGREGATE_MEMBERS.items() if k not in ("E2", "E3", "E4")}

# Yield is a ratio, so aggregating it involves a derived constant; a fraction of
# a percent is expected. Levels must match to the rounding in the JSON.
TOL_LEVEL = 1e-6
TOL_YIELD_PCT = 0.5

fails: list[str] = []
notes: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        fails.append(msg)


def main() -> None:
    print("loading source")
    df = pd.read_csv(
        CSV, keep_default_na=False, na_values=[""],
        usecols=["Commodity_Description", "Country_Code", "Market_Year",
                 "Attribute_ID", "Unit_Description", "Value"],
        dtype={"Attribute_ID": str, "Country_Code": str})
    df = df[df.Attribute_ID.isin(METRICS) & df.Value.notna()]
    df["metric"] = df.Attribute_ID.map(METRICS)

    index = json.loads((DATA / "index.json").read_text())
    by_psd = {c["psd_name"]: c for c in index["commodities"]}
    ent = {e["code"]: e for e in index["entities"]}
    print(f"  {len(df):,} source observations, {len(by_psd)} commodities\n")

    # ---- suppression, implemented here independently of the build ----------
    drop = pd.Series(False, index=df.index)
    for parent, members in SUPPRESS.items():
        par = df[df.Country_Code == parent][
            ["Commodity_Description", "Market_Year", "metric"]].drop_duplicates()
        par["_p"] = True
        kid = df[df.Country_Code.isin(members)]
        merged = kid.merge(par, on=["Commodity_Description", "Market_Year", "metric"],
                           how="left")
        merged.index = kid.index
        drop.loc[merged.index[merged._p.notna()]] = True
    print(f"suppressed {int(drop.sum())} member rows inside historic aggregates\n")
    clean = df[~drop]

    n_country = n_unit = n_world = n_cont = n_yield = n_suppressed = 0
    bad_suppressed: list[str] = []
    thin: list[str] = []
    bad_country: list[str] = []
    bad_world: list[str] = []
    bad_cont: list[str] = []
    bad_yield: list[str] = []
    neg: list[str] = []

    print("reconciling every commodity")
    for psd_name, cat in sorted(by_psd.items()):
        slug = cat["slug"]
        j = json.loads((DATA / "commodity" / f"{slug}.json").read_text())
        yidx = {y: i for i, y in enumerate(j["years"])}
        sub = df[df.Commodity_Description == psd_name]
        sub_clean = clean[clean.Commodity_Description == psd_name]

        # 2 - units
        for m, unit in j["units"].items():
            src = sub[sub.metric == m].Unit_Description.mode()
            if len(src) and src.iat[0] != unit:
                bad_country.append(f"{slug}/{m}: unit {unit!r} != source {src.iat[0]!r}")
            n_unit += 1

        # 1 - every surviving country-year value round-trips, and every
        #     suppressed one is absent (that is the point of suppressing it)
        for (code, yr, m), v in sub_clean.set_index(
                ["Country_Code", "Market_Year", "metric"]).Value.items():
            series = j["series"].get(code, {}).get(m)
            got = None if series is None else series[yidx[yr]]
            if got is None or abs(got - round(v, 4)) > TOL_LEVEL:
                bad_country.append(f"{slug}/{code}/{yr}/{m}: json={got} source={v}")
            n_country += 1
            if got is not None and got < 0:
                neg.append(f"{slug}/{code}/{yr}/{m}={got}")

        dropped = sub[drop.reindex(sub.index, fill_value=False)]
        for (code, yr, m), v in dropped.set_index(
                ["Country_Code", "Market_Year", "metric"]).Value.items():
            series = j["series"].get(code, {}).get(m)
            if series is not None and series[yidx[yr]] is not None:
                bad_suppressed.append(f"{slug}/{code}/{yr}/{m} should be suppressed")
            n_suppressed += 1

        # derive k for this commodity, as the build does
        wide = sub_clean.pivot_table(index=["Country_Code", "Market_Year"],
                                     columns="metric", values="Value")
        k = None
        if {"yield", "area", "production"} <= set(wide.columns):
            fit = wide[(wide["production"] > 0) & (wide["area"] > 0) & (wide["yield"] > 0)]
            if len(fit) >= 20:
                k = float((fit["yield"] * fit["area"] / fit["production"]).median())

        # 3/4/5 - aggregates
        for yr in j["years"]:
            rows = sub_clean[sub_clean.Market_Year == yr]
            for m in ("production", "area"):
                w = j["series"].get("@World", {}).get(m)
                if w is None or w[yidx[yr]] is None:
                    continue
                expect = rows[rows.metric == m].Value.sum()
                if abs(expect - w[yidx[yr]]) > max(TOL_LEVEL, abs(expect) * 1e-9):
                    bad_world.append(f"{slug}/{yr}/{m}: json={w[yidx[yr]]} sum={expect}")
                n_world += 1

                # continents close on World, allowing the un-continented residual
                parts = 0.0
                for c in CONTINENTS:
                    cs = j["series"].get("@" + c, {}).get(m)
                    if cs and cs[yidx[yr]] is not None:
                        parts += cs[yidx[yr]]
                resid = rows[(rows.metric == m) & (rows.Country_Code == "ZZ")].Value.sum()
                if abs(parts + resid - w[yidx[yr]]) > max(1e-4, abs(expect) * 1e-9):
                    bad_cont.append(
                        f"{slug}/{yr}/{m}: continents+other={parts + resid} world={w[yidx[yr]]}")
                n_cont += 1

            wy = j["series"].get("@World", {}).get("yield")
            if k and wy and wy[yidx[yr]] is not None:
                # An aggregate ratio must take numerator and denominator over the
                # same rows: area where published, otherwise implied from the
                # entity's own yield, and the row dropped if neither is usable.
                w = rows.pivot_table(index="Country_Code", columns="metric",
                                     values="Value")
                if "production" in w and "yield" in w:
                    implied = (w["production"] * k / w["yield"]).where(w["yield"] > 0)
                    eff = w["area"].fillna(implied) if "area" in w else implied
                    use = w.assign(_a=eff)
                    use = use[use._a.notna() & (use._a > 0) & use["production"].notna()]
                    if len(use) and use._a.sum() > 0:
                        expect = k * use["production"].sum() / use._a.sum()
                        d = abs(expect - wy[yidx[yr]]) / expect * 100
                        if d > TOL_YIELD_PCT:
                            bad_yield.append(
                                f"{slug}/{yr}: json={wy[yidx[yr]]:.4f} "
                                f"derived={expect:.4f} ({d:.2f}%)")
                        n_yield += 1
                        # How much of world production the area-reporting subset
                        # covers. A low share means the aggregate yield describes
                        # a fraction of the crop, not the world.
                        total = w["production"].sum()
                        if total > 0:
                            cov = use["production"].sum() / total
                            if cov < 0.80:
                                thin.append(f"{slug}/{yr}: {cov:.0%} of production")

    print()
    check(not bad_country, f"country values match source ({n_country:,} checked)")
    for b in bad_country[:5]:
        print("        " + b)
    check(not bad_world, f"World = sum of reporting entities ({n_world:,} checked)")
    for b in bad_world[:5]:
        print("        " + b)
    check(not bad_cont, f"continents close on World ({n_cont:,} checked)")
    for b in bad_cont[:5]:
        print("        " + b)
    check(not bad_yield,
          f"World yield = k x production / area within {TOL_YIELD_PCT}% ({n_yield:,} checked)")
    for b in bad_yield[:5]:
        print("        " + b)
    check(not bad_suppressed,
          f"rows inside historic aggregates are suppressed ({n_suppressed} checked)")
    for b in bad_suppressed[:5]:
        print("        " + b)
    check(not neg, f"no negative values ({n_country:,} checked)")
    for b in neg[:5]:
        print("        " + b)
    check(n_unit > 0, f"unit strings match source ({n_unit} commodity-metrics)")

    # How many countries USDA actually tracks per commodity. For dairy and some
    # meats it is a short list of major producers, so "World" is a partial total
    # rather than a global one -- worth knowing before comparing against FAO.
    latest = df[df.metric == "production"].groupby("Commodity_Description").Market_Year.max()
    cover = []
    for com, g in df[df.metric == "production"].groupby("Commodity_Description"):
        if com not in by_psd:
            continue
        r = g[g.Market_Year == latest[com]]
        cover.append((int((r.Value > 0).sum()), by_psd[com]["name"]))
    cover.sort()
    thin_cover = [c for c in cover if c[0] < 20]
    if thin_cover:
        print(f"\n  NOTE  {len(thin_cover)} of {len(cover)} commodities are tracked for fewer "
              f"than 20 countries, so their\n        \"World\" is a sum of major producers, "
              f"not a global total. Fewest:")
        for cnt, nm in thin_cover[:8]:
            print(f"        {nm:32s} {cnt:3d} countries")

    # Reported, not failed: a caveat about the data, not a defect in the build.
    if thin:
        print(f"\n  NOTE  {len(thin)} commodity-years where the entities reporting area "
              f"cover <80% of production,\n        so the aggregate yield describes only "
              f"part of the crop. Worst cases:")
        for t in sorted(thin, key=lambda s: float(s.split(": ")[1].rstrip("% of production")))[:8]:
            print("        " + t)

    print(f"\n=== failures: {len(fails)}")
    for f in fails:
        print("  -", f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
