import unittest
from gnss_maps.mowing_heading import track
from gnss_maps.mowing_export import merged_kml

class HeadingTests(unittest.TestCase):
    def point(self,x,y,segment=1):
        return dict(lat=35+y/110940.5745,lon=137+x/91288.1696,segment=segment)

    def test_curve_and_reversals(self):
        points=[self.point(x,y) for x,y in [(0,0),(0,1),(.5,1.866),(1.366,2.366),(2.366,2.366),(1.366,2.366),(2.366,2.366)]]
        result=track(points)
        self.assertEqual(result[0]['heading'],0)
        for p in result[4:]:self.assertAlmostEqual(p['heading'],90,places=2)
        self.assertTrue(result[5]['reverse'])
        self.assertFalse(result[6]['reverse'])
        self.assertEqual(track(points[:4]),result[:4])
        self.assertIn('時系列方位推定',merged_kml(result,0,'test')['kml'])

    def test_jitter_and_gap_hold_heading(self):
        result=track([self.point(0,0),self.point(.02,-.02),self.point(5,0,2)])
        self.assertEqual([p['heading'] for p in result],[0,0,0])
        self.assertFalse(any(p['reverse'] for p in result))
