#!/usr/bin/env python
"""
Post-process wiki_kringum.json:
1. Move leading years to end of captions  ("1918 eruption of Katla" -> "eruption of Katla, 1918")
2. Summarize texts over 3500 chars
3. Translate: EN-only items get Icelandic, IS-only items get English
4. Add name_eng field matching the DB schema

Resumable: progress saved after each API call to wiki_kringum_progress.json
"""

import json
import os
import re
import sys
import time

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_CHARS = 3500
INPUT_FILE = "wiki_kringum.json"
PROGRESS_FILE = "wiki_kringum_progress.json"
OUTPUT_FILE = "wiki_kringum.json"
API_DELAY = 0.3  # seconds between API calls

client = anthropic.Anthropic()

# ---------------------------------------------------------------------------
# Step 1: Year caption restructuring
# ---------------------------------------------------------------------------

YEAR_RE = re.compile(r"^(\d{4}(?:\s*[–\-]\s*\d{4})?)\s+(.+)$")


def restructure_year_caption(name):
    """Move leading year(s) to end of caption. Returns (new_name, changed)."""
    m = YEAR_RE.match(name)
    if not m:
        return name, False
    year_str = m.group(1)
    # Only apply to years >= 1000 (skip things like "365 (media corporation)")
    first_year = int(re.match(r"\d+", year_str).group())
    if first_year < 1000:
        return name, False
    rest = m.group(2)
    # Capitalize first letter of the rest
    rest = rest[0].upper() + rest[1:] if rest else rest
    return f"{rest}, {year_str}", True


# ---------------------------------------------------------------------------
# Step 2 & 3: Summarize + Translate via Claude API
# ---------------------------------------------------------------------------

SEPARATOR = "===SEPARATOR==="

SYSTEM_EN_TO_IS = """You are an expert Icelandic translator and editor. You translate English text about Iceland into natural, fluent Icelandic.

Rules:
- Write correct, natural Icelandic. Pay close attention to declensions (beyging), grammatical case (fall), gender (kyn), and word order.
- The tone should be encyclopedic and informative, like a well-written Icelandic reference article.
- Preserve all Icelandic place names, personal names, and dates exactly.
- Do NOT transliterate English place names that already have standard Icelandic forms — use the Icelandic form.
- If the text references Wikipedia-style lists, "See also" sections, or citation notes at the end, omit them.
- The translated text MUST be {max_chars} characters or fewer. If the source text is very long, summarize while preserving the most important facts, dates, and names.

Respond with EXACTLY this format (two sections separated by the separator line):
<translated caption>
===SEPARATOR===
<translated text>"""

SYSTEM_IS_TO_EN = """You are an expert translator. You translate Icelandic text about Iceland into natural, fluent English.

Rules:
- Write clear, natural English in an encyclopedic tone.
- Preserve all Icelandic place names and personal names in their original Icelandic form (with accents).
- If the text references Wikipedia-style lists, "See also" sections, or citation notes at the end, omit them.
- The translated text MUST be {max_chars} characters or fewer. If the source text is very long, summarize while preserving the most important facts, dates, and names.

Respond with EXACTLY this format (two sections separated by the separator line):
<translated caption>
===SEPARATOR===
<translated text>"""

SYSTEM_SUMMARIZE = """You are an expert editor. Summarize the following text to {max_chars} characters or fewer while preserving the most important facts, dates, names, and narrative.

Rules:
- Keep the same language as the input text.
- If the input is Icelandic: write correct, natural Icelandic with proper declensions, case, and gender.
- If the input is English: write clear, natural English.
- Encyclopedic tone.
- Omit Wikipedia-style lists, "See also" sections, and citation notes.
- Preserve Icelandic place names and personal names exactly.

Respond with ONLY the summarized text, nothing else."""


def call_claude(system_prompt, user_text, retries=2):
    """Call Claude API and return raw text response with retry logic."""
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
                print(f"    Retry {attempt+1}/{retries} after error: {e}")
                time.sleep(2)
            else:
                raise


def parse_translation(response_text):
    """Parse a caption + text response split by separator."""
    if SEPARATOR in response_text:
        parts = response_text.split(SEPARATOR, 1)
        caption = parts[0].strip()
        text = parts[1].strip()
        return caption, text
    # Fallback: first line is caption, rest is text
    lines = response_text.strip().split("\n", 1)
    caption = lines[0].strip()
    text = lines[1].strip() if len(lines) > 1 else ""
    return caption, text


def summarize_text(text):
    """Summarize text to MAX_CHARS using Claude."""
    result = call_claude(
        SYSTEM_SUMMARIZE.format(max_chars=MAX_CHARS),
        text,
    )
    return result


def process_item(item):
    """Process a single item: summarize if needed, then translate missing language."""
    lang = item.get("lang", "")
    story_is = item.get("story", "")
    story_en = item.get("story_eng", "")
    name = item.get("name", "")
    name_eng = item.get("name_eng", "")

    if lang == "en" and story_en and not story_is:
        # EN-only: need to summarize EN if too long, then translate to IS
        source_text = story_en

        # Summarize EN text if over limit
        if len(source_text) > MAX_CHARS:
            print(f"    Summarizing EN text ({len(source_text)} chars)...")
            source_text = summarize_text(source_text)
            item["story_eng"] = source_text
            item["char_count"] = len(source_text)
            time.sleep(API_DELAY)

        # Translate EN -> IS
        print(f"    Translating EN->IS...")
        prompt = f"Caption: {name}\n\nText:\n{source_text}"
        response = call_claude(
            SYSTEM_EN_TO_IS.format(max_chars=MAX_CHARS),
            prompt,
        )
        is_caption, is_text = parse_translation(response)
        item["story"] = is_text
        item["name_eng"] = name  # original EN name becomes name_eng
        item["name"] = is_caption if is_caption else name
        time.sleep(API_DELAY)

    elif lang == "is" and story_is and not story_en:
        # IS-only: need to summarize IS if too long, then translate to EN
        source_text = story_is

        # Summarize IS text if over limit
        if len(source_text) > MAX_CHARS:
            print(f"    Summarizing IS text ({len(source_text)} chars)...")
            source_text = summarize_text(source_text)
            item["story"] = source_text
            item["char_count"] = len(source_text)
            time.sleep(API_DELAY)

        # Translate IS -> EN
        print(f"    Translating IS->EN...")
        prompt = f"Caption: {name}\n\nText:\n{source_text}"
        response = call_claude(
            SYSTEM_IS_TO_EN.format(max_chars=MAX_CHARS),
            prompt,
        )
        en_caption, en_text = parse_translation(response)
        item["story_eng"] = en_text
        item["name_eng"] = en_caption if en_caption else name
        time.sleep(API_DELAY)

    else:
        # Both present or neither — ensure name_eng exists
        if not name_eng:
            item["name_eng"] = name

    return item


# ---------------------------------------------------------------------------
# Resumable processing
# ---------------------------------------------------------------------------

def load_progress():
    """Load progress file if it exists."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress):
    """Save progress to file."""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def main():
    print("=== wiki_kringum.json Post-Processor ===\n")

    # Load input
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data["items"]
    print(f"Loaded {len(items)} items\n")

    # Load progress (maps item id -> processed item dict)
    progress = load_progress()
    print(f"Resuming: {len(progress)} items already processed\n")

    # Step 1: Year caption restructuring (all items, no API)
    print("--- Step 1: Year caption restructuring ---")
    year_count = 0
    for item in items:
        new_name, changed = restructure_year_caption(item["name"])
        if changed:
            print(f"  \"{item['name']}\" -> \"{new_name}\"")
            item["name"] = new_name
            year_count += 1
    print(f"  Restructured {year_count} captions\n")

    # Steps 2 & 3: Summarize + Translate
    print("--- Steps 2 & 3: Summarize + Translate ---")
    total = len(items)
    processed = 0
    skipped = 0
    errors = 0

    for i, item in enumerate(items):
        item_id = item["id"]

        # Check if already processed
        if item_id in progress:
            # Restore processed data
            items[i] = progress[item_id]
            skipped += 1
            continue

        lang = item.get("lang", "")
        has_both = bool(item.get("story")) and bool(item.get("story_eng"))

        if has_both:
            # Ensure name_eng exists, then just handle summarization
            if not item.get("name_eng"):
                item["name_eng"] = item["name"]

            # Check if either text needs summarization
            if len(item.get("story", "")) > MAX_CHARS:
                print(f"  [{i+1}/{total}] {item_id}: Summarizing IS...")
                try:
                    item["story"] = summarize_text(item["story"])
                    time.sleep(API_DELAY)
                except Exception as e:
                    print(f"    ERROR: {e}")
                    errors += 1

            if len(item.get("story_eng", "")) > MAX_CHARS:
                print(f"  [{i+1}/{total}] {item_id}: Summarizing EN...")
                try:
                    item["story_eng"] = summarize_text(item["story_eng"])
                    time.sleep(API_DELAY)
                except Exception as e:
                    print(f"    ERROR: {e}")
                    errors += 1

            progress[item_id] = item
            save_progress(progress)
            processed += 1
            continue

        print(f"  [{i+1}/{total}] {item_id}: {item['name']} (lang={lang})")

        try:
            items[i] = process_item(item)
            progress[item_id] = items[i]
            save_progress(progress)
            processed += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            errors += 1
            # Save what we have so far even on error
            progress[item_id] = item
            save_progress(progress)

    print(f"\n  Processed: {processed}, Skipped (resumed): {skipped}, Errors: {errors}")

    # Apply year restructuring to name_eng as well (for items that got translated)
    print("\n--- Applying year restructuring to name_eng ---")
    year_eng_count = 0
    for item in items:
        if item.get("name_eng"):
            new_name, changed = restructure_year_caption(item["name_eng"])
            if changed:
                item["name_eng"] = new_name
                year_eng_count += 1
    print(f"  Restructured {year_eng_count} English captions")

    # Update char_count fields
    for item in items:
        is_len = len(item.get("story", ""))
        en_len = len(item.get("story_eng", ""))
        item["char_count"] = max(is_len, en_len)

    # Write output
    data["items"] = items
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {OUTPUT_FILE}")

    # Summary
    both = sum(1 for i in items if i.get("story") and i.get("story_eng"))
    over = sum(1 for i in items if len(i.get("story", "")) > MAX_CHARS or len(i.get("story_eng", "")) > MAX_CHARS)
    has_name_eng = sum(1 for i in items if i.get("name_eng"))
    print(f"\n{'='*40}")
    print(f"SUMMARY")
    print(f"{'='*40}")
    print(f"Total items:        {len(items)}")
    print(f"Both IS+EN text:    {both}")
    print(f"Over {MAX_CHARS} chars:     {over}")
    print(f"Have name_eng:      {has_name_eng}")


if __name__ == "__main__":
    main()
