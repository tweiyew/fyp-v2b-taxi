"""Download Chicago's community-area boundaries and simplify them for the 3D view.

Run once: python -m viz.zones --out viz/zones.geojson
"""

import argparse
import datetime
import json
import urllib.request
from typing import Dict, List, Sequence, Tuple

SOURCE = "https://data.cityofchicago.org/resource/igwz-8jzy.geojson"
NAME_FIXES = {"OHARE": "O'Hare"}

Point = Tuple[float, float]


def _point_line_distance(p: Point, a: Point, b: Point) -> float:
    """Distance from <p> to the segment <a>-<b>, in the units of the input."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def simplify_line(points: Sequence[Point], tolerance: float) -> List[Point]:
    """Douglas-Peucker: drop points closer than <tolerance> to the simplified line.

    The first and last points are always kept.
    """
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        worst, worst_idx = 0.0, None
        for i in range(start + 1, end):
            d = _point_line_distance(points[i], points[start], points[end])
            if d > worst:
                worst, worst_idx = d, i
        if worst_idx is not None and worst > tolerance:
            keep[worst_idx] = True
            stack.extend([(start, worst_idx), (worst_idx, end)])
    return [p for p, k in zip(points, keep) if k]


def simplify_ring(ring: Sequence[Point], tolerance: float) -> List[Point]:
    """Simplify a closed ring, keeping it closed and at least a triangle."""
    simplified = simplify_line(ring, tolerance)
    if len(simplified) < 4:
        step = max(1, (len(ring) - 1) // 3)
        simplified = [ring[0], ring[step], ring[2 * step], ring[0]]
    return simplified


def ring_area_centroid(ring: Sequence[Point]) -> Tuple[float, float, float]:
    """Shoelace area (absolute) and centroid of a closed ring."""
    area2 = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area2 == 0:
        xs, ys = zip(*ring)
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(area2) / 2, cx / (3 * area2), cy / (3 * area2)


def _zone_name(raw: str) -> str:
    return NAME_FIXES.get(raw, raw.title())


def simplify_collection(raw: Dict, tolerance: float = 0.0002, digits: int = 5) -> Dict:
    """Return a FeatureCollection with one simplified MultiPolygon per zone.

    Each feature keeps only: zone (int), name, and the centroid (cx, cy) of the
    zone's largest polygon, which is where taxis and stations are drawn.
    """
    features = []
    for feature in raw["features"]:
        props = feature["properties"]
        zone = int(props.get("area_numbe") or props["area_num_1"])
        polygons = feature["geometry"]["coordinates"]
        if feature["geometry"]["type"] == "Polygon":
            polygons = [polygons]
        simplified = [
            [
                [[round(x, digits), round(y, digits)] for x, y in simplify_ring([tuple(p) for p in ring], tolerance)]
                for ring in polygon
            ]
            for polygon in polygons
        ]
        largest = max(simplified, key=lambda poly: ring_area_centroid(poly[0])[0])
        _, cx, cy = ring_area_centroid(largest[0])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "zone": zone,
                    "name": _zone_name(props["community"]),
                    "cx": round(cx, digits),
                    "cy": round(cy, digits),
                },
                "geometry": {"type": "MultiPolygon", "coordinates": simplified},
            }
        )
    features.sort(key=lambda f: f["properties"]["zone"])
    return {
        "type": "FeatureCollection",
        "source": SOURCE,
        "fetched": datetime.date.today().isoformat(),
        "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="viz/zones.geojson")
    parser.add_argument("--tolerance", type=float, default=0.0002, help="degrees, about 20 m")
    args = parser.parse_args()

    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        raw = json.load(response)
    collection = simplify_collection(raw, tolerance=args.tolerance)
    with open(args.out, "w") as fp:
        json.dump(collection, fp, separators=(",", ":"))
    print(f"Wrote {args.out}: {len(collection['features'])} zones")


if __name__ == "__main__":
    main()
