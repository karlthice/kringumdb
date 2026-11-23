#!/usr/bin/env python3
"""
Step 4 of the English örnefni curation: summarise the scores for review.

Joins data/scores.jsonl (from score_ornefni.py) with data/candidates.json,
copies each description's score to every place name that shares it, and
writes:
  data/scores_report.csv  one row per scored place name, best first
and prints the score distribution, the cost so far, how many place names each
cut-off would keep across all candidates (extrapolated from the scored ones),
and a few examples for every score.

Usage: python report_scores.py [--examples N]
"""
import argparse
import collections
import csv
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = os.path.join(HERE, 'data', 'candidates.json')
SCORES = os.path.join(HERE, 'data', 'scores.jsonl')
REPORT = os.path.join(HERE, 'data', 'scores_report.csv')

# Claude Haiku 5.5, USD per million tokens (standard API, prompts up to 100K tokens).
PRICE = {'input': 0.10, 'output': 0.50, 'cache_read': 0.01, 'cache_write': 0.125}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--examples', type=int, default=3)
    ap.add_argument('--seed', type=int, default=1)
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

    scores, errors, usage = {}, [], collections.Counter()
    for line in open(SCORES, encoding='utf-8'):
        if not line.strip():
            continue
        r = json.loads(line)
        for k, v in r.get('usage', {}).items():
            usage[k] += v
        if 'score' in r:
            scores[r['uuid']] = r
        else:
            errors.append(r)

    rows = []
    for i in items:
        s = scores.get(rep_of[i['uuid']])
        if s:
            rows.append((i, s))
    rows.sort(key=lambda t: (-t[1]['score'], t[0]['ornefni']))

    with open(REPORT, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['score', 'category', 'ornefni', 'nafnberi', 'tilvist', 'gps', 'reason',
                    'gist', 'ornefnalysing', 'uuid', 'prefilter_reasons', 'shared_count'])
        for i, s in rows:
            w.writerow([s['score'], s['category'], i['ornefni'], i['nafnberi'], i['tilvist'],
                        i['gps'], s['reason'], s['gist'], i['clean_text'], i['uuid'],
                        '+'.join(i['reasons']), i['shared_count']])

    n_desc = len(scores)
    total_desc = len(by_desc)
    dist = collections.Counter(s['score'] for s in scores.values())
    cats = collections.Counter(s['category'] for s in scores.values())
    cost = (usage['input_tokens'] * PRICE['input'] + usage['output_tokens'] * PRICE['output']
            + usage['cache_read_input_tokens'] * PRICE['cache_read']
            + usage['cache_creation_input_tokens'] * PRICE['cache_write']) / 1e6

    print('Scored %d of %d unique descriptions (%d place names), %d errors'
          % (n_desc, total_desc, len(rows), len(errors)))
    for e in errors[:10]:
        print('  error %s %s: %s' % (e['uuid'], e['ornefni'], e['error']))
    print('Tokens: %d input, %d cache reads, %d cache writes, %d output; cost about $%.3f'
          % (usage['input_tokens'], usage['cache_read_input_tokens'],
             usage['cache_creation_input_tokens'], usage['output_tokens'], cost))
    if n_desc:
        print('Estimated cost for all %d descriptions: about $%.2f standard, $%.2f with the Batch API'
              % (total_desc, cost / n_desc * total_desc, cost / n_desc * total_desc / 2))

    print('\nScore distribution (unique descriptions):')
    for sc in range(5, -1, -1):
        n = dist.get(sc, 0)
        print('  %d: %4d  (%4.1f%%)' % (sc, n, 100.0 * n / max(n_desc, 1)))
    print('Categories: %s' % dict(cats.most_common()))

    if n_desc:
        print('\nIf the same rates hold for all %d candidates (place names):' % len(items))
        for cut in (5, 4, 3):
            kept = sum(1 for _, s in rows if s['score'] >= cut)
            print('  score >= %d: about %d place names' % (cut, round(kept / len(rows) * len(items))))

    rnd = random.Random(args.seed)
    print('\nExamples:')
    for sc in range(5, -1, -1):
        pool = [(i, s) for i, s in rows if s['score'] == sc]
        if not pool:
            continue
        print('\n== score %d ==' % sc)
        for i, s in rnd.sample(pool, min(args.examples, len(pool))):
            print('- %s (%s, %s): %s' % (i['ornefni'], i['nafnberi'], s['category'], s['gist']))
            print('    why: %s' % s['reason'])
    print('\nFull list: %s' % REPORT)


if __name__ == '__main__':
    main()
