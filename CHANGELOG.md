# Changelog

## 0.1.5 — 2026-10-10

- Use a single Timeline-ready Linework layer for drawing, layer creation and raster vectorization. Create its editable initial frame automatically, remove the Animate Layer action, and avoid creating a second hidden vector layer. Retain the legacy vector reader/editor for existing documents.
- Queue canvas input until Krita delivers new-layer selection, preventing rapid consecutive strokes from creating separate layers. Preserve subsequent user layer changes.
- Refresh geometry in the existing canvas binding after native Undo, so the next edit operates on the restored frame.
- Capture the newly created frame in the canvas binding so subsequent drawing and edits keep the correct frame.
- Declare native preset and size support in all six tools, enabling Krita's toolbar size/flow controls and increase/decrease brush size actions without changing layers. Rebuild all supported platform bridges.
- Add native toolbar and real background-autosave regressions. Recovery tests reopen saved autosave files; they do not simulate a crash or assert that an unknown user file has been repaired.


## 0.1.4 — 2026-10-10

- Select version-specific Windows x64 native bridges for Krita 5.2.14, 5.3.3, 5.3.4, 5.3.4.1, 6.0.3, 6.0.4 and 6.0.4.1. Verify the compiled application target and Qt major before registering tools.
- Use Krita's own PyQt 5 or PyQt 6 binding, scoped enums and matching mouse/tablet event constructors. Clone queued Qt 6 input events natively, avoiding an unavailable timestamp setter that interrupted rapid drawing.
- Preserve modern native smoothing minimum/maximum distances and their proportion lock, and expose Krita's Pixel smoothing mode on 5.3/6.0.
- Rebind newly converted Linework layers when modern libkis delivers the active-node change before geometry metadata is written.
- Keep selection and editable metadata synchronized with native deletion Undo/Redo. Stop delayed layer selection from overriding a layer the user has selected.
- Read the canvas's active node without flushing nested application events, and defer timer-driven rebinding during input.
- Make thickness guide endpoints draggable, with screen-space picking at high zoom and support for the Quick Brush engine used by Basic-1. A rejected thickness edit restores the original appearance and preserves its selection.
- Follow Krita's interface language with catalogs for its 75 listed locales and English fallback. Translation coverage and automatic translation limitations are documented in docs/TRANSLATIONS.md.
- Report the detected Krita version and installation guidance when the native bridge rejects an incompatible application. Preserve the library path and original error for DLL load failures, while checking version compatibility before loading native code.
- Add animated Linework paint layers in Krita's native Timeline while retaining the original vector layer as a hidden backup.
- Carry editable geometry through native frame copying, moving, deletion and linked clones, and preserve it in `.kra` schema 7 annotations.
- Use native Undo for frame geometry and pixels, restore captured-frame previews on cancellation or timeline changes, and hide editing guides during playback.
- Add Animate Layer, New Frame and Duplicate Frame actions to Tools → Scripts and shortcut settings.
- Protect native tool/image lifetime during window closing and resume editing after a cancelled close.
- Include isolated regressions for layer lifecycle, thickness handles and interface language, plus 100 CPU tests. Animation validation covers 27 checks on Linux and the same 27 in each of the official Windows 5.3.4.1 and 6.0.4.1 applications under Wine 11.0. Include an editable animation example and real application captures.

Linux compatibility remains Krita 5.2.14 with compatible libraries. Native paint-layer transforms do not update Linework paths; external pixel changes are preserved and protected against Linework overwrite. Layer duplication, cross-document frame transfer and physical tablets need further validation.

## 0.1.3 — 2026-10-09

- Refine the native Tool Options layout with flat theme-aware headers, small arrows and separators. Put selection/thickness first when editing, combine brush/color actions, and collapse less frequent taper/connection controls initially.
- Index nearby anchors and stroke envelopes for picking, rectangle selection and swept erasing. Incremental updates preserve exact picking and eraser results.
- Cache bounded private native preset prototypes and clone settings for every render. Rebuild the matching Linux and Windows rendering bridges; retain the original ABI entry points and fallback.
- Share unchanged history snapshots and cache serialized stroke data, while returning independent editable undo/redo copies.
- Include 83 CPU tests, 11 real-application GUI regression runs, paired Linux/Windows-Wine performance probes, real screenshots and reproducible measurements.

The native ABI targets Krita 5.2.14. Windows remains an experimental preview: physical hardware/tablet validation is pending, and the full-layer 743-stroke Windows bulk replay/history check remains incomplete. The documented timings measure specific local operations, not total application speed. Animation is not included in this release.

## 0.1.2 — 2026-10-08

- Add whole-line and point-thinning eraser modes, point merging and endpoint joining.
- Add larger point/handle click targets, point/stroke selection and an active-point lock.
- Preserve ordered input during native rendering/saving to fix disappearing strokes and interrupted drawing.
- Include the color-editing fix from 0.1.1, native Linux/Windows packages and regression reports.

## 0.1.1 — 2026-10-08

- Fix recoloring existing native-brush and smooth-line strokes, with selected/whole-layer scope, grouped undo/redo and saved/reopened data preserved.

## 0.1 — 2026-10-08

- Publish editable Linework tools inside Krita, native brush rendering and smoothing, point/handle/thickness editing, and raster conversion using the OpenToonz Centerline core.
- Include experimental Linux and Windows packages, English documentation, Creative Commons artwork attribution and Codex/Ghidra development disclosure.
