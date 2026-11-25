import unittest
from gnss_maps.coverage import calculate
from gnss_maps.experiments import scales

class CoverageTests(unittest.TestCase):
    def p(self,x,y,segment=1,quality=4):
        n,e=scales(35)
        return dict(lat=35+y/n,lon=137+x/e,segment=segment,quality=quality,heading=0)
    def boundary(self):return [self.p(x,y) for x,y in [(0,0),(10,0),(10,10),(0,10),(0,0)]]
    def test_clip_and_overlap(self):
        run=[self.p(-1,5),self.p(11,5)]
        result=calculate(self.boundary(),run,0,0)
        self.assertAlmostEqual(result['boundary_area'],100,5)
        self.assertAlmostEqual(result['covered_area'],5,5)
        self.assertAlmostEqual(result['percent'],5,5)
        self.assertGreater(result['outside_area'],0)
        retraced=calculate(self.boundary(),run+run[::-1],0,0)
        self.assertAlmostEqual(retraced['covered_area'],result['covered_area'],6)
    def test_outside_and_full(self):
        result=calculate(self.boundary(),[self.p(20,20)],0,0)
        self.assertEqual(result['percent'],0)
        tiny=[self.p(x,y) for x,y in [(-.05,-.05),(.05,-.05),(.05,.05),(-.05,.05),(-.05,-.05)]]
        self.assertAlmostEqual(calculate(tiny,[self.p(0,0)],0,0)['percent'],100,6)
    def test_closure_and_invalid_boundaries(self):
        with self.assertRaisesRegex(ValueError,'直線で閉じる'):
            calculate(self.boundary()[:-1],[self.p(5,5)],0,0)
        self.assertAlmostEqual(calculate(self.boundary()[:-1],[self.p(5,5)],0,0,True)['closing_gap'],10,5)
        crossed=[self.p(x,y) for x,y in [(0,0),(10,10),(0,10),(10,0),(0,0)]]
        with self.assertRaises(ValueError):calculate(crossed,[self.p(5,5)])
        broken=self.boundary();broken[1]['segment']=2
        with self.assertRaises(ValueError):calculate(broken,[self.p(5,5)])
        broken=self.boundary();broken[1]['quality']=2
        with self.assertRaises(ValueError):calculate(broken,[self.p(5,5)])
    def test_offset_and_gaps(self):
        run=[self.p(-1,5),self.p(11,5,segment=2)]
        self.assertEqual(calculate(self.boundary(),run,0,0)['covered_area'],0)
        original=calculate(self.boundary(),[self.p(-.5,5)],0,0)
        shifted=calculate(self.boundary(),[self.p(-.5,5)],0,1)
        self.assertEqual(original['covered_area'],0)
        self.assertGreater(shifted['covered_area'],0)
