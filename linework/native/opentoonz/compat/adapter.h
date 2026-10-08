// SPDX-License-Identifier: GPL-3.0-or-later
// Host types only. Polygonization, straight skeleton and quadratic fitting
// are compiled from the BSD-3-Clause OpenToonz sources in ../core.
#pragma once
#include "tgeometry.h"
#include <atomic>
#include <cstring>
#include <memory>
#include <cstdint>

struct TPixel32 {
  unsigned char r=0,g=0,b=0,m=255;
  static const TPixel32 Black;
};
inline const TPixel32 TPixel32::Black={0,0,0,255};
struct TPixelGR8 { unsigned char value=0; };
struct TPixelCM32 {
  int ink=1,tone=255;
  int getInk() const {return ink;}
  int getTone() const {return tone;}
};
class TRaster {
 public:
  int width,height;
  TRaster(int w,int h):width(w),height(h){}
  virtual ~TRaster()=default;
  int getLx() const {return width;}
  int getLy() const {return height;}
  TRect getBounds() const {return TRect(0,0,width-1,height-1);}
  void lock() const {}
  void unlock() const {}
};
template<class T> class TypedRaster : public TRaster {
 public:
  std::vector<T> data;
  TypedRaster(int w,int h):TRaster(w,h),data(size_t(w)*h){}
  T *pixels(int y) {return data.data()+size_t(y)*width;}
  const T *pixels(int y) const {return data.data()+size_t(y)*width;}
};
class TRasterP {
 public:
  std::shared_ptr<TRaster> value;
  TRasterP()=default;
  TRasterP(std::shared_ptr<TRaster> p):value(std::move(p)){}
  TRaster *operator->() const {return value.get();}
  explicit operator bool() const {return bool(value);}
};
template<class T> class TRasterPT : public TRasterP {
 public:
  TRasterPT()=default;
  TRasterPT(int w,int h):TRasterP(std::make_shared<TypedRaster<T>>(w,h)){}
  TRasterPT(const TRasterP &p):TRasterP(std::dynamic_pointer_cast<TypedRaster<T>>(p.value)){}
  TypedRaster<T> *operator->() const {return static_cast<TypedRaster<T>*>(value.get());}
  TypedRaster<T> &operator*() const {return *operator->();}
};
using TRaster32P=TRasterPT<TPixel32>;
using TRasterGR8P=TRasterPT<TPixelGR8>;
using TRasterCM32P=TRasterPT<TPixelCM32>;
using TRasterCM32=TypedRaster<TPixelCM32>;

class TPalette {
 public:
  int getStyleCount() const {return 2;}
  int getClosestStyle(const TPixel32&) const {return 1;}
};
class TStroke {
  int style=1,flags=0;
 public:
  std::vector<TThickPoint> points;
  explicit TStroke(const std::vector<TThickPoint> &p):points(p){}
  void setFlag(int flag,bool enabled) {if(enabled)flags|=flag;else flags&=~flag;}
  bool getFlag(int flag) const {return flags&flag;}
  void setStyle(int value) {style=value;}
  int getStyle() const {return style;}
};

// Same supported configuration fields/defaults as CenterlineConfiguration.
// Qt signals and image ownership are supplied by the Krita/Python integration.
struct CenterlineConfiguration {
  int m_threshold=200,m_despeckling=10;
  double m_maxThickness=100.,m_penalty=.5,m_thicknessRatio=100.;
  bool m_makeFrame=false,m_naaSource=false;
};
class VectorizerCore {
  std::atomic<bool> &cancel;
  std::atomic<int> &progress;
  int partial=0,total=0;
 public:
  VectorizerCore(std::atomic<bool> &c,std::atomic<int> &p):cancel(c),progress(p){}
  bool isCanceled() const {return cancel.load();}
  void setOverallPartials(int n) {total=n;partial=0;}
  void emitPartialDone() {progress.store(15+int(60.*++partial/std::max(1,total)));}
};
