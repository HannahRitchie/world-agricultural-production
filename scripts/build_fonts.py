# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""Write data/fonts.css: the page's webfonts as base64 @font-face rules.

Exported PNGs are produced by rasterising a standalone SVG. A standalone SVG
cannot reach fonts.googleapis.com, so any text in it would fall back to a generic
sans-serif and the export would not match the page. Embedding the latin subsets
as data URIs keeps the export faithful and works offline.

The file is fetched lazily by the page, only when someone clicks Download, so it
does not affect initial load.

Usage:  uv run scripts/build_fonts.py     (only needed if the fonts change)
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import requests

CSS_URL = ("https://fonts.googleapis.com/css2"
           "?family=Inter:wght@600;700&family=Lato:wght@300;400;700&display=swap")
# Google serves woff2 only to browsers that advertise support.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
OUT = Path(__file__).resolve().parent.parent / "data" / "fonts.css"


def main() -> None:
    css = requests.get(CSS_URL, headers={"User-Agent": UA}, timeout=60).text
    blocks = re.findall(r"/\*\s*([\w\-\[\]]+)\s*\*/\s*@font-face\s*\{([^}]*)\}", css)

    cache: dict[str, str] = {}          # url -> base64 (Inter 600/700 share a file)
    rules, total = [], 0
    for subset, body in blocks:
        if subset != "latin":
            continue
        family = re.search(r"font-family:\s*'([^']+)'", body).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", body).group(1)
        style = re.search(r"font-style:\s*(\w+)", body)
        url = re.search(r"url\((https://[^)]+)\)", body).group(1)

        if url not in cache:
            data = requests.get(url, timeout=60).content
            total += len(data)
            cache[url] = base64.b64encode(data).decode()
        rules.append(
            f"@font-face{{font-family:'{family}';"
            f"font-style:{style.group(1) if style else 'normal'};"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{cache[url]}) format('woff2')}}")
        print(f"  {family:6s} {weight}  {url.split('/')[-1]}")

    if not rules:
        raise SystemExit("no latin @font-face blocks found — did the CSS format change?")

    OUT.write_text("\n".join(rules))
    print(f"wrote {OUT.relative_to(OUT.parent.parent)} "
          f"({len(cache)} files, {total / 1024:.0f} KB raw, "
          f"{OUT.stat().st_size / 1024:.0f} KB encoded)")


if __name__ == "__main__":
    main()
