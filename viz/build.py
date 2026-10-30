"""Join a recorded trace with the zone shapes into one self-contained HTML page.

Run: python -m viz.build results/<run-id>
Writes viz/out/<run-id>.html to open in a browser, and viz/out/<run-id>.artifact.html,
the same page without the document wrapper, for publishing as a claude.ai artifact.
"""

import argparse
import json
import os
from typing import Dict

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDERS = ("__ZONES_JSON__", "__TRACE_JSON__", "__META_JSON__")


def _inline(obj) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render(template: str, zones: Dict, trace: Dict, meta: Dict) -> str:
    for placeholder in PLACEHOLDERS:
        if template.count(placeholder) != 1:
            raise ValueError(f"template must contain {placeholder} exactly once")
    return (
        template.replace("__ZONES_JSON__", _inline(zones))
        .replace("__TRACE_JSON__", _inline(trace))
        .replace("__META_JSON__", _inline(meta))
    )


def standalone(page: str) -> str:
    """Wrap the page in a document so it opens directly in a browser."""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"</head>\n<body>\n{page}\n</body>\n</html>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", help="results/<run-id> written by viz.trace")
    parser.add_argument("--zones", default=os.path.join(HERE, "zones.geojson"))
    parser.add_argument("--out-dir", default=os.path.join(HERE, "out"))
    args = parser.parse_args()

    def load(path):
        with open(path) as fp:
            return json.load(fp)

    trace = load(os.path.join(args.run_dir, "trace.json"))
    meta = load(os.path.join(args.run_dir, "metrics.json"))
    with open(os.path.join(HERE, "template.html")) as fp:
        page = render(fp.read(), load(args.zones), trace, meta)

    os.makedirs(args.out_dir, exist_ok=True)
    run_id = os.path.basename(os.path.normpath(args.run_dir))
    local = os.path.join(args.out_dir, f"{run_id}.html")
    artifact = os.path.join(args.out_dir, f"{run_id}.artifact.html")
    with open(local, "w") as fp:
        fp.write(standalone(page))
    with open(artifact, "w") as fp:
        fp.write(page)
    print(f"Open {local}")
    print(f"Publish {artifact} ({os.path.getsize(artifact) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
