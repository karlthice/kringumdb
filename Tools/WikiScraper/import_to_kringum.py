#!/usr/bin/env python
"""
Import wiki_kringum.json items into kringum.db.

Each item already has both Icelandic and English captions and stories.
Sets link or link_eng based on whether the source was IS or EN Wikipedia.
"""

import json
import math
import sqlite3
from datetime import datetime


DB_PATH = "../../kringum.db"
JSON_PATH = "wiki_kringum.json"


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gps(gps):
    if not gps or "," not in gps:
        return None
    try:
        parts = gps.replace(" ", "").split(",")
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data["items"]
    print(f"Loaded {len(items)} items from {JSON_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Build a lookup of existing (name_lower, lat, lon) for safety dedup
    cur.execute("SELECT name, name_eng, gps FROM items")
    existing = []
    for name, name_eng, gps in cur.fetchall():
        coords = parse_gps(gps or "")
        if coords:
            existing.append((
                (name or "").lower().strip(),
                (name_eng or "").lower().strip(),
                coords[0],
                coords[1],
            ))
    print(f"Existing DB items with GPS: {len(existing)}")

    now = datetime.now().isoformat()
    imported = 0
    skipped_dup = 0
    skipped_no_gps = 0

    for item in items:
        coords = parse_gps(item.get("gps", ""))
        if not coords:
            skipped_no_gps += 1
            continue
        lat, lon = coords

        # Safety check: skip if exact name + within 100m of existing
        name_lower = item["name"].lower().strip()
        name_eng_lower = item.get("name_eng", "").lower().strip()
        is_dup = False
        for ex_name, ex_name_eng, ex_lat, ex_lon in existing:
            if haversine(lat, lon, ex_lat, ex_lon) >= 100:
                continue
            if name_lower == ex_name or name_eng_lower == ex_name_eng:
                is_dup = True
                break
        if is_dup:
            skipped_dup += 1
            continue

        name = item["name"]
        name_eng = item.get("name_eng", "")
        gps = item["gps"]
        tag = item.get("tag", "Saga")
        story = item.get("story", "")
        story_eng = item.get("story_eng", "")
        ref = "Wikipedia"
        source = "wikipedia"
        url = item.get("ref", "")

        # link goes in the matching language slot based on source wiki
        wiki_source = item.get("source", "")
        if wiki_source == "wikipedia_is":
            link = url
            link_eng = ""
        else:
            link = ""
            link_eng = url

        cur.execute(
            """INSERT INTO items
               (name, name_eng, gps, tag, story, story_eng, ref, source,
                lastchanged, link, link_eng, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, name_eng, gps, tag, story, story_eng, ref, source,
             now, link, link_eng, 0),
        )
        imported += 1
        existing.append((name_lower, name_eng_lower, lat, lon))

    conn.commit()
    conn.close()

    print()
    print(f"Imported:            {imported}")
    print(f"Skipped (duplicate): {skipped_dup}")
    print(f"Skipped (no GPS):    {skipped_no_gps}")
    print(f"Total in JSON:       {len(items)}")


if __name__ == "__main__":
    main()
