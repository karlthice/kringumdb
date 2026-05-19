#!/usr/bin/env python3
"""
Rewrite þjóðsögur (folk tales) in kringum.db using Google Gemini.

For each item whose name ends with ", þjóðsaga":
  1. Rewrite the story in modern Icelandic (max 2500 chars)
  2. Translate the rewritten story to English

Resumable: progress saved to progress.json after each item.

Usage:
  python rewrite_stories.py                  # process all
  python rewrite_stories.py --limit 5        # process 5 items
  python rewrite_stories.py --dry-run        # preview without DB writes
  python rewrite_stories.py --id 3103        # process a single item by ID
"""

import json
import os
import sqlite3
import sys
import time

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
MAX_CHARS = 2500
API_DELAY = 0.3  # seconds between API calls

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_REWRITE_IS = f"""You are an expert Icelandic writer and storyteller. Rewrite the following Icelandic folk tale (þjóðsaga) in modern, fluent Icelandic.

Rules:
- Keep the story faithful to the original — preserve all names, places, and key events.
- Use modern Icelandic spelling, grammar, and vocabulary. Replace archaic words and constructions with their modern equivalents.
- The tone should be engaging and readable for a modern Icelandic audience, like a well-told story.
- Pay close attention to correct declensions (beyging), grammatical case (fall), gender (kyn), and word order.
- The rewritten text MUST be {MAX_CHARS} characters or fewer. If the original is very long, condense while keeping the most important narrative elements.
- Respond with ONLY the rewritten story text, nothing else. No title, no commentary."""

SYSTEM_TRANSLATE_EN = f"""You are an expert translator. Translate the following modern Icelandic folk tale into natural, fluent English.

Rules:
- Write clear, engaging English that reads like a well-told story.
- Preserve all Icelandic place names and personal names in their original Icelandic form (with accents).
- The translation MUST be {MAX_CHARS} characters or fewer.
- Respond with ONLY the translated text, nothing else. No title, no commentary."""

# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------


def get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "sk-ant-your-key-here":
        print("ERROR: Set ANTHROPIC_API_KEY in .env", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic()


def call_api(client, system_prompt, user_text, retries=3):
    """Call Claude API and return text response with retry logic."""
    for attempt in range(retries + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_text}],
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
# Progress tracking
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
# Main
# ---------------------------------------------------------------------------


def process_item(client, item_id, name, story, dry_run=False):
    """Rewrite one item. Returns (new_story_is, new_story_en) or None on error."""
    print(f"\n  [{item_id}] {name}")
    print(f"    Original: {len(story)} chars")

    # Step 1: Rewrite in modern Icelandic
    print(f"    Rewriting in modern Icelandic...")
    if dry_run:
        print(f"    [DRY RUN] Would call Gemini to rewrite ({len(story)} chars)")
        return None

    new_story_is = call_api(client, SYSTEM_REWRITE_IS, story)
    print(f"    Rewritten: {len(new_story_is)} chars")
    time.sleep(API_DELAY)

    # Step 2: Translate to English
    print(f"    Translating to English...")
    new_story_en = call_api(client, SYSTEM_TRANSLATE_EN, new_story_is)
    print(f"    Translated: {len(new_story_en)} chars")
    time.sleep(API_DELAY)

    return new_story_is, new_story_en


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Rewrite þjóðsögur with Claude")
    parser.add_argument("--limit", type=int, default=0, help="Max items to process (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    parser.add_argument("--id", type=int, default=0, help="Process a single item by ID")
    parser.add_argument("--reset", action="store_true", help="Clear progress and start fresh")
    args = parser.parse_args()

    print("=== StoryRewriter: þjóðsögur ===\n")

    # Connect to DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Query items
    if args.id:
        rows = conn.execute(
            "SELECT id, name, story, story_eng FROM items WHERE id = ? AND name LIKE '%þjóðsaga'",
            (args.id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, story, story_eng FROM items WHERE name LIKE '%þjóðsaga' ORDER BY id"
        ).fetchall()

    print(f"Found {len(rows)} þjóðsaga items")

    # Progress
    if args.reset and os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("Progress reset")

    progress = load_progress()
    print(f"Already processed: {len(progress)} items")

    # Init Claude client
    client = get_client() if not args.dry_run else None

    processed = 0
    skipped = 0
    errors = 0

    for row in rows:
        item_id = str(row["id"])
        name = row["name"]
        story = row["story"]

        if item_id in progress and not args.id:
            skipped += 1
            continue

        if args.limit and processed >= args.limit:
            print(f"\n  Reached limit of {args.limit} items")
            break

        try:
            result = process_item(client, item_id, name, story, dry_run=args.dry_run)

            if result and not args.dry_run:
                new_story_is, new_story_en = result

                # Update DB
                conn.execute(
                    "UPDATE items SET story = ?, story_eng = ? WHERE id = ?",
                    (new_story_is, new_story_en, int(item_id)),
                )
                conn.commit()

                # Save progress
                progress[item_id] = {
                    "name": name,
                    "story_is_len": len(new_story_is),
                    "story_en_len": len(new_story_en),
                }
                save_progress(progress)

                # Print preview
                print(f"\n    --- IS preview (first 200 chars) ---")
                print(f"    {new_story_is[:200]}...")
                print(f"\n    --- EN preview (first 200 chars) ---")
                print(f"    {new_story_en[:200]}...")

            processed += 1

        except Exception as e:
            print(f"    ERROR: {e}")
            errors += 1

    conn.close()

    print(f"\n{'='*40}")
    print(f"SUMMARY")
    print(f"{'='*40}")
    print(f"Processed: {processed}")
    print(f"Skipped (already done): {skipped}")
    print(f"Errors: {errors}")
    print(f"Total in progress.json: {len(progress)}")


if __name__ == "__main__":
    main()
