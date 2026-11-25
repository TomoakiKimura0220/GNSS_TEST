import sqlite3
import unittest
from gnss_maps.experiments import initialise, save, load, list_saved, translate

class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE points(id INTEGER,session TEXT,lat REAL,lon REAL,quality INTEGER)')
        self.db.executemany('INSERT INTO points VALUES (?,?,?,?,?)',[(1,'outline',35,137,4),(2,'run',34.9999,136.9999,2),(3,'run',35.0001,137.0001,2),(4,'other',35,137,2)])
        initialise(self.db)
    def tearDown(self): self.db.close()
    def payload(self):return dict(session='run',first=2,last=3,title='実験1',reference={'session':'outline','id':1},match={'id':2},front=.4,side=.2)
    def test_roundtrip_and_translation_preserves_raw(self):
        exp=save(self.db,self.payload());self.assertEqual(load(self.db,exp['id']),exp)
        self.assertEqual(len(list_saved(self.db)),1)
        raw=[dict(r) for r in self.db.execute("SELECT * FROM points WHERE session='run' ORDER BY id")]
        moved=translate(raw,exp)
        self.assertAlmostEqual(moved[0]['lat'],35);self.assertAlmostEqual(moved[0]['lon'],137)
        self.assertAlmostEqual(moved[1]['lat']-moved[0]['lat'],raw[1]['lat']-raw[0]['lat'])
        self.assertEqual(moved[0]['quality'],2);self.assertEqual(raw[0]['lat'],34.9999)
        self.assertGreater(exp['east'],0);self.assertGreater(exp['north'],0)
    def test_plain_range(self):
        p=self.payload();p.update(reference=None,match=None)
        self.assertEqual(save(self.db,p)['east'],0)
    def test_invalid_reference_quality_or_range(self):
        for change in [dict(first=3,last=2),dict(first=3),dict(reference={'session':'run','id':2}),dict(match={'id':4}),dict(front=float('nan'))]:
            p=self.payload();p.update(change)
            with self.assertRaises(ValueError):save(self.db,p)
