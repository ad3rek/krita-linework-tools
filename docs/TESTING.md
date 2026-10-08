# Tests and reproduction

The original validation environment is **Linux x86_64, Krita 5.2.14 / Qt 5.15.17 / Python 3.12**. The bridge requires compatible native libraries. Canvas regressions run the real application in isolation; they do not replace physical stylus validation.

## CPU tests

From the repository root:

```sh
python3 linework/native/build_vectorize.py
python3 -m unittest discover -s tests -v
```

The first command requires a C++17 `g++` compiler and rebuilds only the vectorizer. The suite also compiles a reference library from the original OpenToonz sources. Neither the OpenToonz application nor a running Krita is required.

**56 tests passed**, including 16 synthetic fixtures compared against the original core: quadratic position and radius controls match exactly. [Published run log](validation/cpu-tests.txt) · [Reference scope](validation/opentoonz-reference.json).

## Krita GUI regressions

Requirements: Krita 5.2.14 compatible with the bridge, its Python/PyQt5 plugin support, `xvfb-run`, `timeout` and Krita's standard presets. Debian/Ubuntu provide `xvfb-run` through `xvfb`, with `xauth` required.

```sh
python3 tests/gui/run.py cc_lineart
python3 tests/gui/run.py multi_point
python3 tests/gui/run.py smoothing
```

Each run creates a **separate configuration, resources, test plugin, temporary directory and Krita instance**. It does not use the user's open documents or Krita configuration. Results go to `work/gui-results/<probe>/`, ignored by Git; `--output /path` chooses another destination.

| Probe | Coverage |
| --- | --- |
| `cc_lineart` | Treated grayscale bitmap, zoomable preview, new layer, all-stroke preset replacement, all-point diameter editing, preserved pressure/handles, history, point editing, shape observer, save/reopen and unchanged source. |
| `multi_point` | Inherited native selection, Shift, mixed fields, thickness across different base widths, hidden originals while dragging, Esc, rectangle, deletion, Ctrl+A and save/reopen. |
| `smoothing` | Qt tablet events through four native filters, compaction and sampled error, pressure, handles, history, Esc, delay, finishing, saving during drawing and tool switching. |

Published reports: [lineart](validation/cc-lineart.json), [multiple selection](validation/multi-point.json), [fresh smoothing run](validation/smoothing.json), and [earlier reduction with reopening in another process](validation/point-reduction.json).

Probes send Qt events and use some internal plugin APIs to check data and history. They are not entirely human-operated sessions. The shape observer counts reads **inside the actual shape mutation scope**, after entering the native outer wait. Reads during brush preparation are expected and permitted.

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
python3 tests/gui/run_windows_wine.py cc_lineart --krita-bin /path/krita-x64-5.2.14/bin
```

This runner creates a disposable Wine prefix and resources, supplies font faces for Krita's SVG text factory, and removes the host Plasma session variable that triggers an incompatible Qt 5.15.7 startup workaround. It never uses the default Wine prefix or the user's Krita settings. These environment adjustments are test harness configuration, not changes to the distributed Krita application.

The Windows multiple-selection and smoothing regressions passed. [Multiple selection report](validation/windows-multi-point.json) · [Smoothing report](validation/windows-smoothing.json) · [Real Windows application screenshot](images/windows-multi-point.png). A physical Windows machine and stylus have not been validated; Wine regression results are reported separately from the Linux results.

The complete 743-stroke Windows `cc_lineart` probe did not finish. Diagnostic traces reached native scratch-image waits during brush redo. Root cause and physical Windows behavior are unconfirmed. [Incomplete probe and release status](validation/windows-status.json). The Windows package is an experimental preview; Linux lineart results do not establish Windows bulk replay/history stability.
