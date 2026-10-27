"""Local GNSS recorder and browser UI: uv run python -m gnss_maps.live"""
from collections import deque
import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import uuid
import webbrowser
import xml.etree.ElementTree as ET

from .nmea import parse_gga
from .timed import time_seconds, NS


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def fields_of(line):
    try:
        if not line.startswith('$'):
            return None
        body, checksum = line.strip()[1:].split('*')
        value = 0
        for c in body:
            value ^= ord(c)
        if len(checksum) != 2 or int(checksum, 16) != value:
            return None
        return body.split(',')
    except ValueError:
        return None


def nmea(body):
    check = 0
    for c in body:
        check ^= ord(c)
    return f'${body}*{check:02X}\r\n'.encode()


def demo_lines():
    """Synthetic data only; never recorded as a real measurement."""
    start = datetime.now(timezone.utc)
    for i in range(1500):
        stamp = start + timedelta(seconds=i / 5)
        clock = stamp.strftime('%H%M%S.%f')[:9]
        quality = '0' if 100 <= i % 300 < 115 else ('5' if i % 300 < 50 else '4')
        lat = f'{3501 + .03 * math.sin(i / 90):010.5f}'
        lon = f'{13901 + .04 * math.cos(i / 90):011.5f}'
        yield nmea(f'GNRMC,{clock},A,{lat},N,{lon},E,0,0,{stamp:%d%m%y},,,A,V')
        if quality == '0':
            yield nmea(f'GNGGA,{clock},,,,,0,00,99.99,,,,,,')
        else:
            yield nmea(f'GNGGA,{clock},{lat},N,{lon},E,{quality},12,0.8,10,M,36,M,0.5,0000')


class Recorder:
    def __init__(self, directory, replay=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.replay = replay
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / 'history.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, title TEXT, source TEXT, started TEXT, ended TEXT,
          status TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS points (
          id INTEGER PRIMARY KEY, session TEXT, received TEXT, utc TEXT,
          measured TEXT, lat REAL, lon REAL, quality INTEGER, satellites INTEGER,
          hdop REAL, segment INTEGER);
        CREATE INDEX IF NOT EXISTS point_session ON points(session,id);
        ''')
        self.db.execute("UPDATE sessions SET status='interrupted', ended=? WHERE status='recording'", (utc_now(),))
        self.db.commit()
        self.stop_event = threading.Event()
        self.thread = None
        self.active = None
        self.last_rx = self.last_fix = None
        self.quality = None
        self.segment = 0
        self.previous = None
        self.dates = {}
        self.error = ''

    def sessions(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('''SELECT s.*, COUNT(p.id) AS point_count,
                SUM(CASE WHEN p.quality=4 THEN 1 ELSE 0 END) AS fix_count
                FROM sessions s LEFT JOIN points p ON p.session=s.id
                GROUP BY s.id ORDER BY s.started DESC''')]

    def points(self, sid, after=0):
        with self.lock:
            return [dict(r) for r in self.db.execute(
                'SELECT * FROM points WHERE session=? AND id>? ORDER BY id LIMIT 5000', (sid, after))]

    def state(self):
        with self.lock:
            now = time.monotonic()
            rx_age = None if self.last_rx is None else now - self.last_rx
            fix_age = None if self.last_fix is None else now - self.last_fix
            running = self.thread is not None and self.thread.is_alive()
            fresh = running and self.quality in (1, 2, 4, 5) and fix_age is not None and fix_age < 3
            return dict(active=self.active, running=running, fresh=fresh, quality=self.quality,
                        rx_age=rx_age, fix_age=fix_age, error=self.error)

    def start(self, source, title='', baud=38400):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('計測中です。先に停止してください。')
            if source == 'demo':
                connection = None
            elif source == 'replay' and self.replay:
                connection = self.replay.open('rb')
            else:
                from serial import Serial
                from serial.tools.list_ports import comports
                if source not in {p.device for p in comports()}:
                    raise ValueError('接続ポートが見つかりません。ポート一覧を更新してください。')
                connection = Serial(source, baudrate=baud, timeout=0.5)
            sid = uuid.uuid4().hex
            try:
                raw = (self.directory / f'{sid}.log').open('wb')
            except OSError:
                if connection:
                    connection.close()
                raise
            self.active = sid
            self.segment = 0
            self.previous = self.last_rx = self.last_fix = self.quality = None
            self.dates = {}
            self.error = ''
            self.stop_event.clear()
            self.db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',
                (sid, title.strip()[:120] or ('デモ' if source == 'demo' else '計測'), source,
                 utc_now(), None, 'recording', ''))
            self.db.commit()
            self.thread = threading.Thread(target=self._run, args=(source, connection, raw), daemon=True)
            self.thread.start()
            return sid

    def import_log(self, payload, title):
        """Parse in isolation so importing never changes the live receiver state."""
        if not payload or len(payload) > 50 * 1024 * 1024:
            raise ValueError('空ファイル、または50 MiBを超えるファイルは読み込めません')
        sid = uuid.uuid4().hex
        target = self.directory / (sid + '.log')
        with tempfile.TemporaryDirectory(dir=self.directory) as staging:
            parsed = Recorder(Path(staging))
            parsed.active = sid
            try:
                for raw in io.BytesIO(payload):
                    if len(raw) > 65536:
                        raise ValueError('1行が長すぎます。NMEAテキストログを選んでください')
                    parsed.ingest(raw.decode('ascii', errors='replace').strip(), commit=False)
                parsed.db.commit()
                count = parsed.db.execute('SELECT COUNT(*) FROM points').fetchone()[0]
                if not count:
                    raise ValueError('有効なGGA位置がありません。NMEAログと測位品質を確認してください')
                staged_log = Path(staging) / 'original.log'
                staged_log.write_bytes(payload)
                with self.lock:
                    try:
                        self.db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',
                            (sid, title.strip()[:120] or 'インポート', 'import', utc_now(), utc_now(), 'completed', ''))
                        rows = parsed.db.execute('SELECT session,received,utc,measured,lat,lon,quality,satellites,hdop,segment FROM points ORDER BY id')
                        self.db.executemany('INSERT INTO points (session,received,utc,measured,lat,lon,quality,satellites,hdop,segment) VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
                        staged_log.replace(target)
                        self.db.commit()
                    except Exception:
                        self.db.rollback()
                        target.unlink(missing_ok=True)
                        raise
                return dict(session=sid, count=count)
            finally:
                parsed.close()

    def ingest(self, line, commit=True):
        with self.lock:
            self.last_rx = time.monotonic()
            f = fields_of(line)
            if f and f[0] in ('GNRMC', 'GPRMC'):
                try:
                    if f[2] != 'A' or len(f[9]) != 6:
                        return
                    day = f[9]
                    sec = time_seconds(f[1])
                    dt = datetime(2000 + int(day[4:]), int(day[2:4]), int(day[:2]), tzinfo=timezone.utc)
                    measured = (dt + timedelta(seconds=sec)).isoformat(timespec='milliseconds')
                    # Cache only recent epochs, allowing RMC before or after GGA.
                    self.dates[f[1]] = measured
                    if len(self.dates) > 20:
                        del self.dates[next(iter(self.dates))]
                    self.db.execute('''UPDATE points SET measured=? WHERE session=? AND utc=?
                        AND measured IS NULL AND id IN
                        (SELECT id FROM points WHERE session=? ORDER BY id DESC LIMIT 20)''',
                        (measured, self.active, f[1], self.active))
                    self.db.commit() if commit else None
                except (ValueError, IndexError):
                    pass
                return
            if not line.startswith(('$GNGGA,', '$GPGGA,')):
                return
            point = parse_gga(line)
            try:
                sec = time_seconds(point[2]) if point else None
                sats = int(f[7]) if point else None
                hdop = float(f[8]) if point and f[8] else None
                if hdop is not None and (not math.isfinite(hdop) or hdop < 0):
                    point = None
            except (ValueError, IndexError, TypeError):
                point = None
            if point is None:
                self.quality = int(f[6]) if f and len(f) > 6 and f[6].isdigit() else None
                self.previous = None
                return
            delta = None if self.previous is None else sec - self.previous
            if delta is not None and self.previous > 23 * 3600 and sec < 3600:
                delta += 86400
            if delta is None or delta <= 0 or delta > 2:
                self.segment += 1
            lat, lon, clock, quality = point
            self.quality = int(quality)
            self.last_fix = time.monotonic()
            self.previous = sec
            measured = self.dates.get(clock)
            # Drop matched dates so a later day cannot reuse them.
            self.dates.pop(clock, None)
            self.db.execute('''INSERT INTO points
                (session,received,utc,measured,lat,lon,quality,satellites,hdop,segment)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (self.active, utc_now(), clock, measured, lat, lon, self.quality, sats, hdop, self.segment))
            self.db.commit() if commit else None

    def _run(self, source, connection, raw):
        status = 'completed'
        try:
            iterator = demo_lines() if source == 'demo' else None
            buffer = b''
            while not self.stop_event.is_set():
                if source == 'demo':
                    chunk = next(iterator, b'')
                elif source == 'replay':
                    chunk = connection.readline()
                else:
                    chunk = connection.read_until(b'\n', size=4096)
                if not chunk:
                    if source in ('demo', 'replay'):
                        break
                    continue
                raw.write(chunk)
                raw.flush()
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    decoded = line.decode('ascii', errors='replace').strip()
                    self.ingest(decoded)
                    if source in ('demo', 'replay') and decoded.startswith(('$GNGGA,', '$GPGGA,')):
                        self.stop_event.wait(0.2)
                if len(buffer) > 16384:
                    buffer = b''
            if buffer:
                self.ingest(buffer.decode('ascii', errors='replace').strip())
        except Exception as error:
            status = 'error'
            with self.lock:
                self.error = str(error)
        finally:
            raw.close()
            if connection:
                connection.close()
            with self.lock:
                self.db.execute('UPDATE sessions SET ended=?,status=?,error=? WHERE id=?',
                                (utc_now(), status, self.error, self.active))
                self.db.commit()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def close(self):
        self.stop()
        self.db.close()

    def export(self, sid, kind):
        with self.lock:
            if not self.db.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
                raise ValueError('履歴がありません')
            if kind == 'log':
                return (self.directory / f'{sid}.log').read_bytes(), 'text/plain'
            points = [dict(r) for r in self.db.execute('SELECT * FROM points WHERE session=? ORDER BY id', (sid,))]
        if kind == 'csv':
            out = io.StringIO(newline='')
            writer = csv.DictWriter(out, fieldnames=['id','session','received','utc','measured','lat','lon','quality','satellites','hdop','segment'])
            writer.writeheader()
            writer.writerows(points)
            return out.getvalue().encode('utf-8-sig'), 'text/csv'
        if kind != 'kml':
            raise ValueError('未対応の形式です')
        ET.register_namespace('', NS)
        root = ET.Element(f'{{{NS}}}kml')
        doc = ET.SubElement(root, f'{{{NS}}}Document')
        groups = []
        for p in points:
            if not groups or groups[-1][-1]['segment'] != p['segment']:
                groups.append([])
            groups[-1].append(p)
        for group in groups:
            mark = ET.SubElement(doc, f'{{{NS}}}Placemark')
            ET.SubElement(mark, f'{{{NS}}}name').text = f"区間 {group[0]['segment']}"
            geom = ET.SubElement(mark, f'{{{NS}}}' + ('LineString' if len(group)>1 else 'Point'))
            ET.SubElement(geom, f'{{{NS}}}altitudeMode').text = 'clampToGround'
            ET.SubElement(geom, f'{{{NS}}}coordinates').text = ' '.join(f"{p['lon']:.8f},{p['lat']:.8f},0" for p in group)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True), 'application/vnd.google-earth.kml+xml'


def make_server(recorder, port, key='', map_id='DEMO_MAP_ID'):
    token = secrets.token_urlsafe(32)
    web = Path(__file__).with_name('web')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, status=200, content_type='application/json; charset=utf-8'):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def allowed(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.allowed():
                return self.send({'error':'Host not allowed'}, 403)
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == '/api/config':
                    return self.send(dict(token=token, maps_key=key, map_id=map_id, replay=bool(recorder.replay)))
                if u.path == '/api/maps':
                    directory = Path('data/desktop/presets')
                    result = []
                    for tile_key, title in [('std','地形図'), ('seamlessphoto','航空写真')]:
                        path = directory / (tile_key+'.mbtiles')
                        if path.exists():
                            from .offline_map import inspect_map
                            info = inspect_map(path)
                            result.append(dict(id=tile_key,title=title,minzoom=info['minzoom'],maxzoom=info['maxzoom'],attribution=info['attribution'],bounds=info['bounds']))
                    return self.send(result)
                if u.path.startswith('/tiles/'):
                    parts = u.path.split('/')
                    if len(parts)!=6 or parts[2] not in ('std','seamlessphoto'):
                        raise ValueError('不正な地図指定')
                    tile_key=parts[2]; z,x,y=map(int,parts[3:])
                    if not 0<=z<=22 or not 0<=x<2**z or not 0<=y<2**z:
                        raise ValueError('範囲外のタイル')
                    path=Path('data/desktop/presets')/(tile_key+'.mbtiles')
                    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                        from .offline_map import tile_with_parent
                        tile=tile_with_parent(db,z,x,y)
                    return self.send(tile or b'',status=200 if tile else 404,content_type='image/png')
                if u.path == '/api/raw':
                    sid=q.get('session',[''])[0]
                    with recorder.lock:
                        exists=recorder.db.execute('SELECT 1 FROM sessions WHERE id=?',(sid,)).fetchone()
                    if not exists:
                        raise ValueError('履歴がありません')
                    target=q.get('utc',[''])[0]
                    rows=deque(maxlen=1000)
                    with (recorder.directory / (sid+'.log')).open('rb') as stream:
                        for number, raw in enumerate(stream,1):
                            line=raw.decode('ascii',errors='replace').strip()
                            f=fields_of(line)
                            rows.append(dict(number=number,text=line,valid=bool(f)))
                            if target and f and f[0] in ('GNGGA','GPGGA') and f[1]==target:
                                break
                    return self.send(list(rows))
                if u.path == '/api/ports':
                    from serial.tools.list_ports import comports
                    return self.send([dict(device=p.device, description=p.description) for p in comports()])
                if u.path == '/api/state':
                    return self.send(recorder.state())
                if u.path == '/api/sessions':
                    return self.send(recorder.sessions())
                if u.path == '/api/points':
                    return self.send(recorder.points(q.get('session',[''])[0], int(q.get('after',['0'])[0])))
                if u.path == '/api/export':
                    data, mime = recorder.export(q.get('session',[''])[0], q.get('kind',['csv'])[0])
                    return self.send(data, content_type=mime)
                files = {'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8')}
                for name,mime in [('leaflet.js','text/javascript'),('leaflet.css','text/css')]:
                    if u.path == '/vendor/leaflet/'+name:
                        return self.send((web/'vendor'/'leaflet'/name).read_bytes(),content_type=mime)
                font_files = {('/fonts/' + p.name): p for p in (web / 'fonts').glob('*.ttf')}
                if u.path in font_files:
                    return self.send(font_files[u.path].read_bytes(), content_type='font/ttf')
                if u.path in files:
                    name, mime = files[u.path]
                    return self.send((web / name).read_bytes(), content_type=mime)
                return self.send({'error':'Not found'},404)
            except (ValueError, OSError, sqlite3.Error) as error:
                self.send({'error':str(error)},400)

        def do_POST(self):
            if not self.allowed() or self.headers.get('X-GNSS-Token') != token:
                return self.send({'error':'操作を許可できません。画面を再読み込みしてください。'},403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if urlparse(self.path).path == '/api/import':
                    if not 0 < length <= 50 * 1024 * 1024:
                        return self.send({'error':'1バイト以上、50 MiB以下のログを選んでください'},413)
                    payload = self.rfile.read(length)
                    if len(payload) != length:
                        raise ValueError('ファイルの転送が途中で切れました')
                    title = parse_qs(urlparse(self.path).query).get('name',['インポート'])[0]
                    return self.send(recorder.import_log(payload, title))
                if not 0 < length <= 4096:
                    raise ValueError('リクエストサイズが不正です')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('操作データが不正です')
                if self.path == '/api/maps/prepare':
                    with recorder.lock:
                        bounds = recorder.db.execute('SELECT MIN(lon),MIN(lat),MAX(lon),MAX(lat) FROM points WHERE session=?',(str(data.get('session','')),)).fetchone()
                    if bounds[0] is None:
                        raise ValueError('地図を準備する履歴を選んでください')
                    from .presets import prepare
                    west,south,east,north=bounds
                    prepare(Path('data/desktop/presets'),(west-.006,south-.006,east+.006,north+.006))
                    return self.send({'ok':True})
                if self.path == '/api/start':
                    baud = int(data.get('baud',38400))
                    if baud not in (9600,19200,38400,57600,115200,230400,460800,921600):
                        raise ValueError('通信速度が不正です')
                    sid = recorder.start(str(data.get('source','')), str(data.get('title','')), baud)
                    return self.send({'session':sid})
                if self.path == '/api/stop':
                    recorder.stop()
                    return self.send({'ok':True})
                self.send({'error':'Not found'},404)
            except (ValueError, OSError, sqlite3.Error) as error:
                self.send({'error':str(error)},400)
    return ThreadingHTTPServer(('127.0.0.1',port), Handler)


def main():
    parser = argparse.ArgumentParser(description='GNSSの受信・履歴・オフライン地図表示')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=Path('data/live'))
    parser.add_argument('--replay', type=Path, help='保存済みログを5Hz相当で再生する入力候補')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    recorder = Recorder(args.data_dir, args.replay)
    try:
        server = make_server(recorder, args.port, os.environ.get('GOOGLE_MAPS_API_KEY',''), os.environ.get('GOOGLE_MAPS_MAP_ID','DEMO_MAP_ID'))
    except OSError as error:
        recorder.close()
        parser.exit(1, f'起動できません: {error}\n')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'ブラウザーで開いてください: {url}\n終了: Ctrl+C / 保存先: {args.data_dir.resolve()}')
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        recorder.close()


if __name__ == '__main__':
    main()
