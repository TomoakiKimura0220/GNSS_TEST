"""Desktop acquisition and replay models; no GUI dependency."""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math
import threading
import time

from .live import fields_of, demo_lines
from .nmea import parse_gga
from .timed import time_seconds, JST


@dataclass
class Fix:
    lat: float
    lon: float
    utc: str
    quality: int
    satellites: str
    hdop: str
    elapsed: float
    segment: int
    raw: str
    measured: datetime | None = None
    rmc: str = ''

    def label(self):
        if self.measured:
            return self.measured.astimezone(JST).isoformat(timespec='milliseconds')
        seconds = time_seconds(self.utc)
        return (datetime(2000, 1, 1) + timedelta(seconds=seconds + 9*3600)).strftime('%H:%M:%S.%f')[:-3] + ' JST（日付不明）'


class Track:
    def __init__(self):
        self.points = []
        self.raw = deque(maxlen=1000)
        self.errors = 0
        self.quality = None
        self.segment = 0
        self.previous = None
        self.last_clock = None
        self.elapsed = 0.0
        self.dates = {}
        self.last_fix = None
        self.gap = 2.0
        self.max_speed = 30.0

    def feed(self, line):
        f = fields_of(line)
        self.raw.append((datetime.now().astimezone().isoformat(timespec='milliseconds'), line, bool(f)))
        if not f:
            self.errors += 1
            if line.startswith(('$GNGGA,', '$GPGGA,')):
                self.previous = None
            return
        if f[0] in ('GNRMC', 'GPRMC'):
            try:
                if len(f[9]) != 6 or f[2] != 'A':
                    return
                sec = time_seconds(f[1])
                day = f[9]
                dt = datetime(2000+int(day[4:]), int(day[2:4]), int(day[:2]), tzinfo=timezone.utc) + timedelta(seconds=sec)
                self.dates[sec] = (dt, line)
                if len(self.dates) > 20:
                    del self.dates[next(iter(self.dates))]
                for p in reversed(self.points[-20:]):
                    if time_seconds(p.utc) == sec and p.measured is None:
                        p.measured, p.rmc = dt, line
                        break
            except (IndexError, ValueError):
                self.errors += 1
            return
        if f[0] not in ('GNGGA', 'GPGGA'):
            return
        try:
            sec = time_seconds(f[1])
            delta = None if self.last_clock is None else sec-self.last_clock
            if delta is not None and self.last_clock > 82800 and sec < 3600:
                delta += 86400
            if delta is not None:
                self.elapsed += delta if delta > 0 else .001
            self.last_clock = sec
            self.quality = int(f[6])
            parsed = parse_gga(line)
            if parsed is None:
                self.previous = None
                return
            lat, lon, utc, quality = parsed
            split = self.previous is None or delta is None or delta <= 0 or delta > self.gap
            if self.previous and delta and delta > 0:
                old = self.previous
                distance = math.hypot((lat-old.lat)*111320, (lon-old.lon)*111320*math.cos(math.radians(lat)))
                split |= distance/delta > self.max_speed
            if split:
                self.segment += 1
            p = Fix(lat, lon, utc, int(quality), f[7], f[8], self.elapsed, self.segment, line)
            if sec in self.dates:
                p.measured, p.rmc = self.dates.pop(sec)
            self.points.append(p)
            self.previous = p
            self.last_fix = time.monotonic()
        except (IndexError, ValueError):
            self.errors += 1
            self.previous = None


def load_log(path, cancel=None, progress=None):
    track = Track()
    total = Path(path).stat().st_size
    if total > 150_000_000:
        raise ValueError('150 MBを超えるログです。分割して読み込んでください。')
    consumed = 0
    with Path(path).open('rb') as stream:
        for i, raw in enumerate(stream):
            if cancel and cancel.is_set():
                raise InterruptedError('読み込みを中止しました')
            if len(raw) > 65536:
                track.errors += 1
                continue
            track.feed(raw.decode('ascii', errors='replace').strip())
            consumed += len(raw)
            if progress and i % 1000 == 0:
                progress(consumed / max(total, 1))
    return track


class Receiver:
    """Serial work and durable raw recording continue independently of the UI."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.track = Track()
        self.thread = None
        self.stop_event = threading.Event()
        self.status = '未接続'
        self.error = ''
        self.save_error = ''
        self.file = None
        self.path = None
        self.started = None
        self.last_rx = None

    def connect(self, port, baud):
        self.disconnect()
        if port != 'デモ（架空データ）':
            import serial
            connection = serial.Serial(port, baudrate=baud, timeout=.3)
        else:
            connection = None
        self.stop_event.clear()
        self.status, self.error = '受信待ち', ''
        self.last_rx = None
        self.track.previous = None
        self.thread = threading.Thread(target=self._run, args=(connection,), daemon=True)
        self.thread.start()

    def record(self, title):
        with self.lock:
            if self.file:
                return
            if not self.thread or not self.thread.is_alive():
                raise ValueError('先に機器へ接続してください。')
            self.directory.mkdir(parents=True, exist_ok=True)
            safe = ''.join(c for c in title if c.isalnum() or c in '-_ ')[:60].strip() or '計測'
            path = self.directory / (datetime.now().strftime('%Y%m%d_%H%M%S_%f_') + safe + '.log')
            stream = path.open('xb', buffering=0)
            self.file, self.path = stream, path
            self.started = time.monotonic()
            self.save_error = ''
            self.track = Track()

    def stop_record(self):
        with self.lock:
            if self.file:
                try:
                    self.file.close()
                except OSError as exc:
                    self.save_error = str(exc)
                finally:
                    self.file = None

    def _run(self, connection):
        pending = b''
        demo = iter(demo_lines()) if connection is None else None
        try:
            while not self.stop_event.is_set():
                chunk = next(demo, b'') if demo else connection.read_until(b'\n', 4096)
                if not chunk:
                    if demo:
                        break
                    continue
                with self.lock:
                    self.last_rx = time.monotonic()
                    self.status = '受信中'
                    if self.file:
                        try:
                            if self.file.write(chunk) != len(chunk):
                                raise OSError('ログの書き込みが不完全です')
                        except OSError as exc:
                            self.save_error = str(exc)
                            self.stop_record()
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        self.track.feed(line.decode('ascii', errors='replace').strip())
                    if len(pending) > 65536:
                        self.track.errors += 1
                        pending = b''
                    # Original bytes remain in the log; only live display is bounded.
                    if len(self.track.points) > 50000:
                        del self.track.points[:10000]
                if demo and chunk.startswith(b'$GNGGA'):
                    self.stop_event.wait(.2)
        except Exception as exc:
            self.error = str(exc)
            self.status = '接続切断'
        finally:
            if connection:
                connection.close()
            if not self.error:
                self.status = '未接続'
            with self.lock:
                self.track.previous = None

    def disconnect(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError('切断処理中です。少し待って再試行してください。')
        self.status = '未接続'

    def close(self):
        self.disconnect()
        self.stop_record()
