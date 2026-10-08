# Krita Linework Tools

Editable linework **inside Krita**, inspired by **Paint Tool SAI** linework layers, with automatic raster conversion using a port of the **same OpenToonz Centerline algorithm**.

Draw directly on the canvas with Krita brush presets, then edit the centerline, Bézier handles, thickness and brush. Six native tools live in Krita's toolbox; their controls appear in **Tool Options**, and Linework layers appear in **Layers** with a dedicated icon.

Developed with **OpenAI Codex**. **Ghidra 11.0.3 was used for static reverse engineering of Paint Tool SAI 2** to investigate its linework features and guide the reproduction of their behavior. The [implementation and scope](#codex-ghidra-and-reverse-engineering) are documented below.

> **Version 0.1 · experimental desktop build for Krita 5.2.14.** The native bridge uses Krita's internal ABI. Each platform package needs the matching application and compatible libraries; other Krita builds require recompilation and validation. Android remains outside the current release.

![Pepper lineart converted into a Linework layer in the real Krita interface](docs/images/pepper-vectorized.png)

*Real Krita screenshot: an editable Linework layer, native tools and the preserved raster source. Artwork: David Revoy, “Characters lineart”, Pepper&Carrot, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); cropped, resized, converted to grayscale and adjusted with levels. [Source and modifications](docs/ARTWORK.md). The screenshots show the plugin's Portuguese controls; this article and the installation documentation are in English.*

## Download and install

Download a platform package from [version 0.1](https://github.com/ad3rek/krita-linework-tools/releases/tag/v0.1). Save your work and close Krita before installing.

The color-editing fix documented below is available in the current `main` source. To install it, download the [main source ZIP](https://github.com/ad3rek/krita-linework-tools/archive/refs/heads/main.zip), extract it and use `install.py` as described below. The existing v0.1 release archives predate this fix.

| Package | Required application | Validation environment |
| --- | --- | --- |
| [Linux x86_64](https://github.com/ad3rek/krita-linework-tools/releases/download/v0.1/Krita-Linework-Tools-0.1-linux-x86_64.zip) | Krita 5.2.14, compatible Qt 5.15.17 libraries | KDE Neon, Python 3.12 |
| [Windows x86_64](https://github.com/ad3rek/krita-linework-tools/releases/download/v0.1/Krita-Linework-Tools-0.1-windows-x86_64.zip) | Official Krita 5.2.14 x64, Qt 5.15.7 | Experimental preview; selection/smoothing tested under Wine 11.0 |

On Linux, extract the archive, open a terminal in its folder and run:

```sh
python3 install.py --enable
```

On Windows, use the **Windows x86_64** archive with the official Krita 5.2.14 x64 build:

1. Extract the archive and open Krita's resource folder through **Settings → Manage Resources → Open Resource Folder**, then close Krita.
2. Copy `linework/`, `linework.desktop` and `linework.action` from the extracted package into the resource folder's `pykrita/` directory. Back up an existing Linework installation first.
3. Reopen Krita, enable **Krita Linework Tools** in **Settings → Configure Krita → Python Plugin Manager**, and restart once more.

The usual resource directory is `%APPDATA%\krita`, but the folder shown by Krita is authoritative. If Python 3 is installed separately, `py -3 install.py --enable` is an alternative with automatic backups. Windows configuration is read from `%LOCALAPPDATA%\kritarc`; a custom `ResourceDirectory` is honored. No compiler or Ghidra installation is needed to use a release package.

Restart Krita and select **Linework Brush**. The installer preserves the previous plugin and any changed configuration in `linework-backups` inside Krita's resource folder. `--resources /path/to/resources` selects a custom resource folder. Manual activation is available in **Settings → Configure Krita → Python Plugin Manager**. See the [manual](linework/Manual.html), [technical reference](docs/REFERENCE.txt) and [native build instructions](linework/native/BUILD.txt).

## Drawing and editing in Krita

Choose **Linework Brush**, pick a preset in Krita's brush panel and draw on the canvas. The current preset, color, size, opacity and flow are captured when a stroke starts. Switching presets affects new strokes; an existing stroke keeps its own preset until you explicitly replace it.

| Tool | What it does |
| --- | --- |
| Linework Brush | Draw with Krita's native paint engines and smoothing. |
| Linework Curve / Line | Place points by clicking; Enter or right click finishes. |
| Linework Edit | Move points or groups, edit handles, insert points and delete the selection. |
| Linework Thickness | Edit the nominal diameter in pixels, with guides and multiple point selection. |
| Linework Erase | Remove an entire stroke. |

The toolbox icons follow Krita's theme and the group has a separator. Controls use the native Tool Options docker. The first stroke creates a Linework layer when the active layer is not already Linework; **Tools → Scripts → New Linework Layer** starts another one.

Krita presets produce raster textures. The editable geometry and the rendered appearance are both embedded in the vector layer and saved in `.kra`. The saved appearance remains visible without the plugin; rerendering requires the original preset and its resources.

In **Linework Edit** or **Linework Thickness**, changing Krita's foreground color recolors the selected strokes, including native brush textures and smooth lines. Color picker changes are collected before rendering and committed as one undo step. Selecting a stroke alone keeps its saved color. **Tool Options → Brush → Apply current color** applies the foreground to **Selected strokes** or **All strokes in the layer**, using the scope above the button. Geometry, pressure, thickness and brush settings are preserved. Presets that use their own multicolor tip or color dynamics can still produce colors beyond the foreground, as in native Krita painting.

![Two red strokes and a selected green stroke recolored using Krita's foreground](docs/images/color-editing.png)

*Synthetic native brush and smooth line test: foreground recoloring, selected/whole-layer scope, grouped undo/redo, rendered pixels, locked layers and `.kra` round trips passed in Krita 5.2.14 on Linux. [Color regression report](docs/validation/color.json).*

## Convert a lineart into editable strokes

The demonstration uses **Pepper**, drawn by **David Revoy** for **Pepper&Carrot**, under **CC BY 4.0**. The fixture is a crop of the original, resized to **833 × 1280**, converted to **8-bit grayscale**, then treated with input levels **128–220**, gamma **1.0**, output **0–255**. This darkens the lines and clears the light shading while retaining edge gradation. The distributed PNG already contains this treatment. [Exact preparation and hashes](docs/validation/artwork-source.json).

Select the active bitmap layer and open **Tools → Scripts → Vectorize Layer to Linework**. Adjust the threshold, despeckling, accuracy and maximum width, then inspect the zoomable preview. Confirming creates a new Linework layer; the source remains intact and can be hidden.

![Vectorization preview comparing the treated grayscale bitmap and detected centerlines](docs/images/pepper-vectorize-preview.png)

*Source on the left, centerline result on the right. David Revoy's artwork, CC BY 4.0, with the preparation described above.*

With threshold **170**, despeckling below **12 px²**, accuracy **9.5** and maximum width **200 px**, the test produced **743 strokes and 2,206 anchors**. The preview reported **0.25 s** for extraction and preparation, excluding final layer creation and native brush rendering. The source pixels remained unchanged after conversion, editing and saving.

The vectorizer extracts centerlines and radii. It does not reconstruct filled regions or gradients. Threshold and image resolution affect the details and small segments detected; sketchy lineart may need cleanup after conversion.

## Points, thickness and changing brushes

In **Linework Edit**, drag a point or a selected group. The active point shows square handles; Alt-drag moves one handle without aligning the opposite one. Double click a stroke or Alt-click to insert a point through subdivision without changing the curve. Delete removes the selection.

Shift-click adds or removes items, dragging on empty canvas makes a point selection rectangle, and Ctrl+A selects all. A selection made with Krita's native **Select Shapes** is inherited by Edit and Thickness. This lets you adjust points across several strokes together.

![Native Pixel Art preset and thickness guides on the converted Pepper strokes](docs/images/pepper-native-thickness.png)

*All 743 strokes were changed to the native `u) Pixel Art` preset and all diameters set to 4 px. Three selected points show width guides and a canvas indicator. David Revoy's artwork, CC BY 4.0, adapted with Linework.*

Thickness means the **nominal brush diameter in pixels**. Recorded stylus pressure remains independent and available to opacity and other sensors. The first width edit of a native stroke converts its pressure-to-size contribution using Krita's own curve. Direct diameter control supports smooth lines and Pixel/Color Smudge presets; tip shape and texture can make the painted area differ from the nominal diameter.

To replace brushes on existing vectors, choose a preset in Krita, select **Selected strokes** or **All strokes in the layer**, and click **Change brush** in Tool Options. Preparation is incremental, with progress and cancellation; the whole operation is one Linework undo step. The installed preset is not modified.

During point, handle or thickness dragging, affected strokes' original appearances are hidden from rendering and held in cache. The preview takes their place. Esc restores the confirmed data and appearance; release rerenders and commits the change.

![Multiple point selection and diameter editing on synthetic curves](docs/images/multi-point-thickness.png)

*Synthetic test curves: selection across strokes, independent diameters and controls in native Tool Options.*

Moving, scaling, rotating or mirroring with native shape tools updates the points and handles and rerenders the preset. Uniform scaling scales thickness; nonuniform scaling uses the geometric mean of the two scale factors. Resizing the whole document does not currently update the stored centerline metadata.

## Native smoothing with fewer points

Linework Brush uses Krita's **KisToolFreehandHelper** and **KisSmoothingOptions**: None, Basic, Weighted and Stabilizer. Distance, finishing, pressure smoothing and delay appear in Tool Options and share Krita's smoothing configuration.

![Native smoothing options in Linework Brush](docs/images/smoothing-options.png)

After a new Brush stroke finishes, its centerline is compacted into fewer Bézier anchors. This happens after native smoothing and preserves corners and pressure/thickness variation within the configured tolerances. Existing strokes, click-created curves and imported OpenToonz output are not automatically compacted.

![Reduced anchors and Bézier handles in saved and reopened test strokes](docs/images/reduced-points.png)

*Saved development reduction example, reopened in the editor.*

A fresh automated canvas run with Qt tablet events and 100 moves per stroke produced:

| Smoothing | Anchors before → after | Maximum sampled position error | Compaction time |
| --- | --- | --- | --- |
| None | 101 → 11 | 0.120 px | 22.1 ms |
| Basic | 101 → 5 | 0.121 px | 75.9 ms |
| Weighted | 101 → 12 | 0.196 px | 54.1 ms |
| Stabilizer | 1,233 → 6 | 0.278 px | 167.7 ms |

These values describe one drawing and run. Stabilizer timing changes its sample count; different curves need different numbers of anchors. The earlier saved `smoothing-and-points.kra` example produced 10/6/12/5 anchors. Both reports are included. Automated tests used Qt tablet events rather than a physical stylus.

## Functional tests

**56 CPU tests passed** in the published checkout. They cover the model, selection, insertion, serialization, fingerprints, affine transforms, compaction and vectorization. A differential test compiles the original OpenToonz sources and checks **exact equality of quadratic position and radius controls in 16 synthetic fixtures**.

| Operation in Krita | Verified behavior |
| --- | --- |
| Treated grayscale bitmap → Linework | New native layer, 743 strokes / 2,206 anchors, unchanged source pixels. |
| Preview zoom | Zoom and fit use cached data. |
| Change every stroke's brush | Pixel Art applied to all strokes; geometry preserved; undo/redo restores the operation. |
| Change every point's diameter | All points reach 4 px; original pressure and handles preserved; one undo step. |
| Edit an imported point | Stroke rerendered; undo/redo restores its data. |
| Save and reopen | Editable data match and the original raster bytes remain unchanged. |
| Another plugin querying shapes | Observer timer runs during preparation; no reads occur during protected scene mutation. |
| Group selection and editing | Select Shapes inheritance, Shift, rectangle, dragging, indicators, deletion and history. |
| Brush and smoothing | Four native filters, pressure, handles, reduction, Esc, delay, tool switching and saving during drawing. |

On the grayscale Pepper fixture, changing the whole layer's preset took **36.1 s** and setting all diameters took **81.8 s**, including rendering and layer writes. These are single local measurements with other processes active, not controlled benchmarks. Large layers and expensive presets can still take time; progress and cancellation are available during preparation.

An outer native busy wait protects shape mutations while Krita drains its workers. Nested waits cannot run timers that read shapes being replaced. The observer test reproduces that access pattern; it does not certify every version of every third-party plugin.

[Testing instructions](docs/TESTING.md), [JSON reports](docs/validation/) and runnable probes are included. Screenshots show the real application. Try the [prepared lineart](examples/pepper-lineart.png), [editable result](examples/pepper-linework.kra) and [smoothing example](examples/smoothing-and-points.kra).

## Windows build and validation

The Windows package contains native **PE x86-64 DLLs**, built with **LLVM-MinGW Clang 18.1.8 UCRT**, matching the official Krita 5.2.14 toolchain. It uses Krita's existing runtime libraries. [Build provenance and binary hashes](docs/validation/windows-build.json).

![Native Windows Krita running the multiple point and thickness regression](docs/images/windows-multi-point.png)

*The official Windows application under Wine 11.0, showing selected points, independent thickness, native Tool Options and the Linework layer icon. Synthetic artwork created for this project.*

The Windows application passed the same multiple-selection regression: inherited Select Shapes selection, grouped thickness, preserved pressure/handles, hidden original previews, Esc restoration, rectangle selection, deletion, history and save/reopen. [Windows report](docs/validation/windows-multi-point.json). The four native smoothing modes also passed: the test strokes reduced from 101/101/101/1,139 to 10/7/12/6 anchors, with pressure, cancellation, delay, saving during drawing and history checked. [Windows smoothing report](docs/validation/windows-smoothing.json). **Known Windows/Wine issue:** the complete 743-stroke bulk brush/thickness/history probe did not finish; diagnostic traces reached native scratch-image waits during brush redo. The cause and behavior on physical Windows are unconfirmed. The Windows download is an **experimental preview**; large-layer replay/history is not validated. [Validation status](docs/validation/windows-status.json). These are Wine-based regressions; a physical Windows tablet has not been tested.

## The same OpenToonz Centerline algorithm

This is a **reimplementation/port of the same OpenToonz Centerline vectorization algorithm inside Krita**, based directly on the original BSD-3-Clause code at revision [`8c5345182b1c3d2ff011a1cf08dad067b6700f08`](https://github.com/opentoonz/opentoonz/tree/8c5345182b1c3d2ff011a1cf08dad067b6700f08).

The port runs polygonization, straight-skeleton extraction, graph organization, stroke fitting and color routines. Quadratic position and radius controls are elevated exactly to cubics for Linework's model. Original files, hashes and integration patches are recorded in [ORIGIN.json](linework/native/opentoonz/ORIGIN.json) and [VECTORIZATION.txt](VECTORIZATION.txt).

The implemented path is Centerline for RGB/grayscale raster. Host adapters provide types and storage. TLV colormaps, NAA preparation and filled regions are outside this integration. Final rendering uses Linework/Krita, so tested core equality does not imply pixel-identical output to the complete OpenToonz application.

## Codex, Ghidra and reverse engineering

**OpenAI Codex was used to develop this plugin**, including analysis, implementation, integration and tests. **Ghidra 11.0.3 was used for static reverse engineering of Paint Tool SAI 2**, using a local executable supplied by the user.

The analysis records show completed PE x86-64 import, **7,038 functions** identified by automatic analysis, and an inventory of **59 strings** associated with the investigated features and their references. The project's [inspection script](docs/InspectLinework.java) walks defined strings and references to locate linework, curve and pressure features.

This evidence supports feature investigation and behavioral inspiration. It does not establish a copy of SAI's internal brush algorithm or file format. The implementation uses Krita's engine, Linework geometry and OpenToonz's open-source code. No SAI executable, Ghidra database, proprietary assets or decompiled SAI code are distributed.

## Limitations and licenses

Each stroke renders onto transparency; presets depending on pigment from other layers do not preserve that interaction. Physical stylus tilt, rotation and velocity are not recorded. Linework has its own session history. There is no `.sai2` import, curve cutting/joining, wraparound canvas or OpenToonz filled-region reconstruction. Full document resizing does not update stored centerline metadata. Physical tablet compatibility needs validation on each device.

The integration is **GPL-3.0-or-later** ([LICENSE](LICENSE)). The OpenToonz core retains **BSD-3-Clause** notices ([THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt)). Pepper artwork and its derivatives are **CC BY 4.0**, credited to **David Revoy** with the changes described in [ARTWORK.md](docs/ARTWORK.md). This independent project does not imply endorsement by Krita, Paint Tool SAI, OpenToonz or the artwork's author.
