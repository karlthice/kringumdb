import math
import io
import json
import zipfile
import sqlite3
from flask import Flask, g, request, jsonify, send_from_directory, send_file
import requests as http_requests
import config

app = Flask(__name__, static_folder='static', static_url_path='/static')

WIKI_HEADERS = {'User-Agent': 'KringumDB/1.0 (https://github.com/kringum; kringum@example.com)'}


# --- Database helpers ---

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(config.DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


# --- Haversine distance ---

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def has_location(gps):
    """True if gps is a usable "lat,lon" coordinate. Empty, the NOLOC sentinel
    (any case), and comma-less values all count as no location, so such items
    are kept off the map, out of nearby results, and out of the export."""
    gps = (gps or '').replace(' ', '')
    if not gps or gps.upper() == 'NOLOC':
        return False
    return ',' in gps


# --- Static serving ---

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# --- API: Items ---

@app.route('/api/items', methods=['POST'])
def get_items():
    data = request.get_json(force=True)
    filt = (data.get('filter') or '').strip()
    db = get_db()

    # Örnefni (place-name imports) are export-only: hide them from the map and item list.
    if not filt:
        rows = db.execute(
            "SELECT * FROM items WHERE IFNULL(tag,'') <> 'Örnefni' ORDER BY id DESC"
        ).fetchall()
    elif len(filt) == 1:
        rows = db.execute(
            "SELECT * FROM items WHERE UPPER(name) LIKE UPPER(? || '%') AND IFNULL(tag,'') <> 'Örnefni' ORDER BY name",
            (filt,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM items WHERE (UPPER(story) LIKE UPPER('%' || ? || '%') OR UPPER(name) LIKE UPPER('%' || ? || '%')) AND IFNULL(tag,'') <> 'Örnefni' ORDER BY id DESC",
            (filt, filt)
        ).fetchall()

    # Map each item to its curated areas (id + caption) via the join table
    area_map = {}
    for r in db.execute(
        """SELECT a2i.item_id AS item_id, ar.id AS area_id, ar.caption AS caption
           FROM area2item a2i JOIN areas ar ON ar.id = a2i.area_id"""
    ).fetchall():
        area_map.setdefault(r['item_id'], []).append((str(r['area_id']), r['caption']))

    items = []
    total_translate = 0
    total_done = 0

    for row in rows:
        item_areas = area_map.get(row['id'], [])
        items.append({
            'ID': row['id'],
            'Name': row['name'],
            'GPS': row['gps'],
            'Tag': row['tag'],
            'Story': row['story'],
            'StoryEng': row['story_eng'],
            'NameEng': row['name_eng'],
            'Link': row['link'],
            'LinkEng': row['link_eng'],
            'Visibility': row['visibility'],
            'Ref': row['ref'],
            'Area': ', '.join(c for _, c in item_areas),
            'AreaIds': [aid for aid, _ in item_areas],
        })

        name = row['name'] or ''
        if filt and 'þjóðsaga' in filt:
            total_translate += 1
            if row['story_eng']:
                total_done += 1
        else:
            if 'þjóðsaga' not in name and 'bókmenntir' not in name:
                total_translate += 1
                if row['story_eng']:
                    total_done += 1

    return jsonify({
        'TotalTranslate': total_translate,
        'TotalDone': total_done,
        'Items': items,
        'Count': len(items),
        'Error': ''
    })


@app.route('/api/items/delete', methods=['POST'])
def delete_item():
    d = request.get_json(force=True)
    item_id = d.get('id', '').strip()
    if not item_id:
        return jsonify({'error': 'No id provided'}), 400
    db = get_db()
    db.execute("DELETE FROM items WHERE id=?", (item_id,))
    db.commit()
    return jsonify({'success': True})


@app.route('/api/items/save', methods=['POST'])
def save_item():
    d = request.get_json(force=True)
    db = get_db()
    item_id = d.get('id', '').strip()

    if not item_id:
        cur = db.execute(
            """INSERT INTO items (name, name_eng, gps, tag, fromdate, todate, story, story_eng, ref, link, link_eng, visibility, lastchanged)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (d.get('name'), d.get('name_eng'), d.get('gps'), d.get('tag'),
             d.get('fromdate', ''), d.get('todate', ''),
             d.get('story'), d.get('story_eng'),
             d.get('ref'), d.get('link'), d.get('link_eng'),
             d.get('visibility', 0))
        )
        item_id = cur.lastrowid
    else:
        item_id = int(item_id)
        db.execute(
            """UPDATE items SET name=?, name_eng=?, gps=?, tag=?, fromdate=?, todate=?,
               story=?, story_eng=?, ref=?, link=?, link_eng=?, visibility=?, lastchanged=datetime('now')
               WHERE id=?""",
            (d.get('name'), d.get('name_eng'), d.get('gps'), d.get('tag'),
             d.get('fromdate', ''), d.get('todate', ''),
             d.get('story'), d.get('story_eng'),
             d.get('ref'), d.get('link'), d.get('link_eng'),
             d.get('visibility', 0), item_id)
        )

    # Rewrite curated area membership
    db.execute("DELETE FROM area2item WHERE item_id=?", (item_id,))
    for aid in (d.get('areas') or []):
        db.execute("INSERT OR IGNORE INTO area2item (area_id, item_id) VALUES (?, ?)", (int(aid), item_id))

    db.commit()
    return jsonify({'success': True})


# --- API: Areas ---

@app.route('/api/areas', methods=['GET'])
def get_areas():
    db = get_db()
    rows = db.execute("SELECT * FROM areas ORDER BY caption").fetchall()
    areas = [{
        'ID': r['id'], 'Caption': r['caption'], 'CaptionEng': r['caption_eng'],
        'GPS': r['gps'], 'Radius': r['radius'],
        'Description': r['description'], 'DescriptionEng': r['description_eng'],
        'Media': r['media'], 'Visibility': r['visibility']
    } for r in rows]
    return jsonify({'Areas': areas})


@app.route('/api/areas/<area_id>', methods=['GET'])
def get_area_by_id(area_id):
    db = get_db()
    if area_id == 'new':
        return jsonify({'Area': {
            'ID': '', 'Caption': '', 'CaptionEng': '', 'GPS': '',
            'Radius': 1000, 'Description': '', 'DescriptionEng': '',
            'Media': '', 'Visibility': 1
        }})
    row = db.execute("SELECT * FROM areas WHERE id=?", (area_id,)).fetchone()
    if not row:
        return jsonify({'Error': 'Area not found'}), 404
    return jsonify({'Area': {
        'ID': row['id'], 'Caption': row['caption'], 'CaptionEng': row['caption_eng'],
        'GPS': row['gps'], 'Radius': row['radius'],
        'Description': row['description'], 'DescriptionEng': row['description_eng'],
        'Media': row['media'], 'Visibility': row['visibility']
    }})


@app.route('/api/areas/save', methods=['POST'])
def save_area():
    d = request.get_json(force=True)
    db = get_db()
    area_id = d.get('id', '').strip() if d.get('id') else ''

    if not area_id:
        db.execute(
            """INSERT INTO areas (caption, caption_eng, gps, radius, description, description_eng, media, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (d.get('caption'), d.get('caption_eng'), d.get('gps'), d.get('radius', 1000),
             d.get('description'), d.get('description_eng'), d.get('media'), d.get('visibility', 0))
        )
    else:
        db.execute(
            """UPDATE areas SET caption=?, caption_eng=?, gps=?, radius=?, description=?, description_eng=?, media=?, visibility=?
               WHERE id=?""",
            (d.get('caption'), d.get('caption_eng'), d.get('gps'), d.get('radius', 1000),
             d.get('description'), d.get('description_eng'), d.get('media'), d.get('visibility', 0), area_id)
        )
    db.commit()
    return jsonify({'success': True})


@app.route('/api/areas/<int:area_id>/items', methods=['GET'])
def items_in_area(area_id):
    db = get_db()
    rows = db.execute(
        """SELECT i.id, i.name, i.tag
           FROM area2item a2i JOIN items i ON i.id = a2i.item_id
           WHERE a2i.area_id = ?
           ORDER BY i.name""",
        (area_id,)
    ).fetchall()
    items = [{'ID': r['id'], 'Name': r['name'], 'Tag': r['tag']} for r in rows]
    return jsonify({'Items': items})


# --- API: Nearby ---

@app.route('/api/nearby', methods=['POST'])
def nearby():
    data = request.get_json(force=True)
    gps = (data.get('gps') or '').replace(' ', '')
    if not has_location(gps):
        return jsonify({'Nearby': []})

    try:
        lat2, lon2 = float(gps.split(',')[0]), float(gps.split(',')[1])
    except (ValueError, IndexError):
        return jsonify({'Nearby': []})

    db = get_db()
    rows = db.execute("SELECT * FROM items ORDER BY name").fetchall()

    results = []
    last_name = ''
    last_gps = ''

    for row in rows:
        item_gps = (row['gps'] or '').replace(' ', '')
        if not has_location(item_gps):
            continue
        name = row['name'] or ''
        if name.startswith('*') or name.startswith('+'):
            continue
        if name == last_name and item_gps == last_gps:
            continue
        tag = row['tag'] or ''
        if 'Gisting' in tag:
            continue

        try:
            lat1, lon1 = float(item_gps.split(',')[0]), float(item_gps.split(',')[1])
        except (ValueError, IndexError):
            continue

        dist = haversine(lat1, lon1, lat2, lon2)
        if dist < 4000:
            results.append({'key': name, 'value': math.floor(dist)})

        last_name = name
        last_gps = item_gps

    results.sort(key=lambda x: x['value'])
    return jsonify({'Nearby': results[:10]})


# --- API: Export ---

@app.route('/api/export', methods=['GET'])
def export():
    language = request.args.get('language', '')
    db = get_db()

    # Export items
    rows = db.execute("SELECT * FROM items ORDER BY name").fetchall()
    items_out = []
    last_name = ''
    last_gps = ''

    for row in rows:
        item_gps = (row['gps'] or '').replace(' ', '')
        if not has_location(item_gps):
            continue
        name_val = row['name'] or ''
        if name_val.startswith('*') or name_val.startswith('+'):
            continue
        if name_val == last_name and item_gps == last_gps:
            continue
        # Örnefni are Icelandic-only: exclude them from the English export.
        if language == 'ENG' and (row['tag'] or '') == 'Örnefni':
            continue

        lat, lon = item_gps.split(',')[0], item_gps.split(',')[1]

        if language == 'ENG':
            story = row['story_eng'] or ''
            name = row['name_eng'] or ''
            link = row['link_eng'] or ''
        else:
            story = row['story'] or ''
            name = row['name'] or ''
            link = row['link'] or ''

        # Text cleanup
        story = story.replace('<p>', '\n\n').replace('<br>', '\n\n')
        story = story.replace('(1,2)', '').replace('#47;', ' ').replace('amp;', ' ').replace('#39;', ' ')

        items_out.append({
            'id': str(row['id']), 'name': name, 'story': story,
            'tag': row['tag'], 'reference': row['ref'], 'source': row['source'],
            'gps': item_gps, 'lat': lat, 'lon': lon,
            'link': link, 'visibility': row['visibility']
        })
        last_name = name_val
        last_gps = item_gps

    # Export areas (with their curated item ids)
    area_items = {}
    for r in db.execute("SELECT area_id, item_id FROM area2item").fetchall():
        area_items.setdefault(r['area_id'], []).append(str(r['item_id']))

    area_rows = db.execute("SELECT * FROM areas ORDER BY caption").fetchall()
    areas_out = []
    for row in area_rows:
        area_gps = (row['gps'] or '').replace(' ', '')
        if not has_location(area_gps):
            continue
        caption_val = row['caption'] or ''
        if caption_val.startswith('*') or caption_val.startswith('+'):
            continue

        lat, lon = area_gps.split(',')[0], area_gps.split(',')[1]

        if language == 'ENG':
            description = row['description_eng'] or ''
            caption = row['caption_eng'] or ''
        else:
            description = row['description'] or ''
            caption = row['caption'] or ''

        areas_out.append({
            'id': str(row['id']), 'caption': caption, 'description': description,
            'gps': area_gps, 'lat': lat, 'lon': lon,
            'radius': str(row['radius']), 'media': row['media'] or '',
            'visibility': row['visibility'],
            'itemIds': area_items.get(row['id'], [])
        })

    if language == 'ENG':
        items_file = 'travel_eng.json'
        areas_file = 'areas_eng.json'
        zip_name = 'kringum_export_eng.zip'
    else:
        items_file = 'travel.json'
        areas_file = 'areas.json'
        zip_name = 'kringum_export.zip'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(items_file, json.dumps(items_out, ensure_ascii=False, indent=2))
        zf.writestr(areas_file, json.dumps(areas_out, ensure_ascii=False, indent=2))
    buf.seek(0)

    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=zip_name)


# --- API: Translate (via Google Gemini) ---

@app.route('/api/translate', methods=['POST'])
def translate():
    if not config.GEMINI_API_KEY:
        return jsonify({'error': 'Gemini API key not configured'}), 400

    data = request.get_json(force=True)
    text = data.get('text', '')
    if not text or len(text) > 10000:
        return jsonify({'error': 'Text empty or too long (max 10000 chars)'}), 400

    try:
        resp = http_requests.post(
            'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent',
            params={'key': config.GEMINI_API_KEY},
            json={
                'contents': [{'parts': [{'text':
                    'Translate the following Icelandic text to English. '
                    'Return ONLY the translated text, nothing else.\n\n' + text
                }]}]
            }
        )
        result = resp.json()
        translated = result['candidates'][0]['content']['parts'][0]['text'].strip()
        return jsonify({'translatedText': translated})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- API: Wikipedia ---

@app.route('/api/wikipedia/search', methods=['POST'])
def wikipedia_search():
    data = request.get_json(force=True)
    text = data.get('text', '')
    if not text:
        return jsonify([])

    try:
        resp = http_requests.get('https://en.wikipedia.org/w/api.php', params={
            'action': 'query', 'format': 'json', 'list': 'search',
            'srsearch': text, 'formatversion': '2'
        }, headers=WIKI_HEADERS)
        result = resp.json()
        items = []
        for item in result.get('query', {}).get('search', [])[:20]:
            items.append({'Caption': item['title'], 'Value': item['pageid']})
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wikipedia/extract', methods=['POST'])
def wikipedia_extract():
    data = request.get_json(force=True)
    pageid = data.get('pageid', '')
    if not pageid:
        return jsonify({'text': ''})

    try:
        resp = http_requests.get('https://en.wikipedia.org/w/api.php', params={
            'action': 'query', 'format': 'json', 'prop': 'extracts',
            'rvprop': 'content', 'exintro': '', 'explaintext': '',
            'pageids': pageid
        }, headers=WIKI_HEADERS)
        result = resp.json()
        pages = result.get('query', {}).get('pages', {})
        text = pages.get(str(pageid), {}).get('extract', '')
        return jsonify({'text': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=8099)
