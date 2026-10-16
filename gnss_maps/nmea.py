"""NMEA GGAの検証と座標変換。"""
def to_dd(value, direction, latitude):
    width = 2 if latitude else 3
    if direction not in ('NS' if latitude else 'EW') or len(direction) != 1:
        raise ValueError('方位が不正です')
    degrees = int(value[:width])
    minutes = float(value[width:])
    limit = 90 if latitude else 180
    if not 0 <= minutes < 60 or not 0 <= degrees <= limit:
        raise ValueError('座標が範囲外です')
    result = degrees + minutes / 60
    if result > limit:
        raise ValueError('座標が範囲外です')
    return -result if direction in 'SW' else result


def parse_gga(line):
    try:
        line = line.strip()
        if not line.startswith('$'):
            return None
        body, checksum = line[1:].split('*')
        actual = 0
        for char in body:
            actual ^= ord(char)
        if len(checksum) != 2 or actual != int(checksum, 16):
            return None
        fields = body.split(',')
        if fields[0] not in ('GNGGA', 'GPGGA') or len(fields) < 15:
            return None
        # 通常測位・補正測位・RTKのみを採用。推測位置などは除外。
        if fields[6] not in ('1', '2', '4', '5'):
            return None
        lat = to_dd(fields[2], fields[3], True)
        lon = to_dd(fields[4], fields[5], False)
        return lat, lon, fields[1], fields[6]
    except (ValueError, IndexError):
        return None

