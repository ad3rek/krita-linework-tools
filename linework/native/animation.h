// SPDX-License-Identifier: GPL-3.0-or-later
// Editable geometry travels with the keyframe through Krita's virtual duplicate().
#pragma once
#include <kis_paint_layer.h>
#include <kis_raster_keyframe_channel.h>
#include <kis_paint_device_frames_interface.h>
#include <kis_image_animation_interface.h>
#include <KisCanvasAnimationState.h>
#include <kis_post_execution_undo_adapter.h>
#include <kis_annotation.h>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QCryptographicHash>
#include <KoColorProfile.h>
#include <kundo2magicstring.h>
#include <climits>

class LineworkRasterFrame final : public KisRasterKeyframe {
public:
    KisPaintDeviceWSP owner;
    QByteArray payload;
    quint64 revision=1;
    LineworkRasterFrame(KisPaintDeviceSP device, const QByteArray &data)
        : KisRasterKeyframe(device), owner(device), payload(data) {}
    KisKeyframeSP duplicate(KisKeyframeChannel *targetChannel = nullptr) override {
        KisPaintDeviceSP source = owner;
        auto raster = dynamic_cast<KisRasterKeyframeChannel*>(targetChannel);
        KisPaintDeviceSP target = raster ? KisPaintDeviceSP(raster->paintDevice()) : source;
        if (!source || !target || (targetChannel && !raster)) return {};
        // The base constructor allocates a NEW, owned physical frame. Never
        // wrap the source ID: its destructor would free another frame's data.
        auto copy = toQShared(new LineworkRasterFrame(target, payload));
        target->framesInterface()->uploadFrame(frameID(), copy->frameID(), source);
        copy->setColorLabel(colorLabel());
        copy->revision=revision;
        return copy;
    }
};

struct LineworkAnimationNode {
    KisNodeSP node;
    KisImageSP image;
    KisPaintDeviceSP device;
    KisRasterKeyframeChannel *channel = nullptr;
    explicit LineworkAnimationNode(Node *wrapper, bool enable = false) {
        if (!wrapper || !QCoreApplication::instance() ||
            QThread::currentThread()!=QCoreApplication::instance()->thread())
            throw std::runtime_error("Animation requires the Krita GUI thread.");
        node=(wrapper->*member(NodeNode{}))();
        auto layer=dynamic_cast<KisPaintLayer*>(node.data());
        if (!layer || !node->image()) throw std::runtime_error("An animated paint layer is required.");
        image=node->image(); device=layer->paintDevice();
        channel=dynamic_cast<KisRasterKeyframeChannel*>(node->getKeyframeChannel(KisKeyframeChannel::Raster.id()));
        if (enable && !channel)
            channel=dynamic_cast<KisRasterKeyframeChannel*>(node->getKeyframeChannel(KisKeyframeChannel::Raster.id(),true));
    }
};

struct LineworkAnimationLock {
    KisImageSP image;
    QScopedValueRollback<int> mutation;
    static KisImageSP ready(KisImageSP image,bool requestEnd) {
        if (requestEnd && !previewMutationDepth && !image->isIdle(true)) image->requestStrokeEnd();
        return image;
    }
    explicit LineworkAnimationLock(KisImageSP img,bool requestEnd=true):image(ready(img,requestEnd)),mutation(previewMutationDepth,previewMutationDepth+1) {
        KisBusyWaitBroker::instance()->notifyWaitOnImageStarted(image.data());
        image->waitForDone();
        image->barrierLock();
    }
    ~LineworkAnimationLock() {
        image->unlock();
        KisBusyWaitBroker::instance()->notifyWaitOnImageEnded(image.data());
    }
};

extern "C" LINEWORK_EXPORT int linework_animation_playback(View *wrapper,int pause) {
    if (!wrapper) return 0;
    auto view=(wrapper->*member(ViewView{}))();
    auto canvas=view ? dynamic_cast<KisCanvas2*>(view->canvasBase()) : nullptr;
    if (!canvas || !canvas->animationState()) return 0;
    const bool playing=canvas->animationState()->playbackState()==PLAYING;
    if (playing && pause) canvas->animationState()->setPlaybackState(PAUSED);
    return playing;
}

static KisPaintDeviceSP lineworkFrameDevice(const KisRasterKeyframeSP &frame, const KisPaintDeviceSP &owner) {
    KisPaintDeviceSP snapshot = new KisPaintDevice(owner->colorSpace());
    frame->writeFrameToDevice(snapshot);
    return snapshot;
}

static QByteArray lineworkDeviceFingerprint(const KisPaintDeviceSP &device) {
    const QRect rect=device->exactBounds();
    QCryptographicHash hash(QCryptographicHash::Sha256);
    const auto cs=device->colorSpace();
    hash.addData(cs->id().toUtf8());
    if (cs->profile()) hash.addData(cs->profile()->uniqueId());
    const KoColor defaultPixel=device->defaultPixel();
    hash.addData(reinterpret_cast<const char*>(defaultPixel.data()),cs->pixelSize());
    hash.addData((QString("|%1,%2,%3,%4|").arg(rect.x()).arg(rect.y()).arg(rect.width()).arg(rect.height())).toUtf8());
    // Hash in bounded strips; do not allocate the entire frame to verify it.
    if (!rect.isEmpty()) {
        const qint64 rowBytes=qint64(rect.width())*cs->pixelSize();
        if (rowBytes>INT_MAX/64) throw std::runtime_error("Frame is too wide to verify safely.");
        QByteArray strip(int(rowBytes*64),Qt::Uninitialized);
        for (int y=rect.y();y<rect.y()+rect.height();y+=64) {
            const int rows=std::min(64,rect.y()+rect.height()-y);
            device->readBytes(reinterpret_cast<quint8*>(strip.data()),rect.x(),y,rect.width(),rows);
            hash.addData(strip.constData(),int(rowBytes*rows));
        }
    }
    return hash.result().toHex();
}

static QByteArray lineworkFrameFingerprint(const KisRasterKeyframeSP &frame, const KisPaintDeviceSP &owner) {
    return lineworkDeviceFingerprint(lineworkFrameDevice(frame,owner));
}

static QJsonObject lineworkPayload(const char *json) {
    QJsonParseError error;
    auto doc=QJsonDocument::fromJson(json ? QByteArray(json) : QByteArray(),&error);
    if (error.error!=QJsonParseError::NoError || !doc.isObject())
        throw std::runtime_error("Invalid Linework frame metadata.");
    return doc.object();
}

static const char *lineworkAnimationResult(const QJsonObject &object) {
    static thread_local QByteArray result;
    result=QJsonDocument(object).toJson(QJsonDocument::Compact);
    return result.constData();
}
static const char *lineworkAnimationError(const std::exception &error) {
    return lineworkAnimationResult({{"error",QString::fromUtf8(error.what())}});
}

// Save/autosave can clone an idle image without sending stroke-end or pumping
// the event loop. Snapshot live keyframes at the native annotation clone point,
// while Krita holds the source image lock. Never call Python during cloning.
class LineworkAnimationAnnotation final : public KisAnnotation {
    KisImageWSP source;
    QByteArray snapshot() const {
        KisImageSP image=source;
        if (!image) return m_annotation;
        auto data=QJsonDocument::fromJson(m_annotation).object();
        auto layers=data.value("layers").toObject();
        std::function<void(KisNodeSP)> visit=[&](KisNodeSP node) {
            if (auto paint=dynamic_cast<KisPaintLayer*>(node.data())) {
                auto channel=dynamic_cast<KisRasterKeyframeChannel*>(node->getKeyframeChannel(KisKeyframeChannel::Raster.id()));
                if (channel) {
                    const QString id=node->uuid().toString();
                    auto previous=layers.value(id).toObject();
                    auto geometry=previous.value("geometry");
                    auto oldFrames=previous.value("frames").toObject();
                    QJsonObject frames;
                    bool owned=previous.value("kind").toString()=="animated";
                    const auto times=channel->allKeyframeTimes();
                    for (int time:times) {
                        auto frame=channel->keyframeAt<KisRasterKeyframe>(time);
                        if (auto editable=dynamic_cast<LineworkRasterFrame*>(frame.data())) {
                            auto payload=QJsonDocument::fromJson(editable->payload).object();
                            frames[QString::number(time)]=payload;
                            geometry=payload.value("geometry"); owned=true;
                        }
                    }
                    if (owned) {
                        for (int time:times) {
                            const QString key=QString::number(time);
                            if (frames.contains(key)) continue;
                            auto pixels=lineworkFrameDevice(channel->keyframeAt<KisRasterKeyframe>(time),paint->paintDevice());
                            if (pixels->exactBounds().isEmpty() && !pixels->defaultPixel().opacityU8())
                                frames[key]=QJsonObject{{"geometry",geometry},{"strokes",QJsonArray()},
                                    {"appearances",QJsonObject()},{"fingerprint",QString::fromLatin1(lineworkDeviceFingerprint(pixels))}};
                            else if (oldFrames.contains(key)) frames[key]=oldFrames.value(key);
                        }
                        layers[id]=QJsonObject{{"kind","animated"},{"geometry",geometry},{"frames",frames}};
                    }
                }
            }
            for (auto child=node->firstChild();child;child=child->nextSibling()) visit(child);
        };
        visit(image->root());
        data["layers"]=layers; data["version"]=7;
        return QJsonDocument(data).toJson(QJsonDocument::Compact);
    }
public:
    LineworkAnimationAnnotation(KisImageSP image,KisAnnotationSP original)
        :KisAnnotation(original->type(),original->description(),original->annotation()),source(image) {}
    KisAnnotation *clone() const override {
        return new KisAnnotation(m_type,m_description,snapshot());
    }
};

extern "C" LINEWORK_EXPORT const char *linework_animation_annotation(Node *wrapper,int) {
    try {
        LineworkAnimationNode state(wrapper);
        auto annotation=state.image->annotation(QStringLiteral("org.felipe.linework.v1"));
        if (annotation && !dynamic_cast<LineworkAnimationAnnotation*>(annotation.data()))
            state.image->addAnnotation(new LineworkAnimationAnnotation(state.image,annotation));
        return lineworkAnimationResult({{"ok",true}});
    } catch (const std::exception &error) { return lineworkAnimationError(error); }
}

// Keep unchanged raster tiles shared with previous snapshots in native Undo.
static KisPaintDeviceSP lineworkFrameDelta(KisPaintDeviceSP before,KisPaintDeviceSP rendered) {
    const int size=before->colorSpace()->pixelSize();
    if (std::memcmp(before->defaultPixel().data(),rendered->defaultPixel().data(),size)) return rendered;
    KisPaintDeviceSP after=new KisPaintDevice(*before.data(),KritaUtils::CopySnapshot);
    const QRect bounds=before->exactBounds().united(rendered->exactBounds());
    if (bounds.isEmpty()) return after;
    QByteArray oldPixels(64*64*size,Qt::Uninitialized),newPixels(64*64*size,Qt::Uninitialized);
    const int left=int(std::floor(bounds.left()/64.0))*64;
    const int top=int(std::floor(bounds.top()/64.0))*64;
    for (int y=top;y<=bounds.bottom();y+=64) for (int x=left;x<=bounds.right();x+=64) {
        before->readBytes(reinterpret_cast<quint8*>(oldPixels.data()),x,y,64,64);
        rendered->readBytes(reinterpret_cast<quint8*>(newPixels.data()),x,y,64,64);
        if (oldPixels!=newPixels) after->writeBytes(reinterpret_cast<const quint8*>(newPixels.constData()),x,y,64,64);
    }
    return after;
}

using AnimationCallback=void(*)(const char*,int);
static AnimationCallback animationCallback=nullptr;
extern "C" LINEWORK_EXPORT void linework_animation_callback(AnimationCallback callback) { animationCallback=callback; }

class LineworkFrameEditCommand final : public KUndo2Command {
    KisNodeSP node,backup;
    KisPaintDeviceSP owner,before,after;
    QSharedPointer<LineworkRasterFrame> frame;
    QByteArray oldPayload,newPayload;
    int time;
    void apply(bool forward) {
        owner->framesInterface()->uploadFrame(frame->frameID(),forward ? after : before);
        frame->payload=forward ? newPayload : oldPayload;
        ++frame->revision;
        if (backup) backup->setVisible(!forward);
        node->setDirty();
        if (auto image=node->image()) {
            image->animationInterface()->invalidateFrame(time,node);
            QPointer<KisImage> guard=image.data();
            const int target=time;
            QMetaObject::invokeMethod(image.data(),[guard,target]{
                if (!guard) return;
                guard->animationInterface()->switchCurrentTimeAsync(target);
                if (animationCallback) {
                    const QByteArray id=QByteArray::number(reinterpret_cast<quintptr>(guard.data()),16);
                    animationCallback(id.constData(),0);
                }
            },Qt::QueuedConnection);
        }
    }
public:
    LineworkFrameEditCommand(KisNodeSP node,KisNodeSP backup,KisPaintDeviceSP owner,
        QSharedPointer<LineworkRasterFrame> frame,int time,KisPaintDeviceSP before,
        KisPaintDeviceSP after,QByteArray oldPayload,QByteArray newPayload)
        :node(node),backup(backup),owner(owner),before(before),after(after),frame(frame),
         oldPayload(oldPayload),newPayload(newPayload),time(time) {
        setText(kundo2_noi18n(QStringLiteral("Edit Linework frame")));
    }
    void redo() override { KUndo2Command::redo(); apply(true); }
    void undo() override { apply(false); KUndo2Command::undo(); }
};

static void lineworkAnimationWatch(LineworkAnimationNode &state) {
    if (!state.image->property("_linework_animation_watch").toBool()) {
        state.image->setProperty("_linework_animation_watch",true);
        auto image=state.image.data();
        QObject::connect(image,&KisImage::sigStrokeEndRequested,image,[image]{
            if (animationCallback && !previewMutationDepth && QThread::currentThread()==image->thread()) {
                const QByteArray id=QByteArray::number(reinterpret_cast<quintptr>(image),16);
                animationCallback(id.constData(),1);
            }
        });
        const QByteArray owner=QByteArray::number(reinterpret_cast<quintptr>(image),16);
        QObject::connect(image,&QObject::destroyed,QCoreApplication::instance(),[owner]{
            if (animationCallback) animationCallback(owner.constData(),2);
        });
    }
    if (state.channel && !state.channel->property("_linework_animation_watch").toBool()) {
        state.channel->setProperty("_linework_animation_watch",true);
        QPointer<KisImage> image=state.image.data();
        QObject::connect(state.channel,&KisKeyframeChannel::sigAnyKeyframeChange,state.image.data(),[image]{
            if (image && animationCallback && !previewMutationDepth) {
                const QByteArray id=QByteArray::number(reinterpret_cast<quintptr>(image.data()),16);
                animationCallback(id.constData(),0);
            }
        },Qt::QueuedConnection);
    }
}

extern "C" LINEWORK_EXPORT const char *linework_animation_info(Node *wrapper,int payloads) {
    try {
        LineworkAnimationNode state(wrapper);
        const QString owner=QString::number(reinterpret_cast<quintptr>(state.image.data()),16);
        const QString node=QString::number(reinterpret_cast<quintptr>(state.node.data()),16);
        if (!state.image->isIdle(payloads!=0)) return lineworkAnimationResult({{"busy",true},{"owner",owner},{"node",node}});
        if (!state.channel) return lineworkAnimationResult({{"animated",false}});
        lineworkAnimationWatch(state);
        QJsonArray frames;
        QList<int> times=state.channel->allKeyframeTimes().values(); std::sort(times.begin(),times.end());
        for (int time:times) {
            auto frame=state.channel->keyframeAt<KisRasterKeyframe>(time);
            auto editable=dynamic_cast<LineworkRasterFrame*>(frame.data());
            QJsonObject entry{{"time",time},{"id",frame->frameID()},{"editable",bool(editable)}};
            if (editable) entry["revision"]=double(editable->revision);
            if (payloads && editable) entry["payload"]=QJsonDocument::fromJson(editable->payload).object();
            if (payloads && !editable) {
                auto pixels=lineworkFrameDevice(frame,state.device);
                if (pixels->exactBounds().isEmpty() && !pixels->defaultPixel().opacityU8()) {
                    entry["empty"]=true;
                    entry["fingerprint"]=QString::fromLatin1(lineworkDeviceFingerprint(pixels));
                }
            }
            frames.append(entry);
        }
        const int uiTime=state.image->animationInterface()->currentUITime();
        auto active=state.channel->activeKeyframeAt<KisRasterKeyframe>(uiTime);
        return lineworkAnimationResult({{"animated",true},{"owner",owner},{"node",node},{"time",uiTime},
            {"active_time",state.channel->activeKeyframeTime(uiTime)},
            {"active_id",active ? active->frameID() : -1},{"frames",frames}});
    } catch (const std::exception &error) { return lineworkAnimationError(error); }
}

extern "C" LINEWORK_EXPORT const char *linework_animation_restore(Node *wrapper,int time,const char *json) {
    try {
        LineworkAnimationNode state(wrapper,true);
        if (!state.channel) throw std::runtime_error("The layer has no raster animation channel.");
        LineworkAnimationLock lock(state.image);
        auto old=state.channel->keyframeAt<KisRasterKeyframe>(time);
        if (!old) throw std::runtime_error("The keyframe no longer exists.");
        auto payload=lineworkPayload(json);
        const auto fingerprint=lineworkFrameFingerprint(old,state.device);
        if (payload.value("fingerprint").toString().toLatin1()!=fingerprint)
            throw std::runtime_error("Raster pixels were changed outside Linework; their content was preserved.");
        if (!dynamic_cast<LineworkRasterFrame*>(old.data())) {
            auto frame=toQShared(new LineworkRasterFrame(state.device,QJsonDocument(payload).toJson(QJsonDocument::Compact)));
            state.device->framesInterface()->uploadFrame(old->frameID(),frame->frameID(),state.device);
            frame->setColorLabel(old->colorLabel());
            const auto aliases=state.channel->timesForFrameID(old->frameID());
            for (int alias:aliases) state.channel->insertKeyframe(alias,frame);
        }
        lineworkAnimationWatch(state);
        return lineworkAnimationResult({{"ok",true}});
    } catch (const std::exception &error) { return lineworkAnimationError(error); }
}

extern "C" LINEWORK_EXPORT const char *linework_animation_empty(Node *wrapper,int time,const char *json) {
    try {
        LineworkAnimationNode state(wrapper,true);
        LineworkAnimationLock lock(state.image);
        auto frame=state.channel->keyframeAt<KisRasterKeyframe>(time);
        if (!frame) throw std::runtime_error("The keyframe no longer exists.");
        auto snapshot=lineworkFrameDevice(frame,state.device);
        if (!snapshot->exactBounds().isEmpty() || snapshot->defaultPixel().opacityU8())
            throw std::runtime_error("This raster frame has no editable Linework data.");
        auto payload=lineworkPayload(json);
        payload["fingerprint"]=QString::fromLatin1(lineworkFrameFingerprint(frame,state.device));
        return lineworkAnimationResult(payload);
    } catch (const std::exception &error) { return lineworkAnimationError(error); }
}

extern "C" LINEWORK_EXPORT const char *linework_animation_commit(Node *wrapper,int time,int frameId,
        const char *json,const char *png,int length,Node *backupWrapper) {
    try {
        auto payload=lineworkPayload(json);
        QImage image=QImage::fromData(reinterpret_cast<const uchar*>(png),length,"PNG");
        if (image.isNull()) throw std::runtime_error("Invalid rendered Linework frame.");
        LineworkAnimationNode state(wrapper);
        LineworkAnimationLock lock(state.image);
        auto source=state.channel ? state.channel->keyframeAt<KisRasterKeyframe>(time) : KisRasterKeyframeSP();
        if (!source || source->frameID()!=frameId) throw std::runtime_error("The edited keyframe was moved or replaced.");
        auto frame=source.dynamicCast<LineworkRasterFrame>();
        auto before=lineworkFrameDevice(source,state.device);
        QJsonObject previous;
        if (frame) previous=QJsonDocument::fromJson(frame->payload).object();
        else {
            if (!before->exactBounds().isEmpty() || before->defaultPixel().opacityU8())
                throw std::runtime_error("This raster frame has no editable Linework data.");
            previous={{"geometry",payload.value("geometry")},{"strokes",QJsonArray()},
                {"appearances",QJsonObject()},{"fingerprint",QString::fromLatin1(lineworkDeviceFingerprint(before))}};
            frame=toQShared(new LineworkRasterFrame(state.device,QJsonDocument(previous).toJson(QJsonDocument::Compact)));
            frame->setColorLabel(source->colorLabel());
        }
        if (previous.value("fingerprint").toString().toLatin1()!=lineworkDeviceFingerprint(before))
            throw std::runtime_error("Raster pixels were changed outside Linework; their content was preserved.");
        KisPaintDeviceSP rendered=new KisPaintDevice(state.device->colorSpace());
        rendered->convertFromQImage(image,nullptr);
        auto after=lineworkFrameDelta(before,rendered);
        const QByteArray oldPayload=frame->payload;
        payload["fingerprint"]=QString::fromLatin1(lineworkDeviceFingerprint(after));
        const QByteArray newPayload=QJsonDocument(payload).toJson(QJsonDocument::Compact);
        KisNodeSP backup=backupWrapper ? (backupWrapper->*member(NodeNode{}))() : KisNodeSP();
        auto command=toQShared(new LineworkFrameEditCommand(state.node,backup,state.device,frame,time,
            before,after,oldPayload,newPayload));
        if (frame.data()!=source.data()) {
            // Adopt a native blank only as part of its first edit's Undo. The
            // original add-frame command retains the base keyframe pointer;
            // replacing it eagerly would break add/edit Undo -> Redo.
            const auto aliases=state.channel->timesForFrameID(source->frameID());
            for (int alias:aliases) state.channel->insertKeyframe(alias,frame,command.data());
            // Channel commands skip their first redo because insertion above
            // already applied it. The post-execution adapter also skips an
            // initial redo; consume the children's skip before storing them.
            command->KUndo2Command::redo();
        }
        state.device->framesInterface()->uploadFrame(frame->frameID(),after);
        frame->payload=newPayload;
        ++frame->revision;
        if (backup) backup->setVisible(false);
        state.image->postExecutionUndoAdapter()->addCommand(command);
        state.node->setDirty();
        state.image->animationInterface()->invalidateFrame(time,state.node);
        return lineworkAnimationResult({{"frame",QJsonObject{{"time",time},{"id",frame->frameID()},{"revision",double(frame->revision)}}}});
    } catch (const std::exception &error) { return lineworkAnimationError(error); }
}

extern "C" LINEWORK_EXPORT const char *linework_animation_frame_action(Node *wrapper,int action,int source,int target) {
    try {
        LineworkAnimationNode state(wrapper,true);
        LineworkAnimationLock lock(state.image);
        if (!state.channel) throw std::runtime_error("The layer has no raster animation channel.");
        if (action!=4 && (target<0 || state.channel->keyframeAt(target)))
            throw std::runtime_error("Choose a frame without an existing keyframe.");
        auto command=toQShared(new KUndo2Command());
        command->setText(kundo2_noi18n(QStringLiteral("Linework animation frame")));
        if (action==1) state.channel->addKeyframe(target,command.data());
        else {
            if (!state.channel->keyframeAt(source)) throw std::runtime_error("The source keyframe no longer exists.");
            if (action==2) state.channel->copyKeyframe(source,target,command.data());
            else if (action==3) state.channel->moveKeyframe(source,target,command.data());
            else if (action==4) state.channel->removeKeyframe(source,command.data());
            else if (action==5) state.channel->cloneKeyframe(source,target,command.data());
            else throw std::runtime_error("Unknown keyframe operation.");
        }
        command->redo(); // Consume keyframe commands' initial skip, without changing the channel.
        state.image->postExecutionUndoAdapter()->addCommand(command);
        state.node->setDirty();
        lineworkAnimationWatch(state);
        return lineworkAnimationResult({{"ok",true}});
    } catch (const std::exception &error) { return lineworkAnimationError(error); }
}

struct LineworkRasterPreview {
    LineworkAnimationNode state;
    KisRasterKeyframeSP frame;
    KisPaintDeviceSP original;
    int time;
    LineworkRasterPreview(Node *node,int t,int id):state(node),time(t) {
        LineworkAnimationLock lock(state.image,false);
        frame=state.channel ? state.channel->keyframeAt<KisRasterKeyframe>(time) : KisRasterKeyframeSP();
        if (!frame || frame->frameID()!=id) throw std::runtime_error("The edited keyframe no longer exists.");
        original=lineworkFrameDevice(frame,state.device);
    }
};
extern "C" LINEWORK_EXPORT void *linework_animation_preview_begin(Node *wrapper,int time,int id) {
    try { return new LineworkRasterPreview(wrapper,time,id); } catch (...) { return nullptr; }
}
extern "C" LINEWORK_EXPORT int linework_animation_preview_apply(void *handle,const char *png,int length) {
    auto preview=static_cast<LineworkRasterPreview*>(handle);
    if (!preview) return 0;
    QImage image=QImage::fromData(reinterpret_cast<const uchar*>(png),length,"PNG");
    if (image.isNull()) return 0;
    LineworkAnimationLock lock(preview->state.image,false);
    KisPaintDeviceSP device=new KisPaintDevice(preview->state.device->colorSpace());
    device->convertFromQImage(image,nullptr);
    preview->state.device->framesInterface()->uploadFrame(preview->frame->frameID(),device);
    preview->state.node->setDirty();
    preview->state.image->animationInterface()->invalidateFrame(preview->time,preview->state.node);
    return 1;
}
extern "C" LINEWORK_EXPORT void linework_animation_preview_end(void *handle) {
    std::unique_ptr<LineworkRasterPreview> preview(static_cast<LineworkRasterPreview*>(handle));
    if (!preview) return;
    LineworkAnimationLock lock(preview->state.image,false);
    preview->state.device->framesInterface()->uploadFrame(preview->frame->frameID(),preview->original);
    preview->state.node->setDirty();
    preview->state.image->animationInterface()->invalidateFrame(preview->time,preview->state.node);
}
