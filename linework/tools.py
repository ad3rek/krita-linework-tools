# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Krita toolbox registration and tool-owned options widgets."""
import ctypes
import traceback
from pathlib import Path
from .qt import sip
from .qt import QWidget, QApplication
from .qt import QAbstractButton, QAction
from .qt import QIcon, QPixmap, QPainter, QPalette, QColor
from .native_brush import load_library
from .i18n import tr

TOOL_IDS = ("LineworkBrush", "LineworkCurve", "LineworkLine", "LineworkEdit", "LineworkPressure", "LineworkErase")
TOOL_LABELS = ("Linework Brush", "Linework Curve", "Linework Line", "Linework Edit", "Linework Thickness", "Linework Erase")
CONTROLLERS = {}
_callback = None
_icons = {}


def theme_icons(window):
    labels = dict(zip(TOOL_IDS, (tr(label) for label in TOOL_LABELS)))
    for action in window.findChildren(QAction):
        if action.objectName() in labels:
            title = labels[action.objectName()]
            if action.text() != title: action.setText(title)
            if action.toolTip() != title: action.setToolTip(title)
            if action.iconText() != title: action.setIconText(title)
    color = window.palette().color(QPalette.ColorRole.WindowText).name()
    if color not in _icons:
        themed = {}
        for mode, ident in enumerate(TOOL_IDS):
            source = QIcon(str(Path(__file__).with_name("icons")/("tool-{}.svg".format(mode))))
            icon = QIcon()
            for size in (16, 22, 24, 32, 48, 64):
                image = source.pixmap(size, size).toImage()
                painter = QPainter(image)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(image.rect(), QColor(color))
                painter.end()
                icon.addPixmap(QPixmap.fromImage(image))
            themed[ident] = icon
        _icons[color] = themed
    for button in window.findChildren(QAbstractButton):
        if button.objectName() in _icons[color]:
            icon = _icons[color][button.objectName()]
            if button.icon().cacheKey() != icon.cacheKey():
                button.setIcon(icon)
            title = labels[button.objectName()]
            if button.toolTip() != title: button.setToolTip(title)


def active_tool():
    library = load_library()
    library.linework_active_tool.restype = ctypes.c_int
    return library.linework_active_tool()


def select_tool(mode):
    library = load_library()
    library.linework_select_tool.argtypes = [ctypes.c_int]
    library.linework_select_tool(mode)


def current_controller(window):
    return next((c for c in CONTROLLERS.values() if not sip.isdeleted(c) and c._window == window.qwindow() and c.active), None)


def install_tools():
    global _callback
    from .tool_options import LineworkToolOptions

    def event(kind, mode, widget_pointer):
        try:
            controller = CONTROLLERS.get(widget_pointer)
            if controller is None or sip.isdeleted(controller):
                if kind in (2, 4):
                    return None
                widget = sip.wrapinstance(widget_pointer, QWidget)
                controller = LineworkToolOptions(widget)
                CONTROLLERS[widget_pointer] = controller
                def destroy_controller():
                    removed = CONTROLLERS.pop(widget_pointer, None)
                    if removed:
                        removed.dispose()
                widget.destroyed.connect(destroy_controller)
            if kind == 1:
                controller.set_tool(mode)
            elif kind == 2:
                controller.pause_tool()
            elif kind == 3:
                return sip.unwrapinstance(controller)
            elif kind == 4:
                controller.finish_native_request()
        except Exception:
            traceback.print_exc()
        return None

    _callback = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)(event)
    library = load_library()
    library.linework_register_tools.argtypes = [type(_callback), ctypes.c_char_p, ctypes.c_char_p]
    library.linework_register_tools.restype = ctypes.c_int
    labels = '\n'.join(tr(label) for label in TOOL_LABELS)
    if not library.linework_register_tools(_callback, str(Path(__file__).with_name("icons")).encode(), labels.encode()):
        raise RuntimeError(tr("Linework tools could not be registered."))
    library.linework_clear_callbacks.argtypes = []
    library.linework_clear_callbacks.restype = None

    def shutdown():
        library.linework_clear_callbacks()
        for controller in tuple(CONTROLLERS.values()):
            controller.dispose()
        CONTROLLERS.clear()
    QApplication.instance().aboutToQuit.connect(shutdown)
