// SPDX-License-Identifier: GPL-3.0-or-later
// Krita 5.2.14 ABI bridge; use only from its GUI thread and loaded libkis objects.
#include <Node.h>
#include <View.h>
#include <Resource.h>
#include <Shape.h>
#include <KoShapeGroup.h>
#include <KoPathShape.h>
#include <SvgShape.h>
#include <SvgLoadingContext.h>
#include <KoDocumentResourceManager.h>
#include <SvgWriter.h>
#include <SvgSavingContext.h>
#include <QBuffer>
#include <memory>
#include <KisView.h>
#include <kis_canvas2.h>
#include <kis_image.h>
#include <kis_node.h>
#include <KoCanvasResourceProvider.h>
#include <KoColorSpaceRegistry.h>
#include <KoColor.h>
#include <KisGlobalResourcesInterface.h>
#include <brushengine/kis_paintop_preset.h>
#include <brushengine/kis_paintop_settings.h>
#include <brushengine/kis_paint_information.h>
#include <tool/kis_resources_snapshot.h>
#include <tool/strokes/freehand_stroke.h>
#include <tool/strokes/KisFreehandStrokeInfo.h>
#include <tool/KisAsynchronousStrokeUpdateHelper.h>
#include <QDomDocument>
#include <QColor>
#include <QCoreApplication>
#include <QThread>
#include <QAbstractItemView>
#include <QAbstractItemDelegate>
#include <QIdentityProxyModel>
#include <QAbstractProxyModel>
#include <QPointer>
#include <QIcon>
#include <QSet>
#include <QMutex>
#include <QMutexLocker>
#include <QImage>
#include <QScopedValueRollback>
#include <kis_node_model.h>
#include <kis_paint_device.h>
#include <kis_indirect_painting_support.h>
#include <kis_painter.h>
#include <kis_undo_store.h>
#include <kis_simple_stroke_strategy.h>
#include <KisBusyWaitBroker.h>
#include <kis_cubic_curve.h>
#include <kis_properties_configuration.h>
#include <kundo2command.h>
#include <KoToolRegistry.h>
#include <KoToolFactoryBase.h>
#include <KoToolManager.h>
#include <KoToolManager_p.h>
#include <KoCanvasBase.h>
#include <KoShapeManager.h>
#include <kis_shape_layer.h>
#include <kis_shape_layer_canvas.h>
#include <tool/kis_tool_paint.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>

// C++ explicit member-pointer instantiation permits access to these exported
// libkis internals, without changing the official class definitions or layouts.
template<class Tag, typename Tag::Type Member> struct Access {
    friend typename Tag::Type member(Tag) { return Member; }
};
struct NodeImage { using Type=KisImageSP(Node::*)() const; friend Type member(NodeImage); };
struct NodeNode { using Type=KisNodeSP(Node::*)() const; friend Type member(NodeNode); };
struct ViewView { using Type=KisView*(View::*)(); friend Type member(ViewView); };
struct ResourceResource { using Type=KoResourceSP(Resource::*)() const; friend Type member(ResourceResource); };
struct ShapeLayerCanvas { using Type=KisShapeLayerCanvasBase*(KisShapeLayer::*)() const; friend Type member(ShapeLayerCanvas); };
struct ShapeShape { using Type=KoShape*(Shape::*)(); friend Type member(ShapeShape); };
template struct Access<NodeImage,&Node::image>;
template struct Access<NodeNode,&Node::node>;
template struct Access<ViewView,&View::view>;
template struct Access<ResourceResource,&Resource::resource>;
template struct Access<ShapeLayerCanvas,&KisShapeLayer::canvas>;
template struct Access<ShapeShape,&Shape::shape>;

#include "smoothing.h"

extern "C" __attribute__((visibility("default"))) int linework_native_busy() {
    return KisBusyWaitBroker::instance()->guiThreadIsWaitingForBetterWeather();
}

extern "C" __attribute__((visibility("default"))) int linework_shape_info(Shape *wrapper,double *out){
    if(!wrapper || !out)return 0;
    auto shape=(wrapper->*member(ShapeShape{}))();if(!shape)return 0;
    auto t=shape->absoluteTransformation();auto size=shape->size();
    out[0]=t.m11();out[1]=t.m12();out[2]=t.m21();out[3]=t.m22();out[4]=t.dx();out[5]=t.dy();
    out[6]=size.width();out[7]=size.height();out[8]=dynamic_cast<KoShapeGroup*>(shape)?1:0;return 1;
}
extern "C" __attribute__((visibility("default"))) const char *linework_shape_canonical(Shape *wrapper){
    static thread_local QByteArray text;
    if(!wrapper)return nullptr;
    auto shape=(wrapper->*member(ShapeShape{}))();if(!shape)return nullptr;
    std::unique_ptr<KoShape> clone(shape->cloneShape());if(!clone)return nullptr;
    if(!dynamic_cast<KoShapeGroup*>(clone.get()) && !clone->size().isEmpty())clone->setSize(QSizeF(1,1));
    clone->setTransformation(QTransform());
    QBuffer buffer,styles;buffer.open(QIODevice::WriteOnly);styles.open(QIODevice::WriteOnly);
    {SvgSavingContext context(buffer,styles);SvgWriter writer({clone.get()});writer.saveDetached(context);}
    text=buffer.data();return text.constData();
}
extern "C" __attribute__((visibility("default"))) int linework_shape_image_bounds(Shape *wrapper,double *out){
    if(!wrapper || !out)return 0;
    auto shape=(wrapper->*member(ShapeShape{}))();
    auto group=dynamic_cast<KoShapeGroup*>(shape);
    if(!group || group->shapes().size()!=1)return 0;
    auto child=group->shapes().first();
    if(!dynamic_cast<SvgShape*>(child))return 0;
    const QRectF bounds=child->absoluteTransformation().mapRect(QRectF(QPointF(),child->size()));
    out[0]=bounds.x();out[1]=bounds.y();out[2]=bounds.width();out[3]=bounds.height();return 1;
}

using ToolCallback=void*(*)(int,int,void*);
static ToolCallback toolCallback=nullptr;
static int previewMutationDepth=0;
static const char *toolIds[]={"LineworkBrush","LineworkCurve","LineworkLine","LineworkEdit","LineworkPressure","LineworkErase"};

class LineworkTool final:public KisToolPaint {
    int mode;
public:
    LineworkTool(KoCanvasBase *canvas,int mode):KisToolPaint(canvas,QCursor(Qt::CrossCursor)),mode(mode){
        setSupportOutline(mode==0);
        if(auto kis=dynamic_cast<KisCanvas2*>(canvas)){
            QObject::connect(kis->image().data(),&KisImage::sigStrokeEndRequested,this,[this]{
                // Saving, cloning and native image operations ask active tools
                // to finish before reading the projection. Internal preview
                // updates are guarded to avoid recursively cancelling the drag.
                if(!previewMutationDepth && toolCallback &&
                   KoToolManager::instance()->activeToolId()==QString::fromLatin1(toolIds[this->mode]))
                    toolCallback(4,this->mode,this->canvas()->canvasWidget());
            });
        }
    }
    void activate(const QSet<KoShape*> &shapes)override{
        KisToolPaint::activate(shapes);
        if(toolCallback)toolCallback(1,mode,canvas()->canvasWidget());
    }
    void deactivate()override{
        if(toolCallback)toolCallback(2,mode,canvas()->canvasWidget());
        KisToolPaint::deactivate();
    }
    // Python's canvas controller captures input while this tool is active;
    // KisToolPaint retains native hover outlines, sampling and size gestures.
    void beginPrimaryAction(KoPointerEvent*)override{}
    void continuePrimaryAction(KoPointerEvent*)override{}
    void endPrimaryAction(KoPointerEvent*)override{}
    QWidget *createOptionWidget()override{
        return toolCallback?static_cast<QWidget*>(toolCallback(3,mode,canvas()->canvasWidget())):nullptr;
    }
};

class LineworkToolFactory final:public KoToolFactoryBase {
    int mode;
public:
    LineworkToolFactory(int mode,const QString &icons):KoToolFactoryBase(QString::fromLatin1(toolIds[mode])),mode(mode){
        const char *labels[]={"Linework Brush — pincel","Linework Curve — curva","Linework Line — linha","Linework Edit — pontos","Linework Thickness — espessura","Linework Erase — apagar traço"};
        setToolTip(QString::fromUtf8(labels[mode]));
        setSection(QStringLiteral("1 Linework"));
        setPriority(40+mode);
        setActivationShapeId(KRITA_TOOL_ACTIVATION_ID);
        setIconName(icons+QString("/tool-%1.svg").arg(mode));
    }
    KoToolBase *createTool(KoCanvasBase *canvas)override{return new LineworkTool(canvas,mode);}
};

extern "C" __attribute__((visibility("default"))) int linework_register_tools(ToolCallback callback,const char *icons){
    if(!callback || !QCoreApplication::instance() || QThread::currentThread()!=QCoreApplication::instance()->thread())return 0;
    toolCallback=callback;
    auto registry=KoToolRegistry::instance();
    auto manager=KoToolManager::instance();
    for(int mode=0;mode<6;mode++)if(!registry->contains(QString::fromLatin1(toolIds[mode]))){
        auto factory=new LineworkToolFactory(mode,QString::fromUtf8(icons));
        registry->add(factory);
        // Python extensions load after the manager's initial registry snapshot.
        // Register the new actions before the first document attaches its canvas.
        if(!manager->toolActionList().isEmpty()){
            auto action=new KoToolAction(factory);
            manager->priv()->toolActionList.append(action);
            Q_EMIT manager->addedTool(action,nullptr);
        }
    }
    return 1;
}

extern "C" __attribute__((visibility("default"))) void linework_select_tool(int mode){
    if(mode>=0 && mode<6)KoToolManager::instance()->switchToolRequested(QString::fromLatin1(toolIds[mode]));
}

extern "C" __attribute__((visibility("default"))) int linework_active_tool(){
    QString id=KoToolManager::instance()->activeToolId();
    for(int i=0;i<6;i++)if(id==QLatin1String(toolIds[i]))return i;
    return -1;
}

extern "C" __attribute__((visibility("default"))) void linework_clear_callbacks(){toolCallback=nullptr;}

class LineworkEditStrategy final:public KisSimpleStrokeStrategy {
public:
    LineworkEditStrategy():KisSimpleStrokeStrategy(QLatin1String("linework_edit")){
        enableJob(JOB_INIT);enableJob(JOB_FINISH);
        setClearsRedoOnStart(false);
        setRequestsOtherStrokesToEnd(false);
    }
};
struct LineworkEditSession { KisImageSP image; KisStrokeId stroke; };
extern "C" __attribute__((visibility("default"))) void *linework_edit_begin(Node *wrapper){
    if(!wrapper)return nullptr;
    auto image=(wrapper->*member(NodeImage{}))();
    if(!image)return nullptr;
    auto session=new LineworkEditSession;
    session->image=image;
    session->stroke=image->startStroke(new LineworkEditStrategy);
    return session;
}
extern "C" __attribute__((visibility("default"))) void linework_edit_end(void *pointer){
    auto session=static_cast<LineworkEditSession*>(pointer);
    if(!session)return;
    session->image->endStroke(session->stroke);
    session->image->waitForDone();
    delete session;
}

// libkis schedules SVG imports/removals on image workers. Its waitForDone()
// feedback pumps a nested Qt event loop, where vector-observer timers can read
// KoShapes concurrently with those writes. Enter the image's outer wait while
// it is stable: subsequent waits drain workers without pumping that feedback.
// Keep this narrowly scoped to committing already-prepared shape appearances.
struct LineworkShapeWrite { KisImageSP image; };
extern "C" __attribute__((visibility("default"))) void *linework_shape_write_begin(Node *wrapper){
    if(!wrapper || QThread::currentThread()!=QCoreApplication::instance()->thread())return nullptr;
    auto image=(wrapper->*member(NodeImage{}))();
    if(!image)return nullptr;
    image->waitForDone();
    auto session=new LineworkShapeWrite{image};
    KisBusyWaitBroker::instance()->notifyWaitOnImageStarted(image.data());
    return session;
}
extern "C" __attribute__((visibility("default"))) void linework_shape_write_end(void *pointer){
    auto session=static_cast<LineworkShapeWrite*>(pointer);
    if(!session)return;
    session->image->waitForDone();
    KisBusyWaitBroker::instance()->notifyWaitOnImageEnded(session->image.data());
    delete session;
}

// Suppress only the layer's render registration. The shape remains a visible
// child of the layer, so SVG, fingerprints, save/autosave and document clones
// retain the committed appearance. Never retain a raw shape pointer across edits.
extern "C" __attribute__((visibility("default"))) int linework_preview_hidden(
        Node *wrapper,const char *name,int hidden){
    if(!wrapper || !name || QThread::currentThread()!=QCoreApplication::instance()->thread())return 0;
    auto node=(wrapper->*member(NodeNode{}))();
    auto layer=dynamic_cast<KisShapeLayer*>(node.data());
    if(!layer || !layer->image())return 0;
    KoShape *shape=nullptr;
    const QString ident=QString::fromUtf8(name);
    for(auto candidate:layer->shapes())if(candidate->name()==ident){shape=candidate;break;}
    if(!shape)return 0;
    auto manager=layer->shapeManager();
    const bool registered=manager->shapes().contains(shape);
    if(!registered && hidden)return 1;
    QScopedValueRollback<int> guard(previewMutationDepth,previewMutationDepth+1);
    layer->image()->waitForDone();
    if(hidden)manager->remove(shape);
    else if(!registered)manager->addShape(shape,KoShapeManager::AddWithoutRepaint);
    (layer->*member(ShapeLayerCanvas{}))()->updateCanvas(shape->boundingRect());
    layer->forceUpdateTimedNode();
    layer->image()->waitForDone();
    return 1;
}

extern "C" __attribute__((visibility("default"))) void linework_refresh_layer(Node *wrapper){
    if(!wrapper)return;
    auto node=(wrapper->*member(NodeNode{}))();
    auto layer=dynamic_cast<KisShapeLayer*>(node.data());
    if(!layer || !layer->image())return;
    layer->image()->waitForDone();
    (layer->*member(ShapeLayerCanvas{}))()->updateCanvas(layer->boundingRect());
    layer->forceUpdateTimedNode();
    layer->image()->waitForDone();
}

// Keep the selected top-level shape and its transform alive: native resize and
// move undo commands retain that pointer. Only regenerate its local appearance.
extern "C" __attribute__((visibility("default"))) int linework_shape_render(
        Node *wrapper,Shape *item,const char *png,const double *coords,int count,
        double x,double y,double width,double height,double sx,double sy){
    if(!wrapper || !item || QThread::currentThread()!=QCoreApplication::instance()->thread())return 0;
    auto node=(wrapper->*member(NodeNode{}))();
    auto layer=dynamic_cast<KisShapeLayer*>(node.data());
    auto shape=(item->*member(ShapeShape{}))();
    if(!layer || !layer->image() || !shape || !layer->shapes().contains(shape))return 0;
    KoShape *target=shape;
    if(auto group=dynamic_cast<KoShapeGroup*>(shape)){
        if(group->shapes().size()!=1)return 0;
        target=group->shapes().first();
    }
    auto path=dynamic_cast<KoPathShape*>(target);
    auto image=dynamic_cast<SvgShape*>(target);
    if(png?(!image || width<=0 || height<=0):(!path || !coords || count<3))return 0;
    bool invertible=false;
    auto inverse=(png?shape:target)->absoluteTransformation().inverted(&invertible);
    if(!invertible)return 0;
    QScopedValueRollback<int> guard(previewMutationDepth,previewMutationDepth+1);
    layer->image()->waitForDone();
    const QRectF oldBounds=shape->boundingRect();
    shape->update();
    if(png){
        QDomDocument xml;auto element=xml.createElement("image");
        element.setAttribute("width",QString::number(width,'g',17));
        element.setAttribute("height",QString::number(height,'g',17));
        element.setAttribute("xlink:href",QStringLiteral("data:image/png;base64,")+QString::fromLatin1(png));
        KoDocumentResourceManager resources;
        SvgLoadingContext context(&resources);context.pushGraphicsContext();
        if(!image->loadSvg(element,context))return 0;
        target->setTransformation(QTransform::fromTranslate(x,y)*QTransform::fromScale(sx,sy)*inverse);
    }else{
        const QTransform map=QTransform::fromScale(sx,sy)*inverse;
        const QTransform transform=target->transformation();
        path->clear();
        for(int i=0;i<count;i++){
            const QPointF point=map.map(QPointF(coords[2*i],coords[2*i+1]));
            if(!i)path->moveTo(point);else path->lineTo(point);
        }
        path->close();target->setTransformation(transform);
        path->normalize();
    }
    target->update();shape->update();
    (layer->*member(ShapeLayerCanvas{}))()->updateCanvas(oldBounds.united(shape->boundingRect()));
    layer->forceUpdateTimedNode();layer->image()->waitForDone();return 1;
}

// The view retains its native model and indexes. Only painting uses this proxy,
// so layer selection, drag/drop, visibility and rename remain native operations.
class LineworkIconModel final : public QIdentityProxyModel {
public:
    QSet<QString> layers;
    QIcon icon;
    explicit LineworkIconModel(QObject *parent):QIdentityProxyModel(parent){}
    QVariant data(const QModelIndex &index,int role=Qt::DisplayRole) const override {
        if(role==Qt::DecorationRole && index.column()==0){
            QModelIndex native=mapToSource(index);
            const QAbstractItemModel *model=sourceModel();
            while(auto proxy=qobject_cast<const QAbstractProxyModel*>(model)){
                native=proxy->mapToSource(native);model=proxy->sourceModel();
            }
            if(auto nodes=qobject_cast<const KisNodeModel*>(model)){
                auto node=nodes->nodeFromIndex(native);
                if(node && layers.contains(node->uuid().toString()))return icon;
            }
        }
        return QIdentityProxyModel::data(index,role);
    }
};

class LineworkIconDelegate final : public QAbstractItemDelegate {
public:
    QPointer<QAbstractItemDelegate> original;
    LineworkIconModel *icons;
    explicit LineworkIconDelegate(QAbstractItemView *view):QAbstractItemDelegate(view),original(view->itemDelegate()),icons(new LineworkIconModel(this)){
        icons->setSourceModel(view->model());
        connect(original,&QAbstractItemDelegate::commitData,this,&QAbstractItemDelegate::commitData);
        connect(original,&QAbstractItemDelegate::closeEditor,this,&QAbstractItemDelegate::closeEditor);
        connect(original,&QAbstractItemDelegate::sizeHintChanged,this,&QAbstractItemDelegate::sizeHintChanged);
    }
    void paint(QPainter *p,const QStyleOptionViewItem &option,const QModelIndex &index)const override{
        if(original)original->paint(p,option,index.column()==0?icons->mapFromSource(index):index);
    }
    QSize sizeHint(const QStyleOptionViewItem &o,const QModelIndex &i)const override{return original?original->sizeHint(o,i):QSize();}
    bool editorEvent(QEvent *e,QAbstractItemModel *m,const QStyleOptionViewItem &o,const QModelIndex &i)override{return original&&original->editorEvent(e,m,o,i);}
    QWidget *createEditor(QWidget *p,const QStyleOptionViewItem &o,const QModelIndex &i)const override{return original?original->createEditor(p,o,i):nullptr;}
    void setEditorData(QWidget *e,const QModelIndex &i)const override{if(original)original->setEditorData(e,i);}
    void setModelData(QWidget *e,QAbstractItemModel *m,const QModelIndex &i)const override{if(original)original->setModelData(e,m,i);}
    void updateEditorGeometry(QWidget *e,const QStyleOptionViewItem &o,const QModelIndex &i)const override{if(original)original->updateEditorGeometry(e,o,i);}
    void destroyEditor(QWidget *e,const QModelIndex &i)const override{if(original)original->destroyEditor(e,i);}
    bool helpEvent(QHelpEvent *e,QAbstractItemView *v,const QStyleOptionViewItem &o,const QModelIndex &i)override{return original&&original->helpEvent(e,v,o,i);}
};

extern "C" __attribute__((visibility("default"))) int linework_layer_icons(void *viewHandle,const char *ids,const char *iconPath){
    if(!QCoreApplication::instance()||QThread::currentThread()!=QCoreApplication::instance()->thread()||!viewHandle)return 0;
    auto view=static_cast<QAbstractItemView*>(viewHandle);
    if(!view->model()||!view->itemDelegate())return 0;
    auto delegate=dynamic_cast<LineworkIconDelegate*>(view->itemDelegate());
    if(!delegate){delegate=new LineworkIconDelegate(view);view->setItemDelegate(delegate);}
    delegate->icons->setSourceModel(view->model());
    QSet<QString> layers;
    for(const auto &id:QString::fromUtf8(ids?ids:"").split('\n',Qt::SkipEmptyParts))layers.insert(id);
    if(delegate->icons->layers!=layers || delegate->icons->icon.isNull()){
        delegate->icons->layers=layers;delegate->icons->icon=QIcon(QString::fromUtf8(iconPath));view->viewport()->update();
    }
    return 1;
}

// Read the pressure contribution to Size with Krita's own curve interpolator.
// Other Size sensors are replaced by the editable diameter when that profile
// is first edited; pressure for opacity/flow/etc. remains independent.
extern "C" __attribute__((visibility("default"))) double linework_pressure_to_size(const char *xml, double pressure) {
    QDomDocument doc;
    if (!xml || !doc.setContent(QString::fromUtf8(xml))) return 1.0;
    KisPropertiesConfiguration config;
    config.fromXML(doc.documentElement());
    if (!config.getBool("PressureSize", false)) return 1.0;
    const double strength = config.getDouble("SizeValue", 1.0);
    if (!config.getBool("SizeUseCurve", true)) return std::clamp(strength, 0.0, 1.0);
    QDomDocument sensors;
    sensors.setContent(config.getString("SizeSensor"));
    QDomElement sensor = sensors.documentElement();
    if (sensor.attribute("id") == "sensorslist") {
        QDomElement pressureSensor;
        for (auto child = sensor.firstChildElement("ChildSensor"); !child.isNull(); child = child.nextSiblingElement("ChildSensor"))
            if (child.attribute("id") == "pressure") pressureSensor = child;
        sensor = pressureSensor;
        if (sensor.isNull()) return std::clamp(strength, 0.0, 1.0);
    }
    if (!sensor.isNull() && sensor.attribute("id") != "pressure") return std::clamp(strength, 0.0, 1.0);
    QString curve = sensor.firstChildElement("curve").text();
    if (curve.isEmpty()) curve = config.getBool("CustomSize", false) ? config.getString("CurveSize", DEFAULT_CURVE_STRING) : DEFAULT_CURVE_STRING;
    if (config.getBool("SizeUseSameCurve", true)) curve = config.getString("SizecommonCurve", curve);
    KisCubicCurve mapping(curve.isEmpty() ? DEFAULT_CURVE_STRING : curve);
    const double p = std::clamp(pressure, 0.0, 1.0);
    const double factor = mapping.isIdentity() ? p : KisCubicCurve::interpolateLinear(p, mapping.floatTransfer(256));
    return std::clamp(strength*factor, 0.0, 1.0);
}

static void useEditableThickness(KisPaintOpSettingsSP settings) {
    // Perspective is a separate KisPaintInformation channel. Using a linear
    // Size sensor here leaves the captured pressure available to all others.
    settings->setProperty("PressureSize", true);
    settings->setProperty("SizeSensor", QString("<params id=\"perspective\"><curve>0,0;1,1;</curve></params>"));
    settings->setProperty("SizeUseCurve", true);
    settings->setProperty("SizeUseSameCurve", true);
    settings->setProperty("SizecommonCurve", DEFAULT_CURVE_STRING);
    settings->setProperty("SizeValue", 1.0);
    settings->setProperty("SizecurveMode", 0);
}

extern "C" __attribute__((visibility("default"))) int linework_paint_with_thickness(void *nodeHandle, void *viewHandle, void *resourceHandle,
    const char *xml, const char *color, double size, double opacity, double flow,
    const double *input, int count, int explicitThickness, char *error, int capacity)
{
    auto fail=[&](const char *message){ if(capacity>0){std::strncpy(error,message,capacity-1);error[capacity-1]=0;}return 0;};
    try {
        if(!QCoreApplication::instance()||QThread::currentThread()!=QCoreApplication::instance()->thread())
            return fail("A pintura nativa deve executar na thread principal do Krita.");
        if(!nodeHandle||!viewHandle||!resourceHandle||!input||count<1||count>200000)
            return fail("Entrada nativa inválida.");
        auto node=static_cast<Node*>(nodeHandle);
        auto view=static_cast<View*>(viewHandle);
        auto resource=static_cast<Resource*>(resourceHandle);
        auto image=(node->*member(NodeImage{}))();
        auto target=(node->*member(NodeNode{}))();
        auto sourceView=(view->*member(ViewView{}))();
        if(!image||!target||!target->paintDevice()||!sourceView||!sourceView->canvasBase())
            return fail("O destino nativo não é uma camada de pintura válida.");
        auto original=(resource->*member(ResourceResource{}))().dynamicCast<KisPaintOpPreset>();
        if(!original)return fail("O preset nativo não foi encontrado.");
        auto brush=original->clone().dynamicCast<KisPaintOpPreset>();
        if(xml&&*xml){
            QDomDocument doc;
            if(!doc.setContent(QString::fromUtf8(xml)))return fail("XML do preset inválido.");
            brush->fromXML(doc.documentElement(),KisGlobalResourcesInterface::instance());
        }
        if(!brush->settings())return fail("O motor deste preset não está disponível.");
        if(brush->settings()->eraserMode())
            return fail("Use a ferramenta Linework Erase para apagar linhas.");
        brush->settings()->setPaintOpSize(size);
        brush->settings()->setPaintOpOpacity(opacity);
        brush->settings()->setPaintOpFlow(flow);
        if (explicitThickness) useEditableThickness(brush->settings());
        auto provider=sourceView->canvasBase()->resourceManager();
        // Build a private canvas resource provider: no changes to the user's
        // preset, foreground, size, flow, selection, mirror tools or canvas.
        KoCanvasResourceProvider local;
        for(int k=0;k<KoCanvasResource::KritaStart;k++) {
            if(provider->hasResource(k))local.setResource(k,provider->resource(k));
        }
        for(int k=KoCanvasResource::KritaStart;k<=KoCanvasResource::BrushRotation;k++) {
            if(provider->hasResource(k))local.setResource(k,provider->resource(k));
        }
        local.setResource(KoCanvasResource::CurrentPaintOpPreset,QVariant::fromValue(brush));
        local.setResource(KoCanvasResource::CurrentPaintOpPresetCache,QVariant());
        local.setResource(KoCanvasResource::Size,size);
        local.setResource(KoCanvasResource::Opacity,opacity);
        local.setResource(KoCanvasResource::Flow,flow);
        local.setResource(KoCanvasResource::EraserMode,false);
        local.setResource(KoCanvasResource::GlobalAlphaLock,false);
        local.setResource(KoCanvasResource::MirrorHorizontal,false);
        local.setResource(KoCanvasResource::MirrorVertical,false);
        local.setResource(KoCanvasResource::EffectiveZoom,1.0);
        local.setResource(KoCanvasResource::EffectiveLodAvailability,false);
        const QString composite=brush->settings()->paintOpCompositeOp();
        local.setResource(KoCanvasResource::CurrentCompositeOp,composite);
        local.setResource(KoCanvasResource::CurrentEffectiveCompositeOp,composite);
        local.setForegroundColor(KoColor(QColor(QString::fromUtf8(color)),target->colorSpace()));
        KisResourcesSnapshotSP snapshot=new KisResourcesSnapshot(image,target,&local,0,{},brush);
        snapshot->setSelectionOverride(KisSelectionSP());
        snapshot->setMirroring(false,false);
        snapshot->setOpacity(opacity);
        snapshot->setStrokeStyle(KisPainter::StrokeStyleBrush);
        snapshot->setFillStyle(KisPainter::FillStyleNone);
        auto strategy=new FreehandStrokeStrategy(snapshot,new KisFreehandStrokeInfo(),kundo2_noi18n("Linework native brush"));
        auto id=image->startStroke(strategy);
        const int stride = explicitThickness ? 5 : 4;
        auto point=[&](int i){const double *v=input+stride*i;return KisPaintInformation(QPointF(v[0],v[1]),std::clamp(v[2],0.0,1.0),0,0,0,0,explicitThickness ? std::clamp(v[4],0.0,1.0) : 1.0,v[3],0.5);};
        if(count==1)image->addJob(id,new FreehandStrokeStrategy::Data(0,point(0)));
        else for(int i=1;i<count;i++)image->addJob(id,new FreehandStrokeStrategy::Data(0,point(i-1),point(i)));
        image->addJob(id,new KisAsynchronousStrokeUpdateHelper::UpdateData(true));
        image->endStroke(id);
        image->waitForDone();
        return 1;
    }catch(const std::exception &e){return fail(e.what());}
    catch(...){return fail("Falha no motor nativo do Krita.");}
}


// A live stroke queues only newly received segments into Krita's paint engine.
// Preview snapshots copy pixels; they never serialize PNGs or replay old points.
struct LineworkStream {
    KoCanvasResourceProvider resources;
    KisImageSP image;
    KisNodeSP target;
    KisStrokeId id;
    KisPaintInformation last;
    bool hasLast=false;
    QMutex previewMutex;
    QImage preview;
    QRect previewBounds;
    bool pendingSnapshot=false;
};

class LineworkSnapshotJob final:public KisStrokeJobData {
public:
    LineworkSnapshotJob():KisStrokeJobData(KisStrokeJobData::BARRIER,KisStrokeJobData::EXCLUSIVE){}
};

class LineworkPreviewStrategy final:public FreehandStrokeStrategy {
    LineworkStream *stream;
public:
    LineworkPreviewStrategy(KisResourcesSnapshotSP snapshot,LineworkStream *stream):
        FreehandStrokeStrategy(snapshot,new KisFreehandStrokeInfo(),kundo2_noi18n("Linework preview")),stream(stream){}
    void doStrokeCallback(KisStrokeJobData *data)override{
        if(dynamic_cast<LineworkSnapshotJob*>(data)){
            auto device=stream->target->paintDevice();
            auto indirect=dynamic_cast<KisIndirectPaintingSupport*>(stream->target.data());
            const bool temporary=indirect && indirect->hasTemporaryTarget();
            if(temporary)device=indirect->temporaryTarget();
            QRect bounds=device->exactBounds().intersected(stream->image->bounds());
            QImage image;
            if(!bounds.isEmpty()){
                image=QImage(bounds.size(),QImage::Format_ARGB32);
                if(temporary){
                    KisPaintDeviceSP previewDevice=new KisPaintDevice(stream->target->colorSpace());
                    KisPainter painter(previewDevice);
                    indirect->setupTemporaryPainter(&painter);
                    painter.bitBlt(bounds.topLeft(),device,bounds);
                    previewDevice->readBytes(image.bits(),bounds);
                }else device->readBytes(image.bits(),bounds);
            }
            QMutexLocker lock(&stream->previewMutex);
            stream->preview=image;stream->previewBounds=bounds;stream->pendingSnapshot=false;
        }else FreehandStrokeStrategy::doStrokeCallback(data);
    }
};

struct LineworkPreviewImage {QImage image;QRect bounds;};

// Read-only, color-managed snapshot of a source layer. Conversion is performed
// on a copy, including 16-bit/float and non-RGB documents; no source is changed.
extern "C" __attribute__((visibility("default"))) void *linework_layer_snapshot(Node *wrapper,int *geometry){
    if(!wrapper || !geometry)return nullptr;
    auto node=(wrapper->*member(NodeNode{}))();
    auto image=(wrapper->*member(NodeImage{}))();
    if(!node || !image || !node->projection())return nullptr;
    image->waitForDone();
    const QRect bounds=node->projection()->exactBounds().intersected(image->bounds());
    if(bounds.isEmpty() || qint64(bounds.width())*bounds.height()>32000000)return nullptr;
    auto result=new LineworkPreviewImage;
    result->bounds=bounds;
    result->image=node->projection()->convertToQImage(nullptr,bounds).convertToFormat(QImage::Format_ARGB32);
    geometry[0]=bounds.x();geometry[1]=bounds.y();geometry[2]=bounds.width();geometry[3]=bounds.height();
    return result;
}

class LineworkScratchUndo final:public KisUndoStore {
public:
    const KUndo2Command *presentCommand()override{return nullptr;}
    void undoLastCommand()override{}
    void addCommand(KUndo2Command *command)override{delete command;}
    void beginMacro(const KUndo2MagicString&)override{}
    void endMacro()override{}
    void purgeRedoState()override{}
};

extern "C" __attribute__((visibility("default"))) void linework_prepare_scratch(void *nodeHandle){
    auto node=static_cast<Node*>(nodeHandle);
    auto image=(node->*member(NodeImage{}))();
    image->waitForDone();
    image->setUndoStore(new LineworkScratchUndo());
}

extern "C" __attribute__((visibility("default"))) void linework_clear_scratch(void *nodeHandle){
    auto node=static_cast<Node*>(nodeHandle);
    auto image=(node->*member(NodeImage{}))();
    image->waitForDone();
    auto target=(node->*member(NodeNode{}))();
    target->paintDevice()->clear();
}

extern "C" __attribute__((visibility("default"))) void *linework_stream_begin(void *nodeHandle,void *viewHandle,void *resourceHandle,
    const char *xml,const char *color,double size,double opacity,double flow,char *error,int capacity){
    auto fail=[&](const char *message)->void*{if(capacity>0){std::strncpy(error,message,capacity-1);error[capacity-1]=0;}return nullptr;};
    auto stream=std::make_unique<LineworkStream>();
    try{
        if(!QCoreApplication::instance()||QThread::currentThread()!=QCoreApplication::instance()->thread()||!nodeHandle||!viewHandle||!resourceHandle)
            return fail("Entrada de prévia inválida.");
        auto node=static_cast<Node*>(nodeHandle);
        auto view=static_cast<View*>(viewHandle);
        auto resource=static_cast<Resource*>(resourceHandle);
        stream->image=(node->*member(NodeImage{}))();
        auto image=stream->image;
        stream->target=(node->*member(NodeNode{}))();
        auto target=stream->target;
        auto sourceView=(view->*member(ViewView{}))();
        if(!image||!target||!target->paintDevice()||!sourceView||!sourceView->canvasBase())
            return fail("O destino nativo não é uma camada de pintura válida.");
        auto original=(resource->*member(ResourceResource{}))().dynamicCast<KisPaintOpPreset>();
        if(!original)return fail("O preset nativo não foi encontrado.");
        auto brush=original->clone().dynamicCast<KisPaintOpPreset>();
        if(xml&&*xml){
            QDomDocument doc;
            if(!doc.setContent(QString::fromUtf8(xml)))return fail("XML do preset inválido.");
            brush->fromXML(doc.documentElement(),KisGlobalResourcesInterface::instance());
        }
        if(!brush->settings())return fail("O motor deste preset não está disponível.");
        if(brush->settings()->eraserMode())
            return fail("Use a ferramenta Linework Erase para apagar linhas.");
        brush->settings()->setPaintOpSize(size);
        brush->settings()->setPaintOpOpacity(opacity);
        brush->settings()->setPaintOpFlow(flow);
        auto provider=sourceView->canvasBase()->resourceManager();
        // Build a private canvas resource provider: no changes to the user's
        // preset, foreground, size, flow, selection, mirror tools or canvas.
        auto &local=stream->resources;
        for(int k=0;k<KoCanvasResource::KritaStart;k++) {
            if(provider->hasResource(k))local.setResource(k,provider->resource(k));
        }
        for(int k=KoCanvasResource::KritaStart;k<=KoCanvasResource::BrushRotation;k++) {
            if(provider->hasResource(k))local.setResource(k,provider->resource(k));
        }
        local.setResource(KoCanvasResource::CurrentPaintOpPreset,QVariant::fromValue(brush));
        local.setResource(KoCanvasResource::CurrentPaintOpPresetCache,QVariant());
        local.setResource(KoCanvasResource::Size,size);
        local.setResource(KoCanvasResource::Opacity,opacity);
        local.setResource(KoCanvasResource::Flow,flow);
        local.setResource(KoCanvasResource::EraserMode,false);
        local.setResource(KoCanvasResource::GlobalAlphaLock,false);
        local.setResource(KoCanvasResource::MirrorHorizontal,false);
        local.setResource(KoCanvasResource::MirrorVertical,false);
        local.setResource(KoCanvasResource::EffectiveZoom,1.0);
        local.setResource(KoCanvasResource::EffectiveLodAvailability,false);
        const QString composite=brush->settings()->paintOpCompositeOp();
        local.setResource(KoCanvasResource::CurrentCompositeOp,composite);
        local.setResource(KoCanvasResource::CurrentEffectiveCompositeOp,composite);
        local.setForegroundColor(KoColor(QColor(QString::fromUtf8(color)),target->colorSpace()));
        KisResourcesSnapshotSP snapshot=new KisResourcesSnapshot(image,target,&local,0,{},brush);
        snapshot->setSelectionOverride(KisSelectionSP());
        snapshot->setMirroring(false,false);
        snapshot->setOpacity(opacity);
        snapshot->setStrokeStyle(KisPainter::StrokeStyleBrush);
        snapshot->setFillStyle(KisPainter::FillStyleNone);
        auto strategy=new LineworkPreviewStrategy(snapshot,stream.get());

        stream->id=image->startStroke(strategy);
        return stream.release();
    }catch(const std::exception &e){return fail(e.what());}
    catch(...){return fail("Falha ao iniciar a prévia nativa.");}
}

extern "C" __attribute__((visibility("default"))) void linework_stream_append(void *handle,const double *input,int count){
    auto stream=static_cast<LineworkStream*>(handle);
    for(int i=0;i<count;i++){
        const double *v=input+4*i;
        KisPaintInformation point(QPointF(v[0],v[1]),std::clamp(v[2],0.0,1.0),0,0,0,0,1,v[3],0.5);
        if(stream->hasLast)stream->image->addJob(stream->id,new FreehandStrokeStrategy::Data(0,stream->last,point));
        else stream->image->addJob(stream->id,new FreehandStrokeStrategy::Data(0,point));
        stream->last=point;stream->hasLast=true;
    }
}

extern "C" __attribute__((visibility("default"))) void *linework_stream_snapshot(void *handle,int *bounds){
    auto stream=static_cast<LineworkStream*>(handle);
    bool request=false;
    auto result=std::make_unique<LineworkPreviewImage>();
    {
        QMutexLocker lock(&stream->previewMutex);
        result->image=stream->preview;result->bounds=stream->previewBounds;
        if(!stream->pendingSnapshot){stream->pendingSnapshot=true;request=true;}
    }
    if(request){
        stream->image->addJob(stream->id,new KisAsynchronousStrokeUpdateHelper::UpdateData(true));
        stream->image->addJob(stream->id,new LineworkSnapshotJob());
    }
    if(result->image.isNull())return nullptr;
    bounds[0]=result->bounds.x();bounds[1]=result->bounds.y();bounds[2]=result->bounds.width();bounds[3]=result->bounds.height();
    return result.release();
}

extern "C" __attribute__((visibility("default"))) const void *linework_preview_pixels(void *handle){
    return static_cast<LineworkPreviewImage*>(handle)->image.constBits();
}

extern "C" __attribute__((visibility("default"))) void linework_preview_delete(void *handle){
    delete static_cast<LineworkPreviewImage*>(handle);
}

extern "C" __attribute__((visibility("default"))) void linework_stream_end(void *handle){
    if(!handle)return;
    auto stream=static_cast<LineworkStream*>(handle);
    stream->image->addJob(stream->id,new KisAsynchronousStrokeUpdateHelper::UpdateData(true));
    stream->image->endStroke(stream->id);
    stream->image->waitForDone();
    delete stream;
}
