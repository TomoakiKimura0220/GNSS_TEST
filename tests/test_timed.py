import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from gnss_maps.timed import rmc_dates, label_for, select_points, write_time_points, NS


def rmc(time='160000.20', date='161026'):
    body = f'GNRMC,{time},A,3500.0,N,13900.0,E,0,0,{date},,,A,V'
    check = 0
    for c in body:
        check ^= ord(c)
    return f'${body}*{check:02X}'


class TimedTests(unittest.TestCase):
    def test_dates_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            log = out / 'log.txt'
            log.write_text(rmc())
            dates = rmc_dates(log)
            self.assertEqual(label_for('160000.20', dates)[0], '2026-10-17T01:00:00.200+09:00')
            self.assertIn('日付不明', label_for('120000.00', dates)[0])
            count = write_time_points(out, [[(35,139,'160000.20','1')]], log, 10)
            self.assertEqual(count, 1)
            name = ET.parse(out / 'time_points.kml').find(f'.//{{{NS}}}Placemark/{{{NS}}}name').text
            self.assertEqual(name, '2026-10-17T01:00:00.200+09:00')
            log.write_text(rmc() + '\n' + rmc(date='171026'))
            self.assertEqual(rmc_dates(log), {})
            log.write_text(rmc()[:-2] + 'XX')
            self.assertEqual(rmc_dates(log), {})

    def test_sampling(self):
        segment = [(35,139,t,'1') for t in ['235959.00','000000.00','000009.00','000009.20']]
        selected = select_points([segment], 10)
        self.assertEqual([p[1][2] for p in selected], ['235959.00','000009.00','000009.20'])
        self.assertEqual(len(select_points([segment], 0)), 4)
        self.assertEqual(len(select_points([[segment[0]], [segment[1]]], 10)), 2)
