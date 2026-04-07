#!/usr/bin/env python
"""
Deduplicate wiki_kringum.json against kringum.db.

For each JSON item:
1. Find DB items within 1km
2. Fuzzy-match names (Icelandic + English)
3. If a name match is found, ask Claude to compare first paragraphs
4. If Claude says they describe the same place, remove the JSON item
"""

import json
import math
import os
import re
import sqlite3
import sys
import time
from difflib import SequenceMatcher

import anthropic
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "../../kringum.db"
JSON_PATH = "wiki_kringum.json"
RADIUS_M = 1000  # 1km
FUZZY_THRESHOLD = 0.65  # Min name similarity to trigger LLM check
PARAGRAPH_CHARS = 500  # First N chars of story to compare
MODEL = "claude-sonnet-4-6"
API_DELAY = 0.2

client = anthropic.Anthropic()


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fuzzy(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def parse_gps(gps):
    if not gps or "," not in gps:
        return None
    try:
        parts = gps.replace(" ", "").split(",")
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None


def first_paragraph(text, max_chars=PARAGRAPH_CHARS):
    """Get the first paragraph (or first N chars) of a story."""
    if not text:
        return ""
    # Try splitting on double newline
    paras = text.split("\n\n")
    first = paras[0].strip()
    if len(first) > max_chars:
        first = first[:max_chars] + "..."
    return first


def load_db_items():
    """Load all DB items with valid GPS."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT id, name, name_eng, gps, story, story_eng FROM items"
    )
    items = []
    for row in cur:
        id_, name, name_eng, gps, story, story_eng = row
        coords = parse_gps(gps)
        if not coords:
            continue
        items.append({
            "id": id_,
            "name": name or "",
            "name_eng": name_eng or "",
            "lat": coords[0],
            "lon": coords[1],
            "story": story or "",
            "story_eng": story_eng or "",
        })
    conn.close()
    return items


def find_candidates(item, db_items):
    """Find DB items within radius that fuzzy-match name. Returns list sorted by score desc."""
    coords = parse_gps(item["gps"])
    if not coords:
        return []
    lat, lon = coords
    j_name = item.get("name", "")
    j_name_eng = item.get("name_eng", "")

    candidates = []
    for db in db_items:
        dist = haversine(lat, lon, db["lat"], db["lon"])
        if dist >= RADIUS_M:
            continue
        # Compute max fuzzy score across all name pairs
        scores = [
            fuzzy(j_name, db["name"]),
            fuzzy(j_name, db["name_eng"]),
            fuzzy(j_name_eng, db["name"]),
            fuzzy(j_name_eng, db["name_eng"]),
        ]
        max_score = max(scores)
        if max_score >= FUZZY_THRESHOLD:
            candidates.append((db, dist, max_score))

    candidates.sort(key=lambda x: -x[2])
    return candidates


COMPARE_SYSTEM = """You are an expert in Icelandic geography and culture. You will be shown two short descriptions of places or items in Iceland. Determine whether they describe the SAME real-world place/item or DIFFERENT places/items that happen to be near each other or share a similar name.

Consider:
- Same physical place / building / landmark / event = SAME
- Same town vs a landmark in that town = DIFFERENT
- A museum vs the building it's housed in = DIFFERENT
- Different translations or spellings of the same place = SAME

Respond with EXACTLY one word: SAME or DIFFERENT"""


def llm_compare(json_item, db_item):
    """Ask Claude if two items describe the same thing."""
    j_name = json_item.get("name", "")
    j_name_eng = json_item.get("name_eng", "")
    j_para = first_paragraph(json_item.get("story", "")) or first_paragraph(json_item.get("story_eng", ""))

    d_name = db_item["name"]
    d_name_eng = db_item["name_eng"]
    d_para = first_paragraph(db_item["story"]) or first_paragraph(db_item["story_eng"])

    user_msg = f"""ITEM A:
Name: {j_name}
Name (English): {j_name_eng}
Description: {j_para}

ITEM B:
Name: {d_name}
Name (English): {d_name_eng}
Description: {d_para}

Are these the same real-world place/item?"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=20,
        system=COMPARE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    answer = resp.content[0].text.strip().upper()
    return "SAME" in answer


def main():
    print("=== Dedup wiki_kringum.json against kringum.db ===\n")

    print(f"Loading DB from {DB_PATH}...")
    db_items = load_db_items()
    print(f"  {len(db_items)} DB items with valid GPS\n")

    print(f"Loading {JSON_PATH}...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]
    print(f"  {len(items)} JSON items\n")

    print(f"Finding candidates (radius={RADIUS_M}m, fuzzy>={FUZZY_THRESHOLD})...")
    to_remove = set()  # indices
    candidates_count = 0
    llm_calls = 0

    for i, item in enumerate(items):
        candidates = find_candidates(item, db_items)
        if not candidates:
            continue
        candidates_count += 1

        # Try each candidate (best first); stop on first SAME match
        for db, dist, score in candidates:
            try:
                is_same = llm_compare(item, db)
                llm_calls += 1
                time.sleep(API_DELAY)
            except Exception as e:
                print(f"  [{i+1}/{len(items)}] LLM error: {e}")
                continue

            verdict = "SAME" if is_same else "diff"
            print(f"  [{i+1}/{len(items)}] {verdict} score={score:.2f} dist={dist:.0f}m  \"{item['name']}\" <-> \"{db['name']}\"")

            if is_same:
                to_remove.add(i)
                break  # No need to check more candidates

    print(f"\n  Candidates checked: {candidates_count}")
    print(f"  LLM calls: {llm_calls}")
    print(f"  Items to remove: {len(to_remove)}")

    # Build cleaned items list
    cleaned = [item for i, item in enumerate(items) if i not in to_remove]
    print(f"\n  Before: {len(items)} items")
    print(f"  After:  {len(cleaned)} items")

    data["items"] = cleaned
    data["metadata"]["dedup_against_db_removed"] = len(to_remove)
    data["metadata"]["new_items"] = len(cleaned)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {JSON_PATH}")


if __name__ == "__main__":
    main()
