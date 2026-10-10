# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenToonz centerline port and exact quadratic-to-cubic degree elevation."""
import ctypes
import json
from pathlib import Path
from .model import Point, Stroke, MAX_POINTS
from .native_library import library_path


class TraceEngine:
    def __init__(self):
        self.lib=ctypes.CDLL(str(library_path('vectorize')))
        try:self.lib.linework_trace_backend.restype=ctypes.c_char_p
        except AttributeError:
            raise ValueError("Save your drawing and reopen Krita to load the OpenToonz engine.") from None
        if self.lib.linework_trace_backend()!=b'opentoonz-centerline-1':
            raise ValueError("The OpenToonz engine does not match this version of the plugin.")
        self.lib.linework_trace_new.restype=ctypes.c_void_p
        for name in ('cancel','delete'):
            fn=getattr(self.lib,'linework_trace_'+name);fn.argtypes=[ctypes.c_void_p];fn.restype=None
        for name in ('result','error'):
            fn=getattr(self.lib,'linework_trace_'+name);fn.argtypes=[ctypes.c_void_p];fn.restype=ctypes.c_char_p
        self.lib.linework_trace_progress.argtypes=[ctypes.c_void_p]
        self.lib.linework_trace_run_opentoonz.argtypes=[ctypes.c_void_p,ctypes.c_char_p]+[ctypes.c_int]*5+[ctypes.c_double]*2+[ctypes.c_int]
        self.handle=self.lib.linework_trace_new()

    def cancel(self):
        if self.handle:self.lib.linework_trace_cancel(self.handle)

    def progress(self):
        return self.lib.linework_trace_progress(self.handle) if self.handle else 100

    def run(self,pixels,width,height,mode=0,threshold=170,despeckle=12,penalty=.5,maximum_width=200,preserve_color=True):
        if len(pixels)!=width*height*4:raise ValueError("Invalid pixel size.")
        result=self.lib.linework_trace_run_opentoonz(self.handle,pixels,width,height,mode,threshold,despeckle,penalty,maximum_width,preserve_color)
        if result<0:raise InterruptedError("Vectorization canceled.")
        if not result:raise ValueError(self.lib.linework_trace_error(self.handle).decode('utf-8'))
        return json.loads(self.lib.linework_trace_result(self.handle))

    def close(self):
        if self.handle:self.lib.linework_trace_delete(self.handle);self.handle=None


def result_strokes(result,offset=(0,0),opacity=1.0,cancel=lambda:False):
    """Elevate each OpenToonz quadratic in (x,y,radius) without fitting it again."""
    if result.get('algorithm')!='opentoonz-centerline':
        raise ValueError("Vectorization result incompatible with the OpenToonz engine.")
    strokes=[]
    for path in result['paths']:
        if cancel():raise InterruptedError("Vectorization canceled.")
        controls=path['quadratics']
        if len(controls)<3 or len(controls)%2!=1:raise ValueError("Invalid quadratic curve.")
        radius=max(p[2] for p in controls)
        # Use a scale factor only; no minimum-width/radius rounding or smoothing.
        width=max(.1,2*radius)
        if width>2000:raise ValueError("The calculated thickness exceeds 2000 px.")
        points=[Point(controls[0][0]+offset[0],controls[0][1]+offset[1],2*controls[0][2]/width)]
        for i in range(0,len(controls)-2,2):
            a,c,b=controls[i:i+3]
            point=points[-1];end=Point(b[0]+offset[0],b[1]+offset[1],2*b[2]/width)
            point.handle_out=(2*(c[0]-a[0])/3,2*(c[1]-a[1])/3)
            end.handle_in=(2*(c[0]-b[0])/3,2*(c[1]-b[1])/3)
            point.pressure_out=4*(c[2]-a[2])/(3*width)
            end.pressure_in=4*(c[2]-b[2])/(3*width)
            points.append(end)
        if len(points)>MAX_POINTS:raise ValueError("Curve with too many points. Reduce precision.")
        r,g,b=path['color']
        strokes.append(Stroke(points,width=width,color='#{:02x}{:02x}{:02x}'.format(r,g,b),
                              opacity=path['opacity']*opacity))
    return strokes
