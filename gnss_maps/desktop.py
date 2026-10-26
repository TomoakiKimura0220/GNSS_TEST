"""Offline GNSS desktop app: uv run python -m gnss_maps.desktop."""
import argparse
import bisect
import csv
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import xml.etree.ElementTree as ET

from .session import Receiver, load_log
from .offline_map import inspect_map, map_widget_class

COLORS = {1: '#667085', 2: '#8055A0', 4: '#007A65', 5: '#B56A00'}
QUALITY = {0: '未測位', 1: '単独測位', 2: '補正測位', 4: 'FIX', 5: 'FLOAT'}


class App:
    def __init__(self, root, directory):
        self.root, self.directory = root, Path(directory)
        self.receiver = Receiver(self.directory / 'logs')
        self.history = None
        self.history_path = None
        self.playing = False
        self.cursor = 0.0
        self.last_tick = time.monotonic()
        self.draw_key = None
        self.jobs = queue.Queue()
        self.cancel = threading.Event()
        self.loading = False
        self.layers = {}
        self.preset_busy = False
        self.preset_cancel = threading.Event()
        self.paths = []
        self.marker = None
        self.current = None
        self.raw_snapshot = []
        self.root.title('GNSS計測 — オフライン地図')
        self.root.geometry('1280x820')
        self.root.minsize(960, 650)
        self.root.configure(bg='#F4F6F8')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Helvetica', 12), background='#F4F6F8', foreground='#172B4D')
        style.configure('TButton', padding=(10, 7))
        style.configure('Primary.TButton', background='#005BAC', foreground='white')
        style.configure('Status.TLabel', font=('Helvetica', 14, 'bold'), padding=8)
        self.build()
        self.read_config()
        self.refresh_ports()
        self.refresh_history()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(150, self.tick)

    def button(self, parent, text, command, **kwargs):
        b = ttk.Button(parent, text=text, command=lambda: self.guard(command), **kwargs)
        b.pack(side='left', padx=3, pady=3)
        return b

    def guard(self, fn):
        try:
            fn()
        except Exception as exc:
            messagebox.showerror('操作できません', str(exc), parent=self.root)

    def build(self):
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill='x')
        ttk.Label(header, text='GNSS計測', font=('Helvetica', 20, 'bold')).pack(side='left', padx=8)
        self.state = ttk.Label(header)
        self.state.pack(side='left', expand=True, fill='x')
        self.record_button = self.button(header, '記録開始', self.toggle_record, style='Primary.TButton')
        self.button(header, 'パネル開閉', self.toggle_panel)
        self.fix_status = ttk.Label(self.root, style='Status.TLabel', text='測位：未接続')
        self.fix_status.pack(fill='x', padx=16)
        self.notice = ttk.Label(self.root, foreground='#9C3C00', wraplength=1150, padding=(16, 4))
        self.notice.pack(fill='x')
        self.body = ttk.Panedwindow(self.root, orient='horizontal')
        self.body.pack(fill='both', expand=True, padx=16, pady=8)
        left = ttk.Frame(self.body)
        self.body.add(left, weight=4)
        toolbar = ttk.Frame(left)
        toolbar.pack(fill='x')
        self.layer = tk.StringVar(value='地形図')
        for name in ('地形図', '航空写真'):
            ttk.Radiobutton(toolbar, text=name, variable=self.layer, value=name, command=self.switch_layer).pack(side='left', padx=5)
        self.follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text='位置に追従', variable=self.follow).pack(side='right')
        self.mode = ttk.Label(left, text='ライブ表示', padding=6)
        self.mode.pack(fill='x')
        self.map = map_widget_class()(left, corner_radius=0, width=850, height=480)
        self.map.pack(fill='both', expand=True)
        self.map.set_position(35, 137)
        self.map.set_zoom(15)
        self.map.canvas.bind('<B1-Motion>', lambda e: self.follow.set(False), add='+')
        controls = ttk.Frame(left)
        controls.pack(fill='x')
        self.button(controls, '現在位置へ', self.center)
        self.button(controls, '経路全体', self.fit)
        ttk.Label(controls, text='FIX：緑　FLOAT：橙　補正：紫　単独：灰').pack(side='right')
        self.attribution = ttk.Label(left, wraplength=780)
        self.attribution.pack(fill='x')
        self.replay = ttk.Frame(left, padding=5)
        self.replay.pack(fill='x')
        row = ttk.Frame(self.replay)
        row.pack(fill='x')
        self.button(row, '先頭', lambda: self.seek(0))
        self.button(row, '前の点', lambda: self.step(-1))
        self.play_button = self.button(row, '▶ 再生', self.play)
        self.button(row, '次の点', lambda: self.step(1))
        self.speed = tk.StringVar(value='1')
        ttk.Combobox(row, textvariable=self.speed, values=['0.5','1','2','5','10'], width=4, state='readonly').pack(side='left')
        ttk.Label(row, text='倍').pack(side='left')
        self.full = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text='全経路を薄く表示', variable=self.full, command=self.invalidate).pack(side='left', padx=8)
        self.button(row, 'ライブに戻る', self.live)
        self.slider = ttk.Scale(self.replay, from_=0, to=1, command=self.seek)
        self.slider.pack(fill='x')
        self.clock = ttk.Label(self.replay, text='履歴を開くと時系列を確認できます')
        self.clock.pack(fill='x')
        self.panel = ttk.Notebook(self.body, width=330)
        self.body.add(self.panel, weight=1)
        tabs = {}
        for name in ('接続', '地図', '履歴', '詳細'):
            tabs[name] = ttk.Frame(self.panel, padding=10)
            self.panel.add(tabs[name], text=name)
        p = tabs['接続']
        ttk.Label(p, text='USBシリアルポート').pack(anchor='w')
        self.port = tk.StringVar(value='デモ（架空データ）')
        self.ports = ttk.Combobox(p, textvariable=self.port, state='readonly', width=30)
        self.ports.pack(fill='x', pady=5)
        self.baud = tk.StringVar(value='38400')
        ttk.Label(p, text='通信速度').pack(anchor='w')
        ttk.Combobox(p, textvariable=self.baud, values=['9600','19200','38400','57600','115200','230400','460800','921600'], state='readonly').pack(fill='x')
        row = ttk.Frame(p); row.pack(fill='x')
        self.button(row, '再検索', self.refresh_ports)
        self.button(row, '接続', self.connect)
        self.button(row, '切断', self.disconnect)
        ttk.Label(p, text='PCのインターネット接続は不要です。\nUSB受信と記録は別操作です。\n切断後は接続先を確認して再接続します。', wraplength=290).pack(pady=15, anchor='w')
        ttk.Label(p, text='区間を分けるしきい値').pack(anchor='w')
        self.gap = tk.StringVar(value='2')
        self.jump = tk.StringVar(value='30')
        for label, value in [('受信間隔（秒）', self.gap), ('位置飛び（m/s）', self.jump)]:
            ttk.Label(p, text=label).pack(anchor='w')
            ttk.Entry(p, textvariable=value).pack(fill='x')
        self.button(p, 'ライブ解析に適用', self.thresholds)
        p = tabs['地図']
        ttk.Label(p, text='標準プリセット：国土地理院', wraplength=290).pack(anchor='w')
        self.button(p, '表示中心の周辺を準備（ネット必要）', self.prepare_presets)
        self.button(p, '標準プリセットに戻す', self.restore_presets)
        self.button(p, '準備を中止', self.preset_cancel.set)
        self.preset_status = ttk.Label(p, wraplength=290)
        self.preset_status.pack(fill='x')
        ttk.Label(p, text='手元の地図（任意）', wraplength=290).pack(anchor='w')
        for name in ('地形図', '航空写真'):
            row = ttk.Frame(p); row.pack(fill='x')
            self.button(row, name+'を追加', lambda n=name: self.import_map(n))
        self.map_info = ttk.Label(p, wraplength=290)
        self.map_info.pack(fill='x', pady=10)
        ttk.Label(p, text='PNG/JPEG等の画像タイルに対応。\nベクトル地図・3D地形は対象外です。\n地図がなくても受信・保存できます。\n地図データは利用条件を確認して用意してください。', wraplength=290).pack(anchor='w')
        self.button(p, '保存範囲へ', self.map_bounds)
        p = tabs['履歴']
        row = ttk.Frame(p); row.pack(fill='x')
        self.button(row, '生ログを開く', self.open_log)
        self.button(row, '一覧更新', self.refresh_history)
        self.history_list = tk.Listbox(p, height=10, exportselection=False)
        self.history_list.pack(fill='both', expand=True, pady=8)
        self.history_list.bind('<Double-Button-1>', lambda e: self.guard(self.open_selected))
        row = ttk.Frame(p); row.pack(fill='x')
        self.button(row, '選択履歴を開く', self.open_selected)
        self.button(row, '中止', self.cancel.set)
        self.progress = ttk.Label(p, wraplength=290)
        self.progress.pack(fill='x')
        row = ttk.Frame(p); row.pack(fill='x')
        self.button(row, 'CSV出力', lambda: self.export('csv'))
        self.button(row, 'KML出力', lambda: self.export('kml'))
        self.button(p, '生ログを保存', self.copy_log)
        p = tabs['詳細']
        self.details = ttk.Label(p, wraplength=290)
        self.details.pack(fill='x')
        self.button(p, '選択点の生データ', self.point_raw)
        self.filter = tk.StringVar(value='すべて')
        ttk.Combobox(p, textvariable=self.filter, values=['すべて','GGA','RMC','その他','解析エラー'], state='readonly').pack(fill='x', pady=5)
        self.pause_raw = tk.BooleanVar(value=False)
        ttk.Checkbutton(p, text='表示を一時停止（記録は継続）', variable=self.pause_raw).pack(anchor='w')
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(p, text='自動スクロール', variable=self.autoscroll).pack(anchor='w')
        self.raw = tk.Text(p, height=12, width=35, wrap='none', font=('Courier', 10))
        self.raw.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(p, orient='horizontal', command=self.raw.xview)
        scroll.pack(fill='x'); self.raw.configure(xscrollcommand=scroll.set)
        self.button(p, '選択をコピー', self.copy_selection)
        self.replay.pack_forget()

    def thresholds(self):
        gap, speed = float(self.gap.get()), float(self.jump.get())
        if not (0 < gap < 3600 and 0 < speed < 10000):
            raise ValueError('しきい値は正の数で指定してください')
        with self.receiver.lock:
            self.receiver.track.gap, self.receiver.track.max_speed = gap, speed

    def invalidate(self):
        self.draw_key = None

    def toggle_panel(self):
        if str(self.panel) in self.body.panes():
            self.body.forget(self.panel)
        else:
            self.body.add(self.panel, weight=1)

    def refresh_ports(self):
        from serial.tools.list_ports import comports
        self.ports['values'] = ['デモ（架空データ）'] + [p.device for p in comports()]

    def connect(self):
        self.receiver.connect(self.port.get(), int(self.baud.get()))
        self.thresholds()

    def disconnect(self):
        if self.receiver.file and not messagebox.askyesno('記録中', '記録を停止して切断しますか？'):
            return
        self.receiver.stop_record()
        self.receiver.disconnect()
        self.refresh_history()

    def toggle_record(self):
        if self.receiver.file:
            self.receiver.stop_record()
            self.refresh_history()
        else:
            title = simpledialog.askstring('記録開始', '計測名', initialvalue='デモ' if self.port.get().startswith('デモ') else '計測')
            if title is not None:
                self.receiver.record(title)
                self.thresholds()
                self.live()

    def save_maps(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        config = self.directory / 'maps.json'
        temporary = config.with_suffix('.tmp')
        temporary.write_text(json.dumps({k:v['path'] for k,v in self.layers.items()}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(config)

    def restore_presets(self):
        from .presets import PRESETS
        for name, (layer, _) in PRESETS.items():
            path = self.directory / 'presets' / (layer+'.mbtiles')
            if path.exists():
                self.layers[name] = inspect_map(path)
        self.save_maps()
        self.switch_layer()

    def prepare_presets(self):
        if self.preset_busy:
            raise ValueError('地図を準備中です')
        lat, lon = self.map.get_position()
        bounds = (lon-.006, lat-.0045, lon+.006, lat+.0045)
        if not messagebox.askyesno('オフライン地図の準備', '表示中心の周辺約1 km四方を保存します。準備時のみネット通信します。\n国土地理院の地形図・航空写真（倍率14〜18）。取得範囲が配信元に伝わります。\n準備しますか？'):
            return
        self.preset_busy = True
        self.preset_cancel.clear()
        from .presets import prepare
        def job():
            try:
                prepare(self.directory/'presets', bounds, lambda text:self.jobs.put(('map_progress',text)),self.preset_cancel)
                self.jobs.put(('maps_ready',None))
            except Exception as exc:
                self.jobs.put(('map_error',str(exc)))
        threading.Thread(target=job,daemon=True).start()

    def import_map(self, name):
        path = filedialog.askopenfilename(filetypes=[('画像地図', '*.mbtiles'), ('すべて', '*')])
        if not path:
            return
        info = inspect_map(path)
        self.layers[name] = info
        self.directory.mkdir(parents=True, exist_ok=True)
        config = self.directory / 'maps.json'
        temporary = config.with_suffix('.tmp')
        temporary.write_text(json.dumps({k:v['path'] for k,v in self.layers.items()}, ensure_ascii=False), encoding='utf-8')
        temporary.replace(config)
        self.layer.set(name)
        self.switch_layer()
        self.map_bounds()

    def read_config(self):
        try:
            config = self.directory / 'maps.json'
            if config.exists():
                for name, path in json.loads(config.read_text(encoding='utf-8')).items():
                    try:
                        self.layers[name] = inspect_map(path)
                    except Exception as exc:
                        self.notice.configure(text='保存済み地図を開けません：'+str(exc))
        except (OSError, ValueError) as exc:
            self.notice.configure(text=str(exc))
        self.switch_layer()

    def switch_layer(self):
        source = self.layers.get(self.layer.get())
        self.map.use_map(source)
        self.attribution.configure(text=source['attribution'] if source else '背景地図なし — 経路の受信・保存は利用できます')
        self.map_info.configure(text='\n\n'.join(f"{k}：{v['name']}\n倍率 {v['minzoom']}–{v['maxzoom']}\n範囲 {v['bounds'] or '情報なし'}" for k,v in self.layers.items()) or '地図データは未取得です。')
        self.invalidate()

    def map_bounds(self):
        source = self.layers.get(self.layer.get())
        if source and source['bounds']:
            west, south, east, north = map(float, source['bounds'].split(','))
            self.follow.set(False)
            self.map.fit_bounding_box((north, west), (south, east))

    def refresh_history(self):
        self.history_files = sorted((self.directory/'logs').glob('*.log'), reverse=True)
        self.history_list.delete(0, 'end')
        for path in self.history_files:
            self.history_list.insert('end', path.name)

    def open_selected(self):
        selected = self.history_list.curselection()
        if selected:
            self.load(self.history_files[selected[0]])

    def open_log(self):
        path = filedialog.askopenfilename(filetypes=[('NMEAログ', '*.log *.txt *.nmea'), ('すべて','*')])
        if path:
            self.load(Path(path))

    def load(self, path):
        if self.loading:
            raise ValueError('読み込み中です。中止するか完了を待ってください。')
        self.loading = True
        self.cancel.clear()
        self.progress.configure(text='読み込み中…')
        def job():
            try:
                track = load_log(path, self.cancel, lambda value: self.jobs.put(('progress', value)))
                self.jobs.put(('loaded', (track, Path(path))))
            except Exception as exc:
                self.jobs.put(('error', str(exc)))
        threading.Thread(target=job, daemon=True).start()

    def live(self):
        self.history = None
        self.playing = False
        self.replay.pack_forget()
        self.mode.configure(text='ライブ表示')
        self.invalidate()

    def seek(self, value):
        self.cursor = float(value)
        self.invalidate()

    def step(self, direction):
        if self.history and self.history.points:
            points = self.history.points
            i = bisect.bisect_right([p.elapsed for p in points], self.cursor)-1
            self.slider.set(points[max(0, min(len(points)-1, i+direction))].elapsed)
            self.playing = False

    def play(self):
        if self.history and self.history.points:
            if self.cursor >= self.history.elapsed:
                self.slider.set(0)
            self.playing = not self.playing

    def center(self):
        self.follow.set(True)
        if self.current:
            self.map.set_position(self.current.lat, self.current.lon)

    def fit(self):
        track = self.history or self.receiver.track
        if track.points:
            self.follow.set(False)
            points = track.points
            self.map.fit_bounding_box((max(p.lat for p in points)+.0001, min(p.lon for p in points)-.0001),
                                     (min(p.lat for p in points)-.0001, max(p.lon for p in points)+.0001))

    def point_raw(self):
        if self.current:
            win = tk.Toplevel(self.root); win.title('選択点の元データ')
            text = tk.Text(win, width=110, height=9, wrap='word')
            text.pack(fill='both', expand=True)
            text.insert('end', self.current.label()+'\n\n'+self.current.raw+'\n'+self.current.rmc)

    def copy_selection(self):
        try:
            value = self.raw.get('sel.first','sel.last')
        except tk.TclError:
            return
        self.root.clipboard_clear(); self.root.clipboard_append(value)

    def copy_log(self):
        source = self.history_path if self.history else self.receiver.path
        if not source:
            raise ValueError('保存済みログがありません')
        target = filedialog.asksaveasfilename(defaultextension='.log')
        if target:
            if Path(target).resolve() == Path(source).resolve():
                raise ValueError('元ログとは別のファイルを指定してください')
            import shutil
            shutil.copyfile(source, target)

    def export(self, kind):
        points = list((self.history or self.receiver.track).points)
        if not points:
            raise ValueError('出力する測位点がありません')
        if not self.history and self.receiver.path:
            points = load_log(self.receiver.path).points
        target = filedialog.asksaveasfilename(defaultextension='.'+kind)
        if not target:
            return
        if kind == 'csv':
            with open(target, 'w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['datetime_jst','latitude','longitude','quality','segment','elapsed_seconds'])
                writer.writerows((p.label(),p.lat,p.lon,p.quality,p.segment,p.elapsed) for p in points)
        else:
            root = ET.Element('kml', xmlns='http://www.opengis.net/kml/2.2')
            doc = ET.SubElement(root, 'Document')
            groups = []
            for p in points:
                if not groups or groups[-1][-1].segment != p.segment:
                    groups.append([])
                groups[-1].append(p)
            for group in groups:
                mark = ET.SubElement(doc, 'Placemark')
                geom = ET.SubElement(mark, 'LineString' if len(group)>1 else 'Point')
                ET.SubElement(geom, 'coordinates').text = ' '.join(f'{p.lon},{p.lat},0' for p in group)
            ET.ElementTree(root).write(target, encoding='utf-8', xml_declaration=True)

    def render(self, points, index, stale=False):
        key = (id(self.history), len(points), index, self.full.get(), stale, self.layer.get())
        if self.draw_key == key:
            return
        self.draw_key = key
        for path in self.paths:
            path.delete()
        self.paths = []
        def lines(data, background=False):
            # Preserve every segment boundary while limiting drawing cost.
            groups = []
            for p in data:
                if not groups or (p.segment, p.quality) != (groups[-1][-1].segment, groups[-1][-1].quality):
                    previous = groups[-1][-1] if groups and groups[-1][-1].segment == p.segment else None
                    groups.append([previous] if previous else [])
                groups[-1].append(p)
            for group in groups:
                if len(group) < 2:
                    continue
                stride = max(1, len(group)//1500)
                coords = [(p.lat,p.lon) for p in group[::stride]]
                coords.append((group[-1].lat,group[-1].lon))
                self.paths.append(self.map.set_path(coords, color='#BCC4CF' if background else COLORS.get(group[-1].quality,'#667085'), width=2 if background else 4))
        if self.history and self.full.get():
            lines(points, True)
        lines(points[:index+1])
        if self.marker:
            self.marker.delete(); self.marker = None
        self.current = points[index] if 0 <= index < len(points) else None
        if self.current:
            p = self.current
            label = ('最後の位置' if stale else '再生位置' if self.history else '現在位置')
            self.marker = self.map.set_marker(p.lat,p.lon, text=label, marker_color_circle='#FFFFFF',
                marker_color_outside='#667085' if stale else COLORS.get(p.quality,'#667085'), command=lambda m: self.point_raw())
            if self.follow.get():
                self.map.set_position(p.lat, p.lon)
            self.details.configure(text=f'{p.label()}\n緯度 {p.lat:.9f}\n経度 {p.lon:.9f}\n品質 {p.quality} / 衛星 {p.satellites}\nHDOP {p.hdop}（位置誤差ではありません）')
        else:
            self.details.configure(text='有効な位置がありません')

    def tick(self):
        try:
            self.update()
        except Exception as exc:
            self.notice.configure(text='画面更新エラー：'+str(exc))
        self.root.after(200, self.tick)

    def update(self):
        now = time.monotonic()
        delta = now-self.last_tick; self.last_tick = now
        while not self.jobs.empty():
            kind, value = self.jobs.get_nowait()
            if kind == 'map_progress':
                self.preset_status.configure(text=value)
            elif kind == 'map_error':
                self.preset_busy = False
                self.preset_status.configure(text='準備できません：'+value)
            elif kind == 'maps_ready':
                self.preset_busy = False
                self.restore_presets()
                self.preset_status.configure(text='準備完了。以後はオフラインで使えます。')
            elif kind == 'progress':
                self.progress.configure(text=f'読み込み中 {value:.0%}')
            elif kind == 'error':
                self.loading = False
                self.progress.configure(text=value)
            else:
                self.loading = False
                self.history, self.history_path = value
                self.playing = False
                self.cursor = 0
                self.slider.configure(to=max(.001, self.history.elapsed))
                self.slider.set(0)
                self.replay.pack(fill='x')
                self.mode.configure(text='履歴表示：'+self.history_path.name)
                self.progress.configure(text=f'{len(self.history.points):,}点 / 解析エラー {self.history.errors}行\n' + ('描画できる測位点がありません' if not self.history.points else f'{self.history.points[0].label()}\n〜 {self.history.points[-1].label()}'))
                self.fit(); self.invalidate()
        with self.receiver.lock:
            r = self.receiver
            age = now-r.last_rx if r.last_rx else None
            status = '受信停止' if age is not None and age>3 and r.status=='受信中' else r.status
            recording = f'記録中 {int(now-r.started)}秒' if r.file else '未記録'
            if r.save_error:
                recording = '保存失敗（記録していません）'
            self.state.configure(text=f'USB：{status}   │   {recording}')
            self.record_button.configure(text='記録停止' if r.file else '記録開始')
            quality = QUALITY.get(r.track.quality, '未測位')
            last = r.track.points[-1] if r.track.points else None
            stale = r.track.quality not in (1,2,4,5) or not r.track.last_fix or now-r.track.last_fix>3 or r.status in ('未接続','接続切断')
            self.fix_status.configure(text=f'ライブ測位：{quality}'+('（位置更新なし）' if stale else '')+f'   使用衛星：{last.satellites if last else "—"}   最終受信：'+(f'{age:.1f}秒前' if age is not None else '—'))
            messages = [v for v in (r.error, ('保存失敗：'+r.save_error) if r.save_error else '', self.map.tile_problem) if v]
            self.notice.configure(text=' ｜ '.join(messages))
            track = self.history or r.track
            points = list(track.points)
            raw = list(track.raw)
        if self.history:
            if self.playing:
                self.slider.set(min(self.history.elapsed, self.cursor+delta*float(self.speed.get())))
                if self.cursor >= self.history.elapsed:
                    self.playing = False
            index = bisect.bisect_right([p.elapsed for p in points], self.cursor)-1
            selected = points[index] if index>=0 else None
            offset = self.cursor-selected.elapsed if selected else 0
            stale = selected is None or offset > track.gap
            self.clock.configure(text=(selected.label() if selected else '有効位置なし') + f'   経過 {self.cursor:.1f}秒' + (f'   データなし・{offset:.1f}秒前の位置' if stale and selected else ''))
        else:
            index = len(points)-1
        self.play_button.configure(text='❚❚ 停止' if self.playing else '▶ 再生')
        self.render(points,index,stale)
        if not self.pause_raw.get():
            choice = self.filter.get()
            rows = [(stamp,line,valid) for stamp,line,valid in raw if choice=='すべて' or
                    choice in ('GGA','RMC') and line[3:6]==choice or
                    choice=='解析エラー' and not valid or
                    choice=='その他' and line[3:6] not in ('GGA','RMC')]
            if rows != self.raw_snapshot:
                view = self.raw.yview()
                self.raw.delete('1.0','end')
                self.raw.insert('end','\n'.join(('読込 ' if self.history else '受信 ')+stamp+'  '+line for stamp,line,valid in rows))
                self.raw_snapshot = rows
                if self.autoscroll.get():
                    self.raw.see('end')
                else:
                    self.raw.yview_moveto(view[0])

    def close(self):
        if self.receiver.file and not messagebox.askyesno('記録中', '記録を停止して終了しますか？'):
            return
        self.cancel.set()
        self.preset_cancel.set()
        self.receiver.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='オフラインGNSS計測・履歴再生')
    parser.add_argument('--data-dir', type=Path, default=Path('data/desktop'))
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    root = tk.Tk()
    app = App(root,args.data_dir)
    if args.log:
        app.load(args.log)
    root.mainloop()


if __name__ == '__main__':
    main()
