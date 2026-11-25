import unittest
import xml.etree.ElementTree as ET
from gnss_maps.mowing_export import merged_kml

class MowingExportTests(unittest.TestCase):
    def point(self,x,y,segment=1):
        return dict(lat=35+y/110940.5745,lon=137+x/91288.1696,segment=segment)

    def test_retrace_merges_and_escapes(self):
        result=merged_kml([self.point(0,0),self.point(0,3),self.point(0,0)],0,'A & B')
        self.assertEqual(result['polygons'],1)
        ET.fromstring(result['kml'])
        self.assertIn('A &amp; B',result['kml'])

    def test_gaps_stay_separate(self):
        result=merged_kml([self.point(0,0),self.point(20,20,2)],0,'Gap')
        self.assertEqual(result['polygons'],2)

    def test_hole_preserved(self):
        points=[self.point(x,y) for x,y in [(0,0),(5,0),(5,5),(0,5),(0,0)]]
        result=merged_kml(points,0,'Loop')
        self.assertEqual(result['polygons'],1)
        self.assertIn('innerBoundaryIs',result['kml'])

    def test_invalid(self):
        with self.assertRaises(ValueError):merged_kml([],0,'Empty')
        with self.assertRaises(ValueError):merged_kml([self.point(0,0)],float('nan'),'NaN')

class OffsetTests(unittest.TestCase):
    def test_invalid_offsets(self):
        for value in [float('nan'),float('inf'),11,-11]:
            with self.assertRaises(ValueError):
                merged_kml([{'lat':35,'lon':137,'segment':1}],0,'test',value,0)
    def test_offset_rotates_with_heading(self):
        import xml.etree.ElementTree as ET
        def centre(heading,front,side):
            result=merged_kml([{'lat':35,'lon':137,'segment':1,'heading':heading}],0,'test',front,side)
            node=ET.fromstring(result['kml'])
            coords=node.find('.//{*}coordinates').text.split()
            xy=[tuple(map(float,c.split(',')[:2])) for c in coords]
            return ((min(p[0] for p in xy)+max(p[0] for p in xy))/2,(min(p[1] for p in xy)+max(p[1] for p in xy))/2)
        a=centre(0,.4,.2);b=centre(90,.4,.2)
        self.assertGreater(a[0],137);self.assertGreater(a[1],35)
        self.assertGreater(b[0],137);self.assertLess(b[1],35)
        c=centre(0,0,0)
        self.assertAlmostEqual(c[0],137,8);self.assertAlmostEqual(c[1],35,8)
