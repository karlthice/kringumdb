#!/usr/bin/env python3
"""
Step 1 of the English örnefni curation: fetch every place name that the
importer would accept from LMÍ's live WFS service (IS 50V örnefni).

Reads the three layers ornefni_punktar, ornefni_linur and ornefni_flakar from
gis.lmi.is and keeps the same features import_ornefni.py keeps: a non-blank
name (ornefni) and a description (ornefnalysing) of at least 5 characters after
trimming. Each geometry is reduced to one point with the importer's rules
(point -> the point, line -> middle vertex, polygon -> average of the first
ring, multi -> first part), so the coordinates match the rows in kringum.db.

The service rounds EPSG:4326 output to 4 decimals (5-11 m), so geometries are
requested in ISN93 (EPSG:3057, metres, full precision) and converted to
latitude/longitude here (Lambert conformal conic on GRS80; ISN93 coincides
with WGS84 to well under a metre). Polygons are averaged after conversion,
in degrees, as the importer always did.

Every record keeps the LMÍ uuid, which is stable across releases and is the key
the later curation steps use.

Output: data/ornefni_all.json
  {"fetched_at": ..., "releases": {...}, "count": N, "items": [ {...}, ... ]}

Usage: python fetch_ornefni.py [--out path] [--page-size N]
"""
import argparse
import collections
import datetime
import json
import math
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, 'data', 'ornefni_all.json')

WFS_URL = 'https://gis.lmi.is/geoserver/wfs'
LAYERS = ['ornefni_punktar', 'ornefni_linur', 'ornefni_flakar']
FILTER = 'strLength(strTrim(ornefnalysing)) >= 5 AND strLength(strTrim(ornefni)) > 0'

FIELDS = ['id', 'uuid', 'ornefni', 'tvinefni', 'nafnberi', 'nafnberikenni',
          'ornefnaflokkur', 'ornefnaflokkurkenni', 'tilvist', 'heimild',
          'ornefnalysing', 'gagnaeigandi', 'gagnasafn', 'birtingarkvardi',
          'dagsinnsetningar', 'dagsleidrettingar', 'dagsuppfaerslu']

# Sanity box for the North Atlantic around Iceland, used to catch axis-order
# mistakes. The dataset includes seabed names far offshore (Jan Mayen ridge,
# Reykjanes ridge), so a wide box is needed.
LAT_RANGE = (55.0, 75.0)
LON_RANGE = (-40.0, 0.0)
# Iceland itself, plus its near-shore islands (Grímsey, Kolbeinsey, Vestmannaeyjar).
# Names outside it are flagged offshore=True.
ISLAND_LAT = (62.5, 67.5)
ISLAND_LON = (-25.5, -12.5)


# ISN93 / Lambert 1993 (EPSG:3057): LCC 2SP on GRS80.
_A = 6378137.0
_F = 1 / 298.257222101
_E = math.sqrt(2 * _F - _F * _F)
_LAT1, _LAT2, _LAT0, _LON0 = (math.radians(v) for v in (64.25, 65.75, 65.0, -19.0))
_X0 = _Y0 = 500000.0


def _m(phi):
    return math.cos(phi) / math.sqrt(1 - (_E * math.sin(phi)) ** 2)


def _t(phi):
    es = _E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - es) / (1 + es)) ** (_E / 2)


_N = (math.log(_m(_LAT1)) - math.log(_m(_LAT2))) / (math.log(_t(_LAT1)) - math.log(_t(_LAT2)))
_FF = _m(_LAT1) / (_N * _t(_LAT1) ** _N)
_RHO0 = _A * _FF * _t(_LAT0) ** _N


def isn93_to_lonlat(x, y):
    """(lon, lat) in degrees for ISN93 easting/northing in metres."""
    dx, dy = x - _X0, _RHO0 - (y - _Y0)
    rho = math.copysign(math.hypot(dx, dy), _N)
    t = (rho / (_A * _FF)) ** (1 / _N)
    lon = math.atan2(dx, dy) / _N + _LON0
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(15):
        es = _E * math.sin(phi)
        nxt = math.pi / 2 - 2 * math.atan(t * ((1 - es) / (1 + es)) ** (_E / 2))
        if abs(nxt - phi) < 1e-12:
            phi = nxt
            break
        phi = nxt
    return math.degrees(lon), math.degrees(phi)


def to_lonlat(c):
    """Convert a nested GeoJSON coordinate array from ISN93 to lon/lat."""
    if c and isinstance(c[0], (int, float)):
        return list(isn93_to_lonlat(c[0], c[1]))
    return [to_lonlat(x) for x in c]


def representative(geom):
    """(lon, lat) of one point for a GeoJSON geometry, using import_ornefni.py's rules."""
    if not geom:
        return None
    t, c = geom.get('type'), geom.get('coordinates')
    if not c:
        return None
    if t == 'Point':
        return tuple(c[:2])
    if t == 'LineString':
        return tuple(c[len(c) // 2][:2])
    if t == 'Polygon':
        ring = c[0]
        if not ring:
            return None
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    if t.startswith('Multi'):
        return representative({'type': t[len('Multi'):], 'coordinates': c[0]})
    return None


def clean_date(v):
    """'2026-11-19Z' -> '2026-11-19'."""
    return v.rstrip('Z') if isinstance(v, str) else v


def get_page(layer, start, count, session):
    params = {
        'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
        'typeNames': 'IS_50V:' + layer, 'srsName': 'EPSG:3057',
        'outputFormat': 'application/json', 'sortBy': 'id',
        'startIndex': start, 'count': count, 'CQL_FILTER': FILTER,
    }
    for attempt in range(5):
        try:
            r = session.get(WFS_URL, params=params, timeout=300)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            wait = 2 ** attempt * 5
            print('    page %d failed (%s), retrying in %ds' % (start, e, wait), file=sys.stderr)
            time.sleep(wait)
    sys.exit('Giving up on %s at startIndex %d' % (layer, start))


def fetch_layer(layer, page_size, session):
    items, start, total, bad_geom = [], 0, None, 0
    while True:
        page = get_page(layer, start, page_size, session)
        if total is None:
            total = page.get('numberMatched') or page.get('totalFeatures')
        feats = page.get('features', [])
        for f in feats:
            p = f.get('properties', {})
            g = f.get('geometry')
            if g and g.get('coordinates'):
                g = {'type': g['type'], 'coordinates': to_lonlat(g['coordinates'])}
            rep = representative(g)
            if rep is None:
                bad_geom += 1
                continue
            lon, lat = rep
            if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
                bad_geom += 1
                continue
            rec = {'layer': layer}
            for k in FIELDS:
                v = p.get(k)
                if isinstance(v, str):
                    v = v.strip()
                if k.startswith('dags'):
                    v = clean_date(v)
                rec[k] = v
            rec['lat'] = round(lat, 7)
            rec['lon'] = round(lon, 7)
            rec['gps'] = '%.7f,%.7f' % (lat, lon)
            rec['offshore'] = not (ISLAND_LAT[0] <= lat <= ISLAND_LAT[1]
                                   and ISLAND_LON[0] <= lon <= ISLAND_LON[1])
            items.append(rec)
        start += len(feats)
        print('  %-16s %6d / %s' % (layer, start, total))
        if not feats or (total is not None and start >= int(total)):
            break
    return items, int(total or 0), bad_geom


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--page-size', type=int, default=5000)
    args = ap.parse_args()

    session = requests.Session()
    all_items, summary = [], {}
    for layer in LAYERS:
        items, total, bad = fetch_layer(layer, args.page_size, session)
        if len(items) + bad != total:
            sys.exit('%s: got %d features (+%d bad geometries), service reported %d'
                     % (layer, len(items), bad, total))
        summary[layer] = {'kept': len(items), 'bad_geometry': bad}
        all_items.extend(items)

    uuids = collections.Counter(i['uuid'] for i in all_items)
    missing = uuids.pop(None, 0) + uuids.pop('', 0)
    dupes = {u: n for u, n in uuids.items() if n > 1}
    releases = collections.Counter(i['gagnasafn'] for i in all_items)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out = {
        'fetched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'source': WFS_URL,
        'filter': FILTER,
        'releases': dict(releases.most_common()),
        'layers': summary,
        'count': len(all_items),
        'items': all_items,
    }
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print('\nWrote %d place names to %s' % (len(all_items), args.out))
    for layer, s in summary.items():
        print('  %-16s %6d kept, %d unusable geometries' % (layer, s['kept'], s['bad_geometry']))
    print('Releases: %s' % dict(releases.most_common()))
    print('Offshore (outside the Iceland box): %d' % sum(i['offshore'] for i in all_items))
    print('uuid: %d missing, %d duplicated' % (missing, len(dupes)))
    if missing or dupes:
        print('  WARNING: uuid is not a clean key; duplicates: %s'
              % list(dupes.items())[:10], file=sys.stderr)


if __name__ == '__main__':
    main()
