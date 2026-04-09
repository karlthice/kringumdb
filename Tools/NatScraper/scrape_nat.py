#!/usr/bin/env python3
"""
Scraper for nat.is "sögustaðir" (historic places) listing pages.

For each of the 8 regional listing pages, walks the headings to find item
links, follows each link to extract the main descriptive text, and writes
nat_sogustadir.json with: name, url, area (region), location (sub-area
heading from the listing page), text (descriptive body), and coords
(lat/lng when available from the WPGMZA marker API).
"""

import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REGIONS = [
    ("Vesturland", "https://is.nat.is/sogustadir-vesturlandi/"),
    ("Vestfirðir", "https://is.nat.is/sogustadir-vestfjordum/"),
    ("Strandir",   "https://is.nat.is/sogustadir-strondum/"),
    ("Norðurland", "https://is.nat.is/sogustadir-nordurlandi/"),
    ("Austurland", "https://is.nat.is/sogustadir-austurlandi/"),
    ("Suðurland",  "https://is.nat.is/sogustadir-sudurlandi/"),
    ("Reykjanes",  "https://is.nat.is/sogustadir-reykjanesi/"),
    ("Hálendið",   "https://is.nat.is/sogustadir-halendinu/"),
]

MARKERS_API = "https://is.nat.is/wp-json/wpgmza/v1/markers"
BODY_SELECTOR = ".elementor-widget-theme-post-content"
REQUEST_DELAY = 0.3
OUTPUT_FILE = "nat_sogustadir.json"

# Headings that recur on every listing page as page chrome — never an item or sub-area
HEADING_BLACKLIST = {
    "Íslenski ferðavefurinn",
    "Landshlutar Ferðavísir",
    "Landshlutar Ferðavísir\u200b",
    "Veldu landshluta",
    "Afþreying",
    "Um okkur",
    "Ýmsir staðir tengdir sögu landshlutans",
    "Allar ábendingar eru velkomnar. Reynum að hafa staðreyndir eins réttar og mögulegt  er.",
    "Allar ábendingar eru velkomnar. Reynum að hafa staðreyndir eins réttar og mögulegt er.",
}

session = requests.Session()
session.headers.update({"User-Agent": "KringumDB-NatScraper/1.0"})


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch(url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
            return None
    return None


def slug_of(url: str) -> str:
    """Normalised slug for matching marker links to item links."""
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1].lower()


# ---------------------------------------------------------------------------
# Marker lookup (optional coordinates)
# ---------------------------------------------------------------------------

def load_markers() -> dict[str, dict]:
    """Fetch all WPGMZA markers and index them by URL slug."""
    print("Fetching marker coordinates from WPGMZA API ...")
    html = fetch(MARKERS_API)
    if not html:
        return {}
    try:
        data = json.loads(html)
    except json.JSONDecodeError as e:
        print(f"  ERROR parsing markers JSON: {e}", file=sys.stderr)
        return {}

    by_slug: dict[str, dict] = {}
    for m in data:
        link = m.get("link") or ""
        if not link:
            continue
        slug = slug_of(link)
        if not slug:
            continue
        try:
            lat = float(m["lat"])
            lng = float(m["lng"])
        except (KeyError, ValueError, TypeError):
            continue
        by_slug[slug] = {"lat": lat, "lng": lng}
    print(f"  loaded {len(by_slug)} markers with coordinates")
    return by_slug


# ---------------------------------------------------------------------------
# Listing page parsing
# ---------------------------------------------------------------------------

def is_item_link(href: str) -> bool:
    """An item link points to an is.nat.is article (single-segment slug)."""
    if not href:
        return False
    p = urlparse(href)
    if "is.nat.is" not in p.netloc:
        return False
    parts = [seg for seg in p.path.split("/") if seg]
    if len(parts) != 1:
        return False
    # Skip listing pages themselves
    if parts[0].startswith("sogustadir-"):
        return False
    return True


def detect_item_level(headings) -> int | None:
    """Return the heading level (2..6) that contains the most item links."""
    counts: dict[int, int] = {}
    for h in headings:
        a = h.find("a")
        if a and is_item_link(a.get("href", "")):
            level = int(h.name[1])
            counts[level] = counts.get(level, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def parse_listing(html: str, region: str) -> list[dict]:
    """Walk headings in document order, return list of {name, url, location}."""
    soup = BeautifulSoup(html, "html.parser")
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])

    item_level = detect_item_level(headings)
    if item_level is None:
        print(f"  WARN: no item headings detected for {region}", file=sys.stderr)
        return []

    items: list[dict] = []
    current_location: str | None = None

    for h in headings:
        level = int(h.name[1])
        a = h.find("a")
        text = h.get_text(strip=True)

        if a and is_item_link(a.get("href", "")):
            # An item heading
            items.append({
                "name": text,
                "url": a["href"],
                "location": current_location or region,
            })
        else:
            # Unlinked heading — candidate sub-area marker (must be above item level)
            if (
                level < item_level
                and text
                and text not in HEADING_BLACKLIST
                and not text.startswith("Sögustaðir")
            ):
                current_location = text

    return items


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------

def parse_detail(html: str) -> str:
    """Extract the main descriptive text from a detail page."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(BODY_SELECTOR)
    if not el:
        return ""
    text = el.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_existing(path: str) -> dict[str, dict]:
    """Load existing output file (if any) keyed by URL for resume support."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {r["url"]: r for r in data}
    except Exception as e:
        print(f"  WARN: failed to load {path}: {e}", file=sys.stderr)
        return {}


def main() -> None:
    resume = "--resume" in sys.argv
    markers = load_markers()
    existing = load_existing(OUTPUT_FILE) if resume else {}
    if resume:
        print(f"Resume mode: {len(existing)} items already in {OUTPUT_FILE}")

    all_items: dict[str, dict] = dict(existing)  # url -> record

    for region, listing_url in REGIONS:
        print(f"\n=== {region} ===")
        html = fetch(listing_url)
        if not html:
            continue
        items = parse_listing(html, region)
        print(f"  found {len(items)} items on listing page")

        for i, item in enumerate(items, 1):
            url = item["url"]
            existing_rec = all_items.get(url)
            # Skip if we already have a complete record for this URL
            if existing_rec and existing_rec.get("text"):
                continue

            print(f"  [{i}/{len(items)}] {item['name']}")
            time.sleep(REQUEST_DELAY)
            detail_html = fetch(url)
            text = parse_detail(detail_html) if detail_html else ""

            record = {
                "name": item["name"],
                "url": url,
                "area": region,
                "location": item["location"],
                "text": text,
                "coords": markers.get(slug_of(url)),
            }
            all_items[url] = record

    out_path = OUTPUT_FILE
    out_list = list(all_items.values())
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_list, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(out_list)} items to {out_path}")
    with_coords = sum(1 for r in out_list if r["coords"])
    with_text = sum(1 for r in out_list if r["text"])
    print(f"  {with_coords} items have coordinates from the marker API")
    print(f"  {with_text} items have body text ({len(out_list) - with_text} empty)")


if __name__ == "__main__":
    main()
