"""Explicit one-time provisioning; map rendering itself stays offline."""
import io
import math
from pathlib import Path
import sqlite3
import time
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from PIL import Image

PRESETS = {'地形図': ('std', 'png'), '航空写真': ('seamlessphoto', 'jpg')}
ATTRIBUTION = '出典：国土地理院（地理院タイル） https://maps.gsi.go.jp/development/ichiran.html'


def tile_xy(lat, lon, zoom):
    n = 1 << zoom
    return (max(0, min(n-1, int((lon+180)/360*n))),
            max(0, min(n-1, int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n))))


_prepare_lock = threading.Lock()


def prepare(directory, bounds, progress=lambda s: None, cancel=None):
    if not _prepare_lock.acquire(blocking=False):
        raise ValueError('地図を取得中です。完了してから再実行してください')
    try:
        return _prepare(directory, bounds, progress, cancel)
    finally:
        _prepare_lock.release()


def _prepare(directory, bounds, progress=lambda s: None, cancel=None):
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -85 < south < north < 85):
        raise ValueError('保存範囲が不正です')
    tiles = []
    for z in range(14, 19):
        x0, y0 = tile_xy(north, west, z)
        x1, y1 = tile_xy(south, east, z)
        tiles.extend((z,x,y) for x in range(x0,x1+1) for y in range(y0,y1+1))
        if len(tiles)>1000:
            raise ValueError('範囲が広すぎます。小さな範囲で準備してください（上限1,000画像／レイヤー）')
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, (layer, ext) in PRESETS.items():
        target = directory / (layer+'.mbtiles')
        temp = directory / (layer+'.partial')
        temp.unlink(missing_ok=True)
        missing = 0
        try:
            with sqlite3.connect(temp) as db:
                db.executescript('CREATE TABLE metadata(name TEXT PRIMARY KEY,value TEXT); CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_data BLOB,PRIMARY KEY(zoom_level,tile_column,tile_row));')
                metadata = {'name':'国土地理院 '+name, 'format':ext,'scheme':'tms','bounds':','.join(map(str,bounds)), 'minzoom':'14','maxzoom':'18','attribution':ATTRIBUTION}
                db.executemany('INSERT INTO metadata VALUES (?,?)',metadata.items())
                for i,(z,x,y) in enumerate(tiles):
                    if cancel and cancel.is_set(): raise InterruptedError('地図準備を中止しました')
                    progress(f'{name}：{i+1}/{len(tiles)}画像（未提供 {missing}）')
                    request = Request(f'https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.{ext}',headers={'User-Agent':'GNSS-Test-Offline/0.2'})
                    try:
                        with urlopen(request, timeout=20) as response: data=response.read(5_000_001)
                    except HTTPError as exc:
                        if exc.code == 404:
                            missing += 1; continue
                        raise
                    if len(data)>5_000_000: raise ValueError('地図画像が大きすぎます')
                    with Image.open(io.BytesIO(data)) as image: image.verify()
                    db.execute('INSERT INTO tiles VALUES (?,?,?,?)',(z,x,(1<<z)-1-y,data))
                    time.sleep(.08)
                if db.execute('SELECT COUNT(*) FROM tiles').fetchone()[0] == 0:
                    raise ValueError(name+'の画像がありません')
                db.execute('INSERT INTO metadata VALUES (?,?)',('missing_tiles',str(missing)))
            temp.replace(target)
            results[name] = str(target.resolve())
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    return results
