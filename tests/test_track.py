import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from gnss_maps.nmea import parse_gga, to_dd
from gnss_maps.__main__ import read_track, write_kml, NS


def sentence(utc='120000.00', quality='1'):
    body = f'GNGGA,{utc},3500.00000,N,13900.00000,E,{quality},09,1.40,163.9,M,36.0,M,,'
    check = 0
    for char in body:
        check ^= ord(char)
    return f'${body}*{check:02X}'


class TrackTests(unittest.TestCase):
    def test_coordinates(self):
        self.assertAlmostEqual(to_dd('3500.00000', 'N', True), 35.0)
        self.assertAlmostEqual(to_dd('13900.00000', 'W', False), -139.0)
        with self.assertRaises(ValueError):
            to_dd('3560.0', 'N', True)

    def test_invalid(self):
        self.assertIsNone(parse_gga(sentence(quality='0')))
        self.assertIsNone(parse_gga(sentence()[:-2] + '00'))

    def test_gaps_and_kml(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'input.txt'
            p.write_text('\n'.join([sentence('235959.80'), sentence('000000.00'), sentence('000000.20','0'), sentence('000000.40'), sentence('000003.40')]))
            segments, stats = read_track(p, 2)
            self.assertEqual([len(s) for s in segments], [2, 1, 1])
            self.assertEqual(stats['valid_points'], 4)
            k = Path(tmp) / 'out.kml'
            write_kml(k, segments)
            coords = ET.parse(k).find(f'.//{{{NS}}}coordinates').text
            self.assertTrue(coords.startswith('139.00000000,35.00000000,0'))


if __name__ == '__main__':
    unittest.main()
