"""Causal heading estimate: north-facing forward start, no pivot turns."""
import math


def track(points):
    heading, reverse, anchor, segment = 0.0, False, None, None
    result = []
    for p in points:
        if anchor is None or p['segment'] != segment:
            anchor = p
            segment = p['segment']
        else:
            lat = math.radians(anchor['lat'])
            d = 1 - .00669437999014 * math.sin(lat)**2
            north = 6378137*(1-.00669437999014)/d**1.5*math.pi/180
            east = 6378137/math.sqrt(d)*math.cos(lat)*math.pi/180
            e, n = (p['lon']-anchor['lon'])*east, (p['lat']-anchor['lat'])*north
            if math.hypot(e, n) >= .20:
                travel = math.degrees(math.atan2(e, n)) % 360
                candidate = (travel + (180 if reverse else 0)) % 360
                delta = (candidate-heading+180) % 360-180
                if abs(delta) > 120:
                    reverse = not reverse
                    candidate = (candidate+180) % 360
                heading = candidate
                anchor = p
        result.append(dict(p, heading=heading, reverse=reverse))
    return result
