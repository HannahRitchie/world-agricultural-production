# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "fonttools", "brotli"]
# ///
"""Render a static 4x2 small-multiples PNG for publishing (Substack etc.).

Top row    yield of corn, wheat, rice and soybeans
Bottom row production of the same four

World totals, computed by build_data.py. Each panel is a single series, so no
categorical palette is needed — the column headings carry identity and one ink
serves every panel. y-axes are shared within each row so the four crops are
directly comparable, and both forms start at zero.

Usage:
    uv run scripts/make_static_chart.py                      # lines, from 1960
    uv run scripts/make_static_chart.py --kind column --start 2000

Output: static-charts/yield-and-production-4x2[-column][-<start>].png
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = ROOT / "static-charts"
FONT_CACHE = Path(__file__).parent / "_fonts"

# Hue per crop, held constant down each column so the yield panel and the
# production panel for a crop read as a pair. This set passes the all-pairs
# gates that small multiples require (worst CVD dE 9.2, normal-vision 16.3);
# the reference palette's first four do not, because yellow meets orange.
CROPS = [
    ("corn", "Corn (maize)", "#2a78d6"),
    ("wheat", "Wheat", "#eb6834"),
    ("rice-milled", "Rice", "#1baf7a"),
    ("oilseed-soybean", "Soybeans", "#4a3aa7"),
]

# The provisional and forecast years come from the build, not hardcoded, so they
# follow each monthly USDA release.

TEXT = "#1d2934"
MUTED = "#5b6b7c"
FAINT = "#8b98a5"
GRID = "#e3e8ec"          # solid hairline, one shade off the surface
SURFACE = "#ffffff"


def install_fonts() -> tuple[str, str]:
    """Unpack the woff2 subsets in data/fonts.css so matplotlib can use them.

    Keeps the static chart's typography identical to the explorer's.
    Returns (display_family, body_family), falling back to DejaVu Sans.
    """
    css = DATA / "fonts.css"
    if not css.exists():
        return "DejaVu Sans", "DejaVu Sans"
    FONT_CACHE.mkdir(exist_ok=True)
    try:
        from fontTools.ttLib import TTFont, woff2
        from fontTools.varLib import instancer
    except ImportError:
        return "DejaVu Sans", "DejaVu Sans"

    pattern = re.compile(
        r"font-family:'([^']+)';font-style:(\w+);font-weight:(\d+);"
        r"[^;]*;src:url\(data:font/woff2;base64,([^)]+)\)")
    seen = set()
    for family, _style, weight, b64 in pattern.findall(css.read_text()):
        target = FONT_CACHE / f"{family}-{weight}.ttf"
        if target.exists():
            seen.add(family)
            continue
        raw = FONT_CACHE / f"{family}-{weight}.woff2"
        raw.write_bytes(base64.b64decode(b64))
        try:
            woff2.decompress(str(raw), str(target))
            # Inter is a variable font whose default instance is weight 400, so
            # matplotlib would silently render "bold" as regular. Pin the axis.
            font = TTFont(str(target))
            if "fvar" in font:
                pinned = instancer.instantiateVariableFont(
                    font, {"wght": int(weight)}, inplace=False)
                pinned["OS/2"].usWeightClass = int(weight)
                pinned.save(str(target))
            font.close()
            seen.add(family)
        except Exception as exc:                                  # noqa: BLE001
            print(f"  could not unpack {family} {weight}: {exc}")
        finally:
            raw.unlink(missing_ok=True)

    for ttf in FONT_CACHE.glob("*.ttf"):
        font_manager.fontManager.addfont(str(ttf))
    have = {f.name for f in font_manager.fontManager.ttflist}
    display = "Inter" if "Inter" in have and "Inter" in seen else "DejaVu Sans"
    body = "Lato" if "Lato" in have and "Lato" in seen else "DejaVu Sans"
    print(f"  fonts: display={display}, body={body}")
    return display, body


def load(slug: str, year_min: int) -> tuple[dict, dict]:
    d = json.loads((DATA / "commodity" / f"{slug}.json").read_text())
    world = d["series"]["@World"]
    idx = {y: i for i, y in enumerate(d["years"])}
    out = {}
    for metric in ("yield", "production"):
        series = world.get(metric) or []
        pts = [(y, series[idx[y]]) for y in d["years"]
               if year_min <= y <= d["year_projection"]
               and series and series[idx[y]] is not None]
        out[metric] = pts
    return d, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("line", "column"), default="line")
    ap.add_argument("--start", type=int, default=1960)
    args = ap.parse_args()
    year_min, kind = args.start, args.kind

    display, body = install_fonts()
    plt.rcParams.update({
        "font.family": body,
        "text.color": TEXT,
        "axes.edgecolor": GRID,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "svg.fonttype": "none",
    })

    data = {slug: load(slug, year_min) for slug, _, _ in CROPS}
    meta = data[CROPS[0][0]][0]
    prov, proj = meta["year_provisional"], meta["year_projection"]
    if {(d["year_provisional"], d["year_projection"]) for d, _ in data.values()} != {(prov, proj)}:
        raise SystemExit("crops disagree on the provisional/forecast years")

    fig, axes = plt.subplots(
        2, 4, figsize=(13.2, 6.9), dpi=190,
        gridspec_kw={"hspace": 0.40, "wspace": 0.13,
                     "left": 0.062, "right": 0.988, "top": 0.760, "bottom": 0.190})

    rows = [
        ("yield", "Yield", "tonnes per hectare"),
        ("production", "Production", "million tonnes"),
    ]
    # Shared y-limit per row so the four crops compare directly.
    limits = {}
    for metric, _, _ in rows:
        top = max(v for slug, _, _ in CROPS for _, v in data[slug][1][metric])
        if metric == "production":
            top /= 1000.0
        limits[metric] = top * 1.12

    for r, (metric, row_label, unit) in enumerate(rows):
        for c, (slug, label, hue) in enumerate(CROPS):
            ax = axes[r][c]
            pts = data[slug][1][metric]
            xs = [y for y, _ in pts]
            ys = [(v / 1000.0 if metric == "production" else v) for _, v in pts]

            ax.set_axisbelow(True)
            ax.yaxis.grid(True, color=GRID, linewidth=0.8, linestyle="-")
            ax.xaxis.grid(False)
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(GRID)
            ax.spines["bottom"].set_linewidth(0.8)

            solid = [(x, y) for x, y in zip(xs, ys) if x < proj]
            fcast = [(x, y) for x, y in zip(xs, ys) if x >= proj]

            if kind == "column":
                # Bars encode magnitude by length, so the baseline stays at zero.
                # 0.82 of the year step leaves a surface gap between columns.
                ax.bar([x for x, _ in solid], [y for _, y in solid],
                       width=0.82, color=hue, linewidth=0)
                # The forecast year is an open box with a dashed outline, so it
                # reads as a projection rather than an observation.
                ax.bar([x for x, _ in fcast], [y for _, y in fcast],
                       width=0.82, facecolor="none", edgecolor=hue,
                       linewidth=1.4, linestyle=(0, (3.2, 2.2)), zorder=4)
                label_dx, label_dy, label_ha = 0, 7, "center"
            else:
                ax.plot([x for x, _ in solid], [y for _, y in solid],
                        color=hue, linewidth=2.0, solid_capstyle="round")
                if fcast:
                    bridge = solid[-1:] + fcast
                    ax.plot([x for x, _ in bridge], [y for _, y in bridge],
                            color=hue, linewidth=2.0, linestyle=(0, (3.2, 2.2)))
                ax.plot([xs[-1]], [ys[-1]], "o", markersize=6.4, zorder=5,
                        markerfacecolor=SURFACE, markeredgecolor=hue,
                        markeredgewidth=1.8)
                label_dx, label_dy, label_ha = -3, 10, "right"

            # One direct label per panel: the latest value.
            ax.annotate(f"{ys[-1]:,.1f}" if ys[-1] < 100 else f"{ys[-1]:,.0f}",
                        (xs[-1], ys[-1]), textcoords="offset points",
                        xytext=(label_dx, label_dy), ha=label_ha, fontsize=10.5,
                        fontweight="bold", color=TEXT)

            pad_l = 0.9 if kind == "column" else 1
            pad_r = 1.4 if kind == "column" else 3
            ax.set_xlim(year_min - pad_l, proj + pad_r)
            ax.set_ylim(0, limits[metric])
            step = 20 if (proj - year_min) > 40 else 5
            ticks = [y for y in range(year_min, proj + 1) if y % step == 0]
            ax.set_xticks(ticks)
            ax.tick_params(axis="both", length=0, labelsize=10, pad=5)
            if c == 0:
                ax.set_ylabel(unit, fontsize=10, color=FAINT, labelpad=8)
            else:
                ax.set_yticklabels([])
            if r == 0:
                ax.set_xticklabels([])
            # Crop name over every panel in both rows, so each row reads on its own.
            ax.set_title(label, fontsize=12.5, fontweight="bold",
                         color=TEXT, pad=8, fontfamily=display)

            # Row name above the row, clear of the crop titles.
            if c == 0:
                ax.text(0.0, 1.175, row_label, transform=ax.transAxes,
                        fontsize=11.5, fontweight="bold", color=MUTED,
                        ha="left", va="bottom")

    fig.text(0.062, 0.950,
             "How is global production of the largest crops tracking this year?",
             fontsize=19, fontweight="bold", color=TEXT, ha="left",
             fontfamily=display)
    fig.text(0.062, 0.898,
             f"Historical estimates, and the latest forecast for {proj} "
             f"(as of the latest August release).",
             fontsize=11.5, color=MUTED, ha="left", va="top", linespacing=1.5)

    fig.text(0.062, 0.115,
             "Data source: USDA Foreign Agricultural Service, Production, Supply "
             "and Distribution (PSD). Based on marketing years, given as the start "
             "year.\n"
             f"{proj} is a forecast, shown as an open dashed {'bar' if kind == 'column' else 'line'}; "
             f"{prov} is a provisional estimate. Rice production is on a milled basis "
             "while rice yield is on a rough (paddy) basis, as published by USDA.",
             fontsize=8.8, color=FAINT, ha="left", va="top", linespacing=1.55)

    suffix = ("" if kind == "line" else "-column") + \
             ("" if year_min == 1960 else f"-{year_min}")
    OUT = OUT_DIR / f"yield-and-production-4x2{suffix}.png"
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT, facecolor=SURFACE)
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size / 1024:.0f} KB, "
          f"{int(fig.get_size_inches()[0] * fig.dpi)}x"
          f"{int(fig.get_size_inches()[1] * fig.dpi)} px)")


if __name__ == "__main__":
    main()
