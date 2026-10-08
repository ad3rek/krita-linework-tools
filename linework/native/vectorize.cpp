// SPDX-License-Identifier: GPL-3.0-or-later
// Krita adapter for the BSD-3-Clause OpenToonz centerline algorithm.
// Algorithm sources, original revision and license: opentoonz/ORIGIN.json.
#include "export.h"
#include "tcenterlinevectP.h"
#include <atomic>
#include <chrono>
#include <iomanip>
#include <locale>
#include <mutex>
#include <sstream>
#include <stdexcept>

static constexpr const char *revision="8c5345182b1c3d2ff011a1cf08dad067b6700f08";
struct TraceContext {std::atomic<bool> cancel{false};std::atomic<int> progress{0};std::string json,error;};
// Upstream adjustments use file-local globals: serialize concurrent workers.
static std::timed_mutex algorithmMutex;
static void checkpoint(TraceContext &c){if(c.cancel.load())throw std::runtime_error("cancelled");}
struct SkeletonDeleter {
  void operator()(SkeletonList *s) const {if(s){for(auto p:*s)delete p;delete s;}}
};
struct OwnedStrokes {
  std::vector<TStroke*> values;
  ~OwnedStrokes(){for(auto s:values)delete s;}
};
static bool ink(const uint8_t *p,int mode,int threshold){
  return mode==1 ? p[3]>=threshold : std::max(p[2],std::max(p[1],p[0]))<threshold*(p[3]/255.0);
}
// Appearance sampling is optional and runs after OpenToonz geometry is done.
// Off preserves OpenToonz's RGB-raster closest-to-black palette style.
static void appearance(const TStroke &s,const uint8_t *pixels,int width,int height,
  int mode,int threshold,bool preserve,int &r,int &g,int &b,double &opacity){
  r=g=b=0;opacity=1.;if(!preserve)return;
  double sr=0,sg=0,sb=0,sa=0;size_t count=0;
  for(size_t i=0;i+2<s.points.size();i+=2){
    auto a=s.points[i],c=s.points[i+1],z=s.points[i+2];
    int steps=std::max(1,int(std::ceil(tdistance(a,c)+tdistance(c,z))));
    for(int j=0;j<=steps;++j){
      double t=double(j)/steps,u=1-t;
      int x=int(std::floor(u*u*a.x+2*u*t*c.x+t*t*z.x));
      int y=height-1-int(std::floor(u*u*a.y+2*u*t*c.y+t*t*z.y));
      if(x<0||x>=width||y<0||y>=height)continue;
      auto p=pixels+4*(size_t(y)*width+x);if(!p[3]||!ink(p,mode,threshold))continue;
      sr+=p[2];sg+=p[1];sb+=p[0];sa+=p[3];++count;
    }
  }
  if(count){r=std::lround(sr/count);g=std::lround(sg/count);b=std::lround(sb/count);opacity=sa/(255.*count);}
}
extern "C" {
LINEWORK_EXPORT const char *linework_trace_backend(){return "opentoonz-centerline-1";}
LINEWORK_EXPORT void *linework_trace_new(){return new TraceContext;}
LINEWORK_EXPORT void linework_trace_cancel(void *p){if(p)static_cast<TraceContext*>(p)->cancel.store(true);}
LINEWORK_EXPORT void linework_trace_delete(void *p){delete static_cast<TraceContext*>(p);}
LINEWORK_EXPORT int linework_trace_progress(void *p){return p?static_cast<TraceContext*>(p)->progress.load():0;}
LINEWORK_EXPORT const char *linework_trace_result(void *p){return static_cast<TraceContext*>(p)->json.c_str();}
LINEWORK_EXPORT const char *linework_trace_error(void *p){return static_cast<TraceContext*>(p)->error.c_str();}
// A still-open Krita can retain Python from 0.5.x after files are updated.
// Refuse its old ABI instead of interpreting missing float arguments.
LINEWORK_EXPORT int linework_trace_run(void *handle,const uint8_t*,int,int,int,int,int){
  static_cast<TraceContext*>(handle)->error="Salve seu desenho e reabra o Krita para carregar o motor OpenToonz.";return 0;
}
LINEWORK_EXPORT int linework_trace_run_opentoonz(void *handle,const uint8_t *bgra,int width,int height,
  int mode,int threshold,int despeckle,double penalty,double maximumWidth,int preserveColor){
  auto &ctx=*static_cast<TraceContext*>(handle);
  try {
    if(!bgra||width<=0||height<=0||int64_t(width)*height>32000000||threshold<1||threshold>254||
       (mode!=0&&mode!=1)||despeckle<0||!std::isfinite(penalty)||penalty<0||penalty>9||
       !std::isfinite(maximumWidth)||maximumWidth<=0||maximumWidth>2000)
      throw std::runtime_error("Invalid raster dimensions or OpenToonz parameters");
    checkpoint(ctx);std::unique_lock<std::timed_mutex> lock(algorithmMutex,std::defer_lock);
    while(!lock.try_lock_for(std::chrono::milliseconds(10)))checkpoint(ctx);
    checkpoint(ctx);
    TRasterP raster;TRaster32P rgba;TRasterGR8P alpha;
    if(mode==0){rgba=TRaster32P(width,height);raster=rgba;}
    else{alpha=TRasterGR8P(width,height);raster=alpha;}
    int foreground=0;
    for(int y=0;y<height;++y){checkpoint(ctx);for(int x=0;x<width;++x){
      auto p=bgra+4*(size_t(y)*width+x);foreground+=ink(p,mode,threshold);
      if(mode==0)rgba->pixels(height-1-y)[x]={p[2],p[1],p[0],p[3]};
      else alpha->pixels(height-1-y)[x].value=255-p[3];
    }}
    CenterlineConfiguration config;
    config.m_threshold=mode==1?256-threshold:threshold;
    config.m_despeckling=despeckle;config.m_penalty=penalty;config.m_maxThickness=maximumWidth/2.;
    VectorizerCoreGlobals globals;globals.currConfig=&config;
    VectorizerCore progress(ctx.cancel,ctx.progress);Contours polygons;OwnedStrokes strokes;TPalette palette;
    ctx.progress.store(5);polygonize(raster,polygons,globals);checkpoint(ctx);
    ctx.progress.store(15);std::unique_ptr<SkeletonList,SkeletonDeleter> skeleton(skeletonize(polygons,&progress,globals));
    checkpoint(ctx);ctx.progress.store(80);organizeGraphs(skeleton.get(),globals);
    calculateSequenceColors(raster,globals);checkpoint(ctx);ctx.progress.store(85);
    conversionToStrokes(strokes.values,globals);checkpoint(ctx);
    applyStrokeColors(strokes.values,raster,&palette,globals);ctx.progress.store(95);
    if(strokes.values.size()>10000)throw std::runtime_error("Too many strokes; increase noise removal");
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(17);
    out<<"{\"algorithm\":\"opentoonz-centerline\",\"revision\":\""<<revision<<"\",\"foreground\":"<<foreground<<",\"paths\":[";
    bool first=true;
    for(auto s:strokes.values){
      checkpoint(ctx);if(s->getStyle()<0)continue;
      if(s->points.size()>39999)throw std::runtime_error("Too many control points; decrease accuracy");
      for(auto p:s->points)if(!std::isfinite(p.x)||!std::isfinite(p.y)||!std::isfinite(p.thick)||p.thick<0)
        throw std::runtime_error("OpenToonz produced invalid control points");
      if(!first)out<<',';first=false;int r,g,b;double opacity;
      appearance(*s,bgra,width,height,mode,threshold,preserveColor,r,g,b,opacity);
      out<<"{\"color\":["<<r<<','<<g<<','<<b<<"],\"opacity\":"<<opacity<<",\"quadratics\":[";
      for(size_t i=0;i<s->points.size();++i){if(i)out<<',';auto p=s->points[i];out<<'['<<p.x<<','<<height-p.y<<','<<p.thick<<']';}
      out<<"]}";
    }
    out<<"]}";ctx.json=out.str();ctx.progress.store(100);return 1;
  }catch(const std::exception &e){ctx.error=e.what();return ctx.cancel.load()?-1:0;}
}
}
