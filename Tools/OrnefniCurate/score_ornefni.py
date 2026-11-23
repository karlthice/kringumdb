#!/usr/bin/env python3
"""
Step 3 of the English örnefni curation: score candidates with Claude.

Reads data/candidates.json (from prefilter.py) and asks Claude how interesting
each place-name description is for visitors using the English version of
KringumDB. Each answer has a score (0-5), a category, a one-sentence reason
and a short English gist so a reviewer who does not read Icelandic can check
the score.

Place names that share the exact same description are scored once: the first
of them (by uuid) is sent, and the result is copied to the others when the
report is built.

Results are appended to data/scores.jsonl, one JSON object per line keyed by
the description's representative uuid, so a run can be stopped and resumed.
Already-scored descriptions are skipped.

Modes:
  --pilot N    score a random sample of N unique descriptions (seeded)
  (default)    score every unique description not yet scored
  --dry-run    print the prompt for one item and exit, no API call

Needs ANTHROPIC_API_KEY in the environment or in the repo's .env file.

Usage:
  python score_ornefni.py --pilot 300
  python score_ornefni.py --pilot 300 --dry-run
"""
import argparse
import concurrent.futures
import json
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DEFAULT_IN = os.path.join(HERE, 'data', 'candidates.json')
DEFAULT_OUT = os.path.join(HERE, 'data', 'scores.jsonl')

MODEL = 'claude-haiku-5-5'
EFFORT = 'low'
MAX_TOKENS = 4000

CATEGORIES = [
    'folklore',       # hidden people, elves, trolls, ghosts, curses, buried treasure, legends
    'tragedy',        # drownings, people lost in storms, avalanches, shipwrecks, killings
    'history',        # settlement, sagas, assemblies, churches, outlaws, notable people and events
    'way_of_life',    # shielings, fishing stations, peat cutting, sheep folds, trading, old customs
    'nature',         # unusual natural features or phenomena
    'name_origin',    # an explanation of how the place got its name
    'location_only',  # only says where the place is or what it looks like
    'other',
]

SYSTEM_PROMPT = """You help curate Icelandic place names (örnefni) for the English version of a travel app. The app shows short stories about places near the user, read by visitors to Iceland who do not know Icelandic and have no local knowledge.

Each place name comes from the official place-name database. Its description (ornefnalysing) was written by local farmers and collectors, mostly in the 20th century. Most descriptions only say where the place is. A few hold a story, a belief, an event or a glimpse of old life that a visitor would enjoy hearing about when standing there.

Score how interesting the description would be to such a visitor, judging only what the description itself says. Do not add knowledge from elsewhere, and do not reward a name that sounds interesting if the description says nothing about it.

5: A real story a visitor would remember: a legend or belief tied to the spot (hidden people, elves, trolls, ghosts, curses, buried treasure), a dramatic event (a drowning, someone lost in a storm, a killing, a shipwreck, a burial), or a named person with something happening to them.
4: Clearly interesting but less of a story: how people lived and worked here (shielings, fishing stations, outlaw hideouts, routes and crossings with some human detail), an unusual natural feature, a vivid local saying, or a name explained by an event.
3: Mildly interesting: a plain name explanation, one curious fact, or a historic remain mentioned with little detail.
2: Mostly location with a small detail (e.g. "a good fishing spot", "peat was cut here").
1: Only location, shape, size, ownership, boundaries or vegetation.
0: Fragmentary, unclear without a map, a list of names, or only a reference to another source.

Also give:
- category: the single best fit.
- reason: one short English sentence explaining the score.
- gist: one or two plain English sentences saying what the description tells, so a reviewer who does not read Icelandic can check the score. Keep Icelandic names as they are. Do not add anything the description does not say.

Being no longer in existence (tilvist "Er ekki til") does not lower the score: a vanished farm or shieling can still be a good story."""

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'score': {'type': 'integer', 'enum': [0, 1, 2, 3, 4, 5]},
        'category': {'type': 'string', 'enum': CATEGORIES},
        'reason': {'type': 'string'},
        'gist': {'type': 'string'},
    },
    'required': ['score', 'category', 'reason', 'gist'],
    'additionalProperties': False,
}


def load_env_file(path):
    """Tiny .env loader, same as the other Tools."""
    if not os.path.exists(path):
        return
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def unique_descriptions(items):
    """Group candidates by exact description; return {rep_uuid: (rep_item, [uuids])}."""
    groups = {}
    for i in sorted(items, key=lambda x: x['uuid']):
        groups.setdefault(i['ornefnalysing'], []).append(i)
    out = {}
    for members in groups.values():
        rep = members[0]
        out[rep['uuid']] = (rep, [m['uuid'] for m in members])
    return out


def user_message(item):
    lines = ['Place name: ' + item['ornefni']]
    if item.get('tvinefni'):
        lines.append('Other names: ' + item['tvinefni'])
    lines.append('Feature type (nafnberi): ' + (item.get('nafnberi') or 'unknown'))
    lines.append('Exists (tilvist): ' + (item.get('tilvist') or 'unknown'))
    lines.append('')
    lines.append('Description (ornefnalysing):')
    lines.append(item['clean_text'])
    return '\n'.join(lines)


def load_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line:
                rec = json.loads(line)
                if 'score' in rec:
                    done.add(rec['uuid'])
    return done


def score_one(client, item, anthropic):
    """Call Claude for one item; returns a result dict (with 'error' on failure)."""
    base = {'uuid': item['uuid'], 'ornefni': item['ornefni'], 'model': MODEL, 'effort': EFFORT}
    for attempt in range(5):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[{'type': 'text', 'text': SYSTEM_PROMPT,
                         'cache_control': {'type': 'ephemeral'}}],
                messages=[{'role': 'user', 'content': user_message(item)}],
                output_config={'effort': EFFORT,
                               'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA}},
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as e:
            wait = 2 ** attempt * 5
            print('  retry %s in %ds: %s' % (item['uuid'], wait, type(e).__name__), file=sys.stderr)
            time.sleep(wait)
            continue
        except anthropic.APIStatusError as e:
            return dict(base, error='%s %s' % (e.status_code, e.message))
        usage = {'input_tokens': resp.usage.input_tokens,
                 'output_tokens': resp.usage.output_tokens,
                 'cache_read_input_tokens': resp.usage.cache_read_input_tokens or 0,
                 'cache_creation_input_tokens': resp.usage.cache_creation_input_tokens or 0}
        if resp.stop_reason == 'refusal':
            cat = resp.stop_details.category if resp.stop_details else None
            return dict(base, error='refusal (%s)' % cat, usage=usage)
        if resp.stop_reason == 'max_tokens':
            return dict(base, error='max_tokens', usage=usage)
        text = next((b.text for b in resp.content if b.type == 'text'), '')
        try:
            data = json.loads(text)
        except ValueError:
            return dict(base, error='invalid JSON: ' + text[:200], usage=usage)
        return dict(base, **data, usage=usage)
    return dict(base, error='gave up after retries')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--in', dest='inp', default=DEFAULT_IN)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--pilot', type=int, default=0, help='score a random sample of N descriptions')
    ap.add_argument('--seed', type=int, default=20261123)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    with open(args.inp, encoding='utf-8') as fh:
        items = json.load(fh)['items']
    groups = unique_descriptions(items)
    reps = sorted(groups)
    if args.pilot:
        reps = sorted(random.Random(args.seed).sample(reps, min(args.pilot, len(reps))))

    done = load_done(args.out)
    todo = [groups[u][0] for u in reps if u not in done]
    print('%d unique descriptions selected, %d already scored, %d to score'
          % (len(reps), len(reps) - len(todo), len(todo)))

    if args.dry_run:
        if todo:
            print('\n--- system ---\n' + SYSTEM_PROMPT)
            print('\n--- user (first item) ---\n' + user_message(todo[0]))
            print('\n--- schema ---\n' + json.dumps(OUTPUT_SCHEMA, indent=1))
        return
    if not todo:
        return

    load_env_file(os.path.join(ROOT, '.env'))
    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('ANTHROPIC_API_KEY is not set (looked in the environment and %s)'
                 % os.path.join(ROOT, '.env'))
    import anthropic
    client = anthropic.Anthropic()

    lock = threading.Lock()
    counts = {'ok': 0, 'error': 0, 'in': 0, 'out': 0, 'cache_read': 0}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'a', encoding='utf-8') as fh, \
            concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(score_one, client, it, anthropic) for it in todo]
        for n, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            rec = fut.result()
            with lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                fh.flush()
                counts['error' if 'error' in rec else 'ok'] += 1
                u = rec.get('usage', {})
                counts['in'] += u.get('input_tokens', 0)
                counts['out'] += u.get('output_tokens', 0)
                counts['cache_read'] += u.get('cache_read_input_tokens', 0)
            if n % 25 == 0 or n == len(todo):
                print('  %d/%d scored (%d errors)' % (n, len(todo), counts['error']))

    print('\nDone: %d scored, %d errors -> %s' % (counts['ok'], counts['error'], args.out))
    print('Tokens: %d input (+%d cache reads), %d output'
          % (counts['in'], counts['cache_read'], counts['out']))


if __name__ == '__main__':
    main()
