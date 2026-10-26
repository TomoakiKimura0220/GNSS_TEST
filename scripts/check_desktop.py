"""Run an actual Tk event loop with synthetic data and all HTTP disabled."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tempfile
import tkinter as tk
from unittest.mock import patch
from gnss_maps.desktop import App

with tempfile.TemporaryDirectory() as directory, patch('requests.get', side_effect=AssertionError('Network forbidden')) as network:
    root=tk.Tk()
    app=App(root, directory)
    failures=[]
    def finish():
        try:
            assert len(app.receiver.track.points)>2
            assert not app.receiver.error, app.receiver.error
            assert not app.receiver.save_error, app.receiver.save_error
            assert '画面更新エラー' not in app.notice.cget('text'), app.notice.cget('text')
            app.receiver.stop_record()
            app.load(app.receiver.path)
            root.after(1200, replay)
        except Exception as exc:
            failures.append(exc); app.close()
    def replay():
        try:
            assert app.history and app.history.points
            app.slider.set(app.history.elapsed/2)
            app.update()
            assert app.current
            app.step(1)
            app.play()
            app.update()
            network.assert_not_called()
        except Exception as exc:
            failures.append(exc)
        finally:
            app.close()
    root.after(100,app.connect)
    root.after(300,lambda: app.receiver.record('synthetic'))
    root.after(2300,finish)
    root.mainloop()
    if failures: raise failures[0]
    print('PASS: Tk startup, synthetic serial, recording, log import, seek, replay; no HTTP')
