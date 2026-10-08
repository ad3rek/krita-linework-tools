# Tests and reproduction

The original validation environment is **Linux x86_64, Krita 5.2.14 / Qt 5.15.17 / Python 3.12**. The bridge requires compatible native libraries. Canvas regressions run the real application in isolation; they do not replace physical stylus validation.

## CPU tests

From the repository root:

```sh
python3 linework/native/build_vectorize.py
python3 -m unittest discover -s tests -v
```

The first command requires a C++17 `g++` compiler and rebuilds only the vectorizer. The suite also compiles a reference library from the original OpenToonz sources. Neither the OpenToonz application nor a running Krita is required.

**70 tests passed**, including 16 synthetic fixtures compared against the original core: quadratic position and radius controls match exactly. [Published run log](validation/cpu-tests.txt) · [Reference scope](validation/opentoonz-reference.json).

## Krita GUI regressions

Requirements: Krita 5.2.14 compatible with the bridge, its Python/PyQt5 plugin support, `xvfb-run`, `timeout` and Krita's standard presets. Debian/Ubuntu provide `xvfb-run` through `xvfb`, with `xauth` required.

```sh
python3 tests/gui/run.py cc_lineart
python3 tests/gui/run.py multi_point
python3 tests/gui/run.py smoothing
python3 tests/gui/run.py color
python3 tests/gui/run.py stroke_lifecycle
python3 tests/gui/run.py eraser_topology
```

Each run creates a **separate configuration, resources, test plugin, temporary directory and Krita instance**. It does not use the user's open documents or Krita configuration. Results go to `work/gui-results/<probe>/`, ignored by Git; `--output /path` chooses another destination.

| Probe | Coverage |
| --- | --- |
| `cc_lineart` | Treated grayscale bitmap, zoomable preview, new layer, all-stroke preset replacement, all-point diameter editing, preserved pressure/handles, history, point editing, shape observer, save/reopen and unchanged source. |
| `multi_point` | Inherited native selection, Shift, mixed fields, thickness across different base widths, hidden originals while dragging, Esc, rectangle, deletion, Ctrl+A and save/reopen. |
| `smoothing` | Qt tablet events through four native filters, compaction and sampled error, pressure, handles, history, Esc, delay, finishing, saving during drawing and tool switching. |
| `color` | Foreground recoloring of native brushes and smooth lines, selected/whole-layer scope, debounce, rendered pixels, grouped undo/redo, locked layers and save/reopen. |
| `eraser_topology` | 21 checks: native point thinning, zero recovery, pressure, saving, swept line deletion, cancellation, locks, active style and retained diameters, merging/welding/closing, expanded point/handle targets, point/stroke selection, active-point lock and save/reopen. |
| `stroke_lifecycle` | Rapid mouse/tablet input in four modes, double click, another gesture during native rendering, queued mouse/tablet/shortcuts, missed release, separate undo steps, continued drawing, native pixels and save/reopen. |

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
