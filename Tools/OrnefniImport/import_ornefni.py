#!/usr/bin/env python3
"""
Import LMÍ IS 50V örnefni (place names) from a WGS84 GeoPackage into kringum.db.

Layers imported: ornefni_punktar (points), ornefni_linur (lines), ornefni_flakar (areas).
Only features with a description (ornefnalysing) of length >= 5 are kept.
Each geometry is reduced to one representative lat/lon point:
  - point   -> the point
  - line    -> the middle vertex
  - polygon -> average of the exterior-ring vertices
Rows are written with tag 'Örnefni' / source 'lmi'. KringumDB hides this tag from the
map and the item list (see app.py); it is only included in the (Icelandic) export.

All existing tag='Örnefni' rows are cleared first, so re-runs replace cleanly.
GeoPackage CRS is EPSG:4326, so gps is stored as "lat,lon" with dot decimals.

Usage: python import_ornefni.py [path/to.gpkg] [path/to/kringum.db]
"""
import os
import sys
import struct
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(HERE, '..', '..', 'kringum.db'))
DEFAULT_GPKG = os.path.expanduser('~/Downloads/is_50v_4326/is_50v_ornefni_epsg_4326.gpkg')

LAYERS = ['ornefni_punktar', 'ornefni_linur', 'ornefni_flakar']

# nafnberi (feature type) -> Icelandic definition, ported from the reference C#.
NAFNBERI_DESC = {
    "afréttur": "Heiðaland sem bændur nota sameiginlega sem sumarhaga handa búfé.",
    "dys": "Upphækkuð gröf, venjulega hulin grjóthrúgu.",
    "grjótbyrgi": "Gerði, vígi eða fiskibyrgi úr grjóti.",
    "kvíar": "Lítil rétt þar sem sauðkindur voru mjólkaðar.",
    "mógröf": "Gryfja í votlendi þar sem mór er tekinn.",
    "naust": "Skipa- og bátaskýli, oft án þaks.",
    "rétt": "Lokað svæði, hlaðið, steypt eða girt með hólfum fyrir búfé.",
    "sel": "Dvalarstaður með húsakosti í sumarhögum langt frá bæ þar sem búsmalar mjólkuðu.",
    "stekkur": "Fjárrétt með afstúkuðu rými fyrir lömb innst.",
    "árós": "Staður þar sem á fellur í sjó eða stöðuvatn, ármynni.",
    "bugða": "Beygja í straumi.",
    "drög": "Uppsprettur og lækir sem sameinast í eitt.",
    "hylur": "Djúpur staður í straumvatni.",
    "kíll": "Langur og djúpur lygn lækur sem tengir stundum vatnsföll, tjarnir eða vötn saman.",
    "kvísl": "Grein af meginvatni ár eða straums.",
    "læna": "Lítill, straumlygn lækur",
    "svelgur": "Hringiða í vatnsfalli.",
    "flúðir": "Klöpp rétt undir yfirborði rennandi vatns.",
    "vað": "Staður þar sem er fær leið yfir vatnsfall.",
    "lind": "Vatnsrás úr grunnvatninu upp á yfirborð jarðar, uppspretta",
    "volgra": "Volg lind, hlý uppspretta.",
    "lón": "Stöðuvatn sem myndast við jaðar skriðjökuls þegar hann hopar, jökullón.",
    "stokkur": "Náttúrulegir skurðir á engjum",
    "uppistöðulón": "Vatn sem safnað er ofan stíflu til miðlunar",
    "vík": "Lítill bugur inn í strönd.",
    "vogur": "Allstórt skarð inn í land.",
    "renna": "Skora eða rás sem hægt er að sigla um. Röst.",
    "áll": "Djúp og þröng renna á sjávarbotni.",
    "hnjúkur": "Skýrt afmarkaður hákollur fjalls, hnúkur",
    "fell": "Stakt fjall",
    "drangur": "Hár og mjór stakur klettur eða steinn, drangi.",
    "bjarg": "Stór steinn, klettur, strandberg, fuglabjarg. Hátt, þverhnípt.",
    "egg": "Skörp brún á fjalli, fjallsegg.",
    "hjalli": "Sléttur stallur eða þrep í fjallshlíð.",
    "klöpp": "Flatt og slétt, jarðfast bjarg.",
    "bakki": "Strönd, brún, barmur, land fram með ár- eða sjávarbakka.",
    "hlíð": "Löng brekka eða halli frá fjallsrótum upp á fjallsbrún eða upp að hamrabelti.",
    "kinn": "Löng brekka eða halli frá fjallsrótum upp á fjallsbrún eða upp að hamrabelti.",
    "stapi": "Allhár klettur sem er áberandi hár og ávalur (hringlaga).",
    "öxl": "Stallur á fjallshrygg, lækkar snögglega, fjallsöxl.",
    "ás": "Aflöng, ávöl hæð í landslagi.",
    "holt": "Mishæð í landslagi, gróðurlítil og oft grýtt ofan til. Móaland hálfgróið eða lyngvaxið.",
    "kambur": "Malarbrún, malarhryggur í landslagi.",
    "leiti": "Mishæð í landslagi (sem ber við sjónarhring).",
    "rimi": "Dálítil landræma, lítið eitt hærri en umhverfið.",
    "háls": "Hæð í landslagi, hæðardrag.",
    "hryggur": "Aflöng mishæð í landslagi.",
    "múli": "Afmarkaður fjallsendi fram úr fjallaröð.",
    "rani": "Hryggur sem gengur fram undan fjalli eða tunga í landslagi.",
    "tunga": "Mjó landspilda milli tveggja vatnsfalla, gilja o.fl.",
    "botn": "Innsti hluti fjarðar eða dals.",
    "dalsmynni": "Svæðið þar sem dalur byrjar, inngangur í dal.",
    "drag": "Innsti hluti, upphaf dals þar sem fjöllin eru lág og aflíðandi.",
    "kleif": "Geil í fjallshlíð, skarð.",
    "skál": "Dæld í landslagi.",
    "ketill": "Sigdæld.",
    "bali": "Slétt grasflöt, grasbali.",
    "bás": "Lítil dæld í grónu landi.",
    "bolli": "Lítil grasivaxin lægð í landslagi.",
    "engjastykki": "Lítið nokkuð flatt grassvæði.",
    "geiri": "Grassvæði.",
    "gróf": "Lægð í yfirborði lands eftir vatn.",
    "grund": "Slétt, grasi gróin jörð.",
    "hólf": "Lítið, sérstaklega aðgreint grasi gróið svæði.",
    "hvammur": "Grasi gróin lægð eða slakki inn í hlíð eða brekku.",
    "hvilft": "Stuttur skálarlaga dalur í fjallshlíð.",
    "ræma": "Aflöng landspilda.",
    "stykki": "Partur eða sneið af túni/engi.",
    "torfa": "Gróin spilda umlukin ógrónu landi.",
    "flag": "Svæði með moldarjarðvegi án grassvarðar.",
    "jarðfall": "Holrúm sem myndast þegar jarðvegi skolar burt undan yfirborðinu og yfirborðið fellur síðan saman.",
    "melur": "Gróðursnautt svæði þakið möl eða smásteinum.",
    "urð": "Stórgrýtt svæði, grjótdyngjur sem hrunið hafa úr fjöllum eða björgum.",
    "dý": "Pollur, fen í votlendi, oft með mosa í kring.",
    "fit": "Sjávarfitjar, votlendi við strendur.",
    "eyri": "Sand eða malarsvæði (stundum uppgróið) meðfram á (vatni), myndað af framburði árinnar",
    "hólmi": "Smáey, misvel gróin.",
    "rif": "Ílöng sandbunga í vatni.",
    "lág": "Lítil dæld í grónu landi.",
    "eiði": "Grandi. Rif eða landræma milli ness (höfða) og meginlands.",
}


def gpb_to_wkb(blob):
    """Strip the GeoPackage binary header, returning the inner WKB (or None)."""
    if blob is None or len(blob) < 8 or blob[0:2] != b'GP':
        return None
    flags = blob[3]
    env_ind = (flags >> 1) & 0x07
    env_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env_ind, 0)
    return blob[8 + env_size:]


class _Cur:
    __slots__ = ('b', 'o')

    def __init__(self, b):
        self.b = b
        self.o = 0

    def u8(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def u32(self, le):
        v = struct.unpack_from('<I' if le else '>I', self.b, self.o)[0]
        self.o += 4
        return v

    def f64(self, le):
        v = struct.unpack_from('<d' if le else '>d', self.b, self.o)[0]
        self.o += 8
        return v


def _read_geom(c):
    le = c.u8() == 1
    gtype = c.u32(le) % 1000  # strip Z/M variants; data is 2D
    if gtype == 1:    # Point
        return ('point', (c.f64(le), c.f64(le)))
    if gtype == 2:    # LineString
        n = c.u32(le)
        return ('line', [(c.f64(le), c.f64(le)) for _ in range(n)])
    if gtype == 3:    # Polygon
        nr = c.u32(le)
        rings = []
        for _ in range(nr):
            npt = c.u32(le)
            rings.append([(c.f64(le), c.f64(le)) for _ in range(npt)])
        return ('polygon', rings)
    if gtype in (4, 5, 6):  # Multi(Point|LineString|Polygon)
        n = c.u32(le)
        return ('multi', [_read_geom(c) for _ in range(n)])
    raise ValueError('unsupported geometry type %d' % gtype)


def _representative(geom):
    kind, val = geom
    if kind == 'point':
        return val
    if kind == 'line':
        return val[len(val) // 2] if val else None
    if kind == 'polygon':
        ring = val[0] if val else []
        if not ring:
            return None
        sx = sum(p[0] for p in ring) / len(ring)
        sy = sum(p[1] for p in ring) / len(ring)
        return (sx, sy)
    if kind == 'multi':
        return _representative(val[0]) if val else None
    return None


def rep_lonlat(blob):
    """Return (lon, lat) of a representative point for a GeoPackage geometry blob."""
    wkb = gpb_to_wkb(blob)
    if wkb is None:
        return None
    return _representative(_read_geom(_Cur(wkb)))


def _cap_first(s):
    return s[0].upper() + s[1:] if s else s


def _lower_first(s):
    return s[0].lower() + s[1:] if s else s


def build_story(ornefni, tvinefni, nafnberi, ornefnalysing, tilvist):
    nafnberi = nafnberi or ''
    if tvinefni:
        s = f"{ornefni} ({tvinefni}) er {nafnberi}"
    else:
        s = f"{ornefni} er {nafnberi}"
    s += " sem er ekki lengur til.  " if tilvist == "Er ekki til" else ".  "
    desc = NAFNBERI_DESC.get(nafnberi, "")
    if desc:
        s += "\n\n" + _cap_first(nafnberi) + " er " + _lower_first(desc)
    s += "\n\n" + ornefnalysing
    return s


def main():
    gpkg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GPKG
    dbpath = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB
    if not os.path.exists(gpkg):
        sys.exit('GeoPackage not found: ' + gpkg)
    if not os.path.exists(dbpath):
        sys.exit('kringum.db not found: ' + dbpath)
    print('GeoPackage:', gpkg)
    print('kringum.db:', dbpath)

    src = sqlite3.connect(gpkg)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dbpath)
    dst.execute('PRAGMA foreign_keys=ON')

    cleared = dst.execute("DELETE FROM items WHERE tag='Örnefni'").rowcount
    print("Cleared existing 'Örnefni' rows:", cleared)

    rows = []
    skipped_geom = 0
    for layer in LAYERS:
        cnt = 0
        q = ("SELECT ornefni, tvinefni, nafnberi, ornefnalysing, tilvist, heimild, geom "
             "FROM %s WHERE ornefnalysing IS NOT NULL AND LENGTH(TRIM(ornefnalysing)) >= 5" % layer)
        for r in src.execute(q):
            ornefni = (r['ornefni'] or '').strip()
            lysing = (r['ornefnalysing'] or '').strip()
            if not ornefni or len(lysing) < 5:
                continue
            try:
                rep = rep_lonlat(r['geom'])
            except Exception:
                rep = None
            if rep is None:
                skipped_geom += 1
                continue
            lon, lat = rep
            gps = "%.7f,%.7f" % (lat, lon)
            story = build_story(ornefni, (r['tvinefni'] or '').strip(), r['nafnberi'], lysing, r['tilvist'])
            ref = "LMI Örnefni. " + (r['heimild'] or '')
            rows.append((ornefni, gps, story, ref))
            cnt += 1
        print('  %-18s %d' % (layer, cnt))

    dst.executemany(
        "INSERT INTO items (name, gps, tag, story, ref, source, fromdate, todate, lastchanged, "
        "story_eng, name_eng, link, link_eng, visibility) "
        "VALUES (?, ?, 'Örnefni', ?, ?, 'lmi', '', '', datetime('now'), '', '', '', '', 0)",
        rows)
    dst.commit()

    total = dst.execute("SELECT COUNT(*) FROM items WHERE tag='Örnefni'").fetchone()[0]
    print("\nInserted %d rows (skipped %d unparseable geometries)." % (len(rows), skipped_geom))
    print("kringum.db now has %d 'Örnefni' rows." % total)


if __name__ == '__main__':
    main()
