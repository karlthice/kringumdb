#!/usr/bin/env python3
"""Import notable shipwreck / sinking-event items into kringum.db.

Each entry in sinkings.json becomes one Saga-tagged item, geotagged at the
approximate site of the sinking. Import is idempotent: an item whose name is
already present is skipped.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "..", "..", "kringum.db")
JSON_PATH = os.path.join(HERE, "sinkings.json")
REF = "mbl.is 13.6.2026; Háskóli Íslands; Vísir.is"
SOURCE = "local"
TAG = "Saga"


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else JSON_PATH
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.now().isoformat()

    inserted = 0
    skipped = 0
    for item in items:
        existing = cur.execute(
            "SELECT id FROM items WHERE name = ?", (item["name"],)
        ).fetchone()
        if existing:
            print(f"SKIP (already in DB): {item['name']} (id={existing[0]})")
            skipped += 1
            continue

        cur.execute(
            """INSERT INTO items
               (name, name_eng, gps, tag, story, story_eng, ref,
                fromdate, todate, source, lastchanged, link, link_eng,
                visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["name"],
                item["name_eng"],
                item["gps"],
                item.get("tag", TAG),
                item["story"],
                item["story_eng"],
                item.get("ref", REF),
                item.get("fromdate", ""),
                item.get("todate", ""),
                SOURCE,
                now,
                item.get("link", ""),
                item.get("link_eng", ""),
                0,
            ),
        )
        print(f"INSERT: {item['name']}  @ {item['gps']}")
        inserted += 1

    conn.commit()
    conn.close()
    print()
    print(f"Inserted: {inserted}")
    print(f"Skipped:  {skipped}")


if __name__ == "__main__":
    main()
