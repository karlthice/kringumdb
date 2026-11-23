#!/usr/bin/env python3
"""
Step 2 of the English örnefni curation: a cheap rule-based filter, no AI.

Reads data/ornefni_all.json (from fetch_ornefni.py) and keeps the place names
worth sending to the AI scoring step. The filter is deliberately generous:
it only removes entries that are very unlikely to hold a story, and step 3
does the real judging.

A place name is a candidate when it is not offshore and either
  - its cleaned description is at least MIN_CLEAN_LEN characters, or
  - its description matches a folklore, death/drama or history keyword.

"Cleaned" means source boilerplate is stripped before measuring: the
"Örnefnaskrá <farm>. AG, HJ:" headers, "Í örnefnaskrá segir:", page
references "(bls. 3)", map numbers "(46)" and extra whitespace. Long
descriptions are often just directions padded with these.

Output: data/candidates.json
  {"source_fetched_at": ..., "rules": {...}, "stats": {...}, "count": N, "items": [...]}
Each item is the fetched record plus: clean_text, clean_len, keywords
(matched groups), reasons (why it passed) and shared_count (how many fetched
place names carry the exact same description).

Usage: python prefilter.py [--in path] [--out path] [--min-len N]
"""
import argparse
import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IN = os.path.join(HERE, 'data', 'ornefni_all.json')
DEFAULT_OUT = os.path.join(HERE, 'data', 'candidates.json')

MIN_CLEAN_LEN = 150

# Matched case-insensitively against the description only. Names are not
# searched: a name like "Hulduklettur" usually comes with a description that
# only says where the rock is.
KEYWORDS = {
    'folklore': [
        r'huldu', r'álfa', r'álfkon', r'álfab[æy]', r'tröll', r'skess', r'\brisa?\b',
        r'draug', r'reimt', r'reimleik', r'afturgang', r'útburð', r'nykur', r'nykr',
        r'skrímsl', r'álög', r'álaga', r'galdr', r'fjársjóð', r'fólgi[ðn]', r'gullkist',
        r'þjóðsag', r'munnmæl', r'sagan segir', r'sögn', r'sagt er', r'sagt var',
        r'sögur herma', r'trú var', r'trúað var', r'talið var', r'talið er að',
        r'átti að hafa', r'á að hafa',
    ],
    'death': [
        r'drukkn', r'drekkt', r'\bfórst', r'\bfórust', r'urðu úti', r'varð úti',
        r'úti varð', r'beið bana', r'biðu bana', r'\blést', r'\blík\b', r'\blíki[ðn]',
        r'\bdys', r'grafinn', r'grafin\b', r'heyg[ðt]', r'\bmyrt', r'var veginn',
        r'voru vegnir', r'bardag', r'orrust', r'aftak', r'af lífi', r'hengd',
        r'snjóflóð', r'strandaði', r'skipsstrand', r'skipbrot',
    ],
    'history': [
        r'landnám', r'útileg', r'útlag', r'þingstað', r'kirkjustað', r'bænhús',
        r'fornmann', r'fornmanna', r'biskup', r'konung', r'Grettir', r'Grettis',
        r'Njál', r'Hallgerð', r'Jón Arason', r'Guðmund\w* góð',
    ],
}
KEYWORD_RX = {g: re.compile('|'.join(p), re.IGNORECASE) for g, p in KEYWORDS.items()}

BOILERPLATE = [
    # "Örnefnaskrá Einarsstaða. AG, HJ:" / "Örnefnalýsing Stakkholts. ...:" at the start
    re.compile(r'^\s*(Í\s+)?[Öö]rnefna(skrá|skrár|lýsing|lýsingu)\b[^:\n]{0,120}:\s*'),
    # "Örnefni í Gilsbakkalandi. SS,BH,ÓS:"
    re.compile(r'^\s*Örnefni í [^:\n]{0,80}:\s*'),
    # "Viðbót ÞK,MK:"
    re.compile(r'^\s*Viðbót[^:\n]{0,40}:\s*'),
    # "Í örnefnaskrá segir:" anywhere
    re.compile(r'Í\s+örnefna(skrá|lýsingu)\s+segir\s*:?\s*', re.IGNORECASE),
    # "(bls. 3)", "(bls. 2-3)"
    re.compile(r'\(\s*bls\.?\s*[\d\s,\-–]+\)'),
    # map numbers "(46)", "(145)"
    re.compile(r'\(\s*\d{1,4}\s*\)'),
]


def clean_text(text):
    t = text or ''
    for _ in range(2):  # headers can be stacked ("Örnefnaskrá X. AG: Viðbót ÞK:")
        for rx in BOILERPLATE:
            t = rx.sub(' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--in', dest='inp', default=DEFAULT_IN)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--min-len', type=int, default=MIN_CLEAN_LEN)
    args = ap.parse_args()

    with open(args.inp, encoding='utf-8') as fh:
        src = json.load(fh)
    items = src['items']

    shared = collections.Counter(i['ornefnalysing'] for i in items)

    out, dropped = [], collections.Counter()
    for i in items:
        if i.get('offshore'):
            dropped['offshore'] += 1
            continue
        ct = clean_text(i['ornefnalysing'])
        kws = [g for g, rx in KEYWORD_RX.items() if rx.search(i['ornefnalysing'])]
        reasons = []
        if len(ct) >= args.min_len:
            reasons.append('length')
        if kws:
            reasons.append('keyword')
        if not reasons:
            dropped['short_no_keyword'] += 1
            continue
        rec = dict(i)
        rec.update({
            'clean_text': ct,
            'clean_len': len(ct),
            'keywords': kws,
            'reasons': reasons,
            'shared_count': shared[i['ornefnalysing']],
        })
        out.append(rec)

    by_reason = collections.Counter('+'.join(r['reasons']) for r in out)
    by_kw = collections.Counter(k for r in out for k in r['keywords'])
    by_layer = collections.Counter(r['layer'] for r in out)
    stats = {
        'input': len(items),
        'candidates': len(out),
        'dropped': dict(dropped),
        'by_reason': dict(by_reason.most_common()),
        'by_keyword_group': dict(by_kw.most_common()),
        'by_layer': dict(by_layer.most_common()),
        'no_longer_exists': sum(r['tilvist'] == 'Er ekki til' for r in out),
        'shared_description': sum(r['shared_count'] > 1 for r in out),
        'unique_descriptions': len({r['ornefnalysing'] for r in out}),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({
            'source_fetched_at': src.get('fetched_at'),
            'releases': src.get('releases'),
            'rules': {'min_clean_len': args.min_len, 'keywords': KEYWORDS},
            'stats': stats,
            'count': len(out),
            'items': out,
        }, fh, ensure_ascii=False, indent=1)

    print('Input:      %6d place names' % stats['input'])
    print('Candidates: %6d -> %s' % (stats['candidates'], args.out))
    print('Dropped:    %s' % stats['dropped'])
    print('Why kept:   %s' % stats['by_reason'])
    print('Keywords:   %s' % stats['by_keyword_group'])
    print('Layers:     %s' % stats['by_layer'])
    print('No longer exists: %d; share a description with another name: %d; unique descriptions: %d'
          % (stats['no_longer_exists'], stats['shared_description'], stats['unique_descriptions']))


if __name__ == '__main__':
    main()
