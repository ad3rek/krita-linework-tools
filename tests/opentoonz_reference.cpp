// SPDX-License-Identifier: GPL-3.0-or-later
// Reference driver: compiled with the unmodified OpenToonz algorithm files,
// not the production port's patched copies. Host containers/math are shared.
#include "tcenterlinevectP.h"
#include <iomanip>
#include <sstream>
#include <locale>
extern "C" const char *linework_opentoonz_reference(const unsigned char *bgra,
  int w,int h,int mode,int threshold,int despeckle,double penalty,double maxWidth){
  static std::string output;
  TRasterP ras;TRaster32P rgb;TRasterGR8P gray;
  if(mode==0){rgb=TRaster32P(w,h);ras=rgb;}
  else{gray=TRasterGR8P(w,h);ras=gray;}
  for(int y=0;y<h;++y)for(int x=0;x<w;++x){
    const unsigned char *pixel=bgra+4*(y*w+x);
    if(mode==0)rgb->pixels(h-y-1)[x]={pixel[2],pixel[1],pixel[0],pixel[3]};
    else gray->pixels(h-y-1)[x].value=255-pixel[3];
  }
  CenterlineConfiguration conf;conf.m_threshold=mode?256-threshold:threshold;
  conf.m_despeckling=despeckle;conf.m_penalty=penalty;conf.m_maxThickness=maxWidth/2;
  VectorizerCoreGlobals globals;globals.currConfig=&conf;
  std::atomic<bool> cancel{false};std::atomic<int> progress{0};VectorizerCore vectorizer(cancel,progress);
  Contours contours;polygonize(ras,contours,globals);
  SkeletonList *skeleton=skeletonize(contours,&vectorizer,globals);
  organizeGraphs(skeleton,globals);
  std::vector<TStroke*> result;TPalette palette;
  calculateSequenceColors(ras,globals);
  conversionToStrokes(result,globals);
  applyStrokeColors(result,ras,&palette,globals);
  std::ostringstream stream;stream.imbue(std::locale::classic());stream<<std::setprecision(17)<<'[';
  bool first=true;
  for(auto stroke:result){
    if(stroke->getStyle()>=0){
      if(!first)stream<<',';first=false;stream<<'[';
      for(size_t i=0;i<stroke->points.size();++i){
        auto p=stroke->points[i];if(i)stream<<',';stream<<'['<<p.x<<','<<h-p.y<<','<<p.thick<<']';
      }
      stream<<']';
    }
    delete stroke;
  }
  stream<<']';for(auto graph:*skeleton)delete graph;delete skeleton;
  output=stream.str();return output.c_str();
}
