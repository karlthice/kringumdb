#!/usr/bin/env python3
"""
Import Icelandic saga items into kringum.db.

Reads 4 JSON files (laxdæla, njála, egilssaga, hrafnkell), translates
stories to English via Claude Sonnet, assigns random GPS near Iceland's
center, and inserts into the items table.

Usage:
  python import_sagas.py                  # import all
  python import_sagas.py --limit 3        # import 3 items
  python import_sagas.py --dry-run        # preview without DB writes
"""

import argparse
import json
import math
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime

import anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "kringum.db")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "progress.json")

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

MODEL = "claude-sonnet-4-6"
API_DELAY = 0.3

# Center of Iceland and 50km radius
CENTER_LAT = 64.96
CENTER_LNG = -18.51
RADIUS_KM = 50

# Saga file definitions: (filename, IS suffix, EN suffix)
SAGAS = [
    ("laxdæla.json", "Laxdæla", "Laxdaela saga"),
    ("njála.json", "Njála", "Njals saga"),
    ("egilssaga.json", "Egils saga", "Egils saga"),
    ("hrafnkell.json", "Hrafnkels saga", "Hrafnkels saga"),
]

# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

SYSTEM_TRANSLATE = """You are an expert translator. Translate the following Icelandic text about an Icelandic saga location into natural, fluent English.

Rules:
- Preserve all Icelandic place names and personal names in their original form (with accents).
- The tone should be encyclopedic and engaging.
- Respond with ONLY the translated text, nothing else. No title, no commentary."""


def get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "sk-ant-your-key-here":
        print("ERROR: Set ANTHROPIC_API_KEY in .env", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic()


def translate_to_english(client, text, retries=2):
    """Translate Icelandic text to English via Claude."""
    for attempt in range(retries + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM_TRANSLATE,
                messages=[{"role": "user", "content": text}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            if attempt < retries:
                wait = 2 ** (attempt + 1)
                print(f"    Retry {attempt + 1}/{retries} after error: {e}")
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# GPS generation
# ---------------------------------------------------------------------------

def random_gps_in_radius():
    """Generate a random GPS point within RADIUS_KM of Iceland's center."""
    angle = random.uniform(0, 2 * math.pi)
    # sqrt for uniform distribution within circle
    dist = RADIUS_KM * math.sqrt(random.uniform(0, 1))

    lat_offset = dist / 111.0 * math.cos(angle)
    lng_offset = dist / (111.0 * math.cos(math.radians(CENTER_LAT))) * math.sin(angle)

    lat = CENTER_LAT + lat_offset
    lng = CENTER_LNG + lng_offset

    return f"{lat:.6f}, {lng:.6f}"


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def load_saga_file(filename):
    """Load a saga JSON file, handling markdown code fences if present."""
    path = os.path.join(SCRIPT_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Strip markdown code fences if present
    content = re.sub(r"^```json\s*\n", "", content)
    content = re.sub(r"\n```\s*$", "", content)

    return json.loads(content)


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def normalize(s):
    s = s.lower().strip()
    s = re.sub(r'[.,;:!?"()\-]', " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_existing_names(conn):
    rows = conn.execute("SELECT name FROM items").fetchall()
    return {normalize(row[0]) for row in rows}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Import saga items into kringum.db")
    parser.add_argument("--limit", type=int, default=0, help="Max items to process (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--reset", action="store_true", help="Clear progress and start fresh")
    args = parser.parse_args()

    print("=== Saga Importer ===\n")

    # Load all saga items
    all_items = []
    for filename, saga_is, saga_en in SAGAS:
        items = load_saga_file(filename)
        print(f"  {filename}: {len(items)} items")
        for item in items:
            all_items.append({
                "name_is": f"{item['Name']}, {saga_is}",
                "name_en": f"{item['Name']}, {saga_en}",
                "story_is": item["Story"],
                "saga_is": saga_is,
            })

    print(f"\nTotal items: {len(all_items)}")

    # DB connection
    conn = sqlite3.connect(DB_PATH)
    existing = get_existing_names(conn)
    print(f"Existing items in DB: {len(existing)}")

    # Progress
    if args.reset and os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("Progress reset")

    progress = load_progress()
    print(f"Already processed: {len(progress)}")

    # Claude client
    client = get_client() if not args.dry_run else None

    now = datetime.now().isoformat()
    imported = 0
    skipped_dup = 0
    skipped_done = 0
    errors = 0

    for item in all_items:
        key = item["name_is"]

        # Skip if already in progress
        if key in progress:
            skipped_done += 1
            continue

        # Skip duplicates
        if normalize(key) in existing:
            skipped_dup += 1
            continue

        if args.limit and imported >= args.limit:
            print(f"\n  Reached limit of {args.limit}")
            break

        print(f"\n  [{imported + 1}] {item['name_is']}")

        if args.dry_run:
            gps = random_gps_in_radius()
            print(f"    GPS: {gps}")
            print(f"    Story: {len(item['story_is'])} chars")
            print(f"    [DRY RUN] Would translate and insert")
            imported += 1
            continue

        try:
            # Translate
            print(f"    Translating to English...")
            story_eng = translate_to_english(client, item["story_is"])
            print(f"    Translated: {len(story_eng)} chars")
            time.sleep(API_DELAY)

            # Generate GPS
            gps = random_gps_in_radius()

            # Insert
            conn.execute(
                """INSERT INTO items
                   (name, name_eng, gps, tag, story, story_eng, ref, source, lastchanged, link, link_eng, visibility)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["name_is"],
                    item["name_en"],
                    gps,
                    "Saga",
                    item["story_is"],
                    story_eng,
                    "Stratos ehf",
                    "Stratos ehf",
                    now,
                    "",
                    "",
                    0,
                ),
            )
            conn.commit()

            # Save progress
            progress[key] = {
                "name_en": item["name_en"],
                "gps": gps,
                "story_eng_len": len(story_eng),
            }
            save_progress(progress)

            # Preview
            print(f"    GPS: {gps}")
            print(f"    EN preview: {story_eng[:150]}...")

            imported += 1
            existing.add(normalize(key))

        except Exception as e:
            print(f"    ERROR: {e}")
            errors += 1

    conn.close()

    print(f"\n{'='*40}")
    print(f"SUMMARY")
    print(f"{'='*40}")
    print(f"Imported: {imported}")
    print(f"Skipped (duplicate): {skipped_dup}")
    print(f"Skipped (already done): {skipped_done}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
