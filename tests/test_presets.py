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
