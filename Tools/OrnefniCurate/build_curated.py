#!/usr/bin/env python3
"""
Step 6 of the örnefni curation: build curated.json from the written stories.

Reads data/stories.jsonl (from write_stories.py) and data/scores.jsonl, and
writes curated.json: one entry per curated place name, keyed by its LMÍ uuid,
with the tag, the English title and story, and the cleaned Icelandic story.
Skipped place names are left out. Tools/OrnefniImport/import_ornefni.py applies
this file on every import, so curated.json (committed) is the master copy:
edit a story here, not in kringum.db, or the next import will overwrite it.

Entries already in curated.json are kept as they are (they may have been
edited by hand); only new uuids are added. --replace rebuilds from scratch.

Usage: python build_curated.py [--replace]
"""
import argparse
import collections
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STORIES = os.path.join(HERE, 'data', 'stories.jsonl')
SCORES = os.path.join(HERE, 'data', 'scores.jsonl')
CANDIDATES = os.path.join(HERE, 'data', 'candidates.json')
OUT = os.path.join(HERE, 'curated.json')

# Haiku's scoring category -> KringumDB's standard category (the first tag part).
CATEGORY_TAG = {
    'folklore': 'Saga', 'tragedy': 'Saga', 'history': 'Saga',
    'way_of_life': 'Menning', 'name_origin': 'Menning', 'other': 'Menning',
    'location_only': 'Menning',
    'nature': 'Náttúra',
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--replace', action='store_true')
    args = ap.parse_args()

    items = json.load(open(CANDIDATES, encoding='utf-8'))['items']
    by_desc = collections.defaultdict(list)
    for i in items:
        by_desc[i['ornefnalysing']].append(i)
    rep_of = {}
    for members in by_desc.values():
        members.sort(key=lambda x: x['uuid'])
        for m in members:
            rep_of[m['uuid']] = members[0]['uuid']

    scores = {}
    for line in open(SCORES, encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            if 'score' in r:
                scores[r['uuid']] = r

    stories = {}
    for line in open(STORIES, encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            if 'error' not in r:
                stories[r['uuid']] = r

    old = {}
    if os.path.exists(OUT) and not args.replace:
        old = json.load(open(OUT, encoding='utf-8'))['items']

    out = dict(old)
    added = 0
    for uuid, r in sorted(stories.items()):
        if r['skip'] or uuid in out:
            continue
        s = scores[rep_of[uuid]]
        out[uuid] = {
            'ornefni': r['ornefni'],
            'tag': CATEGORY_TAG[s['category']] + ';Örnefni',
            'name_eng': r['name_eng'].strip(),
            'story_eng': r['story_eng'].strip(),
            'story_is': r['story_is'].strip(),
            'score': s['score'],
            'category': s['category'],
            'model': r['model'],
        }
        added += 1

    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump({
            'about': 'Curated LMÍ place names for KringumDB, keyed by LMÍ uuid. '
                     'Applied by Tools/OrnefniImport/import_ornefni.py. Edit stories here.',
            'updated': datetime.date.today().isoformat(),
            'count': len(out),
            'items': dict(sorted(out.items())),
        }, fh, ensure_ascii=False, indent=1)
    tags = collections.Counter(v['tag'] for v in out.values())
    print('curated.json: %d entries (%d kept, %d added)' % (len(out), len(old), added))
    print('Tags: %s' % dict(tags.most_common()))


if __name__ == '__main__':
    main()
