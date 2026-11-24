#!/usr/bin/env python3
"""
Translate the items that are in the English export but have no English text.

Picks every item that /api/export?language=ENG would export (has gps, name not
starting with * or +, not an Örnefni) whose story_eng is empty and whose
Icelandic story is not, and asks Claude for story_eng and, when name_eng is
empty, name_eng, following the conventions of the existing translations.

Two stages:
  python translate_missing.py               # translate -> results.jsonl (resumable)
  python translate_missing.py --apply       # back up kringum.db, then write the
                                            # results into empty story_eng/name_eng
Options: --limit N (seeded sample), --dry-run (print the prompt), --ids 1,2,3
"""
import argparse
import collections
import concurrent.futures
import datetime
import json
import os
import random
import shutil
import sqlite3
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DB_PATH = os.path.join(ROOT, 'kringum.db')
OUT = os.path.join(HERE, 'results.jsonl')

MODEL = 'claude-opus-5-5'
EFFORT = 'medium'
MAX_TOKENS = 16000
PRICE = {'input': 4.00, 'output': 20.00, 'cache_read': 0.20, 'cache_write': 5.00}

SYSTEM_PROMPT = """You translate entries in KringumDB, an Icelandic travel app that shows people stories about the places around them, from Icelandic into English for the app's English version. Readers are visitors to Iceland.

Each request gives an item's Icelandic title, its category, and its Icelandic text. Return name_eng (the English title) and story_eng (the English text).

The text:
- Translate faithfully and completely into natural, fluent English. Do not summarise, shorten, add or explain anything, and do not comment on the text.
- Keep the layout: the same paragraphs and blank lines, and any HTML tags or markup exactly as they are.
- Keep Icelandic names of people, farms, places and institutions in their Icelandic form, with accents.
- Quotations (book excerpts, poems, the text from a book cover) are translated faithfully as well, keeping the quotation marks. For poems, give a faithful line-by-line translation; do not try to rhyme.
- Standard headings used in these entries: "Af bókarkápu:" -> "From the book cover:", "Upphaf sögunnar:" -> "Beginning of the story:", "Úr bókinni:" -> "From the book:".
- A title of a book, poem or work: use its published English title only when you are certain one exists (for example Sjálfstætt fólk -> Independent People, Ég man þig -> I Remember You). Otherwise translate the title literally. In the text, give the work's title in English only, without the Icelandic original in brackets (for example "I Remember You by Yrsa Sigurðardóttir", "Deception by Sigurjón Pálsson (2012)").

The title (name_eng):
- Keep the structure of the Icelandic title. Proper names stay in Icelandic; common words are translated.
- Titles often end with a category word after a comma. Translate it the way the rest of the database does: bókmenntir -> literature, dýralíf -> wildlife, þjóðsaga -> legend, bær -> farm, torfbær -> turf farm, eyðibýli -> abandoned farm, gönguleið -> hiking trail, listaverk -> artwork, ljóð -> poem. A year stays as it is.
- Examples from the database: "Sjálfstætt fólk, bókmenntir" -> "Independent People, literature"; "Orðin sem aldrei voru sögð, bókmenntir" -> "The words that were never said, literature"; "Haftyrðill, dýralíf" -> "Little auk, wildlife"; "Melrakki, dýralíf" -> "Fox, wildlife"; "Gil, eyðibýli" -> "Gil, abandoned farm"; "Krimmi - Vitnið" -> "Krimmi - Witness"; "Laxárdalur, bær" -> "Laxárdalur, farm"; "Lundarkirkja" -> "Lundarkirkja, church"."""

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {'name_eng': {'type': 'string'}, 'story_eng': {'type': 'string'}},
    'required': ['name_eng', 'story_eng'],
    'additionalProperties': False,
}


def load_env_file(path):
    if not os.path.exists(path):
        return
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def missing_items(db):
    """Rows the English export would include that have no story_eng (same walk as app.export)."""
    out, last_name, last_gps = [], '', ''
    for r in db.execute('SELECT * FROM items ORDER BY name').fetchall():
        gps = (r['gps'] or '').replace(' ', '')
        name = r['name'] or ''
        if not gps or name.startswith('*') or name.startswith('+'):
            continue
        if name == last_name and gps == last_gps:
            continue
        if (r['tag'] or '') == 'Örnefni':
            continue
        last_name, last_gps = name, gps
        if not (r['story_eng'] or '').strip() and len((r['story'] or '').strip()) >= 5:
            out.append(r)
    return out


def user_message(r):
    return 'Title: %s\nCategory (tag): %s\n\nText:\n%s' % (r['name'], r['tag'] or '', r['story'])


def translate_one(client, r, anthropic):
    base = {'id': r['id'], 'name': r['name'], 'model': MODEL}
    for attempt in range(5):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                system=[{'type': 'text', 'text': SYSTEM_PROMPT,
                         'cache_control': {'type': 'ephemeral'}}],
                messages=[{'role': 'user', 'content': user_message(r)}],
                output_config={'effort': EFFORT,
                               'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA}},
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as e:
            time.sleep(2 ** attempt * 5)
            continue
        except anthropic.APIStatusError as e:
            return dict(base, error='%s %s' % (e.status_code, e.message))
        u = resp.usage
        usage = {'input_tokens': u.input_tokens, 'output_tokens': u.output_tokens,
                 'cache_read_input_tokens': u.cache_read_input_tokens or 0,
                 'cache_creation_input_tokens': u.cache_creation_input_tokens or 0}
        if resp.stop_reason in ('refusal', 'max_tokens'):
            return dict(base, error=resp.stop_reason, usage=usage)
        text = next((b.text for b in resp.content if b.type == 'text'), '')
        try:
            data = json.loads(text)
        except ValueError:
            return dict(base, error='invalid JSON: ' + text[:200], usage=usage)
        return dict(base, **data, usage=usage)
    return dict(base, error='gave up after retries')


def load_results():
    res = {}
    if os.path.exists(OUT):
        for line in open(OUT, encoding='utf-8'):
            if line.strip():
                r = json.loads(line)
                if 'error' not in r:
                    res[r['id']] = r
    return res


def apply(db):
    res = load_results()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = DB_PATH + '.bak-' + stamp
    shutil.copy2(DB_PATH, backup)
    print('Backup: %s' % backup)
    n_story = n_name = 0
    for rid, r in res.items():
        cur = db.execute("UPDATE items SET story_eng=?, lastchanged=datetime('now') "
                         "WHERE id=? AND IFNULL(TRIM(story_eng),'')=''", (r['story_eng'].strip(), rid))
        n_story += cur.rowcount
        cur = db.execute("UPDATE items SET name_eng=? WHERE id=? AND IFNULL(TRIM(name_eng),'')=''",
                         (r['name_eng'].strip(), rid))
        n_name += cur.rowcount
    db.commit()
    print('Wrote story_eng on %d items and name_eng on %d items' % (n_story, n_name))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--ids', default='')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    if args.apply:
        apply(db)
        return

    rows = missing_items(db)
    if args.ids:
        want = {int(x) for x in args.ids.split(',')}
        rows = [r for r in rows if r['id'] in want]
    if args.limit:
        rows = random.Random(args.seed).sample(rows, min(args.limit, len(rows)))
    done = load_results()
    todo = [r for r in rows if r['id'] not in done]
    print('%d items without English text, %d already translated, %d to translate'
          % (len(rows), len(rows) - len(todo), len(todo)))
    if args.dry_run:
        if todo:
            print('\n--- system ---\n' + SYSTEM_PROMPT + '\n\n--- user ---\n' + user_message(todo[0]))
        return
    if not todo:
        return

    load_env_file(os.path.join(ROOT, '.env'))
    import anthropic
    client = anthropic.Anthropic()
    lock, counts, usage = threading.Lock(), collections.Counter(), collections.Counter()
    with open(OUT, 'a', encoding='utf-8') as fh, \
            concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(translate_one, client, r, anthropic) for r in todo]
        for n, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            rec = fut.result()
            with lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                fh.flush()
                counts['error' if 'error' in rec else 'ok'] += 1
                if 'error' in rec:
                    print('  error %s %s: %s' % (rec['id'], rec['name'], rec['error']), file=sys.stderr)
                usage.update(rec.get('usage', {}))
            if n % 25 == 0 or n == len(todo):
                print('  %d/%d done (%d errors)' % (n, len(todo), counts['error']), flush=True)
    cost = (usage['input_tokens'] * PRICE['input'] + usage['output_tokens'] * PRICE['output']
            + usage['cache_read_input_tokens'] * PRICE['cache_read']
            + usage['cache_creation_input_tokens'] * PRICE['cache_write']) / 1e6
    print('Done: %d translated, %d errors -> %s; cost about $%.2f' % (counts['ok'], counts['error'], OUT, cost))


if __name__ == '__main__':
    main()
