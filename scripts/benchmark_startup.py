"""Compare time to the first GUI event-loop turn in fresh Python processes.

Use identical dependencies for both trees. This is not a cold-disk or frozen
bootloader benchmark; the first sample is reported separately from warm samples.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r'''
import sys, time, json
sys.path.insert(0, sys.argv[1])
started = time.perf_counter()
from curvemole.gui import app
from curvemole.gui.updates import UpdateController
from curvemole.gui.plugin_updates import PluginUpdateController
from PySide6.QtCore import QTimer, QSettings
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, sys.argv[2])
UpdateController.check = lambda *args, **kwargs: None
PluginUpdateController.check = lambda *args, **kwargs: None
original = app.create_main_window
def create(*args, **kwargs):
    window = original(*args, **kwargs)
    def ready():
        print(json.dumps({'ready_seconds': time.perf_counter() - started,
                          'pandas_loaded': 'pandas' in sys.modules}), flush=True)
    QTimer.singleShot(0, ready)
    return window
app.create_main_window = create
raise SystemExit(app.main(['CurveMole']))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=7)
    args = parser.parse_args()
    if args.samples < 2:
        parser.error('At least two samples are required')
    results = {'baseline': [], 'candidate': []}
    with tempfile.TemporaryDirectory(prefix='curvemole-benchmark-') as temporary:
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', CURVEMOLE_SMOKE_TEST='1',
                   XDG_CONFIG_HOME=temporary, XDG_CACHE_HOME=temporary)
        env.pop('CURVEMOLE_PACKAGING_SMOKE', None)
        for index in range(args.samples):
            # Alternate order to reduce systematic page-cache/order bias.
            labels = ['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline']
            for label in labels:
                source = getattr(args, label).resolve() / 'src'
                completed = subprocess.run(
                    [sys.executable, '-c', CHILD, str(source), temporary],
                    cwd=temporary, env=env, capture_output=True, text=True,
                    check=True, timeout=120,
                )
                sample = json.loads(completed.stdout.strip().splitlines()[-1])
                results[label].append(sample)
    report = {'platform': sys.platform, 'python': sys.version, 'samples': results}
    for label, samples in results.items():
        report[label + '_warm_median_seconds'] = statistics.median(
            sample['ready_seconds'] for sample in samples[1:]
        )
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
