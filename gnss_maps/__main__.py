"""uv run python -m gnss_maps LOG --out result"""
import argparse
import csv
import json
import math
from pathlib import Path
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from .nmea import parse_gga
from .timed import write_time_points

NS = 'http://www.opengis.net/kml/2.2'
ET.register_namespace('', NS)


def seconds(utc):
    if len(utc) < 6:
        raise ValueError('時刻が不正です')
    h, m, s = int(utc[:2]), int(utc[2:4]), float(utc[4:])
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError('時刻が不正です')
    return h * 3600 + m * 60 + s


def read_track(path, gap):
    segments, current = [], []
    stats = {'gga_lines': 0, 'excluded_gga': 0, 'valid_points': 0}
    previous = None
    def finish():
        nonlocal current, previous
        if current:
            segments.append(current)
        current, previous = [], None
    with path.open(encoding='utf-8-sig', errors='replace') as stream:
        for line in stream:
            if not line.startswith(('$GNGGA,', '$GPGGA,')):
                continue
            stats['gga_lines'] += 1
            point = parse_gga(line)
            try:
                now = seconds(point[2]) if point else None
            except ValueError:
                point = None
            if point is None:
                stats['excluded_gga'] += 1
                finish()
                continue
            if previous is not None:
                delta = now - previous
                # UTC日付境界だけは翌日として扱う。日付はGGAには含まれない。
                if previous > 23 * 3600 and now < 3600:
                    delta += 86400
                if delta <= 0 or delta > gap:
                    finish()
            current.append(point)
            previous = now
            stats['valid_points'] += 1
    finish()
    return segments, stats


def element(parent, name, text=None):
    node = ET.SubElement(parent, f'{{{NS}}}{name}')
    if text is not None:
        node.text = str(text)
    return node


def write_kml(path, segments):
    root = ET.Element(f'{{{NS}}}kml')
    doc = element(root, 'Document')
    element(doc, 'name', 'GNSS 移動履歴')
    style = element(doc, 'Style')
    style.set('id', 'track')
    line = element(style, 'LineStyle')
    element(line, 'color', 'ffff6600')
    element(line, 'width', '4')
    for index, segment in enumerate(segments, 1):
        mark = element(doc, 'Placemark')
        element(mark, 'name', f'区間 {index}')
        element(mark, 'description', f'UTC {segment[0][2]} ～ {segment[-1][2]} / {len(segment)}点')
        element(mark, 'styleUrl', '#track')
        geom = element(mark, 'LineString' if len(segment) > 1 else 'Point')
        if len(segment) > 1:
            element(geom, 'tessellate', '1')
        element(geom, 'altitudeMode', 'clampToGround')
        element(geom, 'coordinates', ' '.join(f'{p[1]:.8f},{p[0]:.8f},0' for p in segment))
    for name, point in [('開始', segments[0][0]), ('終了（最後の有効位置）', segments[-1][-1])]:
        mark = element(doc, 'Placemark')
        element(mark, 'name', name)
        geom = element(mark, 'Point')
        element(geom, 'coordinates', f'{point[1]:.8f},{point[0]:.8f},0')
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description='NMEAログをGoogleマイマップ用KMLへ変換')
    parser.add_argument('log', type=Path)
    parser.add_argument('--out', type=Path, default=Path('result'))
    parser.add_argument('--gap-seconds', type=float, default=2.0, help='この秒数を超える空白で線を分割（既定2秒）')
    parser.add_argument('--time-step', type=float, default=10.0, help='時刻付き地点の間隔（秒）。0で全点、既定10秒')
    args = parser.parse_args()
    if not math.isfinite(args.time_step) or args.time_step < 0:
        parser.error('--time-stepには0以上の有限数を指定してください')
    if not math.isfinite(args.gap_seconds) or args.gap_seconds <= 0:
        parser.error('--gap-secondsには正の有限数を指定してください')
    try:
        segments, stats = read_track(args.log, args.gap_seconds)
        if not segments:
            parser.exit(1, '有効な位置がありません。GGA出力・測位状態・ログ形式を確認してください。\n')
        args.out.mkdir(parents=True, exist_ok=True)
        write_kml(args.out / 'track.kml', segments)
        with (args.out / 'points.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['segment', 'utc_hhmmss', 'latitude_dd', 'longitude_dd', 'quality'])
            for index, segment in enumerate(segments, 1):
                for lat, lon, utc, quality in segment:
                    writer.writerow([index, utc, f'{lat:.8f}', f'{lon:.8f}', quality])
        stats['time_points'] = write_time_points(args.out, segments, args.log, args.time_step)
        last = segments[-1][-1]
        stats['segments'] = len(segments)
        stats['last_valid_google_maps_url'] = 'https://www.google.com/maps/search/?' + urlencode({'api': 1, 'query': f'{last[0]:.8f},{last[1]:.8f}'})
        (args.out / 'summary.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError as error:
        parser.exit(1, f'ファイルを読み書きできません: {error}\n')
    print(f"有効な位置: {stats['valid_points']}点 / 区間: {len(segments)}")
    print(f'Googleマイマップに読み込むファイル: {args.out / "track.kml"}')
    print(f"時刻付き地点: {stats['time_points']}点 / {args.out / 'time_points.kml'}")
    print(stats['last_valid_google_maps_url'])


if __name__ == '__main__':
    main()
