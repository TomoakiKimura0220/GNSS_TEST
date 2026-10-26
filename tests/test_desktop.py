import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from gnss_maps.live import nmea
from gnss_maps.session import Track, Receiver, load_log


def gga(clock='120000.00', quality=4, lat='3500.0000'):
    return nmea(f'GNGGA,{clock},{lat},N,13700.0000,E,{quality},12,0.8,10,M,36,M,,').decode().strip()


class DesktopTests(unittest.TestCase):
    def test_invalid_and_gap_split_without_dropping_raw(self):
        t = Track()
        t.feed(gga())
        t.feed(gga('120000.20', 0))
        t.feed(gga('120000.40'))
        t.feed(gga('120010.00'))
        t.feed('$GNGGA,broken*00')
        self.assertEqual([p.segment for p in t.points], [1,2,3])
        self.assertEqual(len(t.raw), 5)
        self.assertEqual(t.errors, 1)
        self.assertAlmostEqual(t.elapsed, 10)

    def test_rmc_after_and_before_gga(self):
        rmc = nmea('GNRMC,120000.00,A,3500.000,N,13700.000,E,0,0,191026,,,A,V').decode().strip()
        for lines in ((gga(),rmc),(rmc,gga())):
            t=Track()
            for line in lines: t.feed(line)
            self.assertEqual(t.points[0].measured.year,2026)
            self.assertIn('21:00:00',t.points[0].label())
            self.assertEqual(t.points[0].rmc,rmc)

    def test_midnight_and_reversal(self):
        t=Track()
        for clock in ('235959.80','000000.00','000000.20','000000.10'):
            t.feed(gga(clock))
        self.assertAlmostEqual(t.points[2].elapsed,.4)
        self.assertEqual(t.points[0].segment,t.points[2].segment)
        self.assertNotEqual(t.points[2].segment,t.points[3].segment)
        self.assertIn('日付不明',t.points[0].label())

    def test_position_jump_preserves_points(self):
        t=Track(); t.feed(gga()); t.feed(gga('120000.20',lat='3600.000'))
        self.assertEqual(len(t.points),2)
        self.assertEqual(t.points[1].segment,2)

    def test_load_bad_bytes_and_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log.txt'; p.write_bytes(b'\xff\n'+gga().encode()+b'\n')
            t=load_log(p)
            self.assertEqual(len(t.points),1)
            self.assertEqual(t.errors,1)
            cancel=threading.Event(); cancel.set()
            with self.assertRaises(InterruptedError): load_log(p,cancel)

    def test_disk_failure_does_not_stop_reception(self):
        class Broken:
            def write(self, value): raise OSError('disk full')
            def close(self): pass
        class Serial:
            def __init__(self,r): self.r=r; self.called=False
            def read_until(self,*args):
                if self.called:
                    self.r.stop_event.set(); return b''
                self.called=True; return (gga()+'\n').encode()
            def close(self): pass
        r=Receiver('/unused'); r.file=Broken()
        r._run(Serial(r))
        self.assertIsNone(r.file)
        self.assertIn('disk full',r.save_error)
        self.assertEqual(len(r.track.points),1)

    def test_serial_exception_keeps_recording_handle_for_resume(self):
        class Serial:
            def read_until(self,*args): raise OSError('unplugged')
            def close(self): pass
        r=Receiver('/unused'); r._run(Serial())
        self.assertEqual(r.status,'接続切断')
        self.assertIn('unplugged',r.error)

if __name__=='__main__': unittest.main()
