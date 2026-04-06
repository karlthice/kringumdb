#!/usr/bin/env python3
"""
Scraper & Geocoder for Icelandic folk tales from snerpa.is
Outputs kringum_thjodsogor.json for the Kringum Iceland app.
"""

import json
import re
import time
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from iceaddr import placename_lookup

BASE_URL = "https://www.snerpa.is/net/thjod/"
MAIN_PAGE = BASE_URL + "thjod.htm"
REQUEST_DELAY = 0.5

# Known category pages and their display names
# We'll discover these from the main page, but keep a name map
CATEGORY_NAMES = {
    "alfa.htm": "Álfar og huldufólk",
    "draug.htm": "Draugar",
    "galdr.htm": "Galdrar",
    "kimni.htm": "Kímnisögur",
    "troll.htm": "Tröll",
    "efra.htm": "Úr efra og neðra - Helgisögur",
    "sjo.htm": "Úr sjó og vötnum",
    "util.htm": "Útilegumenn",
    "vidb.htm": "Viðburðasögur",
    "ymisl.htm": "Ýmislegt",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update({"User-Agent": "KringumDB-Scraper/1.0"})


def fetch(url: str) -> str | None:
    """Fetch a URL and return decoded UTF-8 text, or None on failure."""
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return r.content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Part 1: Scrape stories
# ---------------------------------------------------------------------------

def get_category_urls() -> list[dict]:
    """Get all category page URLs from the main page."""
    html = fetch(MAIN_PAGE)
    if not html:
        sys.exit("Failed to fetch main page")

    soup = BeautifulSoup(html, "html.parser")
    categories = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        filename = href.lstrip("./")
        if filename in CATEGORY_NAMES:
            categories.append({
                "url": urljoin(MAIN_PAGE, href),
                "filename": filename,
                "name": CATEGORY_NAMES[filename],
            })
    return categories


def get_story_urls(category_url: str) -> list[str]:
    """Get all story page URLs from a category page."""
    html = fetch(category_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Skip navigation links (back to index, main page, etc.)
        if "../" in href or href in ("./thjod.htm",):
            continue
        # Story links are relative .htm files
        if href.endswith(".htm"):
            full_url = urljoin(category_url, href)
            if full_url not in urls:
                urls.append(full_url)
    return urls


def extract_story(html: str, url: str, category: str) -> dict | None:
    """Extract story data from a story page's HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Title from <title> tag
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        return None

    # Story text from blockquote(s)
    blockquotes = soup.find_all("blockquote")
    container = blockquotes[-1] if blockquotes else soup.find("body")
    if not container:
        return None

    # Mark <p> tags as paragraph breaks before extracting text
    for p in container.find_all("p"):
        p.insert_before("\n\n")
    for br in container.find_all("br"):
        br.replace_with("\n\n")
    text = container.get_text()

    # Clean up text
    text = clean_text(text)
    if not text:
        return None

    # Source attribution - check <h6>, or text after blockquote
    source = ""
    h6 = soup.find("h6")
    if h6:
        source = h6.get_text(strip=True).strip("()")
    else:
        # Look for text in parentheses after blockquote
        full_text = soup.get_text()
        source_match = re.search(
            r"\(([^)]*(?:Jón|Árnason|Þjóðsagnasafn|safn|Maurer)[^)]*)\)",
            full_text,
        )
        if source_match:
            source = source_match.group(1)

    # ID from filename
    filename = url.rstrip("/").split("/")[-1]
    story_id = filename.replace(".htm", "")

    return {
        "id": story_id,
        "title": title,
        "category": category,
        "url": url,
        "text": text,
        "source": source,
        "char_count": len(text),
    }


def clean_text(text: str) -> str:
    """Clean story text: join soft line wraps, keep real paragraph breaks."""
    # Normalize \r\r\n (used by some snerpa pages) to single newline
    text = text.replace("\r\r\n", "\n")
    # Normalize remaining line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Real paragraph breaks are marked by our inserted \n\n (from <p> tags)
    # or by genuinely blank lines. Collapse 3+ newlines to exactly 2.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Split into paragraphs (separated by blank line), then join soft wraps
    paragraphs = text.split("\n\n")
    cleaned = []
    for para in paragraphs:
        line = " ".join(para.split())
        if line:
            cleaned.append(line)
    return "\n\n".join(cleaned)


def scrape_all() -> list[dict]:
    """Scrape all stories from snerpa.is."""
    print("=== PART 1: Scraping snerpa.is ===")
    print()

    categories = get_category_urls()
    print(f"Found {len(categories)} categories:")
    for c in categories:
        print(f"  - {c['name']}")
    print()

    all_stories = []
    seen_urls = set()

    for cat in categories:
        print(f"Scraping category: {cat['name']}...")
        time.sleep(REQUEST_DELAY)

        story_urls = get_story_urls(cat["url"])
        print(f"  Found {len(story_urls)} story links")

        for url in story_urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            time.sleep(REQUEST_DELAY)
            html = fetch(url)
            if not html:
                continue

            story = extract_story(html, url, cat["name"])
            if story:
                all_stories.append(story)
                # Progress indicator
                if len(all_stories) % 50 == 0:
                    print(f"  ... {len(all_stories)} stories scraped so far")

        print(f"  Total unique stories so far: {len(all_stories)}")
        print()

    print(f"Scraping complete: {len(all_stories)} stories total")
    return all_stories


# ---------------------------------------------------------------------------
# Part 2: Geocoding
# ---------------------------------------------------------------------------

# Icelandic prepositions that precede place names
# Only captures a single capitalized word (optional hyphenated compound)
PREP_PATTERN = re.compile(
    r"(?:^|[\s,;.(])(?:á|í|frá|við|hjá|undir|yfir|til|úr|að)\s+"
    r"([A-ZÁÐÉÍÓÚÝÞÆÖ][a-záðéíóúýþæö]+(?:-[A-ZÁÐÉÍÓÚÝÞÆÖ]?[a-záðéíóúýþæö]+)?)",
    re.UNICODE,
)

# Place name suffixes common in Icelandic
PLACE_SUFFIXES = re.compile(
    r"[A-ZÁÐÉÍÓÚÝÞÆÖ][a-záðéíóúýþæö]*"
    r"(?:staðir|staður|nes|fjörður|firði|dalur|dal|fell|felli|"
    r"hólar|hólum|vík|ey|eyjar|vatn|vatni|á|ás|bær|bæ|bæjar|"
    r"vellir|völlum|tunga|tungu|borg|garður|garði|höfn|stapi|"
    r"hlíð|hlíðar|bakki|bakka|múli|múla|strönd|hraun|hrauni|"
    r"sandur|sandi|jökull|jökli|fjall|fjalli|lón|lóni|ós|ósi)",
    re.UNICODE,
)

# Pattern for "bóndi á X", "prestur á X", etc.
ROLE_PLACE = re.compile(
    r"(?:prestur|bóndi|sýslumaður|biskup|djákni|séra)\s+"
    r"(?:á|í|frá|við|hjá)\s+"
    r"([A-ZÁÐÉÍÓÚÝÞÆÖ][a-záðéíóúýþæö]+(?:-[a-záðéíóúýþæö]+)?)",
    re.UNICODE,
)

# Icelandic declension transformations for place name normalization
# Each entry: (ending_to_match, replacement) - ordered longest first
DECLENSION_TRANSFORMS = [
    # Fjörður declensions: firði (dat), fjarðar (gen), fjörð (acc)
    ("firði", "fjörður"),
    ("fjarðar", "fjörður"),
    ("fjörð", "fjörður"),
    # Dalur declensions
    ("dalnum", "dalur"),
    ("dalinn", "dalur"),
    ("dals", "dalur"),
    ("dal", "dalur"),
    # Vellir declensions: völlum (dat pl) → vellir
    ("völlum", "vellir"),
    ("valla", "vellir"),
    # Hólar/Staðir plurals
    ("hólum", "hólar"),
    ("stöðum", "staðir"),
    ("staða", "staðir"),
    # Bær declensions
    ("bæ", "bær"),
    ("bæjar", "bær"),
    # Fell declensions
    ("felli", "fell"),
    # Nes declensions
    ("nesjum", "nes"),
    # Öræfum → Öræfi
    ("æfum", "æfi"),
    # Höfða → Höfði (genitive/accusative)
    ("ða", "ði"),
    # Síðu → Síða
    ("íðu", "íða"),
    # Sýsla compounds (just strip for lookup)
    ("sýslu", ""),
    ("sýsla", ""),
    # -landi → -land
    ("landi", "land"),
    ("lands", "land"),
    # Common dative/genitive endings with nominative replacement
    ("inum", ""),     # Dative masculine with article
    ("inu", ""),      # Dative neuter with article
    ("nni", ""),      # Dative feminine with article
    ("anna", ""),     # Genitive plural
    ("unum", ""),
    ("um", "ar"),     # Dative plural → try -ar (Hólum → Hólar)
    ("i", "ur"),      # Dative → nominative masculine (Hvammi → Hvammur)
    ("i", ""),        # Dative: Reykholti → Reykholt
    ("ar", ""),       # Genitive feminine
    ("um", ""),       # Dative plural fallback
    ("s", ""),        # Genitive
    ("ur", ""),       # Nominative masculine
    ("a", ""),        # Various oblique
]

# Minimum length for place name candidates (skip short fragments)
MIN_PLACE_NAME_LENGTH = 4

# Very short fragments that are clearly not place names
# (only filter things that would never be in iceaddr)
NOT_PLACE_NAMES = {
    "herra", "húsfreyja", "húsfrey", "séra",
}


def extract_place_candidates(title: str, text: str) -> list[dict]:
    """Extract potential place name candidates from title and text."""
    candidates = []
    seen = set()

    def add_candidate(name: str, found_in: str):
        # Normalize
        name = name.strip().rstrip(".,;:!?")
        if len(name) < MIN_PLACE_NAME_LENGTH or name.lower() in seen:
            return
        if name.lower() in NOT_PLACE_NAMES:
            return
        seen.add(name.lower())
        candidates.append({"name": name, "found_in": found_in})

    # Method A: Title analysis
    for m in PREP_PATTERN.finditer(title):
        add_candidate(m.group(1), "title")

    # Method B: Place name suffixes in title
    for m in PLACE_SUFFIXES.finditer(title):
        add_candidate(m.group(0), "title")

    # Method C: Preposition patterns in text (first 2000 chars for efficiency)
    text_start = text[:2000]
    for m in PREP_PATTERN.finditer(text_start):
        add_candidate(m.group(1), "text")

    # Method D: Role + place patterns
    for m in ROLE_PLACE.finditer(text_start):
        add_candidate(m.group(1), "text")

    # Method E: Place suffixes in text
    for m in PLACE_SUFFIXES.finditer(text_start):
        add_candidate(m.group(0), "text")

    return candidates


# Common irregular dative/genitive forms → nominative
IRREGULAR_FORMS = {
    "jökli": "Jökull",
    "jökul": "Jökull",
    "vestfjörðum": "Vestfirðir",
    "biskupstungum": "Biskupstungur",
    "öræfum": "Öræfi",
}


def lookup_place(name: str) -> dict | None:
    """Try to resolve a place name using iceaddr. Returns location dict or None."""
    def make_result(r, source="iceaddr"):
        return {
            "name": r["nafn"],
            "lat": r["lat_wgs84"],
            "lng": r["long_wgs84"],
            "source": source,
            "iceaddr_id": r["id"],
        }

    def try_lookup(n):
        return placename_lookup(n)

    # Direct lookup
    results = try_lookup(name)
    if results:
        return make_result(results[0])

    # Try irregular forms dictionary
    irregular = IRREGULAR_FORMS.get(name.lower())
    if irregular:
        results = try_lookup(irregular)
        if results:
            return make_result(results[0])

    # Try declension transforms (case-insensitive ending match)
    tried = set()
    name_lower = name.lower()
    for ending, replacement in DECLENSION_TRANSFORMS:
        if name_lower.endswith(ending) and len(name) > len(ending):
            stem = name[: -len(ending)] + replacement
            if stem.lower() in tried:
                continue
            tried.add(stem.lower())
            results = try_lookup(stem)
            if results:
                return make_result(results[0])
            # Chain: try stripping trailing 's' from the stem
            if stem.endswith("s") and len(stem) > 4:
                stem2 = stem[:-1]
                if stem2.lower() not in tried:
                    tried.add(stem2.lower())
                    results = try_lookup(stem2)
                    if results:
                        return make_result(results[0])

    # Try partial match as last resort
    results = placename_lookup(name, partial=True)
    if results and len(results) <= 5:
        r = results[0]
        if r["nafn"].lower().startswith(name[:4].lower()):
            return make_result(r, "iceaddr_partial")

    return None


def is_valid_iceland_coords(lat: float, lng: float) -> bool:
    """Check if coordinates are within Iceland's bounding box."""
    return 63.0 <= lat <= 67.0 and -25.0 <= lng <= -13.0


def geocode_story(story: dict) -> dict:
    """Add location data to a story."""
    candidates = extract_place_candidates(story["title"], story["text"])

    all_locations = []
    unresolved = []

    for cand in candidates:
        loc = lookup_place(cand["name"])
        if loc and is_valid_iceland_coords(loc["lat"], loc["lng"]):
            loc["found_in"] = cand["found_in"]
            # Avoid duplicate locations (same iceaddr_id)
            if not any(l.get("iceaddr_id") == loc["iceaddr_id"] for l in all_locations):
                all_locations.append(loc)
        else:
            unresolved.append(cand["name"])

    # Determine primary location
    primary = None
    # Prefer title matches
    title_locs = [l for l in all_locations if l["found_in"] == "title"]
    if title_locs:
        primary = title_locs[0]
    elif all_locations:
        primary = all_locations[0]

    # Build confidence string
    if primary:
        confidence = "title_match" if primary["found_in"] == "title" else "text_match"
        primary_out = {
            "name": primary["name"],
            "lat": primary["lat"],
            "lng": primary["lng"],
            "source": primary["source"],
            "confidence": confidence,
        }
    else:
        primary_out = None

    # Clean up all_locations output (remove internal fields)
    locations_out = []
    for loc in all_locations:
        locations_out.append({
            "name": loc["name"],
            "lat": loc["lat"],
            "lng": loc["lng"],
            "source": loc["source"],
            "found_in": loc["found_in"],
        })

    story["primary_location"] = primary_out
    story["all_locations"] = locations_out
    story["unresolved_places"] = unresolved
    return story


def geocode_all(stories: list[dict]) -> list[dict]:
    """Geocode all stories."""
    print("=== PART 2: Geocoding with iceaddr ===")
    print()

    geocoded_count = 0
    for i, story in enumerate(stories):
        geocode_story(story)
        if story["primary_location"]:
            geocoded_count += 1
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(stories)} stories geocoded")

    print(f"Geocoding complete: {geocoded_count}/{len(stories)} stories have locations")
    print()
    return stories


# ---------------------------------------------------------------------------
# Part 3: Output
# ---------------------------------------------------------------------------

def build_output(stories: list[dict]) -> dict:
    """Build the final JSON output structure."""
    # Category counts
    cat_counts: dict[str, int] = {}
    geocoded = 0
    unresolved_total = 0

    for s in stories:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
        if s.get("primary_location"):
            geocoded += 1
        else:
            unresolved_total += 1

    return {
        "metadata": {
            "source": "snerpa.is + iceaddr geocoding",
            "scraped_at": time.strftime("%Y-%m-%d"),
            "total_stories": len(stories),
            "geocoded_stories": geocoded,
            "unresolved_stories": unresolved_total,
            "categories": [
                {"name": name, "count": count}
                for name, count in sorted(cat_counts.items())
            ],
        },
        "stories": stories,
    }


def write_unresolved_report(stories: list[dict], path: str):
    """Write a report of stories and place names that couldn't be geocoded."""
    # Collect all unresolved place names
    all_unresolved: dict[str, int] = {}
    unresolved_stories = []

    for s in stories:
        if not s.get("primary_location"):
            unresolved_stories.append(s)
        for name in s.get("unresolved_places", []):
            all_unresolved[name] = all_unresolved.get(name, 0) + 1

    with open(path, "w", encoding="utf-8") as f:
        f.write("UNRESOLVED GEOCODING REPORT\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Stories without location: {len(unresolved_stories)}\n")
        f.write(f"Total unresolved place names: {len(all_unresolved)}\n\n")

        f.write("TOP UNRESOLVED PLACE NAMES:\n")
        f.write("-" * 30 + "\n")
        for name, count in sorted(all_unresolved.items(), key=lambda x: -x[1])[:30]:
            f.write(f"  {name}: {count} occurrences\n")

        f.write(f"\n\nSTORIES WITHOUT LOCATION ({len(unresolved_stories)}):\n")
        f.write("-" * 30 + "\n")
        for s in unresolved_stories:
            f.write(f"  {s['id']}: {s['title']} [{s['category']}]\n")
            if s.get("unresolved_places"):
                f.write(f"    Candidates tried: {', '.join(s['unresolved_places'])}\n")

    print(f"Wrote unresolved report to {path}")


def print_summary(output: dict):
    """Print a summary to console."""
    meta = output["metadata"]
    print()
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total stories:     {meta['total_stories']}")
    print(f"Geocoded:          {meta['geocoded_stories']}")
    print(f"Without location:  {meta['unresolved_stories']}")
    print()
    print("Stories per category:")
    for cat in meta["categories"]:
        print(f"  {cat['name']}: {cat['count']}")
    print()

    # Top unresolved
    all_unresolved: dict[str, int] = {}
    for s in output["stories"]:
        for name in s.get("unresolved_places", []):
            all_unresolved[name] = all_unresolved.get(name, 0) + 1
    if all_unresolved:
        print("Top 10 unresolved place names:")
        for name, count in sorted(all_unresolved.items(), key=lambda x: -x[1])[:10]:
            print(f"  {name}: {count}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import os

    raw_path = "snerpa_raw.json"

    # Part 1: Scrape (skip if raw data exists and --geocode-only flag)
    if "--geocode-only" in sys.argv and os.path.exists(raw_path):
        print(f"Loading existing raw data from {raw_path}...")
        with open(raw_path, "r", encoding="utf-8") as f:
            stories = json.load(f)
        print(f"Loaded {len(stories)} stories")
        print()
    else:
        stories = scrape_all()
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)
        print(f"Saved raw data to {raw_path}")
        print()

    # Part 2: Geocode
    stories = geocode_all(stories)

    # Part 3: Output
    output = build_output(stories)

    out_path = "kringum_thjodsogor.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved final output to {out_path}")

    write_unresolved_report(stories, "unresolved_report.txt")
    print_summary(output)


if __name__ == "__main__":
    main()
