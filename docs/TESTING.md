# Tests and reproduction

The original validation environment is **Linux x86_64, Krita 5.2.14 / Qt 5.15.17 / Python 3.12**. The bridge requires compatible native libraries. Canvas regressions run the real application in isolation; they do not replace physical stylus validation.

## 0.1.5 validation

The release passed **100 CPU tests** ([log](validation/0.1.5/cpu-tests.txt)). New Linework creation uses the native frame backend directly. The application runs exercise automatic creation on the first stroke, the New Linework Layer menu, raster conversion with both smooth lines and the current preset, and saving/reopening their editable geometry.

All **27 animation checks** passed on Linux 5.2.14 and official Windows 5.3.4.1/6.0.4.1 under Wine, including normal process exits. The first check now verifies a Timeline-ready layer with no conversion action or hidden vector backup. The remaining cases cover native frame duplication/movement/deletion/cloning, point/thickness/brush/color/eraser edits, Undo, Timeline UI, playback, saved files and raster export. Closing several views and returning from a cancelled close also passed on Linux.

The size probe edits Krita's native toolbar through Qt keyboard events, invokes increase/decrease in all six tools, verifies unchanged existing strokes and checks that a new stroke captures 31 px on the selected Linework layer. Windows 5.3.4.1 and 6.0.4.1 both passed with the rebuilt paint-tool factory. Linux also passed toolbar and native-size controls. Synthetic mouse/tablet and queued-input tests verify rapid strokes stay on one automatically created layer; the layer lifecycle probe checks editing immediately after native Undo and switching/removing layers.

The autosave probe uses Krita's real background timer with a two-second interval in isolated settings. It reads and checks the actual autosave archive, reopens it and edits points/diameters with native Undo on legacy vector and frame-backed Linework. Linux and Windows 6.0.4.1 passed. This tests saved autosave files, not an actual crash or startup recovery dialog; the reported user's recovered file was not available. Missing editable metadata cannot be inferred from pixels.

[Reports and scope](validation/0.1.5/release.json) · [Native compilation matrix and hashes](validation/0.1.5/native-build.json). The version-specific bridge uses Krita's internal ABI; unknown versions remain rejected. Physical Windows/tablets and the full 743-stroke Windows bulk replay/history case remain unvalidated. Historical reports below are unchanged.

```sh
python3 tests/gui/run.py brush_size
python3 tests/gui/run.py stroke_lifecycle
python3 tests/gui/run.py autosave_recovery
python3 tests/gui/run.py unified_vectorize
python3 tests/gui/run.py animation
python3 tests/gui/run_windows_wine.py brush_size --krita-bin /path/krita-x64-6.0.4.1/bin
```

## 0.1.4 validation

The release CPU suite passed **100 tests**: [run log](validation/0.1.4/cpu-tests.txt). The [release report](validation/0.1.4/release.json) lists the fresh application runs, and [native build provenance](validation/0.1.4/native-build.json) records the version matrix, official archives, SDK packages and SHA256 hashes. Seven Windows bridges compiled against the matching application headers and exports; the Linux bridge remains specific to 5.2.14.

The official Windows **5.3.4.1 and 6.0.4.1** applications passed the layer lifecycle, thickness-handle and smoothing probes under Wine 11.0. Layer tests exercise deleting and restoring a stroke through both Linework history and native Undo, switching layers without delayed reselection, editing the selected layer and drawing after removing a Linework layer. Thickness tests use the actual **Basic-1 Quick Brush preset**: both guide ends, 100% and 1067% zoom, active-point locking, native pixel changes, exact Undo restoration and selection preservation when a different engine rejects an edit.

Windows 5.3.4.1 and 6.0.4.1 also passed rapid drawing, queued mouse/tablet/shortcut input, continued drawing and saved/reopened pixels with normal exits. Qt 6 input is copied through native event cloning because its PyQt binding omits the timestamp setter used by Qt 5. Both versions passed the Spanish localization probe. Windows 6.0.4.1 additionally passed closing with multiple views and returning to editing after a cancelled close.

The fresh Linux 5.2.14, Windows 5.3.4.1 and Windows 6.0.4.1 animation probes also passed all **27 checks**, including normal process exits. Native image-to-tool stroke requests are disconnected while a window closes and restored if the user cancels closing. Queued animation updates skip closing windows and documents without a live view. The runner records `application_exit_code` and treats a crash after functional checks as a failed run.

Linux 5.2.14 passed the same thickness cases, foreground-color editing, and localization probes for Spanish and Arabic. Localization checks include native tool titles, action/toolbox tooltips, Tool Options, the selected-language override and right-to-left layout. The catalog checks verify all locale JSON files and formatting placeholders; they do not establish translation quality. See [catalog coverage](TRANSLATIONS.md).

To reproduce the additional probes:

```sh
python3 tests/gui/run.py layer_lifecycle
python3 tests/gui/run.py thickness_handles
python3 tests/gui/run.py localization --language es
python3 tests/gui/run.py localization --language ar
python3 tests/gui/run_windows_wine.py thickness_handles --krita-bin /path/krita-x64-5.3.4.1/bin
python3 tests/gui/run_windows_wine.py layer_lifecycle --krita-bin /path/krita-x64-6.0.4.1/bin
```

Every passing application run also requires a normal process exit. Windows testing uses the actual official Windows runtimes in dedicated Wine prefixes; it is not physical Windows or stylus validation. The full 743-stroke Windows bulk replay/history check remains incomplete. Reports below retain their historical version and source scope.

## CPU tests

From the repository root:

```sh
python3 linework/native/build_vectorize.py
python3 -m unittest discover -s tests -v
```

The first command requires a C++17 `g++` compiler and rebuilds only the vectorizer. The suite also compiles a reference library from the original OpenToonz sources. Neither the OpenToonz application nor a running Krita is required.

The initial 0.1 validation had **70 tests passed**, including 16 synthetic fixtures compared against the original core: quadratic position and radius controls match exactly. [Published run log](validation/cpu-tests.txt) · [Reference scope](validation/opentoonz-reference.json).

## Krita GUI regressions

Requirements: a supported Krita version compatible with its bridge and Python/PyQt plugin support, `xvfb-run`, `timeout` and Krita's standard presets. Debian/Ubuntu provide `xvfb-run` through `xvfb`, with `xauth` required.

```sh
python3 tests/gui/run.py cc_lineart
python3 tests/gui/run.py multi_point
python3 tests/gui/run.py smoothing
python3 tests/gui/run.py color
python3 tests/gui/run.py stroke_lifecycle
python3 tests/gui/run.py eraser_topology
python3 tests/gui/run.py animation
```

Each run creates a **separate configuration, resources, test plugin, temporary directory and Krita instance**. It does not use the user's open documents or Krita configuration. Results go to `work/gui-results/<probe>/`, ignored by Git; `--output /path` chooses another destination.

| Probe | Coverage |
| --- | --- |
| `cc_lineart` | Treated grayscale bitmap, zoomable preview, new layer, all-stroke preset replacement, all-point diameter editing, preserved pressure/handles, history, point editing, shape observer, save/reopen and unchanged source. |
| `multi_point` | Inherited native selection, Shift, mixed fields, thickness across different base widths, hidden originals while dragging, Esc, rectangle, deletion, Ctrl+A and save/reopen. |
| `smoothing` | Qt tablet events through four legacy native filters, plus Pixel smoothing on modern builds, compaction and sampled error, pressure, handles, history, Esc, delay, finishing, saving during drawing and tool switching. |
| `color` | Foreground recoloring of native brushes and smooth lines, selected/whole-layer scope, debounce, rendered pixels, grouped undo/redo, locked layers and save/reopen. |
| `eraser_topology` | 21 checks: native point thinning, zero recovery, pressure, saving, swept line deletion, cancellation, locks, active style and retained diameters, merging/welding/closing, expanded point/handle targets, point/stroke selection, active-point lock and save/reopen. |
| `stroke_lifecycle` | Rapid mouse/tablet input in four modes, double click, another gesture during native rendering, queued mouse/tablet/shortcuts, missed release, separate undo steps, continued drawing, native pixels and save/reopen. |
| `animation` | Native raster keyframes: conversion and source backup, frame-local brush/point/thickness/color edits, copying identical pixels with distinct geometry, linked clones, moving/deleting, native Undo/Redo, preview cancellation and time switching, immediate save after copy, `.kra` reopening, PNG frame export and native playback. |

The earlier 5.2.14 animation development build passed **27 checks on Linux** and **27 on Windows under Wine 11.0**: [Linux animation report](validation/animation.json), [Windows/Wine animation report](validation/windows-animation.json). The probe also checks a real Timeline cell/duplicate action, the native blank regenerated when frame 0 is moved, a vector edit in the same document followed by saving, and external native-brush painting protected against Linework overwrite. PNG frames use Krita's guarded save/export snapshot path. Physical Windows and tablets are outside these reports.

Published reports: [lineart](validation/cc-lineart.json), [multiple selection](validation/multi-point.json), [fresh smoothing run](validation/smoothing.json), and [earlier reduction with reopening in another process](validation/point-reduction.json).

Probes send Qt events and use some internal plugin APIs to check data and history. They are not entirely human-operated sessions. The shape observer counts reads **inside the actual shape mutation scope**, after entering the native outer wait. Reads during brush preparation are expected and permitted.

The stroke lifecycle probe delivers a new gesture inside `NativeBrushRenderer._paint`, before the previous render returns. This makes the nested-input boundary deterministic instead of relying on machine-dependent scheduling. The original source cleared the editor with a missing stroke ID; the corrected source queues the gesture. Published [before](validation/stroke-lifecycle-before.json), [Linux](validation/stroke-lifecycle.json) and [Windows/Wine](validation/windows-stroke-lifecycle.json) reports include the source hashes and the scope of this reproduction. After reopening the document in a view, the probe checks the native layer's actual alpha pixels as well as editable metadata.

The fixture preparation is documented in [ARTWORK.md](ARTWORK.md) and [artwork-source.json](validation/artwork-source.json): crop, resize, grayscale and levels. To reproduce it from the original JPEG, install Pillow and run `python3 tests/gui/prepare_fixture.py /path/characters-lineart.jpg`. The GUI test checks that Krita opened the PNG as **GRAYA** and that source-layer bytes remain unchanged.

## Measurement limits

Timings are single local runs with other processes active, not performance guarantees. Stabilizer timers affect sample counts. Anchor counts depend on the drawing and pressure. Canvas position/pressure errors are sampled; separate compaction tests check full intervals and adverse cases.

The reference test shares host type adapters and compares the original core, not the complete OpenToonz application. Preset rendering is Krita's. Affine transforms have CPU regressions and development validation; these three probes do not exercise every native transformation operation.

## Windows application under Wine

The Windows binaries use the official Krita 5.2.14 x64 / Qt 5.15.7 / Python 3.10 runtime and LLVM-MinGW Clang 18.1.8 UCRT. [SDK provenance and binary hashes](validation/windows-build.json).

On Linux with Wine 11.0, Xvfb and DejaVu fonts installed, extract the official Windows Krita portable archive and run:

```sh
python3 tests/gui/run_windows_wine.py multi_point --krita-bin /path/krita-x64-5.2.14/bin
python3 tests/gui/run_windows_wine.py smoothing --krita-bin /path/krita-x64-5.2.14/bin
python3 tests/gui/run_windows_wine.py color --krita-bin /path/krita-x64-5.2.14/bin
python3 tests/gui/run_windows_wine.py stroke_lifecycle --krita-bin /path/krita-x64-5.2.14/bin
python3 tests/gui/run_windows_wine.py eraser_topology --krita-bin /path/krita-x64-5.2.14/bin
python3 tests/gui/run_windows_wine.py cc_lineart --krita-bin /path/krita-x64-5.2.14/bin
```

This runner creates a disposable Wine prefix and resources, supplies font faces for Krita's SVG text factory, and removes the host Plasma session variable that triggers an incompatible Qt 5.15.7 startup workaround. It never uses the default Wine prefix or the user's Krita settings. These environment adjustments are test harness configuration, not changes to the distributed Krita application.

The Windows multiple-selection and smoothing regressions passed. [Multiple selection report](validation/windows-multi-point.json) · [Smoothing report](validation/windows-smoothing.json) · [Real Windows application screenshot](images/windows-multi-point.png). A physical Windows machine and stylus have not been validated; Wine regression results are reported separately from the Linux results.

The 0.1.1 [Windows color regression](validation/windows-color.json) also passed all ten checks, with Krita exiting normally. That run reused an initialized project-owned Wine prefix and isolated test resources after fresh-prefix initialization timed out before Krita started. It did not use the default Wine prefix or the user's Krita configuration. [Linux color regression](validation/color.json).

The complete 743-stroke Windows `cc_lineart` probe did not finish. Diagnostic traces reached native scratch-image waits during brush redo. Root cause and physical Windows behavior are unconfirmed. [Incomplete probe and release status](validation/windows-status.json). The Windows package is an experimental preview; Linux lineart results do not establish Windows bulk replay/history stability.

The 0.1.2 [Linux eraser/topology regression](validation/eraser-topology.json) and [Windows/Wine regression](validation/windows-eraser-topology.json) passed all 21 checks with normal exits. These probes use synthetic paths, real Qt mouse/tablet events, Tool Options actions, native projection pixels and saved metadata. Windows testing reused the initialized project-owned Wine prefix described above. Reports record hashes of the tested editor, tool integration, eraser, topology and probe sources.

## Development performance probe

Run `python3 tests/gui/run.py performance` for the real-application picker/eraser query benchmark and paired native preset-cache checks. The runner extracts the public CC fixture metadata automatically. `python3 tests/gui/run_windows_wine.py performance --krita-bin /path/krita-x64-5.2.14/bin` runs the same probe in the official Windows application. Results separate cold indexing, hot queries, incremental updates and native rendering. Cache tests compare actual pixel hashes for legacy/independent diameter, style changes and XML changes; check bounded eviction, invalid-preset recovery and teardown.

The CPU suite includes conservative grid/control-envelope tests, swept eraser equivalence and snapshot-sharing regressions. The `cc_lineart` stress probe permits up to 1,200 seconds on Linux; it enumerates every shape every 5 ms during preparation, so its elapsed time includes that deliberately heavy observer. A timeout is not a passing result and is recorded separately. Published release reports retain their original source/version scope.

Run `python3 tests/bench_history.py --output work/history-benchmark.json` for the separate Python history benchmark. It extracts the CC fixture and reads the baseline model from Git at `1750421`; the full repository history is required. Timing uses 20 one-anchor edits and three repetitions. A separate tracemalloc run measures Python allocations including history creation, excluding fixture loading and all native/Qt memory.

The development lifecycle probe waits until captured input has drained before checking nested gestures. Native image waits pump Qt timers: a fixed 400 ms check can run inside gesture replay, see a partially processed stroke and close the test window during a native wait. The initial development run exposed this harness race. Checks still require every stroke, native alpha pixels, separate undo steps and a saved/reopened document.

Run `python3 tests/gui/run.py interface` to inspect all six tool modes in the native Tool Options docker at a 290 px width. The probe requires no horizontal overflow, checks that collapsing preserves the thickness value, and captures the native panel with dark/light palettes. `multi_point` also checks editing after the layout change. Interface captures use synthetic test curves.
