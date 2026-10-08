// SPDX-License-Identifier: GPL-3.0-or-later
// Use Krita's freehand helper as a geometry producer. Its native smoothing,
// timers and pressure processing run unchanged; painting jobs are recorded
// rather than submitted to the user's image or the preview image.
#include "export.h"
#include <tool/kis_tool_freehand_helper.h>
#include <tool/kis_painting_information_builder.h>
#include <tool/kis_smoothing_options.h>
#include <kis_image_interfaces.h>
#include <kis_stroke.h>
#include <kis_stroke_strategy.h>
#include <KoPointerEvent.h>
#include <QTabletEvent>
#include <QElapsedTimer>
#include <array>
#include <deque>

static void smoothingValues(KisSmoothingOptions &o, double *v) {
    v[0]=o.smoothingType(); v[1]=o.smoothnessDistance(); v[2]=o.tailAggressiveness();
    v[3]=o.smoothPressure(); v[4]=o.useScalableDistance(); v[5]=o.delayDistance();
    v[6]=o.useDelayDistance(); v[7]=o.finishStabilizedCurve(); v[8]=o.stabilizeSensors();
}
static void setSmoothingValues(KisSmoothingOptions &o, const double *v) {
    // Scalable distance cannot be changed while the stabilizer is selected.
    o.setSmoothingType(KisSmoothingOptions::NO_SMOOTHING);
    o.setUseScalableDistance(v[4]);
    o.setSmoothnessDistance(std::clamp(v[1], 1.0, 1000.0));
    o.setTailAggressiveness(std::clamp(v[2], 0.0, 1.0));
    o.setSmoothPressure(v[3]); o.setDelayDistance(std::clamp(v[5], 0.0, 1000.0));
    o.setUseDelayDistance(v[6]); o.setFinishStabilizedCurve(v[7]); o.setStabilizeSensors(v[8]);
    o.setSmoothingType(static_cast<KisSmoothingOptions::SmoothingType>(std::clamp(int(v[0]),0,3)));
}
extern "C" LINEWORK_EXPORT void linework_smoothing_options(double *values, int write) {
    if (!values) return;
    KisSmoothingOptions options(true);
    if (write) {
        setSmoothingValues(options, values);
        QMetaObject::invokeMethod(&options, "slotWriteConfig", Qt::DirectConnection);
    } else smoothingValues(options, values);
}

class LineworkGeometryFacade final : public KisStrokesFacade {
    KisStrokeSP token;
    std::unique_ptr<KisStrokeStrategy> painters;
public:
    std::deque<std::array<double,11>> segments;
    KisStrokeId startStroke(KisStrokeStrategy *strategy) override {
        painters.reset(strategy);
        token.reset(new KisStroke(new KisStrokeStrategy(QLatin1String("Linework geometry"))));
        return token;
    }
    void addJob(KisStrokeId, KisStrokeJobData *job) override {
        std::unique_ptr<KisStrokeJobData> owner(job);
        auto data=dynamic_cast<FreehandStrokeStrategy::Data*>(job);
        if (!data || segments.size()>=40000) return;
        auto a=data->pi1, b=data->pi2;
        auto c=data->control1, d=data->control2;
        int kind;
        if(data->type==FreehandStrokeStrategy::Data::POINT) {kind=0; b=a; c=d=a.pos();}
        else if(data->type==FreehandStrokeStrategy::Data::LINE) {
            kind=1; c=(2*a.pos()+b.pos())/3; d=(a.pos()+2*b.pos())/3;
        } else if(data->type==FreehandStrokeStrategy::Data::CURVE) kind=2;
        else return;
        segments.push_back({double(kind), a.pos().x(), a.pos().y(), a.pressure(),
                           c.x(),c.y(),d.x(),d.y(),b.pos().x(),b.pos().y(),b.pressure()});
    }
    void endStroke(KisStrokeId) override {
        if(token)token->endStroke();
        token.clear(); painters.reset();
    }
    bool cancelStroke(KisStrokeId id) override {endStroke(id);return true;}
};

class LineworkFreehandHelper final : public KisToolFreehandHelper {
public:
    using KisToolFreehandHelper::KisToolFreehandHelper;
    using KisToolFreehandHelper::cancelPaint;
};

struct LineworkSmoothing {
    KoCanvasResourceProvider resources;
    KisPaintingInformationBuilder builder;
    LineworkGeometryFacade facade;
    std::unique_ptr<LineworkFreehandHelper> helper;
    QElapsedTimer clock;
    bool ended=false;
    void event(const double *input, QEvent::Type type, KisImageSP image={}, KisNodeSP node={}) {
        const QPointF p(input[0],input[1]);
        QTabletEvent tablet(type,p,p,QTabletEvent::Stylus,QTabletEvent::Pen,
                           std::clamp(input[2],0.0,1.0),0,0,0,0,0,Qt::NoModifier,1,
                           Qt::LeftButton,Qt::LeftButton);
        tablet.setTimestamp(clock.elapsed());
        KoPointerEvent pointer(&tablet,p);
        if(type==QEvent::TabletPress) helper->initPaint(&pointer,p,image,node,&facade);
        else helper->paintEvent(&pointer);
    }
    ~LineworkSmoothing() {
        if(helper && helper->isRunning()) helper->cancelPaint();
        helper.reset();
    }
};

extern "C" LINEWORK_EXPORT void *linework_smoothing_begin(Node *wrapper, View *viewWrapper,
        const double *settings, const double *point) {
    if(!wrapper || !viewWrapper || !settings || !point) return nullptr;
    auto image=(wrapper->*member(NodeImage{}))();
    auto node=(wrapper->*member(NodeNode{}))();
    auto view=(viewWrapper->*member(ViewView{}))();
    if(!image || !node || !view || !view->canvasBase()) return nullptr;
    auto session=std::make_unique<LineworkSmoothing>();
    auto source=view->canvasBase()->resourceManager();
    for(int k=0;k<=KoCanvasResource::BrushRotation;k++)
        if(source->hasResource(k))session->resources.setResource(k,source->resource(k));
    // Linework has always captured pen input; retain that behavior and apply
    // Krita's configured tablet curve without changing the canvas setting.
    session->resources.setResource(KoCanvasResource::DisablePressure,true);
    auto options=new KisSmoothingOptions(true);
    setSmoothingValues(*options,settings);
    session->helper=std::make_unique<LineworkFreehandHelper>(&session->builder,&session->resources,
                                                          kundo2_noi18n("Linework smoothing"),options);
    session->clock.start();session->event(point,QEvent::TabletPress,image,node);
    return session.release();
}
extern "C" LINEWORK_EXPORT void linework_smoothing_move(void *handle,const double *point) {
    auto s=static_cast<LineworkSmoothing*>(handle);
    if(s && !s->ended && point)s->event(point,QEvent::TabletMove);
}
extern "C" LINEWORK_EXPORT void linework_smoothing_end(void *handle) {
    auto s=static_cast<LineworkSmoothing*>(handle);
    if(s && !s->ended) {s->helper->endPaint();s->ended=true;}
}
extern "C" LINEWORK_EXPORT int linework_smoothing_take(void *handle,double *output,int capacity) {
    auto s=static_cast<LineworkSmoothing*>(handle);
    if(!s || !output || capacity<1)return 0;
    int count=0;
    while(!s->facade.segments.empty() && count<capacity) {
        auto &segment=s->facade.segments.front();
        std::copy(segment.begin(),segment.end(),output+11*count++);
        s->facade.segments.pop_front();
    }
    return count;
}
extern "C" LINEWORK_EXPORT void linework_smoothing_delete(void *handle) {
    delete static_cast<LineworkSmoothing*>(handle);
}
