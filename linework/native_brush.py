# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Krita paint engines, cached as embedded images on editable centerlines."""
import ctypes
import hashlib
import json
import re
from collections import OrderedDict
from contextlib import contextmanager
from functools import lru_cache
from xml.etree import ElementTree
from pathlib import Path
from PyQt5 import sip
from PyQt5.QtCore import QByteArray, QBuffer, QIODevice, QRect
from PyQt5.QtGui import QImage
from krita import Krita, Preset
from .model import samples, distance, clamp, freeze_thickness, thickness_factor
from .native_library import library_path

_BRIDGE_LIBRARY = None


@lru_cache(maxsize=16)
def size_transfer(xml):
    library = load_library()
    try:
        function = library.linework_pressure_to_size
    except AttributeError as exc:
        raise ValueError('Reabra o Krita para carregar o controle de espessura atualizado.') from exc
    function.argtypes = [ctypes.c_char_p, ctypes.c_double]
    function.restype = ctypes.c_double
    encoded = xml.encode()
    return tuple(function(encoded, i/255) for i in range(256))


def size_factor(brush, pressure):
    transfer = size_transfer(brush['xml'])
    position = clamp(pressure, 0, 1)*255
    i = min(254, int(position)); t = position-i
    return transfer[i]*(1-t)+transfer[i+1]*t


def validate_thickness_brush(brush):
    engine = ElementTree.fromstring(brush['xml']).get('paintopid')
    if engine not in ('paintbrush', 'colorsmudge'):
        raise ValueError('O controle direto de espessura requer um preset dos motores Pixel ou Color Smudge do Krita.')


def ensure_thickness(stroke):
    if stroke.brush:
        validate_thickness_brush(stroke.brush)
    freeze_thickness(stroke, (lambda value: size_factor(stroke.brush, value)) if stroke.brush else None)


def point_thickness(stroke, index):
    point = stroke.points[index]
    factor = (size_factor(stroke.brush, point.pressure) if stroke.brush and point.thickness is None
              else thickness_factor(point))
    return stroke.width*factor


def load_library():
    # Delegates installed on native widgets outlive individual canvas renderers.
    # Keep their library loaded for the complete plugin/application lifetime.
    global _BRIDGE_LIBRARY
    if _BRIDGE_LIBRARY is None:
        if not re.fullmatch(r'5\.2\.14(?:[- ].*)?', Krita.instance().version()):
            raise ValueError("This native bridge requires Krita 5.2.14.")
        try:
            _BRIDGE_LIBRARY = ctypes.PyDLL(str(library_path('native')))
        except OSError as exc:
            raise ValueError("Não foi possível carregar o motor nativo Linework: "+str(exc)) from exc
    return _BRIDGE_LIBRARY


def native_busy():
    function = load_library().linework_native_busy
    function.restype = ctypes.c_int
    return bool(function())


def update_layer_icons(window, layers):
    from PyQt5.QtWidgets import QWidget
    if not layers and _BRIDGE_LIBRARY is None:
        return
    library = load_library()
    update = library.linework_layer_icons
    update.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    update.restype = ctypes.c_int
    icon = str(Path(__file__).with_name("linework-layer.svg")).encode()
    ids = "\n".join(layers).encode()
    for widget in window.findChildren(QWidget):
        if widget.metaObject().className() == "NodeView":
            update(sip.unwrapinstance(widget), ids, icon)


def capture_brush(view):
    eraser = Krita.instance().action("erase_action")
    if eraser and eraser.isChecked():
        raise ValueError("Desative a borracha do Krita; use a ferramenta Linework Erase para apagar linhas.")
    resource = view.currentBrushPreset()
    if resource is None:
        raise ValueError("Selecione um preset no painel Pincéis do Krita.")
    return {"engine": "krita-native", "name": resource.name(),
            "filename": resource.filename(), "xml": Preset(resource).toXML(),
            "flow": view.paintingFlow()}


def set_preview_hidden(layer, uid, hidden):
    """Exclude a committed stroke from rendering without changing saved shapes."""
    library = load_library()
    function = library.linework_preview_hidden
    function.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    function.restype = ctypes.c_int
    return bool(function(sip.unwrapinstance(layer), ("lw_"+uid).encode(), hidden))


def begin_edit_session(layer):
    library = load_library()
    library.linework_edit_begin.argtypes = [ctypes.c_void_p]
    library.linework_edit_begin.restype = ctypes.c_void_p
    return library.linework_edit_begin(sip.unwrapinstance(layer))


def end_edit_session(session):
    if session:
        library = load_library()
        library.linework_edit_end.argtypes = [ctypes.c_void_p]
        library.linework_edit_end.restype = None
        library.linework_edit_end(session)


@contextmanager
def shape_write(layer):
    """Prevent timer reads of KoShapes while libkis image workers modify them."""
    library = load_library()
    try:
        begin = library.linework_shape_write_begin
        end = library.linework_shape_write_end
    except AttributeError as exc:
        raise ValueError("Reabra o Krita para carregar a ponte nativa Linework atualizada.") from exc
    begin.argtypes = [ctypes.c_void_p]; begin.restype = ctypes.c_void_p
    end.argtypes = [ctypes.c_void_p]; end.restype = None
    session = begin(sip.unwrapinstance(layer))
    if not session:
        raise ValueError("Não foi possível iniciar a gravação segura da camada Linework.")
    try:
        yield
    finally:
        end(session)


def refresh_layer(layer):
    library = load_library()
    library.linework_refresh_layer.argtypes = [ctypes.c_void_p]
    library.linework_refresh_layer.restype = None
    library.linework_refresh_layer(sip.unwrapinstance(layer))


def shape_frame(shape):
    from PyQt5.QtGui import QTransform
    library = load_library()
    library.linework_shape_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]
    library.linework_shape_info.restype = ctypes.c_int
    info = (ctypes.c_double*9)()
    if not library.linework_shape_info(sip.unwrapinstance(shape), info):
        raise ValueError('Não foi possível ler a transformação do traço.')
    transform = QTransform(*info[:6])
    return transform if info[8] else QTransform.fromScale(info[6], info[7])*transform


def shape_image_bounds(shape):
    from PyQt5.QtCore import QRectF
    library = load_library()
    library.linework_shape_image_bounds.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]
    library.linework_shape_image_bounds.restype = ctypes.c_int
    info = (ctypes.c_double*4)()
    if not library.linework_shape_image_bounds(sip.unwrapinstance(shape), info):
        raise ValueError('A imagem do traço não pôde ser localizada.')
    return QRectF(*info)


def shape_canonical(shape):
    library = load_library()
    library.linework_shape_canonical.argtypes = [ctypes.c_void_p]
    library.linework_shape_canonical.restype = ctypes.c_char_p
    value = library.linework_shape_canonical(sip.unwrapinstance(shape))
    if not value:
        raise ValueError('Não foi possível verificar a geometria do traço.')
    return value.decode('utf-8')


def render_shape(document, layer, shape, stroke, renderer):
    from .model import outline
    library = load_library()
    function = library.linework_shape_render
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_double), ctypes.c_int]+[ctypes.c_double]*6
    function.restype = ctypes.c_int
    png, points, count = None, None, 0
    x=y=width=height=0
    if stroke.brush:
        bounds, _, encoded = renderer.render(stroke)
        png = encoded.encode()
        x,y,width,height = bounds.x(),bounds.y(),bounds.width(),bounds.height()
    else:
        poly = outline(stroke)
        values = [coordinate for pair in poly for coordinate in pair]
        points = (ctypes.c_double*len(values))(*values)
        count = len(poly)
    if not function(sip.unwrapinstance(layer), sip.unwrapinstance(shape), png, points, count,
                    x,y,width,height,72/document.xRes(),72/document.yRes()):
        raise ValueError('Não foi possível atualizar a aparência do traço transformado.')


class NativeBrushRenderer:
    def __init__(self, view):
        self.view = view
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.busy = False
        self._paint = None
        self.scratch = None
        self.node = None
        self.stream = None
        self.live_count = 0
        self.live_length = 0
        self.preset_cache = None
        self.use_preset_cache = True
        self._cached_paint = self._cached_stream = None

    def load_bridge(self):
        if self._paint is not None:
            return
        self.library = load_library()
        try:
            self._uncached_paint = self.library.linework_paint_with_thickness
        except AttributeError as exc:
            raise ValueError('Reabra o Krita para carregar o controle de espessura atualizado.') from exc
        self._uncached_paint.argtypes = ([ctypes.c_void_p]*3+[ctypes.c_char_p]*2+
            [ctypes.c_double]*3+[ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int])
        self._uncached_paint.restype = ctypes.c_int
        self._paint = self.paint_native
        for name in ("linework_prepare_scratch", "linework_clear_scratch", "linework_stream_end", "linework_preview_delete"):
            function = getattr(self.library, name)
            function.argtypes = [ctypes.c_void_p]
            function.restype = None
        self.library.linework_stream_begin.argtypes = ([ctypes.c_void_p]*3+[ctypes.c_char_p]*2+
            [ctypes.c_double]*3+[ctypes.c_char_p, ctypes.c_int])
        self.library.linework_stream_begin.restype = ctypes.c_void_p
        self.library.linework_stream_append.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.c_int]
        self.library.linework_stream_append.restype = None
        self.library.linework_stream_snapshot.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        self.library.linework_stream_snapshot.restype = ctypes.c_void_p
        self.library.linework_preview_pixels.argtypes = [ctypes.c_void_p]
        self.library.linework_preview_pixels.restype = ctypes.c_void_p
        # Older native bridges remain usable through the original entry points.
        if hasattr(self.library,'linework_paint_cached'):
            self._cached_paint = self.library.linework_paint_cached
            self._cached_paint.argtypes = self._uncached_paint.argtypes+[ctypes.c_void_p]
            self._cached_paint.restype = ctypes.c_int
            self._cached_stream = self.library.linework_stream_begin_cached
            self._cached_stream.argtypes = self.library.linework_stream_begin.argtypes+[ctypes.c_void_p]
            self._cached_stream.restype = ctypes.c_void_p
            self.library.linework_preset_cache_new.argtypes=[]
            self.library.linework_preset_cache_new.restype=ctypes.c_void_p
            self.library.linework_preset_cache_delete.argtypes=[ctypes.c_void_p]
            self.library.linework_preset_cache_delete.restype=None
            self.library.linework_preset_cache_stats.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_longlong)]
            self.library.linework_preset_cache_stats.restype=None

    def paint_native(self, *args):
        if self.use_preset_cache and self.preset_cache:
            return self._cached_paint(*args,self.preset_cache)
        return self._uncached_paint(*args)

    def preset_cache_stats(self):
        if not self.preset_cache: return None
        values=(ctypes.c_longlong*4)()
        self.library.linework_preset_cache_stats(self.preset_cache,values)
        return dict(zip(('hits','misses','entries','xml_bytes'),values))

    def ensure_scratch(self):
        self.load_bridge()
        document = self.view.document()
        if self.scratch and (self.scratch.width(), self.scratch.height()) != (document.width(), document.height()):
            self.close()
        if self._cached_paint is not None and self.preset_cache is None:
            self.preset_cache = self.library.linework_preset_cache_new()
        if self.scratch is None:
            self.scratch = Krita.instance().createDocument(document.width(), document.height(),
                "Linework render", "RGBA", "U8", "sRGB-elle-V2-srgbtrc.icc", 72)
            self.scratch.setBatchmode(True)
            self.node = self.scratch.createNode("Linework render", "paintlayer")
            self.scratch.rootNode().addChildNode(self.node, None)
            self.library.linework_prepare_scratch(sip.unwrapinstance(self.node))

    def close(self):
        self.end_live()
        if self.scratch is not None:
            self.scratch.setModified(False)
            self.scratch.close()
            self.scratch = self.node = None
        if self.preset_cache:
            cache,self.preset_cache=self.preset_cache,None
            self.library.linework_preset_cache_delete(cache)

    def image_snapshot(self):
        bounds = self.node.bounds().intersected(QRect(0, 0, self.scratch.width(), self.scratch.height()))
        if bounds.isEmpty():
            bounds = QRect(0, 0, 1, 1)
        pixels = bytes(self.node.pixelData(bounds.x(), bounds.y(), bounds.width(), bounds.height()))
        image = QImage(pixels, bounds.width(), bounds.height(), bounds.width()*4, QImage.Format_ARGB32).copy()
        return bounds, image

    def start_live(self, stroke):
        self.end_live()
        self.ensure_scratch()
        self.library.linework_clear_scratch(sip.unwrapinstance(self.node))
        resource = self.preset_resource(stroke.brush)
        error = ctypes.create_string_buffer(1024)
        function = self._cached_stream if self.use_preset_cache and self.preset_cache else self.library.linework_stream_begin
        extra = (self.preset_cache,) if function is self._cached_stream else ()
        self.stream = function(sip.unwrapinstance(self.node), sip.unwrapinstance(self.view),
            sip.unwrapinstance(resource), stroke.brush["xml"].encode(), stroke.color.encode(),
            stroke.width, stroke.opacity, stroke.brush.get("flow", 1), error, len(error),*extra)
        if not self.stream:
            raise ValueError(error.value.decode("utf-8", "replace"))
        self.live_count = 0
        self.live_length = 0
        self.append_live(stroke)

    def append_live(self, stroke):
        points = getattr(stroke, '_live_points', stroke.points)
        if not self.stream or self.live_count >= len(points):
            return
        values = []
        for i in range(self.live_count, len(points)):
            point = points[i]
            if i:
                self.live_length += distance(points[i-1], point)
            pressure = stroke.minimum+(1-stroke.minimum)*point.pressure
            # End taper uses the final curve length and is applied on release.
            pressure *= 1-stroke.taper_start+stroke.taper_start*min(1, self.live_length/max(1, stroke.width*3))
            values.extend((point.x, point.y, clamp(pressure, 0, 1), self.live_length*3))
        coords = (ctypes.c_double*len(values))(*values)
        self.library.linework_stream_append(self.stream, coords, len(values)//4)
        self.live_count = len(points)

    def live_snapshot(self):
        if not self.stream:
            return None
        bounds = (ctypes.c_int*4)()
        preview = self.library.linework_stream_snapshot(self.stream, bounds)
        if not preview:
            return None
        try:
            x, y, width, height = bounds
            pixels = ctypes.string_at(self.library.linework_preview_pixels(preview), width*height*4)
            image = QImage(pixels, width, height, width*4, QImage.Format_ARGB32).copy()
            return QRect(x, y, width, height), image
        finally:
            self.library.linework_preview_delete(preview)

    def end_live(self):
        if self.stream:
            stream, self.stream = self.stream, None
            self.library.linework_stream_end(stream)

    def preset_resource(self, brush):
        current = self.view.currentBrushPreset()
        if current and current.filename() == brush["filename"]:
            return current
        resources = Krita.instance().resources("preset")
        for resource in resources.values():
            if resource.filename() == brush["filename"] and resource.name() == brush["name"]:
                return resource
        raise ValueError("Reinstale o preset nativo “{}” para editar este traço.".format(brush["name"]))

    def render(self, stroke, preview=False):
        key = hashlib.sha256(json.dumps(stroke.data(), sort_keys=True).encode()).hexdigest()
        if not preview and key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if self.busy:
            raise ValueError("O renderizador de pincéis está ocupado.")
        self.load_bridge()
        self.busy = True
        try:
            self.end_live()
            self.ensure_scratch()
            resource = self.preset_resource(stroke.brush)
            self.library.linework_clear_scratch(sip.unwrapinstance(self.node))
            center = samples(stroke)
            lengths = [0.0]
            for a, b in zip(center, center[1:]):
                lengths.append(lengths[-1]+distance(a, b))
            total = lengths[-1] or 1
            values = []
            explicit = all(p.thickness is not None for p in stroke.points)
            if explicit: validate_thickness_brush(stroke.brush)
            widths = []
            for p, length in zip(center, lengths):
                progress = length/total
                pressure = stroke.minimum+(1-stroke.minimum)*thickness_factor(p)
                pressure *= 1-stroke.taper_start+stroke.taper_start*min(1, progress/.15)
                pressure *= 1-stroke.taper_end+stroke.taper_end*min(1, (1-progress)/.15)
                if explicit:
                    widths.append(clamp(stroke.width*pressure, 0, 2000))
                else:
                    values.extend((p.x, p.y, clamp(pressure, 0, 1), length*3))
            render_size = stroke.width
            if explicit:
                render_size = max(stroke.width, max(widths))
                for p, length, width in zip(center, lengths, widths):
                    values.extend((p.x, p.y, clamp(p.pressure, 0, 1), length*3, width/render_size))
            coords = (ctypes.c_double*len(values))(*values)
            error = ctypes.create_string_buffer(1024)
            ok = self._paint(sip.unwrapinstance(self.node), sip.unwrapinstance(self.view),
                sip.unwrapinstance(resource), stroke.brush["xml"].encode(), stroke.color.encode(),
                render_size, stroke.opacity, stroke.brush.get("flow", 1), coords,
                len(center), int(explicit), error, len(error))
            if not ok:
                raise ValueError(error.value.decode("utf-8", "replace"))
            bounds, image = self.image_snapshot()
            if preview:
                return bounds, image, None
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            if not image.save(buffer, "PNG"):
                raise ValueError("Falha ao gravar a aparência do pincel.")
            encoded = bytes(data.toBase64()).decode("ascii")
            result = (bounds, image, encoded)
            self.cache[key] = result
            self.cache_bytes += image.byteCount()+len(encoded)
            while self.cache_bytes > 64*1024*1024 and len(self.cache) > 1:
                _, old = self.cache.popitem(last=False)
                self.cache_bytes -= old[1].byteCount()+len(old[2])
            return result
        finally:
            self.busy = False

    def svg_image(self, stroke):
        bounds, _, encoded = self.render(stroke)
        # Krita's image SVG writer regenerates image IDs. A named group keeps
        # the editable stroke identity stable across .kra serialization.
        return ('<g id="lw_{}"><image x="{}" y="{}" width="{}" height="{}" '
                'xlink:href="data:image/png;base64,{}"/></g>').format(stroke.uid,
                    bounds.x(), bounds.y(), bounds.width(), bounds.height(), encoded)
