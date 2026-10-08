# SPDX-License-Identifier: GPL-3.0-or-later
from krita import Extension, Krita
from PyQt5.QtCore import QTimer, QEvent, Qt
from PyQt5.QtWidgets import QApplication
from .storage import metadata
from .native_brush import update_layer_icons, native_busy
from .tools import select_tool, current_controller, theme_icons


class LineworkExtension(Extension):
    def setup(self):
        self.timer = QTimer(self)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.update_icons)
        self.timer.start()
        self._annotations = {}
        self._vectorizers = []
        self._transform_pending = None
        self._syncing = False
        self._tablet_down = False
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.TabletPress:self._tablet_down = True
        elif event.type() == QEvent.TabletRelease:self._tablet_down = False
        return False

    def sync_native_transforms(self):
        from .tools import active_tool
        from .transforms import pending_signature, sync_layer
        if (self._syncing or active_tool() >= 0 or self._tablet_down or
                QApplication.mouseButtons() != Qt.NoButton or QApplication.activeModalWidget()):
            self._transform_pending = None
            return
        window = Krita.instance().activeWindow()
        view = window.activeView() if window else None
        document = view.document() if view else None
        layer = document.activeNode() if document else None
        if layer is None or layer.type() != 'vectorlayer':
            self._transform_pending = None
            return
        try:
            signature = pending_signature(document, layer)
            key = (document.rootNode().uniqueId().toString(),layer.uniqueId().toString(),signature)
            if not signature or key != self._transform_pending:
                self._transform_pending = key
                return
            self._syncing = True
            if sync_layer(document, layer, view):self._transform_pending = None
        except (RuntimeError, ValueError) as exc:
            window.qwindow().statusBar().showMessage(str(exc),5000)
            self._transform_pending = None
        finally:self._syncing = False

    def update_icons(self):
        if native_busy(): return
        self.sync_native_transforms()
        for window in Krita.instance().windows():
            theme_icons(window.qwindow())
            view = window.activeView()
            document = view.document() if view else None
            if document is None:
                update_layer_icons(window.qwindow(), {})
                continue
            try:
                key = document.rootNode().uniqueId().toString()
                raw = bytes(document.annotation("org.felipe.linework.v1"))
                cached = self._annotations.get(key)
                if cached is None or cached[0] != raw:
                    cached = (raw, tuple(metadata(document)["layers"]))
                    self._annotations[key] = cached
                update_layer_icons(window.qwindow(), cached[1])
            except (RuntimeError, ValueError):
                continue

    def createActions(self, window):
        action = window.createAction("linework_edit", "Linework Brush", "tools/scripts")
        action.triggered.connect(lambda: select_tool(0))
        new_action = window.createAction("linework_new", "Nova camada Linework…", "tools/scripts")
        # Krita passes a stack-allocated libkis Window to createActions. Never
        # retain that wrapper in a callback; resolve the active window on use.
        new_action.triggered.connect(self.new_layer)
        vectorize_action = window.createAction('linework_vectorize', 'Vetorizar camada em Linework…', 'tools/scripts')
        vectorize_action.triggered.connect(self.vectorize)

    def vectorize(self):
        from .vectorize import open_vectorizer
        dialog = open_vectorizer()
        if dialog:
            self._vectorizers.append(dialog)
            dialog.destroyed.connect(lambda: self._vectorizers.remove(dialog) if dialog in self._vectorizers else None)

    def new_layer(self):
        window = Krita.instance().activeWindow()
        if window is None or window.qwindow() is None:
            return
        select_tool(0)
        controller = current_controller(window)
        if controller:
            controller.new_layer()
