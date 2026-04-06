#!/usr/bin/env python3
"""
Import scraped þjóðsögur into kringum.db, skipping duplicates.
Names end with ',-þjóðsaga' to distinguish imported stories.
"""

import json
import re
import sqlite3
import sys
from datetime import datetime


DB_PATH = "../../kringum.db"
JSON_PATH = "kringum_thjodsogor.json"


def normalize(s: str) -> str:
    """Normalize a title for comparison."""
    s = s.lower().strip()
    s = re.sub(r",?\s*-?þjóðsaga\s*$", "", s)
    s = re.sub(r"^\*", "", s)
    s = re.sub(r'[.,;:!?"()\-]', " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_existing_titles(cur) -> set[str]:
    """Get normalized titles of all existing þjóðsögur in the DB."""
    cur.execute("SELECT name FROM items WHERE name LIKE '%þjóðsaga%' OR name LIKE '%þjóðsögur%'")
    titles = set()
    for (name,) in cur.fetchall():
        titles.add(normalize(name))
    return titles


def is_duplicate(title_norm: str, existing: set[str]) -> bool:
    """Check if a story is already in the DB."""
    # Exact normalized match
    if title_norm in existing:
        return True
    # Substring match (either direction) for longer titles
    if len(title_norm) > 10:
        for ex in existing:
            if title_norm in ex or ex in title_norm:
                return True
    # First 3 words match
    words = title_norm.split()[:3]
    if len(words) >= 2:
        for ex in existing:
            if ex.split()[:3] == words:
                return True
    return False


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    existing = get_existing_titles(cur)
    print(f"Existing þjóðsögur in DB: {len(existing)}")

    now = datetime.now().isoformat()
    imported = 0
    skipped_dup = 0
    skipped_no_gps = 0

    for story in data["stories"]:
        title_norm = normalize(story["title"])

        if is_duplicate(title_norm, existing):
            skipped_dup += 1
            continue

        loc = story.get("primary_location")
        if not loc:
            skipped_no_gps += 1
            continue

        # Format fields to match DB conventions
        name = f"{story['title']},-þjóðsaga"
        gps = f"{loc['lat']:.6f}, {loc['lng']:.6f}"
        tag = "Saga"
        text = story["text"]
        source = "local"
        ref = story["url"]
        link = story["url"]

        cur.execute(
            """INSERT INTO items (name, gps, tag, story, ref, source, lastchanged, link, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, gps, tag, text, ref, source, now, link, 0),
        )
        imported += 1
        # Add to existing set so we don't import our own duplicates
        existing.add(title_norm)

    conn.commit()
    conn.close()

    print(f"Imported:          {imported}")
    print(f"Skipped (duplicate): {skipped_dup}")
    print(f"Skipped (no GPS):  {skipped_no_gps}")
    print(f"Total in JSON:     {len(data['stories'])}")


if __name__ == "__main__":
    main()
