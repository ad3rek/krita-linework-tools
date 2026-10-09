#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare history snapshots with a Git baseline on the public CC fixture."""
import argparse, gc, importlib.util, json, statistics, subprocess, sys
import tempfile, time, tracemalloc, zipfile
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module); return module


def run(module, fixture, steps, memory=False):
    gc.collect(); strokes = module.load_strokes(fixture)
    if memory: tracemalloc.start()
    history = module.History(strokes); begin = time.perf_counter()
    for _ in range(steps):
        strokes[0].points[0].x += .1; history.commit(strokes)
    result = {'commit_median_ms': (time.perf_counter()-begin)*1000/steps}
    if memory:
        result['peak_mib'] = tracemalloc.get_traced_memory()[1]/1024**2
        tracemalloc.stop()
    history.undo(); history.redo()
    assert [s.data() for s in history.current] == [s.data() for s in strokes]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='17504211558079f1ef5de008e6a1d2943fe81c3c')
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.steps <= 0: parser.error('steps must be positive')
    project = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(project/'examples/pepper-linework.kra') as archive:
        data = json.loads(archive.read('Unnamed/annotations/org.felipe.linework.v1'))
        fixture = next(iter(data['layers'].values()))['strokes']
    baseline = subprocess.check_output(['git', 'show', args.baseline_ref+':linework/model.py'], cwd=project)
    result = {'baseline_ref': args.baseline_ref, 'strokes': len(fixture),
              'anchors': sum(len(s['points']) for s in fixture), 'steps': args.steps,
              'scope': 'One anchor per step; three timing repetitions. Separate Python tracemalloc peak, including history creation and excluding fixture load / Qt / native images.'}
    with tempfile.TemporaryDirectory(prefix='linework-history-') as tmp:
        path = Path(tmp)/'baseline.py'; path.write_bytes(baseline)
        for name, module in [('before', load('history_bench_before', path)),
                             ('after', load('history_bench_after', project/'linework/model.py'))]:
            result[name] = {'commit_median_ms': statistics.median(run(module, fixture, args.steps)['commit_median_ms'] for _ in range(3)),
                            'peak_mib': run(module, fixture, args.steps, True)['peak_mib']}
    encoded = json.dumps(result, indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__': main()
