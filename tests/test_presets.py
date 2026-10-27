import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
from gnss_maps.presets import prepare, tile_xy

class PresetTests(unittest.TestCase):
    def test_coordinates(self):
        self.assertEqual(tile_xy(0,0,1),(1,1))
    def test_reject_large_range_before_network(self):
        with tempfile.TemporaryDirectory() as d, patch('gnss_maps.presets.urlopen') as request:
            with self.assertRaises(ValueError): prepare(d, (130,30,140,40))
            request.assert_not_called()
    def test_failed_download_preserves_previous_map(self):
        with tempfile.TemporaryDirectory() as d, patch('gnss_maps.presets.urlopen',side_effect=OSError('offline')):
            p=Path(d)/'std.mbtiles'; p.write_bytes(b'existing')
            with self.assertRaises(OSError): prepare(d,(137,35,137.0001,35.0001))
            self.assertEqual(p.read_bytes(),b'existing')
            self.assertFalse((Path(d)/'std.partial').exists())

class ParentTileTests(unittest.TestCase):
    def test_missing_detail_uses_correct_parent_quadrant(self):
        import sqlite3, io
        from PIL import Image
        from gnss_maps.offline_map import tile_with_parent
        db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE tiles(zoom_level,tile_column,tile_row,tile_data)')
        im=Image.new('RGB',(256,256),'red');im.paste('blue',(128,0,256,128))
        out=io.BytesIO();im.save(out,format='PNG')
        db.execute('INSERT INTO tiles VALUES(1,1,1,?)',(out.getvalue(),))
        result=tile_with_parent(db,2,3,0)
        with Image.open(io.BytesIO(result)) as tile:
            self.assertEqual(tile.getpixel((128,128)),(0,0,255))
        self.assertIsNone(tile_with_parent(db,2,0,3))
        db.close()
