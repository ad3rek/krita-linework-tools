# SPDX-License-Identifier: GPL-3.0-or-later
"""Use Krita's own Qt binding, without loading another Qt major into its process."""
from importlib import import_module
from krita import Krita

QT_MAJOR = 6 if Krita.instance().version().split('.', 1)[0] == '6' else 5
_binding = 'PyQt'+str(QT_MAJOR)
sip = import_module(_binding+'.sip')
QtCore = import_module(_binding+'.QtCore')
QtGui = import_module(_binding+'.QtGui')
QtWidgets = import_module(_binding+'.QtWidgets')
_tablet_device = None


def __getattr__(name):
    for module in (QtCore, QtGui, QtWidgets):
        if hasattr(module, name):
            return getattr(module, name)
    if name == 'QTest':
        return import_module(_binding+'.QtTest').QTest
    raise AttributeError(name)


def event_position(event):
    if hasattr(event, 'position'):
        return event.position()
    return event.posF() if hasattr(event, 'posF') else event.localPos()


def copy_tablet_event(event):
    if QT_MAJOR == 6:
        return QtGui.QTabletEvent(event.type(), event.pointingDevice(),
            event.position(), event.globalPosition(), event.pressure(),
            event.xTilt(), event.yTilt(), event.tangentialPressure(), event.rotation(),
            event.z(), event.modifiers(), event.button(), event.buttons())
    return QtGui.QTabletEvent(event.type(), event.posF(), event.globalPosF(), event.device(),
        event.pointerType(), event.pressure(), event.xTilt(), event.yTilt(),
        event.tangentialPressure(), event.rotation(), event.z(), event.modifiers(),
        event.uniqueId(), event.button(), event.buttons())


def copy_mouse_event(event):
    if QT_MAJOR == 6:
        return QtGui.QMouseEvent(event.type(), event.position(), event.scenePosition(),
            event.globalPosition(), event.button(), event.buttons(), event.modifiers(),
            event.pointingDevice())
    return QtGui.QMouseEvent(event.type(), event.localPos(), event.windowPos(), event.screenPos(),
        event.button(), event.buttons(), event.modifiers(), event.source())


def tablet_event(kind, pos, pressure, button, buttons, modifiers):
    """Synthetic pen events for application regressions on both bindings."""
    global _tablet_device
    if QT_MAJOR == 6:
        if _tablet_device is None:
            device, pointing = QtGui.QInputDevice, QtGui.QPointingDevice
            _tablet_device = pointing('Linework test pen', 1, device.DeviceType.Stylus,
                pointing.PointerType.Pen, device.Capability.Position | device.Capability.Pressure,
                1, 1)
        return QtGui.QTabletEvent(kind, _tablet_device, pos, pos, pressure,
                                 0, 0, 0, 0, 0, modifiers, button, buttons)
    return QtGui.QTabletEvent(kind, pos, pos, QtGui.QTabletEvent.Stylus, QtGui.QTabletEvent.Pen,
                             pressure, 0, 0, 0, 0, 0, modifiers, 1, button, buttons)
