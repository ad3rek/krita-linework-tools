# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-keyframe Linework geometry with Krita's native raster animation cache."""
from .i18n import tr
import base64
import ctypes
import json
import traceback
from functools import lru_cache
from .qt import sip
from .qt import QByteArray, QBuffer, QIODevice, QRectF, QTimer, Qt
from .qt import QColor, QImage, QPainter
from krita import Krita
from .model import load_strokes
from .editor import painter_path
from .native_brush import load_library, native_busy


class AnimationBusy(RuntimeError):
    pass


_bootstrapped = set()
_bootstrapping = set()
_shutting_down = False
_syncing = False
_pending = set()
_callback = None


@lru_cache(maxsize=16)
def function(name):
    types = {
        'info': [ctypes.c_void_p, ctypes.c_int],
        'restore': [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p],
        'empty': [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p],
        'commit': [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p,
                   ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p],
        'frame_action': [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int],
        'annotation': [ctypes.c_void_p, ctypes.c_int],
    }
    try:
        result = getattr(load_library(), 'linework_animation_'+name)
    except AttributeError as exc:
        raise ValueError(tr("Reopen Krita to load the updated Linework animation bridge.")) from exc
    result.argtypes = types[name]
    result.restype = ctypes.c_char_p
    return result


def call(name, layer, *args):
    raw = function(name)(sip.unwrapinstance(layer), *args)
    if not raw:
        raise ValueError(tr("The animation bridge did not return a result."))
    data = json.loads(raw)
    if data.get('error'):
        raise ValueError(data['error'])
    if data.get('busy'):
        _pending.add(data.get('owner'))
        raise AnimationBusy(tr("Wait for Krita to complete the frame operation."))
    return data


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def empty_record(document):
    from .storage import document_geometry
    return {'geometry': document_geometry(document), 'strokes': [], 'appearances': {}}


def bootstrap_layer(document, layer, saved=None):
    info = call('info', layer, 1)
    if not info.get('animated'):
        return info
    identity = info['owner'], info['node']
    if identity in _bootstrapped:
        return info
    if saved is None:
        from .storage import metadata, layer_id
        saved = metadata(document)['layers'].get(layer_id(layer), {})
    if saved.get('kind') != 'animated':
        return info
    if identity in _bootstrapping:
        raise AnimationBusy(tr("Wait for Krita to complete the frame operation."))
    _bootstrapping.add(identity)
    try:
        # Cloned timeline cells share a physical keyframe; keep them linked on load.
        aliases = {}
        for frame in info['frames']:
            record = saved.get('frames', {}).get(str(frame['time']))
            if record and not frame['editable']:
                previous = aliases.setdefault(frame['id'], record)
                if previous != record:
                    raise ValueError(tr("Linked Linework frame data is in conflict."))
        for frame in info['frames']:
            record = saved.get('frames', {}).get(str(frame['time']))
            if record and not frame['editable']:
                try:
                    call('restore', layer, frame['time'], encoded(record))
                except ValueError:
                    continue
        document.waitForDone()
        call('annotation', layer, 0)
        info = call('info', layer, 1)
        # Ordinary animated layers and layers still loading their annotations must
        # remain eligible for bootstrap. Busy restores can be retried safely.
        _bootstrapped.add(identity)
        return info
    finally:
        _bootstrapping.discard(identity)



def descriptor(document, layer, previous=None):
    if layer is None or layer.type() != 'paintlayer':
        return None
    info = call('info', layer, 0)
    if not info.get('animated'):
        return None
    time = previous['time'] if previous else info['active_time']
    frame = next((f for f in info['frames'] if f['time'] == time and (not previous or f['id'] == previous['id'])), None)
    if frame is None:
        if previous: raise ValueError(tr("The Linework frame has been moved or replaced."))
        return {'time': -1, 'id': -1, 'revision': 0}
    return {key: frame.get(key, 0) for key in ('time', 'id', 'revision')}


def frame_key(document, layer):
    frame = descriptor(document, layer)
    return tuple(frame[key] for key in ('time', 'id', 'revision')) if frame else None


def playback(view, pause=False):
    method = load_library().linework_animation_playback
    method.argtypes = [ctypes.c_void_p, ctypes.c_int]
    method.restype = ctypes.c_int
    return bool(method(sip.unwrapinstance(view), int(pause)))


def record(document, layer, frame=None):
    info = bootstrap_layer(document, layer)
    if not info.get('animated'):
        return None
    time = frame['time'] if frame else info['active_time']
    current = next((entry for entry in info['frames'] if entry['time'] == time), None)
    if current is None and not frame:
        from .storage import metadata, layer_id
        saved = metadata(document)['layers'].get(layer_id(layer), {})
        return empty_record(document) if saved.get('kind') == 'animated' else None
    if current is None or (frame and current['id'] != frame['id']):
        raise ValueError(tr("The Linework frame has been moved or replaced."))
    if not current['editable']:
        from .storage import metadata, layer_id
        saved = metadata(document)['layers'].get(layer_id(layer), {})
        if saved.get('kind') != 'animated':
            return None
        # Keep the native blank pointer until its first edit. Krita's add-frame
        # Undo command holds that pointer; adoption belongs to the edit command.
        return call('empty', layer, time, encoded(empty_record(document)))
    payload = current['payload']
    from .storage import check_geometry
    check_geometry(document, payload)
    # Refuse external raster painting/transforms instead of overwriting them.
    call('restore', layer, time, encoded(payload))
    return payload


def read_frame(document, layer):
    payload = record(document, layer)
    if payload is not None:
        sync_document(document)
    return load_strokes(payload['strokes']) if payload is not None else None


def appearance(payload, stroke):
    data = payload.get('appearances', {}).get(stroke.uid)
    if not data:
        raise ValueError(tr("The brush's saved appearance is not in the Linework frame."))
    image = QImage.fromData(base64.b64decode(data['png']), 'PNG')
    if image.isNull():
        raise ValueError(tr("Could not read the brush appearance for this frame."))
    return QRectF(*data['bounds']), image


def png(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise ValueError(tr("Unable to save the appearance of the frame."))
    return bytes(data)


def compose(document, payload, hidden=()):
    image = QImage(document.width(), document.height(), QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        raise ValueError(tr("There is not enough memory to render the Linework frame."))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for stroke in load_strokes(payload['strokes']):
            if stroke.uid in hidden:
                continue
            if stroke.brush:
                bounds, pixels = appearance(payload, stroke)
                painter.setOpacity(1)
                painter.drawImage(bounds, pixels)
            else:
                painter.setOpacity(stroke.opacity)
                painter.setBrush(QColor(stroke.color))
                painter.drawPath(painter_path(stroke))
    finally:
        painter.end()
    return image


def write_frame(document, layer, strokes, renderer, frame=None, backup=None):
    if layer.locked():
        raise ValueError(tr("Unlock the layer before applying."))
    document.waitForDone()
    previous = record(document, layer, frame)
    if previous is None:
        raise ValueError(tr("This layer is not an animated Linework layer."))
    frame = frame or descriptor(document, layer)
    old = {stroke['id']: stroke for stroke in previous['strokes']}
    payload = empty_record(document)
    payload['strokes'] = [stroke.data() for stroke in strokes]
    for stroke in strokes:
        if not stroke.brush:
            continue
        if old.get(stroke.uid) == stroke.data():
            payload['appearances'][stroke.uid] = previous['appearances'][stroke.uid]
        else:
            bounds, _, data = renderer.render(stroke)
            payload['appearances'][stroke.uid] = {'bounds': [bounds.x(), bounds.y(), bounds.width(), bounds.height()], 'png': data}
    pixels = png(compose(document, payload))
    result = call('commit', layer, frame['time'], frame['id'], encoded(payload), pixels,
                  len(pixels), sip.unwrapinstance(backup) if backup else None)
    frame.update(result['frame'])
    document.setModified(True)
    document.waitForDone()
    sync_document(document)
    return layer


def initialize_layer(document, layer):
    document.waitForDone()
    payload = call('empty', layer, 0, encoded(empty_record(document)))
    call('restore', layer, 0, encoded(payload))
    document.waitForDone()
    info = call('info', layer, 1)
    _bootstrapped.add((info['owner'], info['node']))
    sync_document(document)


def convert(document, source, layer, view):
    from .storage import read_layer
    from .preview import SavedAppearanceCache
    strokes = read_layer(document, source, view)
    if strokes is None:
        raise ValueError(tr("Select a vector Linework layer to animate."))
    cache = SavedAppearanceCache()
    prepared = {}
    for stroke in strokes:
        if stroke.brush:
            bounds, image = cache.get(document, source, stroke)
            prepared[stroke.uid] = bounds, image, base64.b64encode(png(image)).decode()
    class OriginalAppearances:
        def render(self, stroke): return prepared[stroke.uid]
    initialize_layer(document, layer)
    write_frame(document, layer, strokes, OriginalAppearances(), backup=source if source.visible() else None)
    layer.setName(source.name()+tr(" — animation"))
    document.setActiveNode(layer)
    return layer


def sync_document(document):
    from .storage import ANNOTATION, metadata, layer_id, document_geometry
    data = metadata(document)
    changed = False
    owner = None
    for layer in document.rootNode().findChildNodes('', True, False, 'paintlayer'):
        info = call('info', layer, 1)
        if not info.get('animated'):
            continue
        key = layer_id(layer)
        previous = data['layers'].get(key, {})
        if previous.get('kind') != 'animated' and not any('payload' in f for f in info['frames']):
            continue
        owner = layer
        frames = {}
        for entry in info['frames']:
            time = str(entry['time'])
            if 'payload' in entry:
                frames[time] = entry['payload']
            elif entry.get('empty'):
                frames[time] = dict(empty_record(document), fingerprint=entry['fingerprint'])
            else:
                frames[time] = previous.get('frames', {}).get(time)
        frames = {time: payload for time, payload in frames.items() if payload is not None}
        if frames or previous.get('kind') == 'animated':
            current = {'kind': 'animated', 'geometry': document_geometry(document), 'frames': frames}
            if current != previous:
                data['layers'][key] = current
                changed = True
    if changed:
        data['version'] = 7
        document.setAnnotation(ANNOTATION, 'Editable Linework strokes and animation frames', QByteArray(encoded(data)))
    if owner is not None:
        call('annotation', owner, 0)


def bootstrap_document(document):
    from .storage import metadata, layer_id
    data = metadata(document)
    for layer in document.rootNode().findChildNodes('', True, False, 'paintlayer'):
        saved = data['layers'].get(layer_id(layer), {})
        if saved.get('kind') == 'animated':
            bootstrap_layer(document, layer, saved)


def protect_save(document, data):
    """Vector commits can replace the shared annotation in an animated .kra."""
    from .storage import layer_id
    if data.get('version', 6) < 7:
        return
    for layer in document.rootNode().findChildNodes('', True, False, 'paintlayer'):
        if data['layers'].get(layer_id(layer), {}).get('kind') == 'animated':
            call('annotation', layer, 0)
            return


def flush():
    global _syncing
    if _shutting_down or _syncing or _bootstrapping or not _pending:
        return
    from .tools import CONTROLLERS
    if native_busy() or any(not sip.isdeleted(c) and c._window_closing
                            for c in tuple(CONTROLLERS.values())):
        QTimer.singleShot(100, flush)
        return
    _syncing = True
    try:
        busy = False
        application = Krita.instance()
        # Saved-image clones and documents whose final view is being destroyed
        # must not bootstrap keyframes or request native stroke-end callbacks.
        live_documents = {view.document().rootNode().uniqueId().toString()
                          for view in application.views() if view.document() is not None}
        for document in application.documents():
            if document.rootNode().uniqueId().toString() not in live_documents:
                continue
            try:
                bootstrap_document(document)
                if _pending:
                    sync_document(document)
            except AnimationBusy:
                busy = True
                continue
            except (ValueError, RuntimeError):
                # The active tool reports incompatible raster edits on binding.
                continue
        if not busy:
            _pending.clear()
    finally:
        _syncing = False


def install_callback():
    global _callback
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int)
    def callback(owner, reason):
        global _syncing
        owner = owner.decode()
        if reason == 2:
            _bootstrapped.difference_update({key for key in _bootstrapped if key[0] == owner})
            _pending.discard(owner)
            return
        _pending.add(owner)
        if _shutting_down:
            return
        if _syncing or _bootstrapping:
            QTimer.singleShot(100, flush)
            return
        # Native tool callbacks finish previews before the image snapshot.
        # Metadata synchronization belongs to the outer event loop: stroke-end
        # signals also occur during save, image waits and view destruction.
        QTimer.singleShot(0, flush)
    _callback = callback_type(callback)
    library = load_library()
    try:
        register = library.linework_animation_callback
    except AttributeError:
        return False
    register.argtypes = [callback_type]
    register.restype = None
    register(_callback)
    from .qt import QApplication
    def shutdown():
        global _shutting_down
        _shutting_down = True
        _pending.clear()
        register(callback_type())
    QApplication.instance().aboutToQuit.connect(shutdown)
    return True


class EditPreview:
    """Restore the captured physical frame even if the timeline changes mid-edit."""
    def __init__(self, document, layer, frame):
        self.document = document
        self.payload = record(document, layer, frame)
        library = load_library()
        begin = library.linework_animation_preview_begin
        begin.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        begin.restype = ctypes.c_void_p
        self.handle = begin(sip.unwrapinstance(layer), frame['time'], frame['id'])
        if not self.handle:
            raise ValueError(tr("Unable to start Linework frame preview."))

    def hide(self, uids):
        pixels = png(compose(self.document, self.payload, uids))
        apply = load_library().linework_animation_preview_apply
        apply.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        apply.restype = ctypes.c_int
        if not apply(self.handle, pixels, len(pixels)):
            raise ValueError(tr("Unable to update Linework frame preview."))

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            end = load_library().linework_animation_preview_end
            end.argtypes = [ctypes.c_void_p]
            end.restype = None
            end(handle)
