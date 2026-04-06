#!/usr/bin/env python3
"""
Sweep Icelandic + English Wikipedia for all geotagged articles in Iceland.
Only keeps articles with real text content.
Deduplicates against existing Kringum DB items.
Outputs kringum-compatible JSON.
"""

import json
import math
import re
import time
import sys

import requests

WIKI_APIS = {
    "is": "https://is.wikipedia.org/w/api.php",
    "en": "https://en.wikipedia.org/w/api.php",
}
HEADERS = {"User-Agent": "KringumDB/1.0 (kringum@example.com)"}

# Iceland bounding box
LAT_MIN, LAT_MAX = 63.0, 67.0
LON_MIN, LON_MAX = -25.0, -13.0

# Grid sweep parameters
RADIUS = 10000  # 10km per query (API max)
STEP_KM = 15    # grid spacing in km (some overlap at 10km radius)
REQUEST_DELAY = 0.2
EXTRACT_BATCH = 20  # fetch extracts in batches of 20 page IDs


session = requests.Session()
session.headers.update(HEADERS)


# ---------------------------------------------------------------------------
# Grid sweep
# ---------------------------------------------------------------------------

def km_to_deg_lat(km):
    return km / 111.0

def km_to_deg_lon(km, lat):
    return km / (111.0 * math.cos(math.radians(lat)))


def generate_grid():
    """Generate grid points covering Iceland."""
    points = []
    lat = LAT_MIN
    while lat <= LAT_MAX:
        lon = LON_MIN
        while lon <= LON_MAX:
            points.append((lat, lon))
            lon += km_to_deg_lon(STEP_KM, lat)
        lat += km_to_deg_lat(STEP_KM)
    return points


def geosearch(lat, lon, lang="is"):
    """Query Wikipedia GeoSearch API for articles near a point."""
    api = WIKI_APIS[lang]
    try:
        r = session.get(api, params={
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lon}",
            "gsradius": RADIUS,
            "gslimit": 500,
            "format": "json",
        }, timeout=30)
        data = r.json()
        return data.get("query", {}).get("geosearch", [])
    except Exception as e:
        print(f"  ERROR geosearch at {lat},{lon}: {e}", file=sys.stderr)
        return []


def wikitext_to_plain(wikitext):
    """Convert wikitext markup to plain text."""
    if not wikitext:
        return ""
    text = wikitext
    # Remove templates {{...}} (handle nested by repeating)
    for _ in range(5):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    # Remove files/images [[File:...|...]]
    text = re.sub(r"\[\[(?:File|Mynd|Image):[^\]]*\]\]", "", text, flags=re.IGNORECASE)
    # Remove categories [[Flokkur:...]]
    text = re.sub(r"\[\[(?:Flokkur|Category):[^\]]*\]\]", "", text, flags=re.IGNORECASE)
    # Convert links [[target|display]] → display, [[target]] → target
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    # Remove external links [url text] → text
    text = re.sub(r"\[https?://[^\s\]]+ ([^\]]*)\]", r"\1", text)
    text = re.sub(r"\[https?://[^\]]*\]", "", text)
    # Remove bold/italic markup
    text = re.sub(r"'{2,}", "", text)
    # Remove HTML tags
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^/]*/?>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Remove section headers
    text = re.sub(r"={2,}\s*[^=\n]+\s*={2,}", "\n\n", text)
    # Remove magic words / parser functions
    text = re.sub(r"__[A-Z]+__", "", text)
    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = text.split("\n\n")
    cleaned = []
    for para in paragraphs:
        line = " ".join(para.split())
        if line and len(line) > 20:
            cleaned.append(line)
    return "\n\n".join(cleaned)


def fetch_extracts(pageids, lang="is"):
    """Fetch article content via revisions API and convert to plain text."""
    if not pageids:
        return {}
    api = WIKI_APIS[lang]
    try:
        r = session.get(api, params={
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "pageids": "|".join(str(p) for p in pageids),
            "format": "json",
        }, timeout=30)
        pages = r.json().get("query", {}).get("pages", {})
        result = {}
        for pid_str, page in pages.items():
            pid = int(pid_str)
            revisions = page.get("revisions", [])
            if revisions:
                wikitext = revisions[0].get("slots", {}).get("main", {}).get("*", "")
                # Skip redirects
                if wikitext.strip().upper().startswith("#REDIRECT") or \
                   wikitext.strip().upper().startswith("#TILVÍSUN"):
                    result[pid] = ""
                else:
                    result[pid] = wikitext_to_plain(wikitext)
            else:
                result[pid] = ""
        return result
    except Exception as e:
        print(f"  ERROR fetching extracts: {e}", file=sys.stderr)
        return {}


def sweep_iceland(lang="is"):
    """Sweep Iceland with grid and collect all geotagged articles."""
    grid = generate_grid()
    print(f"[{lang}] Grid: {len(grid)} points to sweep")

    articles = {}

    for i, (lat, lon) in enumerate(grid):
        results = geosearch(lat, lon, lang)
        for item in results:
            pid = item["pageid"]
            if pid not in articles:
                articles[pid] = {
                    "pageid": pid,
                    "title": item["title"],
                    "lat": item["lat"],
                    "lon": item["lon"],
                    "lang": lang,
                }
        if (i + 1) % 50 == 0:
            print(f"  [{lang}] {i + 1}/{len(grid)} grid points, {len(articles)} unique articles")
        time.sleep(REQUEST_DELAY)

    print(f"[{lang}] Sweep complete: {len(articles)} unique geotagged articles")
    return articles


def fetch_all_extracts(articles, lang="is"):
    """Fetch extracts for all articles in batches."""
    # Build map: composite_key -> numeric_pageid
    key_map = {}
    for key, art in articles.items():
        if art.get("lang") == lang:
            key_map[art["pageid"]] = key  # numeric pageid -> composite key

    numeric_pids = list(key_map.keys())
    print(f"[{lang}] Fetching extracts for {len(numeric_pids)} articles...")
    with_text = 0

    for i in range(0, len(numeric_pids), EXTRACT_BATCH):
        batch = numeric_pids[i:i + EXTRACT_BATCH]
        extracts = fetch_extracts(batch, lang)
        for pid, text in extracts.items():
            composite_key = key_map.get(pid)
            if composite_key and composite_key in articles:
                articles[composite_key]["extract"] = text
                if text:
                    with_text += 1
        if (i + EXTRACT_BATCH) % 200 == 0:
            print(f"  [{lang}] {min(i + EXTRACT_BATCH, len(numeric_pids))}/{len(numeric_pids)} extracts fetched")
        time.sleep(REQUEST_DELAY)

    print(f"[{lang}] Extracts complete: {with_text}/{len(numeric_pids)} have text")
    return articles


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def load_existing():
    """Load existing Kringum DB items for dedup."""
    with open("existing_items.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    existing_names = set()
    existing_coords = []

    for item in items:
        name = item["name"]
        # Normalize: strip suffixes like ", þjóðsaga" etc
        clean = re.sub(r",\s*[-]?þjóðsaga\s*$", "", name)
        clean = re.sub(r",\s*\d{4}\s*$", "", clean)  # year suffixes
        clean = clean.strip().lower()
        if clean:
            existing_names.add(clean)

        # Parse GPS
        gps = item["gps"].replace(" ", "")
        if "," in gps:
            try:
                lat, lon = float(gps.split(",")[0]), float(gps.split(",")[1])
                if 63 <= lat <= 67:
                    existing_coords.append((lat, lon, name.lower()))
            except ValueError:
                pass

    return existing_names, existing_coords


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_duplicate(title, lat, lon, existing_names, existing_coords):
    """Check if a Wikipedia article duplicates an existing Kringum item."""
    title_lower = title.strip().lower()

    # Exact name match
    if title_lower in existing_names:
        return True

    # Check if any existing item has the same name AND is within 5km
    for elat, elon, ename in existing_coords:
        dist = haversine(lat, lon, elat, elon)
        if dist < 500:
            # Very close — check partial name overlap
            if title_lower in ename or ename in title_lower:
                return True
            # Same first word and very close
            tw = title_lower.split()[0] if title_lower else ""
            ew = ename.split()[0] if ename else ""
            if tw and tw == ew and dist < 200:
                return True

    return False


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def clean_extract(text):
    """Clean Wikipedia extract text."""
    if not text:
        return ""
    # Remove section headers like "== Heading =="
    text = re.sub(r"={2,}\s*[^=]+\s*={2,}", "", text)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_output(articles, existing_names, existing_coords):
    """Build Kringum-compatible output, filtering duplicates and empty articles."""
    items = []
    skipped_no_text = 0
    skipped_dup = 0
    skipped_short = 0
    seen_coords = set()  # avoid near-duplicate en/is articles for same place

    for pid, art in sorted(articles.items(), key=lambda x: (x[1].get("lang", ""), x[1]["title"])):
        text = clean_extract(art.get("extract", ""))
        if not text:
            skipped_no_text += 1
            continue
        if len(text) < 100:
            skipped_short += 1
            continue

        if is_duplicate(art["title"], art["lat"], art["lon"],
                        existing_names, existing_coords):
            skipped_dup += 1
            continue

        # Skip if we already have an article very close (prefer IS over EN)
        coord_key = f"{art['lat']:.3f},{art['lon']:.3f}"
        if coord_key in seen_coords:
            skipped_dup += 1
            continue
        seen_coords.add(coord_key)

        lang = art.get("lang", "is")
        wiki_base = "is" if lang == "is" else "en"
        wiki_url = f"https://{wiki_base}.wikipedia.org/wiki/{art['title'].replace(' ', '_')}"

        item = {
            "id": f"{lang}_{pid}",
            "name": art["title"],
            "gps": f"{art['lat']:.6f}, {art['lon']:.6f}",
            "tag": "Saga",
            "story": text if lang == "is" else "",
            "story_eng": text if lang == "en" else "",
            "ref": wiki_url,
            "source": f"wikipedia_{lang}",
            "lang": lang,
            "char_count": len(text),
        }
        items.append(item)

    print(f"\nFiltering results:")
    print(f"  No text: {skipped_no_text}")
    print(f"  Too short (<100 chars): {skipped_short}")
    print(f"  Duplicate: {skipped_dup}")
    print(f"  New items: {len(items)}")
    print(f"    IS: {sum(1 for i in items if i['lang'] == 'is')}")
    print(f"    EN: {sum(1 for i in items if i['lang'] == 'en')}")

    return {
        "metadata": {
            "source": "is.wikipedia.org + en.wikipedia.org geosearch",
            "scraped_at": time.strftime("%Y-%m-%d"),
            "total_articles_found": len(articles),
            "articles_with_text": sum(1 for a in articles.values() if a.get("extract")),
            "duplicates_skipped": skipped_dup,
            "new_items": len(items),
        },
        "items": items,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import os
    print("=== Wikipedia Geosearch Scraper (IS + EN) ===\n")

    raw_path = "wiki_raw.json"

    if "--reuse-raw" in sys.argv and os.path.exists(raw_path):
        print(f"Loading existing raw data from {raw_path}...")
        with open(raw_path, "r", encoding="utf-8") as f:
            all_articles = json.load(f)
        # Re-fetch extracts (they were broken before)
        fetch_all_extracts(all_articles, "is")
        fetch_all_extracts(all_articles, "en")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(all_articles, f, ensure_ascii=False, indent=2)
    else:
        # Step 1: Sweep both wikis
        articles_is = sweep_iceland("is")
        articles_en = sweep_iceland("en")

        # Merge — prefix pageids to avoid collision
        all_articles = {}
        for pid, art in articles_is.items():
            all_articles[f"is_{pid}"] = art
        for pid, art in articles_en.items():
            all_articles[f"en_{pid}"] = art

        # Step 2: Fetch extracts for both
        fetch_all_extracts(all_articles, "is")
        fetch_all_extracts(all_articles, "en")

        # Save raw
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"Saved raw data to {raw_path}")

    # Step 3: Deduplicate and build output
    print("\nLoading existing Kringum items for dedup...")
    existing_names, existing_coords = load_existing()
    print(f"  {len(existing_names)} unique names, {len(existing_coords)} GPS points")

    output = build_output(all_articles, existing_names, existing_coords)

    with open("wiki_kringum.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to wiki_kringum.json")

    # Summary
    meta = output["metadata"]
    print(f"\n{'=' * 40}")
    print(f"SUMMARY")
    print(f"{'=' * 40}")
    print(f"Grid sweep articles:    {meta['total_articles_found']}")
    print(f"With text:              {meta['articles_with_text']}")
    print(f"Duplicates skipped:     {meta['duplicates_skipped']}")
    print(f"New items for Kringum:  {meta['new_items']}")


if __name__ == "__main__":
    main()
