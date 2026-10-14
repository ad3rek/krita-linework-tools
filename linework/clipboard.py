# SPDX-License-Identifier: GPL-3.0-or-later
"""Carry editable records alongside Krita's own whole-layer clipboard data."""
import copy
import json
import logging
import math
import time
from .qt import QObject, QTimer, QByteArray, QApplication, QAction, sip
from .storage import metadata, layer_id, document_geometry, ANNOTATION
from .animation import AnimationBusy, bootstrap_layer, sync_document, protect_save, encoded, call

MIME = 'application/x-krita-linework-layers-v1'
NODE_MIME = 'application/x-krita-node-internal-pointer'
_log = logging.getLogger(__name__)


def walk(node):
    for child in node.childNodes():
        yield child
        yield from walk(child)


def menu_actions(menu):
    for action in menu.actions():
        yield action
        if action.menu() is not None:
            yield from menu_actions(action.menu())


def selected_roots(view):
    """Match Krita's tree order and avoid copying a selected child twice."""
    selected = {layer_id(node) for node in view.selectedNodes()}
    roots = []
    for node in walk(view.document().rootNode()):
        if layer_id(node) not in selected:
            continue
        parent = node.parentNode()
        while parent and layer_id(parent) not in selected:
            parent = parent.parentNode()
        if parent is None:
            roots.append(node)
    return roots


def snapshot_node(document, node, records):
    return {'source_id': layer_id(node), 'name': node.name(), 'type': node.type(),
            'record': copy.deepcopy(records.get(layer_id(node))),
            'children': [snapshot_node(document, child, records) for child in node.childNodes()]}


def contains_record(node):
    return node.get('record') is not None or any(contains_record(child) for child in node['children'])


def clipboard_payload(mime):
    """Reject incomplete sidecars before entering a Qt action callback."""
    try:
        if not mime.hasFormat(MIME):
            return None
        payload = json.loads(bytes(mime.data(MIME)))
        if (not isinstance(payload, dict) or type(payload.get('version')) is not int or
                payload['version'] != 1 or type(payload.get('document_version')) is not int or
                payload['document_version'] not in range(1, 9) or
                not isinstance(payload.get('layers'), list) or not payload['layers']):
            return None
        pending = list(payload['layers'])
        while pending:
            node = pending.pop()
            if (not isinstance(node, dict) or
                    any(not isinstance(node.get(key), str) for key in ('name','type','source_id')) or
                    not isinstance(node.get('children'), list) or 'record' not in node):
                return None
            record = node['record']
            if record is not None:
                if not isinstance(record, dict):
                    return None
                def valid_geometry(value):
                    return (isinstance(value, list) and len(value) == 4 and
                            all(type(item) in (int,float) and math.isfinite(item) and item > 0 for item in value))
                if 'geometry' in record and not valid_geometry(record['geometry']):
                    return None
                if record.get('kind') == 'animated':
                    frames = record.get('frames')
                    if not isinstance(frames, dict):
                        return None
                    for frame, value in frames.items():
                        int(frame)
                        if (not isinstance(value, dict) or
                                ('geometry' in value and not valid_geometry(value['geometry']))):
                            return None
                elif (not isinstance(record.get('strokes', []), list) or
                      not isinstance(record.get('shapes', {}), dict)):
                    return None
            pending.extend(node['children'])
        return payload
    except (ValueError, KeyError, TypeError, RuntimeError, RecursionError):
        return None


def pair_nodes(nodes, snapshots):
    if len(nodes) != len(snapshots):
        return None
    pairs = []
    for node, saved in zip(nodes, snapshots):
        if node.type() != saved['type'] or node.name() != saved['name']:
            return None
        children = pair_nodes(node.childNodes(), saved['children'])
        if children is None:
            return None
        pairs.append((node, saved))
        pairs.extend(children)
    return pairs


def destination_record(document, saved):
    record = copy.deepcopy(saved)
    geometry = document_geometry(document)
    if record.get('kind') == 'animated':
        record['geometry'] = geometry
        for payload in record.get('frames', {}).values():
            payload['geometry'] = geometry
    else:
        # Legacy SVG coordinates use points, whereas Linework uses pixels.
        previous = record.get('geometry', geometry)
        if previous[2:] != geometry[2:]:
            from .model import load_strokes, transform_stroke
            sx, sy = geometry[2]/previous[2], geometry[3]/previous[3]
            strokes = load_strokes(record['strokes'])
            for stroke in strokes:
                transform_stroke(stroke, [sx,0,0,sy,0,0])
            record['strokes'] = [stroke.data() for stroke in strokes]
        record['geometry'] = geometry
    return record


def restore_nodes(document, pairs, version):
    """Adopt matching native frames without repainting or adding an Undo step."""
    data = metadata(document)
    transferred = {}
    for node, snapshot in pairs:
        saved = snapshot['record']
        if saved is None:
            continue
        key = layer_id(node)
        if key in data['layers']:
            continue
        record = destination_record(document, saved)
        if node.type() == 'paintlayer' and record.get('kind') == 'animated':
            # restore() checks every frame's actual raster fingerprint. Linked
            # frames keep Krita's physical aliases and the clipboard snapshot.
            bootstrap_layer(document, node, record)
        elif node.type() == 'vectorlayer' and record.get('kind') != 'animated':
            from .storage import check_layer
            check_layer(node, record)
        else:
            continue
        transferred[key] = record
    if not transferred:
        return False
    # Reread because restoring native frames can deliver synchronization events.
    data = metadata(document)
    data['layers'].update(transferred)
    data['version'] = max(data.get('version',6), version)
    document.setAnnotation(ANNOTATION, 'Editable Linework strokes and animation frames', QByteArray(encoded(data)))
    protect_save(document, data)
    document.setModified(True)
    return True


class LayerClipboard(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._capture = None
        self._pastes = []
        self._writing = False
        self._actions = set()
        QApplication.clipboard().dataChanged.connect(self.changed)

    def connect_action(self, action):
        if action is None:
            return
        key = sip.unwrapinstance(action)
        if key not in self._actions:
            self._actions.add(key)
            _log.debug('Hooked native paste action %s at %s',action.objectName(),key)
            action.triggered.connect(self.paste)
            action.destroyed.connect(lambda _=None,key=key:self._actions.discard(key))

    def watch_current_actions(self):
        from krita import Krita
        # Standard actions can be replaced when the active view changes.
        for identifier in ('edit_paste', 'paste_layer_from_clipboard'):
            self.connect_action(Krita.instance().action(identifier))

    def watch_window(self, window, attempt=0):
        if sip.isdeleted(window):
            return
        found = 0
        # XMLGUI actions can be owned by an action collection outside the
        # main-window QObject tree. Resolve the actions actually in its menus.
        menus = {action.objectName(): action for action in menu_actions(window.menuBar())}
        for identifier in ('edit_paste', 'paste_layer_from_clipboard'):
            action = menus.get(identifier) or window.findChild(QAction, identifier)
            if action is None:
                continue
            found += 1
            self.connect_action(action)
        self.watch_current_actions()
        if found < 2 and attempt < 20:
            QTimer.singleShot(100,lambda:self.watch_window(window,attempt+1))

    def changed(self):
        if self._writing:
            return
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        self._capture = None
        # Pixel selections, Copy Merged and other applications retain Krita's
        # ordinary raster clipboard behavior. Never label those as whole layers.
        if mime is None or not mime.hasFormat(NODE_MIME):
            return
        from krita import Krita
        window = Krita.instance().activeWindow()
        view = window.activeView() if window else None
        if view is None or view.document() is None:
            return
        self.watch_window(window.qwindow())
        roots = selected_roots(view)
        if not roots:
            return
        capture = (mime, view.document(), roots, time.monotonic()+10)
        self._capture = capture
        QTimer.singleShot(0, lambda: self.enrich(capture))

    def enrich(self, capture):
        mime, document, roots, deadline = capture
        if not self.current_capture(capture):
            if self._capture is capture:
                self._capture = None
            return
        retry = False
        try:
            # Read after native copy releases its image lock and finish any
            # queued frame metadata, including an immediate Timeline copy.
            sync_document(document)
            if not self.current_capture(capture):
                return
            data = metadata(document)
            snapshots = [snapshot_node(document,node,data['layers']) for node in roots]
            if not any(contains_record(node) for node in snapshots):
                return
            for root in roots:
                for node in [root, *walk(root)]:
                    record = data['layers'].get(layer_id(node))
                    if record and record.get('kind') == 'animated':
                        for frame, payload in record['frames'].items():
                            call('restore', node, int(frame), encoded(payload))
                            if not self.current_capture(capture):
                                return
            payload = {'version':1, 'document_version':data['version'], 'layers':snapshots}
            # Keep the actual KisMimeData object. Replacing it with a generic
            # QMimeData would flatten native layers, masks and animation frames.
            self._writing = True
            mime.setData(MIME, QByteArray(encoded(payload)))
        except AnimationBusy:
            if time.monotonic() < deadline and self.current_capture(capture):
                retry = True
                QTimer.singleShot(100, lambda: self.enrich(capture))
        except (RuntimeError, ValueError):
            return
        finally:
            self._writing = False
            if not retry and self._capture is capture:
                # The clipboard owns its copied native nodes and serialized
                # records. Do not keep the original image alive after copy.
                self._capture = None

    def current_capture(self, capture):
        return (self._capture is capture and not sip.isdeleted(capture[0]) and
                QApplication.clipboard().mimeData() is capture[0])

    def paste(self):
        from krita import Krita
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(NODE_MIME):
            return
        payload = clipboard_payload(mime)
        # A busy native copy may still be enriching its clipboard. Keep the
        # destination now, then wait for that same copy to become ready.
        if payload is None and (mime.hasFormat(MIME) or self._capture is None or
                                not self.current_capture(self._capture) or self._capture[0] is not mime):
            return
        window = Krita.instance().activeWindow()
        view = window.activeView() if window else None
        if view is None or view.document() is None:
            return
        operation = (view, view.document(), payload, time.monotonic()+10, mime)
        _log.debug('Paste into %s, clipboard metadata ready: %s',
                   layer_id(view.document().rootNode()),payload is not None)
        self._pastes.append(operation)
        QTimer.singleShot(0, lambda: self.restore(operation))

    def restore(self, operation):
        view, document, payload, deadline, mime = operation
        if operation not in self._pastes:
            return
        try:
            current = view.document()
            if current is None or layer_id(current.rootNode()) != layer_id(document.rootNode()):
                self._pastes.remove(operation)
                return
            if payload is None:
                if sip.isdeleted(mime) or QApplication.clipboard().mimeData() is not mime:
                    self._pastes.remove(operation)
                    return
                if not mime.hasFormat(MIME):
                    raise AnimationBusy('Wait for native clipboard metadata.')
                payload = clipboard_payload(mime)
                if payload is None:
                    self._pastes.remove(operation)
                    return
            roots = selected_roots(view)
            pairs = pair_nodes(roots, payload['layers'])
            _log.debug('Restore target %s, selected %s, matched %s',layer_id(document.rootNode()),
                       [(node.name(),layer_id(node)) for node in roots],pairs is not None)
            # The native node insertion/selection command is asynchronous.
            # Do not adopt the original layer when pasting into the same image.
            if pairs is None or any(layer_id(node)==snapshot['source_id'] for node,snapshot in pairs):
                raise AnimationBusy('Wait for native clipboard insertion.')
            adopted = restore_nodes(document, pairs, payload['document_version'])
            _log.debug('Restored editable records: %s',adopted)
            if not adopted:
                raise AnimationBusy('Wait for the newly pasted layer selection.')
        except AnimationBusy:
            if time.monotonic() < deadline:
                QTimer.singleShot(100, lambda: self.restore(operation)); return
        except (RuntimeError, ValueError, KeyError, TypeError, IndexError) as exc:
            # Failed verification never repaints or replaces native pasted data.
            logging.getLogger(__name__).warning('Could not restore pasted Linework: %s',exc)
        self._pastes.remove(operation)
