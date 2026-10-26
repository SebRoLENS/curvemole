"""Keep optional table processing out of startup without changing table results."""

import os
import subprocess
import sys


def test_empty_gui_does_not_import_pandas():
    subprocess.run(
        [sys.executable, '-c', '''
import sys
from PySide6.QtWidgets import QApplication
from curvemole.gui.app import create_main_window
app = QApplication([])
window = create_main_window()
assert not any(name in sys.modules for name in ('pandas', 'scipy', 'matplotlib', 'yaml'))
window._release_update_controller.timer.stop()
window.plugin_update_controller.timer.stop()
window.close()
'''],
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen', CURVEMOLE_SMOKE_TEST='1'),
        check=True, timeout=60,
    )


def test_desktop_launcher_is_lightweight_and_public_api_remains_identical():
    subprocess.run([sys.executable, '-c', '''
import sys
import curvemole
import curvemole.desktop
import curvemole.single_instance
assert not any(name in sys.modules for name in ('numpy', 'scipy', 'curvemole.gui', 'PySide6.QtWidgets'))
from curvemole.core.data import Curve
assert curvemole.Curve is Curve
assert curvemole.Project is curvemole.core.project.Project
assert 'Curve' in dir(curvemole)
'''], check=True, timeout=30)
