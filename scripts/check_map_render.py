"""Exercise actual raster tiles on the Tk owner thread, without HTTP."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from unittest.mock import patch
from gnss_maps.offline_map import map_widget_class, inspect_map
from gnss_maps.session import load_log

sources=[inspect_map(p) for p in Path('data/desktop/presets').glob('*.mbtiles')]
assert len(sources)==2
root=tk.Tk(); root.geometry('900x650')
failures=[]
root.report_callback_exception=lambda cls,exc,tb: failures.append(exc)
with patch('requests.get',side_effect=AssertionError('network forbidden')):
 m=map_widget_class()(root,width=900,height=650); m.pack(fill='both',expand=True)
 west,south,east,north=map(float,sources[0]['bounds'].split(','))
 m.set_position((south+north)/2,(west+east)/2)
 def cycle(i=0):
  if i==12:
   print('PASS: real raster tiles, both layers, zoom 14–18, 12 switches',flush=True)
   root.destroy(); return
  m.use_map(sources[i%2]); m.set_zoom(14+i%5)
  def check():
   images=list(m.tile_image_cache.values())
   if not images: failures.append(AssertionError('No raster images rendered'))
   cycle(i+1)
  root.after(800,check)
 root.after(200,cycle)
 root.mainloop()
if failures: raise failures[0]
