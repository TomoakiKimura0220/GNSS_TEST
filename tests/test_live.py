import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from gnss_maps.live import Recorder, nmea, make_server, demo_lines


def gga(clock='120000.00', quality='4'):
    return nmea(f'GNGGA,{clock},3500.00000,N,13900.00000,E,{quality},12,0.8,10,M,36,M,0.5,0000').decode()


def rmc(clock='120000.00', day='191026'):
    return nmea(f'GNRMC,{clock},A,3500.00000,N,13900.00000,E,0,0,{day},,,A,V').decode()


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rec = Recorder(Path(self.temp.name))
        # Deterministic test session, without starting a background reader.
        self.rec.active='test'
        self.rec.db.execute("INSERT INTO sessions VALUES ('test','test','test','2026-10-19',NULL,'recording','')")
        self.rec.db.commit()
        (Path(self.temp.name)/'test.log').write_text('')

    def tearDown(self):
        self.rec.close()
        self.temp.cleanup()

    def test_demo_coordinates_remain_valid(self):
        from gnss_maps.nmea import parse_gga
        for raw in demo_lines():
            line=raw.decode()
            if line.startswith("$GNGGA") and line.split(",")[6] != "0":
                self.assertIsNotNone(parse_gga(line))

    def test_timestamp_order_and_gaps(self):
        self.rec.ingest(rmc())
        self.rec.ingest(gga())
        self.rec.ingest(gga('120000.20'))
        self.rec.ingest(rmc('120000.20'))
        self.rec.ingest(gga('120000.40','0'))
        self.rec.ingest(gga('120000.60','5'))
        self.rec.ingest(gga('120004.00','4'))
        points=self.rec.points('test')
        self.assertEqual([p['segment'] for p in points],[1,1,2,3])
        self.assertEqual(points[0]['measured'],'2026-10-19T12:00:00.000+00:00')
        self.assertEqual(points[1]['measured'],'2026-10-19T12:00:00.200+00:00')
        self.assertIsNone(points[-1]['measured'])
        self.assertEqual(len(self.rec.points('test',points[1]['id'])),2)
        data,_=self.rec.export('test','csv')
        self.assertEqual(len(list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))),4)
        data,_=self.rec.export('test','kml')
        self.assertIn(b'139.00000000,35.00000000,0',data)

    def test_freshness_and_invalid(self):
        fake=type('Thread',(),{'is_alive':lambda self:True})()
        with patch.object(self.rec,'thread',fake):
            self.rec.ingest(gga())
            self.assertTrue(self.rec.state()['fresh'])
            self.rec.last_fix-=4
            self.assertFalse(self.rec.state()['fresh'])
            self.rec.ingest(gga('120000.20','0'))
            self.assertEqual(self.rec.state()['quality'],0)
            self.assertFalse(self.rec.state()['fresh'])
            self.rec.ingest(gga('120000.40')[:-4]+'FF\r\n')
            self.assertIsNone(self.rec.state()['quality'])
        self.assertEqual(len(self.rec.points('test')),1)

    def test_restart_marks_interrupted(self):
        self.rec.db.execute("UPDATE sessions SET status='recording' WHERE id='test'")
        self.rec.db.commit()
        self.rec.close()
        self.rec=Recorder(Path(self.temp.name))
        self.assertEqual(self.rec.sessions()[0]['status'],'interrupted')

    def test_serial_partial_lines_disconnect(self):
        class Port:
            device='COM_TEST'
        class FakeSerial:
            def __init__(self,*a,**k):
                raw=gga().encode()
                self.chunks=iter([raw[:12],raw[12:]])
            def read_until(self,*a,**k):
                try:return next(self.chunks)
                except StopIteration:raise OSError('device disconnected')
            def close(self):pass
        with patch('serial.tools.list_ports.comports',return_value=[Port()]),patch('serial.Serial',FakeSerial):
            sid=self.rec.start('COM_TEST','serial test')
            self.rec.thread.join(2)
        self.assertEqual(len(self.rec.points(sid)),1)
        self.assertEqual(self.rec.sessions()[0]['status'],'error')
        self.assertIn('disconnected',self.rec.state()['error'])
        self.assertFalse(self.rec.state()['fresh'])
        self.assertEqual((Path(self.temp.name)/f'{sid}.log').read_bytes(),gga().encode())

    def test_import_preserves_original_and_live_state(self):
        self.rec.ingest(gga())
        before=self.rec.state()
        payload=(rmc()+gga()+"broken\n"+gga('120000.20')).encode()
        result=self.rec.import_log(payload,'sample.log')
        self.assertEqual(result['count'],2)
        self.assertEqual((Path(self.temp.name)/(result['session']+'.log')).read_bytes(),payload)
        self.assertEqual(self.rec.state()['active'],before['active'])
        self.assertEqual(self.rec.state()['quality'],before['quality'])
        self.assertEqual(len(self.rec.points('test')),1)
        self.assertTrue(self.rec.points(result['session'])[0]['measured'])

    def test_invalid_import_leaves_no_session(self):
        for payload in [b'',b'not nmea',b'x'*65537]:
            with self.assertRaises(ValueError):
                self.rec.import_log(payload,'bad.log')
        self.assertEqual(len(self.rec.sessions()),1)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.log'))),1)

    def test_http_endpoints_and_token(self):
        server=make_server(self.rec,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/config') as response:
                config=json.load(response)
            with urlopen(base+'/') as response:
                self.assertIn('GNSS 観測ノート',response.read().decode())
            (Path(self.temp.name)/'test.log').write_text(gga()+'broken\n')
            with urlopen(base+'/api/raw?session=test') as response:
                rows=json.load(response)
                self.assertEqual([r['valid'] for r in rows],[True,False])
                self.assertEqual(rows[1]['number'],2)
            with urlopen(base+'/api/raw?session=test&utc=120000.00') as response:
                self.assertEqual(len(json.load(response)),1)
            with urlopen(base+'/vendor/leaflet/leaflet.js') as response:
                self.assertIn(b'Leaflet',response.read())
            with self.assertRaises(HTTPError):
                urlopen(base+'/api/raw?session=../missing')
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base+'/api/start',data=b'{"source":"demo"}',headers={'Content-Type':'application/json'}))
            self.assertEqual(caught.exception.code,403)
            body=json.dumps({'source':'demo','title':'demo test'}).encode()
            headers={'Content-Type':'application/json','X-GNSS-Token':config['token']}
            with urlopen(Request(base+'/api/start',data=body,headers=headers)) as response:
                sid=json.load(response)['session']
            payload=(rmc()+gga()).encode()
            with urlopen(Request(base+'/api/import?name=sample.log',data=payload,headers={'X-GNSS-Token':config['token'],'Content-Type':'application/octet-stream'})) as response:
                imported=json.load(response)
                self.assertEqual(imported['count'],1)
                self.assertNotEqual(imported['session'],sid)
                self.assertEqual(self.rec.active,sid)
            with self.assertRaises(HTTPError) as rejected:
                urlopen(Request(base+'/api/import',data=payload))
            self.assertEqual(rejected.exception.code,403)
            time.sleep(.3)
            with urlopen(Request(base+'/api/stop',data=b'{}',headers=headers)) as response:
                self.assertTrue(json.load(response)['ok'])
            self.assertGreater(len(self.rec.points(sid)),0)
            with self.assertRaises(HTTPError):
                urlopen(Request(base+'/api/sessions',headers={'Host':'evil.example'}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__=='__main__':
    unittest.main()
