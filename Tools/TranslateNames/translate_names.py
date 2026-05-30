#!/usr/bin/env python3
"""
Translate Icelandic item titles to English via Gemini for items that have a
translated story (story_eng) but no English title (name_eng yet empty).

Loads GEMINI_API_KEY from ../../env (.env at repo root) or the environment.
Idempotent — re-runnable; only touches rows where name_eng is empty.

Usage: python translate_names.py [--limit N] [--dry-run]
"""
import os
import sys
import time
import argparse
import sqlite3
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(HERE, '..', '..', 'kringum.db'))
ENV_PATH = os.path.normpath(os.path.join(HERE, '..', '..', '.env'))

URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent'

PROMPT = (
    "Translate this Icelandic item title to a concise English title. "
    "Keep proper nouns (place names, person names, river/mountain names) in their "
    "original Icelandic form. If the title ends with ', þjóðsaga' render that as "
    "', legend'. Return ONLY the translated title, no quotes, no commentary.\n\n"
)


def load_env_file(path):
    """Tiny .env loader — no python-dotenv dependency."""
    if not os.path.exists(path):
        return
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def translate(name, key):
    """Send a single title to Gemini, return cleaned-up English string or None."""
    resp = requests.post(
        URL,
        params={'key': key},
        json={'contents': [{'parts': [{'text': PROMPT + name}]}]},
        timeout=30,
    )
    if resp.status_code == 429:
        return ('RATE_LIMIT', None)
    resp.raise_for_status()
    j = resp.json()
    try:
        text = j['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError):
        return (None, j)
    # Strip wrapping quotes if Gemini added them
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    return (text, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='Translate at most N items (0 = no limit)')
    ap.add_argument('--dry-run', action='store_true', help="Print translations without writing to DB")
    ap.add_argument('--sleep', type=float, default=0.15, help='Seconds between successful calls (default 0.15)')
    args = ap.parse_args()

    load_env_file(ENV_PATH)
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key:
        sys.exit('GEMINI_API_KEY not set (looked in env and .env)')

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, name FROM items "
        "WHERE story_eng IS NOT NULL AND TRIM(story_eng)<>'' "
        "AND (name_eng IS NULL OR TRIM(name_eng)='') "
        "ORDER BY id"
    ).fetchall()
    total = len(rows)
    if args.limit > 0:
        rows = rows[:args.limit]
    print(f'Candidates: {total}; will process: {len(rows)}{"  (dry-run)" if args.dry_run else ""}')

    done = 0
    failed = []
    backoff = 1.0
    for r in rows:
        nid, name = r['id'], r['name']
        try:
            eng, info = translate(name, key)
        except Exception as e:
            print(f'  [{nid}] http error: {e}; backing off {backoff:.1f}s')
            failed.append(nid)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
        if eng == 'RATE_LIMIT':
            print(f'  [{nid}] 429; backing off {backoff:.1f}s')
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        if not eng:
            print(f'  [{nid}] no candidate text; skip. ({str(info)[:120]})')
            failed.append(nid)
            continue
        backoff = 1.0
        if args.dry_run:
            print(f'  [{nid}] {name!r} -> {eng!r}')
        else:
            db.execute('UPDATE items SET name_eng=? WHERE id=?', (eng, nid))
            db.commit()
        done += 1
        if done % 25 == 0:
            print(f'  [{done}/{len(rows)}] last: {name!r} -> {eng!r}')
        time.sleep(args.sleep)

    print()
    print(f'Done: {done} translated, {len(failed)} failed.')
    if failed:
        print('Failed ids (first 30):', failed[:30])


if __name__ == '__main__':
    main()
