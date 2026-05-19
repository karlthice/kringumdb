#!/usr/bin/env python3
"""Import the 2021-present Reykjanes eruption items into kringum.db.

Items are merged by location: each Fagradalsfjall-system valley (Geldingadalir,
Meradalir, Litli-Hrútur) gets one row, and the entire Sundhnúksgígaröðin
sequence (Dec 2023 onward, multiple eruptions along the same crater row) is
one merged row.
"""

import json
import os
import sqlite3
from datetime import datetime

HERE = os.path.dirname(__file__)
DB_PATH = os.path.join(HERE, "..", "..", "kringum.db")
JSON_PATH = os.path.join(HERE, "eruptions.json")
REF = "Veðurstofa Íslands; Wikipedia; icelandgeology.net"
SOURCE = "local"


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
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
                fromdate, todate, source, lastchanged, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["name"],
                item["name_eng"],
                item["gps"],
                item["tag"],
                item["story"],
                item["story_eng"],
                REF,
                item.get("fromdate", ""),
                item.get("todate", ""),
                SOURCE,
                now,
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
