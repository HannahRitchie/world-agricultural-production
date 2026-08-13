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
directly comparable; the x-axis is shared throughout.

Usage:  uv run scripts/make_static_chart.py
Output: static-charts/yield-and-production-4x2.png
"""
from __future__ import annotations

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
OUT = ROOT / "static-charts" / "yield-and-production-4x2.png"
FONT_CACHE = Path(__file__).parent / "_fonts"

CROPS = [
    ("corn", "Corn (maize)"),
    ("wheat", "Wheat"),
    ("rice-milled", "Rice"),
    ("oilseed-soybean", "Soybeans"),
]

# The 2026 USDA forecast is excluded; 2025 is a provisional estimate.
YEAR_MIN, YEAR_MAX = 1960, 2025

# Single validated ink (lightness band, chroma floor and contrast all pass for
# the light surface). Colour carries no information here, so one hue is used.
INK = "#2a6ba8"
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


def load(slug: str) -> tuple[dict, dict]:
    d = json.loads((DATA / f"{slug}.json").read_text()) if slug.endswith(".json") \
        else json.loads((DATA / "commodity" / f"{slug}.json").read_text())
    world = d["series"]["@World"]
    idx = {y: i for i, y in enumerate(d["years"])}
    out = {}
    for metric in ("yield", "production"):
        series = world.get(metric) or []
        pts = [(y, series[idx[y]]) for y in d["years"]
               if YEAR_MIN <= y <= YEAR_MAX and series and series[idx[y]] is not None]
        out[metric] = pts
    return d, out


def main() -> None:
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

    data = {slug: load(slug) for slug, _ in CROPS}

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
        top = max(v for slug, _ in CROPS for _, v in data[slug][1][metric])
        if metric == "production":
            top /= 1000.0
        limits[metric] = top * 1.12

    for r, (metric, row_label, unit) in enumerate(rows):
        for c, (slug, label) in enumerate(CROPS):
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

            ax.plot(xs, ys, color=INK, linewidth=2.0, solid_capstyle="round")

            # One direct label per panel: the endpoint value.
            ax.plot([xs[-1]], [ys[-1]], "o", color=INK, markersize=4.6,
                    markeredgecolor=SURFACE, markeredgewidth=1.4, zorder=5)
            ax.annotate(f"{ys[-1]:,.1f}" if ys[-1] < 100 else f"{ys[-1]:,.0f}",
                        (xs[-1], ys[-1]), textcoords="offset points",
                        xytext=(-3, 9), ha="right", fontsize=10.5,
                        fontweight="bold", color=INK)

            ax.set_xlim(YEAR_MIN - 1, YEAR_MAX + 4)
            ax.set_ylim(0, limits[metric])
            ax.set_xticks([1960, 1980, 2000, 2020])
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
                        fontsize=11.5, fontweight="bold", color=INK,
                        ha="left", va="bottom")

    fig.text(0.062, 0.950, "Yield and production of the world's four largest crops",
             fontsize=19, fontweight="bold", color=TEXT, ha="left",
             fontfamily=display)
    fig.text(0.062, 0.898,
             "World totals. Yields are 2.5 to 3.3 times higher than in the 1960s, and "
             "production has grown faster still in every case:\n"
             "3.6\u00d7 for wheat and rice, 6.7\u00d7 for corn and 15\u00d7 for soybeans.",
             fontsize=11.5, color=MUTED, ha="left", va="top", linespacing=1.5)

    fig.text(0.062, 0.115,
             "Data: USDA Foreign Agricultural Service, Production, Supply and "
             "Distribution (PSD), August 2026 release. Marketing years, labelled by "
             "the beginning year.\n"
             "2025 is a provisional estimate; the 2026 USDA forecast is excluded. "
             "Rice production is on a milled basis while rice yield is on a rough "
             "(paddy) basis, as published by USDA.\n"
             "Soybean data begins in 1964. Yield axes are shared across the top row "
             "and production axes across the bottom row.",
             fontsize=8.8, color=FAINT, ha="left", va="top", linespacing=1.55)

    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, facecolor=SURFACE)
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size / 1024:.0f} KB, "
          f"{int(fig.get_size_inches()[0] * fig.dpi)}x"
          f"{int(fig.get_size_inches()[1] * fig.dpi)} px)")


if __name__ == "__main__":
    main()
