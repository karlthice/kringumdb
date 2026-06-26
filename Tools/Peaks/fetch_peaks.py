#!/usr/bin/env python3
"""Fetch all named mountain peaks in Iceland from OpenStreetMap (Overpass API)
and emit peaks.json in the travel.json style: a flat array of objects with
gps ("lat, lon"), caption (peak name) and height (elevation in metres).

Peaks without an elevation tag are dropped.

Usage:
    python3 Tools/Peaks/fetch_peaks.py [output_path]

Default output path is peaks.json in the repository root.
"""
import json
import re
import sys
import urllib.parse
import urllib.request

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="IS"][admin_level=2]->.is;
(
  node["natural"="peak"](area.is);
);
out body;
"""


def parse_ele(value):
    """Extract an integer metre value from an OSM `ele` tag, or None."""
    if not value:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace(",", "."))
    if not match:
        return None
    try:
        return round(float(match.group()))
    except ValueError:
        return None


def fetch():
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": QUERY}).encode(),
        headers={"User-Agent": "kringumdb-peaks/1.0"},
    )
    with urllib.request.urlopen(req, timeout=150) as resp:
        return json.load(resp)


def build(data):
    items = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name")
        lat, lon = el.get("lat"), el.get("lon")
        if not name or lat is None or lon is None:
            continue
        height = parse_ele(tags.get("ele"))
        if height is None:
            continue
        items.append({
            "gps": f"{round(lat, 6)}, {round(lon, 6)}",
            "caption": name,
            "height": height,
        })
    # Tallest first; ties broken alphabetically by caption.
    items.sort(key=lambda x: (-x["height"], x["caption"]))
    return items


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "peaks.json"
    items = build(fetch())
    with open(out_path, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(items)} peaks to {out_path}")


if __name__ == "__main__":
    main()
