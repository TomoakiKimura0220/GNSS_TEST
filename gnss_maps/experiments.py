"""Saved ranges and auditable, constant local translations; raw points stay intact."""
import json
import math
import uuid


def initialise(db):
    db.execute('CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.commit()


def scales(lat):
    rad = math.pi / 180
    d = 1 - .00669437999014 * math.sin(lat * rad)**2
    return (6378137 * (1-.00669437999014) / d**1.5 * rad,
            6378137 / math.sqrt(d) * math.cos(lat * rad) * rad)


def point(db, session, ident):
    row = db.execute('SELECT * FROM points WHERE session=? AND id=?', (session, ident)).fetchone()
    if row is None:
        raise ValueError('指定した測位点がありません')
    return dict(row)


def save(db, data):
    session = str(data.get('session', ''))
    first, last = int(data.get('first', 0)), int(data.get('last', 0))
    start, end = point(db, session, first), point(db, session, last)
    if first > last:
        raise ValueError('開始点は終了点以前にしてください')
    count = db.execute('SELECT COUNT(*) FROM points WHERE session=? AND id>=? AND id<=?', (session, first, last)).fetchone()[0]
    if count > 50000:
        raise ValueError('保存する区間は50,000点以内に分けてください')
    title = str(data.get('title', '')).strip()
    if not title or len(title) > 120:
        raise ValueError('区間名を1〜120文字で入力してください')
    front, side = float(data.get('front', .3)), float(data.get('side', 0))
    if not all(math.isfinite(v) and abs(v) <= 10 for v in (front, side)):
        raise ValueError('取り付け補正は−10〜10 mで指定してください')
    result = dict(id=uuid.uuid4().hex, title=title, session=session, first=first, last=last,
                  start=start, end=end, front=front, side=side, reference=None, match=None,
                  east=0, north=0, dlat=0, dlon=0)
    ref, match = data.get('reference'), data.get('match')
    if bool(ref) != bool(match):
        raise ValueError('基準点と位置合わせ点を両方指定してください')
    if ref and match:
        if not isinstance(ref, dict) or not isinstance(match, dict) or not all(k in ref for k in ('session', 'id')) or 'id' not in match:
            raise ValueError('対応点の指定が不正です')
        ref = point(db, str(ref['session']), int(ref['id']))
        match = point(db, session, int(match['id']))
        if ref['quality'] != 4:
            raise ValueError('基準点には品質4（FIX）を選んでください')
        if match['quality'] != 2 or not first <= match['id'] <= last:
            raise ValueError('位置合わせ点は選択区間内の品質2を選んでください')
        n, e = scales(ref['lat'])
        result.update(reference=ref, match=match, dlat=ref['lat']-match['lat'],
                      dlon=ref['lon']-match['lon'])
        result.update(east=result['dlon']*e, north=result['dlat']*n)
    db.execute('INSERT INTO experiments VALUES (?,?)', (result['id'], json.dumps(result, ensure_ascii=False)))
    db.commit()
    return result


def list_saved(db):
    return [json.loads(row[0]) for row in db.execute('SELECT payload FROM experiments ORDER BY rowid DESC')]


def load(db, ident):
    row = db.execute('SELECT payload FROM experiments WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('保存した実験区間がありません')
    return json.loads(row[0])


def translate(points, experiment):
    return [{**p, 'lat':p['lat']+experiment['dlat'], 'lon':p['lon']+experiment['dlon']} for p in points]
