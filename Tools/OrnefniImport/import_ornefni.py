#!/usr/bin/env python3
"""
Import LMÍ IS 50V örnefni (place names) into kringum.db.

Input is the file written by Tools/OrnefniCurate/fetch_ornefni.py (every place
name with a description of at least 5 characters, fetched from LMÍ's live WFS
service, one representative point per geometry), plus the curation file
Tools/OrnefniCurate/curated.json.

Rows are matched on the LMÍ uuid (column lmi_uuid), so an item keeps its id
across imports: audio files, favourites and links stay valid. A row's
lastchanged is only updated when its content changes.

  - Plain place names get tag 'Örnefni', an Icelandic story built from the
    feature type and description, and no English. KringumDB hides this tag from
    the map, the item list, the English export and audio rendering.
  - Curated place names (in curated.json) get the curated tag, such as
    'Saga;Örnefni', the cleaned Icelandic story (story_is) and the English
    title and story. They behave like ordinary items everywhere. Edit their
    text in curated.json: this importer overwrites it in kringum.db.
  - Plain LMÍ rows whose uuid is no longer in the input are deleted. Curated
    rows are never deleted; the importer warns about them instead.

The first run on a database without lmi_uuid adds the column and matches the
existing rows on name and gps (exact, or the same name within 30 m for points
LMÍ has nudged), so their ids are kept too.

Usage: python import_ornefni.py [--in path/to/ornefni_all.json] [--curated path]
                                [--db path/to/kringum.db] [--dry-run]
"""
import argparse
import collections
import json
import math
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(HERE, '..', '..', 'kringum.db'))
CURATE = os.path.normpath(os.path.join(HERE, '..', 'OrnefniCurate'))
DEFAULT_IN = os.path.join(CURATE, 'data', 'ornefni_all.json')
DEFAULT_CURATED = os.path.join(CURATE, 'curated.json')

FIELDS = ('name', 'gps', 'tag', 'story', 'ref', 'story_eng', 'name_eng')

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


def desired_row(rec, cur):
    """The kringum.db field values for one LMÍ record (cur = its curated entry or None)."""
    row = {
        'name': rec['ornefni'],
        'gps': rec['gps'],
        'ref': 'LMI Örnefni. ' + (rec.get('heimild') or ''),
    }
    if cur:
        row.update(tag=cur['tag'], story=cur['story_is'],
                   story_eng=cur['story_eng'], name_eng=cur['name_eng'])
    else:
        row.update(tag='Örnefni',
                   story=build_story(rec['ornefni'], rec.get('tvinefni') or '', rec.get('nafnberi'),
                                     rec['ornefnalysing'], rec.get('tilvist')),
                   story_eng='', name_eng='')
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--in', dest='inp', default=DEFAULT_IN)
    ap.add_argument('--curated', default=DEFAULT_CURATED)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--dry-run', action='store_true', help='report what would change, write nothing')
    args = ap.parse_args()
    for p in (args.inp, args.curated, args.db):
        if not os.path.exists(p):
            sys.exit('Not found: ' + p)

    src = json.load(open(args.inp, encoding='utf-8'))
    recs = [r for r in src['items'] if r.get('uuid')]
    curated = json.load(open(args.curated, encoding='utf-8'))['items']
    print('Input:    %d place names (%s, fetched %s)' % (len(recs), ', '.join(src['releases']), src['fetched_at']))
    print('Curated:  %d entries' % len(curated))
    print('kringum.db:', args.db)

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    cols = {r['name'] for r in db.execute('PRAGMA table_info(items)')}
    if 'lmi_uuid' not in cols:
        if args.dry_run:
            print('(would add column items.lmi_uuid)')
        else:
            db.execute('ALTER TABLE items ADD COLUMN lmi_uuid TEXT')
            print('Added column items.lmi_uuid')
    if not args.dry_run:
        db.execute('CREATE INDEX IF NOT EXISTS idx_items_lmi_uuid ON items(lmi_uuid)')

    existing = [dict(r) for r in db.execute("SELECT * FROM items WHERE source='lmi'")]
    for r in existing:
        r.setdefault('lmi_uuid', None)
    by_uuid = {r['lmi_uuid']: r for r in existing if r['lmi_uuid']}
    by_name_gps = collections.defaultdict(list)
    by_name = collections.defaultdict(list)
    for r in existing:
        if not r['lmi_uuid']:
            by_name_gps[(r['name'], r['gps'])].append(r)
            by_name[r['name']].append(r)
    taken = set()

    def take_near(name, gps, limit_m=30.0):
        """The unmatched old row with this name nearest to gps, if within limit_m."""
        lat, lon = (float(v) for v in gps.split(','))
        best, best_d = None, limit_m
        for r in by_name.get(name, ()):
            if r['id'] in taken:
                continue
            try:
                rlat, rlon = (float(v) for v in r['gps'].split(','))
            except (ValueError, AttributeError):
                continue
            d = math.hypot((rlat - lat) * 111320, (rlon - lon) * 111320 * math.cos(math.radians(lat)))
            if d <= best_d:
                best, best_d = r, d
        return best

    stats = collections.Counter()
    seen_ids = set()
    # Exact matches first, so a near match never steals a row another record matches exactly.
    match = {}
    for rec in recs:
        old = by_uuid.get(rec['uuid'])
        if old is None:
            cands = [r for r in by_name_gps.get((rec['ornefni'], rec['gps']), ()) if r['id'] not in taken]
            if cands:
                old = cands[0]
                stats['matched_by_name_gps'] += 1
        if old is not None:
            taken.add(old['id'])
            match[rec['uuid']] = old
    for rec in recs:
        if rec['uuid'] not in match and by_name.get(rec['ornefni']):
            old = take_near(rec['ornefni'], rec['gps'])
            if old is not None:
                taken.add(old['id'])
                match[rec['uuid']] = old
                stats['matched_by_name_near'] += 1

    for rec in recs:
        cur = curated.get(rec['uuid'])
        want = desired_row(rec, cur)
        old = match.get(rec['uuid'])
        stats['curated' if cur else 'plain'] += 1
        if old is not None:
            seen_ids.add(old['id'])
            changed = [f for f in FIELDS if (old[f] or '') != want[f]]
            if changed:
                stats['updated'] += 1
                if not args.dry_run:
                    db.execute('UPDATE items SET %s, lmi_uuid=?, lastchanged=datetime(\'now\') WHERE id=?'
                               % ', '.join(f + '=?' for f in FIELDS),
                               [want[f] for f in FIELDS] + [rec['uuid'], old['id']])
            else:
                stats['unchanged'] += 1
                if old['lmi_uuid'] != rec['uuid'] and not args.dry_run:
                    db.execute('UPDATE items SET lmi_uuid=? WHERE id=?', (rec['uuid'], old['id']))
        else:
            stats['inserted'] += 1
            if not args.dry_run:
                db.execute(
                    'INSERT INTO items (name, gps, tag, story, ref, story_eng, name_eng, source, lmi_uuid, '
                    'fromdate, todate, link, link_eng, visibility, lastchanged) '
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'lmi', ?, '', '', '', '', 0, datetime('now'))",
                    [want[f] for f in FIELDS] + [rec['uuid']])

    unseen = [r for r in existing if r['id'] not in seen_ids]
    # Never delete curated rows (tag other than plain 'Örnefni'): a short input
    # file or a changed uuid must not drop a curated item and its id.
    gone = [r['id'] for r in unseen if (r['tag'] or '') == 'Örnefni']
    kept_curated = [r for r in unseen if (r['tag'] or '') != 'Örnefni']
    stats['deleted'] = len(gone)
    if kept_curated:
        print('WARNING: %d curated rows are not in the input and were kept: %s'
              % (len(kept_curated), ', '.join('%s (id %s)' % (r['name'], r['id']) for r in kept_curated[:10])),
              file=sys.stderr)
    if not args.dry_run:
        db.executemany('DELETE FROM items WHERE id=?', [(i,) for i in gone])

    in_input = {r['uuid'] for r in recs}
    missing_cur = [u for u in curated if u not in in_input]

    print('\nPlace names: %d plain, %d curated' % (stats['plain'], stats['curated']))
    print('Rows: %d unchanged, %d updated, %d inserted, %d deleted (no longer in LMÍ data)'
          % (stats['unchanged'], stats['updated'], stats['inserted'], stats['deleted']))
    if stats['matched_by_name_gps'] or stats['matched_by_name_near']:
        print('     existing rows without lmi_uuid matched: %d on name + gps, %d on name within 30 m'
              % (stats['matched_by_name_gps'], stats['matched_by_name_near']))
    if missing_cur:
        print('WARNING: %d curated uuids are not in the input (kept in curated.json, not imported): %s'
              % (len(missing_cur), ', '.join(missing_cur[:5])), file=sys.stderr)
    if args.dry_run:
        db.rollback()
        print('\nDry run: nothing written.')
    else:
        db.commit()
        tags = dict(db.execute("SELECT tag, COUNT(*) FROM items WHERE source='lmi' GROUP BY tag").fetchall())
        print('\nkringum.db LMÍ rows by tag: %s' % tags)


if __name__ == '__main__':
    main()
