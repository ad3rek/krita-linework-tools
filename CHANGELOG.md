# Changelog

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
