#!/usr/bin/env python3
"""
Enrich nat_sogustadir.json with coordinates from the English nat.is site.

The Icelandic site (is.nat.is) does not embed per-item coordinates, but the
sister English site (nat.is) injects them inline as
    latfrom: '64.411022', lngfrom: '-21.681961'
in a script block. This script:

1. Dumps every English-site post slug via the WP REST API.
2. For each item in nat_sogustadir.json, finds the matching English slug
   (direct → strip suffix → fuzzy ≥ 0.85).
3. Fetches the English page and extracts the lat/lng pair.
4. Writes the coordinates back into nat_sogustadir.json's `coords` field.

Items that already have coords are not re-fetched.
"""

import json
import os
import re
import sys
import time
import unicodedata
from difflib import get_close_matches

import requests

INPUT_JSON = os.path.join(os.path.dirname(__file__), "nat_sogustadir.json")
EN_POSTS_CACHE = os.path.join(os.path.dirname(__file__), ".nat_en_posts.json")
EN_REST = "https://nat.is/wp-json/wp/v2/posts"
EN_PAGE = "https://nat.is/{slug}/"

REQUEST_DELAY = 0.25
FUZZY_SLUG_CUTOFF = 0.85
COORD_RE = re.compile(
    r"latfrom:\s*'(-?\d+\.\d+)'\s*,\s*lngfrom:\s*'(-?\d+\.\d+)'"
)

session = requests.Session()
session.headers.update({"User-Agent": "KringumDB-NatScraper/1.0"})


# ---------------------------------------------------------------------------
# English post slug index
# ---------------------------------------------------------------------------

def fetch_all_en_posts() -> list[dict]:
    """Page through the English nat.is REST API and return [{id, slug, title}]."""
    print("Dumping English nat.is post slugs ...")
    out = []
    for page in range(1, 100):
        try:
            r = session.get(EN_REST, params={
                "per_page": 100,
                "page": page,
                "_fields": "id,slug,title",
            }, timeout=60)
        except Exception as e:
            print(f"  page {page} error: {e}", file=sys.stderr)
            break
        if r.status_code != 200:
            break
        chunk = r.json()
        if not chunk:
            break
        out.extend(chunk)
        print(f"  page {page} → {len(chunk)} (total {len(out)})")
        time.sleep(REQUEST_DELAY)
    return out


def load_en_posts() -> list[dict]:
    if os.path.exists(EN_POSTS_CACHE):
        try:
            with open(EN_POSTS_CACHE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    posts = fetch_all_en_posts()
    with open(EN_POSTS_CACHE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False)
    return posts


# ---------------------------------------------------------------------------
# Slug matching
# ---------------------------------------------------------------------------

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def find_en_slug(is_slug: str, en_slugs: set[str], en_list: list[str]) -> str | None:
    """Try direct → strip-suffix → fuzzy. Return matching English slug or None."""
    if is_slug in en_slugs:
        return is_slug
    # Strip trailing dash-segments (e.g. "glymur-hvalfirdi" → "glymur")
    parts = is_slug.split("-")
    for i in range(len(parts) - 1, 0, -1):
        c = "-".join(parts[:i])
        if c in en_slugs:
            return c
    # Fuzzy fallback
    cands = get_close_matches(is_slug, en_list, n=1, cutoff=FUZZY_SLUG_CUTOFF)
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# Coord extraction
# ---------------------------------------------------------------------------

def fetch_coords(en_slug: str) -> tuple[float, float] | None:
    url = EN_PAGE.format(slug=en_slug)
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        return None
    m = COORD_RE.search(r.text)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    en_posts = load_en_posts()
    en_slugs = {p["slug"] for p in en_posts}
    en_list = sorted(en_slugs)
    print(f"  {len(en_slugs)} English post slugs indexed\n")

    with open(INPUT_JSON, encoding="utf-8") as f:
        items = json.load(f)
    print(f"Loaded {len(items)} items from {INPUT_JSON}")

    already = sum(1 for it in items if it.get("coords"))
    print(f"  {already} already have coords\n")

    enriched = 0
    no_match = 0
    no_coords = 0

    for i, it in enumerate(items, 1):
        if it.get("coords"):
            continue
        is_slug = it["url"].rstrip("/").split("/")[-1]
        en_slug = find_en_slug(is_slug, en_slugs, en_list)
        if not en_slug:
            no_match += 1
            continue

        time.sleep(REQUEST_DELAY)
        coords = fetch_coords(en_slug)
        if not coords:
            no_coords += 1
            print(f"  [{i}/{len(items)}] {it['name']:40} → en:{en_slug} (no coords)")
            continue

        lat, lng = coords
        it["coords"] = {"lat": lat, "lng": lng, "source": f"nat.is/{en_slug}"}
        enriched += 1
        if enriched % 25 == 0 or enriched <= 10:
            print(f"  [{i}/{len(items)}] {it['name']:40} → ({lat:.5f}, {lng:.5f})")

    with open(INPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    total_with_coords = sum(1 for it in items if it.get("coords"))
    print(f"\n=== Summary ===")
    print(f"  newly enriched:        {enriched}")
    print(f"  no English slug match: {no_match}")
    print(f"  matched but no coords: {no_coords}")
    print(f"  total with coords now: {total_with_coords}/{len(items)}")
    print(f"  written to {INPUT_JSON}")


if __name__ == "__main__":
    main()
