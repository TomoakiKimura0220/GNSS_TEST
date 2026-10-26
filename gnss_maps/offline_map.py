"""Raster MBTiles adapter. Never calls a network tile server."""
import io
import sqlite3
from pathlib import Path


def inspect_map(path):
    path = Path(path).resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        metadata = dict(db.execute('SELECT name,value FROM metadata'))
        first = db.execute('SELECT tile_data FROM tiles LIMIT 1').fetchone()
        if not first:
            raise ValueError('地図画像がありません')
        from PIL import Image
        with Image.open(io.BytesIO(first[0])) as picture:
            picture.verify()
        low, high = db.execute('SELECT MIN(zoom_level),MAX(zoom_level) FROM tiles').fetchone()
    return dict(path=str(path), name=metadata.get('name', path.stem),
                attribution=metadata.get('attribution', '出典情報なし：配布元の条件を確認してください'),
                bounds=metadata.get('bounds', ''), minzoom=low, maxzoom=high,
                scheme=metadata.get('scheme', 'tms'))


def map_widget_class():
    from tkintermapview import TkinterMapView
    from PIL import Image, ImageTk

    class OfflineMap(TkinterMapView):
        def __init__(self, *args, **kwargs):
            self.source = None
            self.tile_problem = '背景地図未取得：地図タブから追加してください'
            super().__init__(*args, use_database_only=True, max_zoom=22, **kwargs)

        def pre_cache(self):
            # Tk images must only be created/deleted on the Tk owner thread.
            pass

        def load_images_background(self):
            pass

        def update_canvas_tile_images(self):
            if not self.running:
                return
            for _ in range(min(8, len(self.image_load_queue_tasks))):
                coords, tile = self.image_load_queue_tasks.pop(0)
                zoom, x, y = coords
                if zoom != round(self.zoom):
                    continue
                image = self.get_tile_image_from_cache(zoom, x, y)
                if image is False:
                    image = self.request_image(zoom, x, y)
                tile.set_image(image)
            self.after(30, self.update_canvas_tile_images)

        def request_image(self, zoom, x, y, db_cursor=None):
            # Override instead of relying on use_database_only: upstream can fetch
            # online when no database cursor exists. This path has no HTTP calls.
            source = self.source
            if source is None:
                return self.empty_tile_image
            try:
                row = y if source['scheme'] == 'xyz' else (1 << zoom)-1-y
                path = Path(source['path'])
                with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                    result = db.execute('SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
                                        (zoom, x % (1 << zoom), row)).fetchone()
                if not result:
                    self.tile_problem = '表示範囲／倍率の一部に保存済み地図がありません'
                    return self.empty_tile_image
                with Image.open(io.BytesIO(result[0])) as img:
                    img = img.convert('RGB').resize((256, 256))
                    image = ImageTk.PhotoImage(img)
                # Do not put old-layer results into the new layer's cache.
                if source is self.source and self.running:
                    self.tile_image_cache[f'{zoom}{x}{y}'] = image
                    return image
            except Exception as exc:
                self.tile_problem = '地図読み込み失敗：' + str(exc)
            return self.empty_tile_image

        def use_map(self, source):
            self.source = source
            self.tile_problem = '' if source else '背景地図未取得：地図タブから追加してください'
            self.tile_image_cache.clear()
            self.set_tile_server('offline://local/{z}/{x}/{y}', max_zoom=source['maxzoom'] if source else 22)
            if source:
                self.min_zoom = source['minzoom']
                self.set_zoom(max(self.min_zoom, min(round(self.zoom), self.max_zoom)))

    return OfflineMap
