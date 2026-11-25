"""Area of the union of mowing footprints clipped to a measured FIX boundary."""
import math
from shapely.geometry import Polygon
from shapely import make_valid
from .mowing_export import footprint
from .experiments import scales, load, translate
from .mowing_heading import track


def calculate(boundary, points, front=.3, side=0, close_boundary=False, repair_boundary=False):
    if len(boundary) < 3 or len({(p['lat'], p['lon']) for p in boundary}) < 3:
        raise ValueError('外周には異なる位置の3点以上が必要です')
    if any(p['quality'] != 4 for p in boundary) or len({p['segment'] for p in boundary}) != 1:
        raise ValueError('外周は途切れのないFIX区間を選んでください。非FIXや欠測をまたぐ外周は計算できません')
    origin = (boundary[0]['lat'], boundary[0]['lon'])
    north, east = scales(origin[0])
    xy = [((p['lon']-origin[1])*east, (p['lat']-origin[0])*north) for p in boundary]
    gap = math.dist(xy[0], xy[-1])
    if gap > 1e-6 and not close_boundary:
        raise ValueError(f'外周の始点と終点は{gap:.3f} m離れています。「直線で閉じる」を選ぶか外周区間を見直してください')
    polygon = Polygon(xy)
    repaired = False
    removed_area = 0
    if not polygon.is_valid and repair_boundary:
        def polygons(g):
            if g.geom_type == 'Polygon':
                return [g]
            return [p for child in getattr(g, 'geoms', []) for p in polygons(child)]
        parts = polygons(make_valid(polygon))
        if not parts:
            raise ValueError('外周を補修しても面積を作れません。区間を選び直してください')
        polygon = max(parts, key=lambda p:p.area)
        removed_area = sum(p.area for p in parts) - polygon.area
        if removed_area > .05 or polygon.area < sum(p.area for p in parts)*.99:
            raise ValueError('交差による分割領域が大きいため自動補修できません。外周区間を選び直してください')
        repaired = True
    if not polygon.is_valid or polygon.area <= 1e-8:
        raise ValueError('外周が自己交差しているか面積がありません。細かな交差なら「自己交差の小領域を除いて補修」を選ぶか、外周区間を選び直してください')
    shape, *_ = footprint(points, front=front, side=side, origin=origin)
    total = polygon.area
    covered = shape.intersection(polygon).area
    return dict(boundary_area=total, covered_area=covered, uncovered_area=max(0,total-covered),
                footprint_area=shape.area, outside_area=max(0,shape.area-covered),
                percent=100*covered/total, closing_gap=gap, points=len(points), front=front,side=side,
                repaired=repaired, removed_area=removed_area,
                boundary_rings=[[[origin[0]+y/north,origin[1]+x/east] for x,y in ring.coords]
                                for ring in [polygon.exterior,*polygon.interiors]])


def from_database(db, data):
    boundary_exp = load(db, str(data.get('boundary', '')))
    run_exp = load(db, str(data.get('experiment', '')))
    first, last = int(data.get('first', 0)), int(data.get('last', 0))
    if not run_exp['first'] <= first <= last <= run_exp['last']:
        raise ValueError('計算範囲が保存した実験区間の外です')
    boundary = [dict(p) for p in db.execute('SELECT * FROM points WHERE session=? AND id>=? AND id<=? ORDER BY id',
                (boundary_exp['session'],boundary_exp['first'],boundary_exp['last']))]
    all_points = [dict(p) for p in db.execute('SELECT * FROM points WHERE session=? AND id<=? ORDER BY id',
                  (run_exp['session'],last))]
    points = [p for p in track(all_points) if p['id']>=first]
    if len(points)>50000 or len(boundary)>50000:
        raise ValueError('計算する外周と実験はそれぞれ50,000点以内にしてください')
    if data.get('aligned') is True:
        points = translate(points,run_exp)
    result=calculate(boundary,points,float(data.get('front',.3)),float(data.get('side',0)),data.get('close_boundary') is True, data.get('repair_boundary') is True)
    result.update(boundary_title=boundary_exp['title'],experiment_title=run_exp['title'],first=first,last=last,
                  aligned=data.get('aligned') is True)
    return result
