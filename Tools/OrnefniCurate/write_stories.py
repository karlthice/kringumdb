#!/usr/bin/env python3
"""
Step 5 of the English örnefni curation: write English names and stories.

Reads data/candidates.json and a scores file (from score_ornefni.py), picks
every place name whose description scored at least --min-score, and asks
Claude for an English title (name_eng), a short English story (story_eng) and a
cleaned Icelandic story (story_is), written only from the Icelandic description. The writer may skip a place name
when the description has nothing worth telling about it.

One request per place name (uuid), not per description: place names that
share a description get their own text, and the writer skips the ones the
description is not really about.

Results are appended to data/stories.jsonl (resumable: uuids already written
are skipped), and data/stories_review.csv is rebuilt after each run with the
Icelandic text next to the English for review. Nothing is written to
kringum.db or curated.json.

Usage:
  python write_stories.py --scores data/pilot_scores.jsonl   # the pilot sample
  python write_stories.py                                     # everything scored >= 3
  python write_stories.py --limit 5 --dry-run                 # show the prompt
"""
import argparse
import collections
import concurrent.futures
import csv
import json
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
CANDIDATES = os.path.join(HERE, 'data', 'candidates.json')
DEFAULT_SCORES = os.path.join(HERE, 'data', 'scores.jsonl')
DEFAULT_OUT = os.path.join(HERE, 'data', 'stories.jsonl')
REVIEW = os.path.join(HERE, 'data', 'stories_review.csv')

MODEL = 'claude-opus-5-5'
EFFORT = 'medium'
MAX_TOKENS = 8000
# Claude Opus 5.5, USD per million tokens.
PRICE = {'input': 4.00, 'output': 20.00, 'cache_read': 0.20, 'cache_write': 5.00}

SYSTEM_PROMPT = """You write short English texts about Icelandic place names (örnefni) for the English version of KringumDB, a travel app that shows visitors stories about the places around them. The readers are visitors to Iceland who do not know Icelandic and have no local knowledge.

For each request you get one place name, its feature type (nafnberi) and its description (ornefnalysing) from the official place-name database of the National Land Survey of Iceland. The descriptions were written by local farmers and collectors, mostly in the 20th century.

Return:

name_eng: the Icelandic name exactly as given, a comma, and the feature type in plain English, lower case. Examples: "Víti, crater", "Kerlingin, cliff", "Líkvarða, cairn", "Seljahryggur, shieling ridge", "Gvendarbrunnur, spring".

story_eng: the English text. Rules:
- Be faithful. Say only what the description says. Do not add facts, dates, names, numbers, motives, feelings, weather or drama that are not in the description, and do not fill gaps with guesses. If the description hedges ("talið er", "sagt er", "á að hafa"), keep the hedge ("is believed to", "is said to").
- Keep every detail that makes the place interesting, even small ones (for example that a ridge was full of fox dens, or that a stream was blessed). Drop only what means nothing to a visitor.
- Lead with what is interesting about the place: the story, the belief, the event, or the glimpse of old life. Give location only where it helps someone standing nearby (for example "directly below the farm", "beside the old road"); leave out chains of neighbouring place names, map numbers, page references and the names of the people who collected the description.
- Keep the length in proportion to the description. A one-sentence description gets one to three sentences. Never write more than about 1200 characters.
- Keep all Icelandic names of people, farms and places in their Icelandic form, with accents.
- You may briefly explain Icelandic terms a visitor would not know, such as sel (a summer shieling where livestock were kept and milked), beitarhús (a sheep house out in the grazing land), huldufólk (hidden people) or Guðmundur góði (Guðmundur the Good, a 13th-century bishop said to have blessed many springs and wells). You may give the meaning of a place name only when the description explains it or the name is made of plain, common words (for example tóa, an old word for fox). Nothing else from outside the description.
- If the description says the place or its buildings are gone, say so.
- Write plain, warm, factual English in the past or present tense as fits. No exclamation marks, no travel-brochure phrases ("nestled", "hidden gem", "steeped in history"), no addressing the reader, no title.

story_is: the Icelandic text for the app's Icelandic version, which may also be read aloud. Rules:
- Base it on the original Icelandic wording. Keep the sentences as they are written wherever they read well; edit only what is needed. Do not translate back from your English text.
- Remove what is not part of the story: collectors' and informants' initials and names used as source references (e.g. "Örnefnaskrá Hrauns. HK:", "(J.G.)", "Í vinnuhandriti Kjartans Ólafssonar ... stendur:"), map numbers, page references, editorial notes and asides such as "(aðspurður)". Keep a person's name when the person is part of the story.
- Follow the same choices as the English: lead with what is interesting, keep the location only where it helps someone standing nearby, leave out chains of neighbouring names that mean nothing to a visitor. Keep every interesting detail.
- Add nothing that is not in the description: no explanations, no background, no new facts. Keep hedges ("talið er", "sagt er").
- Write correct, natural modern Icelandic with correct declension, and fix obvious typos. Keep old words and local names that are part of the story.
- No title, and do not start with a definition like "X er klif."

skip: true when the description has nothing worth telling a visitor about this particular place (only location, boundaries, ownership or a list of names), or when it is really about a different place than the name given (some descriptions are shared between neighbouring names). Then leave story_eng and story_is empty and give the reason in skip_reason. Otherwise skip is false and skip_reason is empty."""

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'skip': {'type': 'boolean'},
        'skip_reason': {'type': 'string'},
        'name_eng': {'type': 'string'},
        'story_eng': {'type': 'string'},
        'story_is': {'type': 'string'},
    },
    'required': ['skip', 'skip_reason', 'name_eng', 'story_eng', 'story_is'],
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


def load_scores(path):
    """{rep_uuid: score record}; later lines win, error lines are ignored."""
    scores = {}
    for line in open(path, encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            if 'score' in r:
                scores[r['uuid']] = r
    return scores


def eligible(items, scores, min_score):
    """[(item, score_record)] for every place name whose description scored >= min_score."""
    by_desc = collections.defaultdict(list)
    for i in items:
        by_desc[i['ornefnalysing']].append(i)
    out = []
    for members in by_desc.values():
        members.sort(key=lambda x: x['uuid'])
        s = scores.get(members[0]['uuid'])
        if s and s['score'] >= min_score:
            out.extend((m, s) for m in members)
    out.sort(key=lambda t: t[0]['uuid'])
    return out


def user_message(item):
    lines = ['Place name: ' + item['ornefni']]
    if item.get('tvinefni'):
        lines.append('Other names: ' + item['tvinefni'])
    lines.append('Feature type (nafnberi): ' + (item.get('nafnberi') or 'unknown'))
    lines.append('Exists (tilvist): ' + (item.get('tilvist') or 'unknown'))
    if item.get('shared_count', 1) > 1:
        lines.append('Note: this exact description is shared by %d place names, so it may be '
                     'about a neighbouring place.' % item['shared_count'])
    lines.append('')
    lines.append('Description (ornefnalysing):')
    lines.append(item['clean_text'])
    return '\n'.join(lines)


def load_done(path):
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            if line.strip():
                rec = json.loads(line)
                if 'error' not in rec:
                    done.add(rec['uuid'])
    return done


def write_one(client, item, anthropic):
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
        u = resp.usage
        usage = {'input_tokens': u.input_tokens, 'output_tokens': u.output_tokens,
                 'cache_read_input_tokens': u.cache_read_input_tokens or 0,
                 'cache_creation_input_tokens': u.cache_creation_input_tokens or 0}
        if resp.stop_reason == 'refusal':
            sd = getattr(resp, 'stop_details', None)
            return dict(base, error='refusal (%s)' % getattr(sd, 'category', None), usage=usage)
        if resp.stop_reason == 'max_tokens':
            return dict(base, error='max_tokens', usage=usage)
        text = next((b.text for b in resp.content if b.type == 'text'), '')
        try:
            data = json.loads(text)
        except ValueError:
            return dict(base, error='invalid JSON: ' + text[:200], usage=usage)
        return dict(base, **data, usage=usage)
    return dict(base, error='gave up after retries')


def cost_of(usage):
    return (usage['input_tokens'] * PRICE['input'] + usage['output_tokens'] * PRICE['output']
            + usage['cache_read_input_tokens'] * PRICE['cache_read']
            + usage['cache_creation_input_tokens'] * PRICE['cache_write']) / 1e6


def write_review(out_path, chosen):
    """Rebuild the review CSV from every successful record in out_path."""
    by_uuid = {i['uuid']: (i, s) for i, s in chosen}
    recs = {}
    for line in open(out_path, encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            if 'error' not in r and r['uuid'] in by_uuid:
                recs[r['uuid']] = r
    rows = sorted(recs.values(), key=lambda r: (-by_uuid[r['uuid']][1]['score'], r['ornefni']))
    with open(REVIEW, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['score', 'skip', 'ornefni', 'name_eng', 'story_eng', 'story_is', 'skip_reason',
                    'ornefnalysing', 'category', 'nafnberi', 'gps', 'uuid'])
        for r in rows:
            i, s = by_uuid[r['uuid']]
            w.writerow([s['score'], 'yes' if r['skip'] else '', i['ornefni'], r['name_eng'],
                        r['story_eng'], r.get('story_is', ''), r['skip_reason'], i['clean_text'],
                        s['category'], i['nafnberi'], i['gps'], i['uuid']])
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--scores', default=DEFAULT_SCORES)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--min-score', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0, help='only a seeded random sample of N place names')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    items = json.load(open(CANDIDATES, encoding='utf-8'))['items']
    chosen = eligible(items, load_scores(args.scores), args.min_score)
    if args.limit:
        chosen = sorted(random.Random(args.seed).sample(chosen, min(args.limit, len(chosen))),
                        key=lambda t: t[0]['uuid'])
    done = load_done(args.out)
    todo = [i for i, _ in chosen if i['uuid'] not in done]
    print('%d place names scored >= %d, %d already written, %d to write'
          % (len(chosen), args.min_score, len(chosen) - len(todo), len(todo)))

    if args.dry_run:
        if todo:
            print('\n--- system ---\n' + SYSTEM_PROMPT)
            print('\n--- user (first item) ---\n' + user_message(todo[0]))
        return

    if todo:
        load_env_file(os.path.join(ROOT, '.env'))
        if not (os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ORNEFNI_KEY')):
            sys.exit('No API key: set ANTHROPIC_API_KEY or ORNEFNI_KEY')
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY')
                                     or os.environ.get('ORNEFNI_KEY'))

        lock = threading.Lock()
        counts = collections.Counter()
        usage = collections.Counter()
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'a', encoding='utf-8') as fh, \
                concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(write_one, client, it, anthropic) for it in todo]
            for n, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                rec = fut.result()
                with lock:
                    fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    fh.flush()
                    if 'error' in rec:
                        counts['error'] += 1
                        print('  error %s %s: %s' % (rec['uuid'], rec['ornefni'], rec['error']),
                              file=sys.stderr)
                    else:
                        counts['skip' if rec['skip'] else 'written'] += 1
                    usage.update(rec.get('usage', {}))
                if n % 25 == 0 or n == len(todo):
                    print('  %d/%d done (%d errors)' % (n, len(todo), counts['error']), flush=True)

        cost = cost_of(usage)
        print('\nThis run: %d written, %d skipped, %d errors -> %s'
              % (counts['written'], counts['skip'], counts['error'], args.out))
        print('Tokens: %d input, %d cache reads, %d cache writes, %d output; cost about $%.2f'
              % (usage['input_tokens'], usage['cache_read_input_tokens'],
                 usage['cache_creation_input_tokens'], usage['output_tokens'], cost))
        if todo:
            print('About $%.3f per place name' % (cost / len(todo)))

    n = write_review(args.out, chosen)
    print('Review file: %s (%d rows)' % (REVIEW, n))


if __name__ == '__main__':
    main()
