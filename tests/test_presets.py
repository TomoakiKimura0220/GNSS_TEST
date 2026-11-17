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

class ConnectionLifetimeTests(unittest.TestCase):
    def test_prepare_closes_database_before_replace_or_cleanup(self):
        import sqlite3
        import io
        from PIL import Image
        real_connect = sqlite3.connect
        image = io.BytesIO()
        Image.new('RGB', (2, 2)).save(image, format='PNG')
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as d:
                connections = []
                def connect(*args, **kwargs):
                    db = real_connect(*args, **kwargs)
                    connections.append(db)  # Retain references to prevent GC hiding leaks.
                    return db
                def assert_closed():
                    for db in connections:
                        with self.assertRaises(sqlite3.ProgrammingError):
                            db.execute('SELECT 1')
                original_replace, original_unlink = Path.replace, Path.unlink
                def replace(path, target):
                    assert_closed()
                    return original_replace(path, target)
                def unlink(path, *args, **kwargs):
                    assert_closed()
                    return original_unlink(path, *args, **kwargs)
                def download(*args, **kwargs):
                    if fail:
                        raise OSError('download failed')
                    return io.BytesIO(image.getvalue())
                with patch('gnss_maps.presets.sqlite3.connect', side_effect=connect), \
                     patch('gnss_maps.presets.urlopen', side_effect=download), \
                     patch('gnss_maps.presets.time.sleep'), \
                     patch.object(Path, 'replace', replace), patch.object(Path, 'unlink', unlink):
                    if fail:
                        with self.assertRaisesRegex(OSError, 'download failed'):
                            prepare(d, (137, 35, 137.0001, 35.0001))
                    else:
                        result = prepare(d, (137, 35, 137.0001, 35.0001))
                        self.assertEqual(len(result), 2)
                    assert_closed()

    def test_inspect_closes_database(self):
        import sqlite3
        import io
        from PIL import Image
        from gnss_maps.offline_map import inspect_map
        real_connect = sqlite3.connect
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'test.mbtiles'
            db = real_connect(p)
            db.executescript('CREATE TABLE metadata(name,value); CREATE TABLE tiles(zoom_level,tile_data);')
            image = io.BytesIO()
            Image.new('RGB', (256, 256)).save(image, format='PNG')
            db.execute('INSERT INTO tiles VALUES (14,?)', (image.getvalue(),))
            db.commit(); db.close()
            connection = real_connect(p)
            with patch('gnss_maps.offline_map.sqlite3.connect', return_value=connection):
                inspect_map(p)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
