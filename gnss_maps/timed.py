"""時刻付きの地点をGoogleマイマップ用に出力する。"""
import csv
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

JST = timezone(timedelta(hours=9))
NS = 'http://www.opengis.net/kml/2.2'


def time_seconds(value):
    h, m, s = int(value[:2]), int(value[2:4]), float(value[4:])
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError('Invalid UTC time')
    return h * 3600 + m * 60 + s


def rmc_dates(path):
    """同じUTC時刻に異なる日付があれば曖昧として使わない。"""
    dates = {}
    with path.open(encoding='utf-8-sig', errors='replace') as stream:
        for line in stream:
            try:
                body, checksum = line.strip()[1:].split('*')
                check = 0
                for char in body:
                    check ^= ord(char)
                if not line.startswith('$') or len(checksum) != 2 or check != int(checksum, 16):
                    continue
                fields = body.split(',')
                if fields[0] not in ('GNRMC', 'GPRMC') or fields[2] != 'A':
                    continue
                value = fields[9]
                if len(value) != 6 or not value.isdigit():
                    continue
                # このプロジェクトは2000〜2099年の計測ログを対象とする。
                day = datetime(2000 + int(value[4:]), int(value[2:4]), int(value[:2]), tzinfo=timezone.utc)
                seconds = time_seconds(fields[1])
                dates.setdefault(seconds, set()).add(day + timedelta(seconds=seconds))
            except (ValueError, IndexError):
                continue
    return {key: next(iter(values)) for key, values in dates.items() if len(values) == 1}


def label_for(utc, dates):
    seconds = time_seconds(utc)
    stamp = dates.get(seconds)
    if stamp:
        return stamp.astimezone(JST).isoformat(timespec='milliseconds'), stamp.isoformat(timespec='milliseconds')
    # PCの日付を使って計測日を推測しない。
    clock = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return clock.astimezone(JST).strftime('%H:%M:%S.%f')[:-3] + ' JST（日付不明）', utc + ' UTC（日付不明）'


def select_points(segments, interval):
    selected = []
    for index, segment in enumerate(segments, 1):
        last_time = None
        for position, point in enumerate(segment):
            now = time_seconds(point[2])
            delta = (now - last_time) % 86400 if last_time is not None else None
            if last_time is None or interval == 0 or delta >= interval or position == len(segment) - 1:
                selected.append((index, point))
                last_time = now
    return selected


def write_time_points(out, segments, log, interval):
    dates = rmc_dates(log)
    rows = select_points(segments, interval)
    root = ET.Element(f'{{{NS}}}kml')
    def add(parent, tag, text=None):
        node = ET.SubElement(parent, f'{{{NS}}}{tag}')
        if text is not None:
            node.text = str(text)
        return node
    doc = add(root, 'Document')
    add(doc, 'name', '時刻別の位置（日本時間）')
    with (out / 'time_points.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['name', 'datetime_jst', 'datetime_utc', 'segment', 'latitude', 'longitude', 'quality'])
        for index, point in rows:
            lat, lon, utc, quality = point
            jst, utc_label = label_for(utc, dates)
            name = jst
            writer.writerow([name, jst, utc_label, index, f'{lat:.8f}', f'{lon:.8f}', quality])
            mark = add(doc, 'Placemark')
            add(mark, 'name', name)
            add(mark, 'description', f'日本時間: {jst}\nUTC: {utc_label}\n区間: {index}\n緯度: {lat:.8f}\n経度: {lon:.8f}\n測位状態: {quality}')
            geom = add(mark, 'Point')
            add(geom, 'coordinates', f'{lon:.8f},{lat:.8f},0')
    ET.indent(root)
    ET.ElementTree(root).write(out / 'time_points.kml', encoding='utf-8', xml_declaration=True)
    return len(rows)
