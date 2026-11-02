"""Join a recorded trace with the zone shapes into one self-contained HTML page.

Run: python -m viz.build results/<run-id>
Writes viz/out/<run-id>.html to open in a browser, and viz/out/<run-id>.artifact.html,
the same page without the document wrapper, for publishing as a claude.ai artifact.
"""

import argparse
import json
import os
import re
from typing import Dict

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
SCENE_FILES = {"__SCENE_CSS__": "scene.css", "__SCENE_HTML__": "scene.html", "__SCENE_JS__": "scene.js"}
DATA = ("__ZONES_JSON__", "__TRACE_JSON__", "__META_JSON__")


def _inline(obj) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def scene_parts(web_dir: str = WEB_DIR) -> Dict[str, str]:
    """The shared scene files (viz/web/scene.*), by the placeholder each one fills."""
    parts = {}
    for placeholder, name in SCENE_FILES.items():
        with open(os.path.join(web_dir, name)) as fp:
            parts[placeholder] = fp.read()
    return parts


def render(template: str, zones: Dict, trace: Dict, meta: Dict, scene: Dict[str, str]) -> str:
    """Fill <template> with the scene files and the run's data. Each placeholder is filled
    once, in a single pass, so text inside one part is never mistaken for another placeholder."""
    values = {**scene, "__ZONES_JSON__": _inline(zones), "__TRACE_JSON__": _inline(trace), "__META_JSON__": _inline(meta)}
    for placeholder in values:
        if template.count(placeholder) != 1:
            raise ValueError(f"template must contain {placeholder} exactly once")
    pattern = re.compile("|".join(re.escape(p) for p in values))
    return pattern.sub(lambda m: values[m.group(0)], template)


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
    with open(os.path.join(WEB_DIR, "replay.html")) as fp:
        page = render(fp.read(), load(args.zones), trace, meta, scene_parts())

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
