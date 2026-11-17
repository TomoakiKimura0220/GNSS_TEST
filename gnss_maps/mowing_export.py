"""Union circular mower footprints in a local WGS84 metre frame."""
import math
import xml.etree.ElementTree as ET
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
from shapely.geometry.polygon import orient


def merged_kml(points, heading, title):
    if not points or not math.isfinite(heading):
        raise ValueError('測位点と有効な固定方位が必要です')
    lat, lon = points[0]['lat'], points[0]['lon']
    rad = math.pi / 180
    d = 1 - .00669437999014 * math.sin(lat * rad)**2
    north = 6378137 * (1-.00669437999014) / d**1.5 * rad
    east = 6378137 / math.sqrt(d) * math.cos(lat * rad) * rad
    groups = []
    for p in points:
        h = p.get("heading", heading)
        dx, dy = .3 * math.sin(h * rad), .3 * math.cos(h * rad)
        if not groups or groups[-1][0] != p['segment']:
            groups.append((p['segment'], []))
        groups[-1][1].append(((p['lon']-lon)*east+dx, (p['lat']-lat)*north+dy))
    shapes = [(LineString(coords) if len(set(coords)) > 1 else Point(coords[0])).buffer(.25, quad_segs=8) for _, coords in groups]
    merged = unary_union(shapes)
    polygons = [merged] if merged.geom_type == 'Polygon' else list(merged.geoms)
    root = ET.Element('kml', xmlns='http://www.opengis.net/kml/2.2')
    doc = ET.SubElement(root, 'Document')
    ET.SubElement(doc, 'name').text = title + ' 草刈り推定範囲'
    ET.SubElement(doc, 'description').text = f'直径50cm、前方30cm補正、北向き前進開始・時系列方位推定。重複を統合。品質別の色は統合して緑色。'
    style = ET.SubElement(doc, 'Style', id='mowing')
    poly_style = ET.SubElement(style, 'PolyStyle')
    ET.SubElement(poly_style, 'color').text = 'ff699605'
    ET.SubElement(poly_style, 'outline').text = '0'
    for i, poly in enumerate(polygons):
        poly = orient(poly, sign=1)
        mark = ET.SubElement(doc, 'Placemark')
        ET.SubElement(mark, 'name').text = f'草刈り推定範囲 {i+1}'
        ET.SubElement(mark, 'styleUrl').text = '#mowing'
        polygon = ET.SubElement(mark, 'Polygon')
        ET.SubElement(polygon, 'altitudeMode').text = 'clampToGround'
        for tag, ring in [('outerBoundaryIs', poly.exterior), *[('innerBoundaryIs', r) for r in poly.interiors]]:
            boundary = ET.SubElement(polygon, tag)
            linear = ET.SubElement(boundary, 'LinearRing')
            ET.SubElement(linear, 'coordinates').text = ' '.join(f'{lon+x/east:.10f},{lat+y/north:.10f},0' for x, y in ring.coords)
    text = ET.tostring(root, encoding='unicode', xml_declaration=True)
    if len(text.encode()) > 5_000_000:
        raise ValueError('統合後もKMLが5MBを超えます。シークバーで対象範囲を短くしてください。')
    return {'kml': text, 'polygons': len(polygons), 'points': len(points)}
