#!/usr/bin/env python3
"""
Dedup nat_sogustadir.json against kringum.db.

For each nat.is item, decide whether it already exists in kringum.db using
approximate location (within ~2 km) AND a fuzzy name comparison. Items that
do NOT have a match are written to nat_sogustadir_new.json.

Matching heuristic
------------------
nat.is publishes some coordinates that are wildly wrong (e.g. Glymur is ~21 km
off, Þingvellir is ~140 km off). To stay robust against bad inputs we use a
tiered rule when the nat.is item has coordinates:

  Tier A — high-confidence name match:
    name fuzzy >= FUZZY_HIGH_NAME (0.95) AND distance <= RADIUS_HIGH_NAME (25 km)
  Tier B — geo-anchored loose name match:
    name fuzzy >= FUZZY_WITH_COORDS (0.70) AND distance <= RADIUS_M (2 km)

If the nat.is item has no coordinates we fall back to a strict name-only check:
    name fuzzy >= FUZZY_NAME_ONLY (0.90).

Name normalisation:
- lowercase
- drop everything after the first comma (kringum sometimes appends ", 1928",
  ", bókmenntir", and nat.is appends ", Ferðast og Fræðast" etc.)
- collapse whitespace
"""

import json
import math
import os
import re
import sqlite3
import sys
from difflib import SequenceMatcher

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "kringum.db")
INPUT_JSON = os.path.join(os.path.dirname(__file__), "nat_sogustadir.json")
OUTPUT_JSON = os.path.join(os.path.dirname(__file__), "nat_sogustadir_new.json")

RADIUS_M = 2000           # 2 km — strict geo-anchored tier
FUZZY_WITH_COORDS = 0.70  # name similarity threshold when coords are available
RADIUS_HIGH_NAME = 25000  # 25 km — slack for nat.is's imprecise coordinates
FUZZY_HIGH_NAME = 0.95    # name similarity required for the slack tier
FUZZY_NAME_ONLY = 0.90    # stricter threshold when nat.is item has no coordinates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gps(gps):
    """Parse 'lat, lng' / 'lat,lng'. Returns (lat, lng) or None."""
    if not gps or "," not in gps:
        return None
    try:
        a, b = gps.replace(" ", "").split(",", 1)
        lat, lng = float(a), float(b)
    except (ValueError, IndexError):
        return None
    # Sanity-check: Iceland roughly 63..67 N, -25..-13 E
    if not (60 <= lat <= 70 and -30 <= lng <= -10):
        return None
    return lat, lng


_SUFFIX_TRIM = re.compile(r"^(.*?)[,\-–—].*$")  # everything up to first comma/dash

def normalise_name(name: str) -> str:
    if not name:
        return ""
    s = name.strip().lower()
    # Drop after the first comma or dash (suffixes like ", bókmenntir" / "- Modern Log Cabin")
    m = _SUFFIX_TRIM.match(s)
    if m and m.group(1).strip():
        s = m.group(1)
    # Strip "ferðast og fræðast" boilerplate just in case it survived
    s = s.replace("ferðast og fræðast", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fuzzy(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def name_match(a: str, b: str) -> float:
    """
    Best of:
    - raw SequenceMatcher ratio
    - 1.0 if all tokens of the shorter name are a token-prefix of the other
      (handles "Glymur Hvalfirði" vs "Glymur", "Reykholt í Reykholtsdal" vs
      "Reykholt", etc.)
    - token-set Jaccard ratio (handles word reordering)
    """
    if not a or not b:
        return 0.0

    base = SequenceMatcher(None, a, b).ratio()

    ta = a.split()
    tb = b.split()
    if ta and tb:
        # Token-prefix containment: shorter is a leading token sequence of longer
        short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if long[: len(short)] == short:
            return 1.0
        # Token-set Jaccard
        sa, sb = set(ta), set(tb)
        jac = len(sa & sb) / len(sa | sb)
        base = max(base, jac)

    return base


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_db_items():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT id, name, name_eng, gps FROM items WHERE name IS NOT NULL"
    )
    items = []
    for id_, name, name_eng, gps in cur:
        coords = parse_gps(gps)
        if not coords:
            continue
        items.append({
            "id": id_,
            "name": name or "",
            "name_eng": name_eng or "",
            "norm": normalise_name(name or ""),
            "norm_eng": normalise_name(name_eng or ""),
            "lat": coords[0],
            "lng": coords[1],
        })
    conn.close()
    return items


def load_nat_items():
    with open(INPUT_JSON, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def best_db_match(nat_item, db_items):
    """Return (db_item, distance_m_or_None, fuzzy_score) for the best match, or None."""
    nat_name = normalise_name(nat_item.get("name", ""))
    if not nat_name:
        return None

    coords = nat_item.get("coords") or None
    nat_lat = nat_lng = None
    if coords and "lat" in coords and "lng" in coords:
        try:
            nat_lat = float(coords["lat"])
            nat_lng = float(coords["lng"])
        except (TypeError, ValueError):
            nat_lat = nat_lng = None

    best = None  # (db_item, dist, score)

    if nat_lat is not None:
        # With-coords path: two tiers
        #   Tier A: high-confidence name match within RADIUS_HIGH_NAME (slack
        #           for nat.is's imprecise coordinates)
        #   Tier B: loose name match within RADIUS_M (geo-anchored)
        for db in db_items:
            dist = haversine(nat_lat, nat_lng, db["lat"], db["lng"])
            if dist > RADIUS_HIGH_NAME:
                continue
            score = max(name_match(nat_name, db["norm"]), name_match(nat_name, db["norm_eng"]))
            if dist <= RADIUS_M and score >= FUZZY_WITH_COORDS:
                pass  # tier B match
            elif score >= FUZZY_HIGH_NAME:
                pass  # tier A match
            else:
                continue
            if best is None or score > best[2]:
                best = (db, dist, score)
    else:
        # No-coords path: stricter name-only fuzzy
        for db in db_items:
            score = max(name_match(nat_name, db["norm"]), name_match(nat_name, db["norm_eng"]))
            if score >= FUZZY_NAME_ONLY:
                if best is None or score > best[2]:
                    best = (db, None, score)

    return best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Loading DB from {DB_PATH} ...")
    db_items = load_db_items()
    print(f"  {len(db_items)} DB items with valid GPS")

    print(f"Loading {INPUT_JSON} ...")
    nat_items = load_nat_items()
    print(f"  {len(nat_items)} nat.is items")

    with_coords = sum(1 for n in nat_items if n.get("coords"))
    print(f"  {with_coords} have coordinates, {len(nat_items) - with_coords} do not")

    print(f"\nMatching (radius={RADIUS_M}m, fuzzy>={FUZZY_WITH_COORDS} with coords, "
          f">={FUZZY_NAME_ONLY} name-only) ...")

    new_items: list[dict] = []
    matched_count = 0
    matched_with_coords = 0
    matched_name_only = 0

    for i, nat in enumerate(nat_items, 1):
        match = best_db_match(nat, db_items)
        if match is None:
            new_items.append(nat)
            continue

        matched_count += 1
        db, dist, score = match
        if dist is None:
            matched_name_only += 1
            print(f"  [{i}/{len(nat_items)}] DUP (name) score={score:.2f} "
                  f"\"{nat['name']}\" <-> \"{db['name']}\"")
        else:
            matched_with_coords += 1
            print(f"  [{i}/{len(nat_items)}] DUP (geo)  score={score:.2f} dist={dist:.0f}m "
                  f"\"{nat['name']}\" <-> \"{db['name']}\"")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(new_items, f, ensure_ascii=False, indent=2)

    print(f"\n=== Summary ===")
    print(f"  matched (geo+name): {matched_with_coords}")
    print(f"  matched (name only, no coords): {matched_name_only}")
    print(f"  total matched: {matched_count}")
    print(f"  new items written: {len(new_items)} → {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
