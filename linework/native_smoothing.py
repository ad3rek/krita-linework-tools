# SPDX-License-Identifier: GPL-3.0-or-later
"""Krita's own freehand smoothing, recorded as editable cubic segments."""
import ctypes
from PyQt5 import sip
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QFormLayout, QComboBox, QDoubleSpinBox, QCheckBox
from .native_brush import load_library
from .model import Point, Stroke, samples, distance, MAX_POINTS
from .curve_fit import compact_stroke


def library():
    lib = load_library()
    try:
        lib.linework_smoothing_options.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int]
        lib.linework_smoothing_options.restype = None
        lib.linework_smoothing_begin.argtypes = [ctypes.c_void_p]*2+[ctypes.POINTER(ctypes.c_double)]*2
        lib.linework_smoothing_begin.restype = ctypes.c_void_p
        lib.linework_smoothing_move.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]
        lib.linework_smoothing_move.restype = None
        for name in ('linework_smoothing_end', 'linework_smoothing_delete'):
            getattr(lib, name).argtypes = [ctypes.c_void_p]
            getattr(lib, name).restype = None
        lib.linework_smoothing_take.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.c_int]
        lib.linework_smoothing_take.restype = ctypes.c_int
    except AttributeError as exc:
        raise ValueError('Reabra o Krita para carregar os motores de suavização do Linework.') from exc
    return lib


def settings(values=None):
    data = (ctypes.c_double*9)(*(values or [0]*9))
    library().linework_smoothing_options(data, int(values is not None))
    return list(data)


class SmoothingOptions(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.form = QFormLayout(self); self.form.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.addItems(['Sem suavização', 'Básica (leve)', 'Ponderada (pesada)', 'Estabilizador'])
        self.mode.setToolTip('Ao concluir o traço, os pontos são reduzidos em todos os modos, '
                             'preservando cantos e variações de pressão e espessura.')
        self.form.addRow('Modo', self.mode)
        self.fields = {}
        for key, label, low, high, suffix in (
                (1, 'Distância', 1, 1000, ''), (2, 'Finalização', 0, 100, ' %'),
                (5, 'Distância de atraso', 0, 1000, ' px')):
            field = QDoubleSpinBox(); field.setRange(low, high); field.setDecimals(1)
            field.setSuffix(suffix); field.setKeyboardTracking(False)
            self.fields[key] = field; self.form.addRow(label, field)
        for key, label in ((3, 'Suavizar pressão'), (4, 'Proporcional ao zoom'),
                           (6, 'Usar atraso'), (7, 'Concluir linha'), (8, 'Estabilizar sensores')):
            field = QCheckBox(label); self.fields[key] = field; self.form.addRow(field)
        self.reload()
        self.mode.currentIndexChanged.connect(self.update_values)
        for field in self.fields.values():
            (field.toggled if isinstance(field, QCheckBox) else field.valueChanged).connect(self.update_values)
        self.update_visibility()

    def reload(self):
        # Read shared native settings again after using Krita's freehand tool.
        self._loading = True
        self.values = settings(); self.mode.setCurrentIndex(int(self.values[0]))
        for key, field in self.fields.items():
            if isinstance(field, QCheckBox): field.setChecked(bool(self.values[key]))
            else: field.setValue(self.values[key]*(100 if key == 2 else 1))
        self._loading = False
        self.update_visibility()

    def update_visibility(self):
        mode = self.mode.currentIndex()
        for key, field in self.fields.items():
            visible = key == 1 and mode in (2, 3) or key in (2, 3, 4) and mode == 2 or key in (5, 6, 7, 8) and mode == 3
            field.setVisible(visible)
            label = self.form.labelForField(field)
            if label: label.setVisible(visible)
        self.form.labelForField(self.fields[1]).setText('Amostras' if mode == 3 else 'Distância')
        self.fields[5].setEnabled(self.fields[6].isChecked())

    def update_values(self, *_):
        if self._loading: return
        self.values[0] = self.mode.currentIndex()
        for key, field in self.fields.items():
            self.values[key] = (float(field.isChecked()) if isinstance(field, QCheckBox)
                                else field.value()/(100 if key == 2 else 1))
        settings(self.values); self.update_visibility(); self.changed.emit()


class NativeSmoother:
    def __init__(self, renderer, values, first):
        self.mode = int(values[0])
        renderer.ensure_scratch()
        self.lib = library()
        self.handle = self.lib.linework_smoothing_begin(sip.unwrapinstance(renderer.node),
            sip.unwrapinstance(renderer.view), (ctypes.c_double*9)(*values),
            (ctypes.c_double*3)(first.x, first.y, first.pressure))
        if not self.handle: raise ValueError('Não foi possível iniciar a suavização nativa.')

    def move(self, point):
        self.lib.linework_smoothing_move(self.handle, (ctypes.c_double*3)(point.x, point.y, point.pressure))

    def take_into(self, stroke):
        changed = False
        if not self.handle: return changed
        while True:
            data = (ctypes.c_double*(11*512))()
            count = self.lib.linework_smoothing_take(self.handle, data, 512)
            if not count: break
            if not hasattr(stroke, '_live_points'): stroke._live_points = []
            for i in range(count):
                kind, x, y, pressure, cx, cy, dx, dy, ex, ey, end_pressure = data[i*11:(i+1)*11]
                # Native stabilizer timers can emit many stationary lines.
                # These contain no new geometry or sensor value; do not add
                # duplicate anchors. Curves returning to their start and
                # stationary pressure changes must still be recorded.
                if kind == 1 and x == ex and y == ey and pressure == end_pressure:
                    continue
                a, b = Point(x, y, pressure), Point(ex, ey, end_pressure)
                if not stroke.points or distance(stroke.points[-1], a) > 1e-6:
                    stroke.points.append(a)
                else:
                    a = stroke.points[-1]; a.pressure = pressure
                if kind == 0:
                    if not stroke._live_points: stroke._live_points.append(Point(x, y, pressure))
                    changed = True; continue
                if len(stroke.points) >= MAX_POINTS: raise ValueError('Este traço atingiu o limite de pontos.')
                a.handle_out = cx-x, cy-y; b.handle_in = dx-ex, dy-ey
                stroke.points.append(b)
                # The live raster receives the same cubic as the saved geometry;
                # only this new segment is sampled, never the previous stroke.
                segment = Stroke([a, b], kind='curve')
                new_samples = samples(segment)
                if stroke._live_points and distance(stroke._live_points[-1], new_samples[0]) < 1e-6:
                    new_samples = new_samples[1:]
                stroke._live_points.extend(new_samples); changed = True
        return changed

    def finish(self, stroke):
        if self.handle:
            try:
                self.lib.linework_smoothing_end(self.handle)
                self.take_into(stroke)
            finally:
                self.close()
            # Only new, completed brush strokes. Keep _live_points untouched
            # while the native renderer finishes its incremental preview.
            compact_stroke(stroke, self.mode)

    def close(self):
        if self.handle:
            self.lib.linework_smoothing_delete(self.handle)
            self.handle = None
