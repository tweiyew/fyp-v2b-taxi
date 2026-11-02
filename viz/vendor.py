"""Download deck.gl and the page fonts into viz/web/vendor/ so the live site works offline.

Run once, with internet: python -m viz.vendor
Writes deck.min.js, fonts.css and the font files it names (latin and latin-ext only).
"""

import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(HERE, "web", "vendor")
DECK_URL = "https://unpkg.com/deck.gl@9.3.11/dist.min.js"
FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600"
    "&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
)
# Google Fonts serves woff2 only to browsers it recognises.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KEEP_SUBSETS = {"latin", "latin-ext"}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def localise_fonts(css: str):
    """Keep the latin and latin-ext @font-face blocks; return (css with local urls, [(url, filename)])."""
    blocks = re.findall(r"/\* ([\w-]+) \*/\s*(@font-face \{.*?\})", css, flags=re.S)
    kept, files = [], []
    for subset, block in blocks:
        if subset not in KEEP_SUBSETS:
            continue
        family = re.search(r"font-family: '([^']+)'", block).group(1)
        weight = re.search(r"font-weight: (\d+)", block).group(1)
        url = re.search(r"url\((https://[^)]+)\)", block).group(1)
        filename = f"{family.replace(' ', '')}-{weight}-{subset}.woff2"
        files.append((url, filename))
        kept.append(f"/* {subset} */\n" + block.replace(url, filename))
    return "\n".join(kept) + "\n", files


def main() -> None:
    os.makedirs(VENDOR_DIR, exist_ok=True)
    with open(os.path.join(VENDOR_DIR, "deck.min.js"), "wb") as fp:
        fp.write(fetch(DECK_URL))
    css, files = localise_fonts(fetch(FONTS_URL).decode())
    if not files:
        raise SystemExit("Google Fonts returned no woff2 fonts; the stylesheet format may have changed")
    for url, filename in files:
        with open(os.path.join(VENDOR_DIR, filename), "wb") as fp:
            fp.write(fetch(url))
    with open(os.path.join(VENDOR_DIR, "fonts.css"), "w") as fp:
        fp.write(css)
    print(f"Wrote {VENDOR_DIR}: deck.min.js, fonts.css, {len(files)} font files")


if __name__ == "__main__":
    main()
