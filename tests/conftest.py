from __future__ import annotations

import atexit
import os
import sys
import tempfile

_test_profile = tempfile.TemporaryDirectory(prefix="curvemole-tests-")
atexit.register(_test_profile.cleanup)
for _key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
    os.environ[_key] = os.path.join(_test_profile.name, _key)

from pathlib import Path  # noqa: E402

import platformdirs  # noqa: E402


def _profile_path(kind):
    def path(appname=None, *args, **kwargs):
        result = Path(_test_profile.name) / kind / (appname or "")
        if kwargs.get("ensure_exists"):
            result.mkdir(parents=True, exist_ok=True)
        return result
    return path


for _kind in ("config", "data", "cache"):
    setattr(platformdirs, f"user_{_kind}_path", _profile_path(_kind))
try:
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _test_profile.name)
except ImportError:
    pass

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from curvemole import Curve  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/curvemole-matplotlib")
os.environ.setdefault("CURVEMOLE_DISABLE_UPDATE_CHECK", "1")


@pytest.fixture(autouse=True)
def release_closed_gui_windows():
    """Dispose finished windows between tests, on Qt's application thread.

    close() ends the session but normally retains the native widget tree. Without
    an application event loop, hundreds of closed test windows can accumulate:
    global theme changes then restyle all of them and exhaust the CI timeout.
    Leave active sessions alone; their tests still own worker shutdown/cleanup.
    """
    yield
    widgets = sys.modules.get("PySide6.QtWidgets")
    main_window = sys.modules.get("curvemole.gui.main_window")
    if widgets is None or main_window is None or widgets.QApplication.instance() is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent

    for window in widgets.QApplication.topLevelWidgets():
        if isinstance(window, main_window.MainWindow) and window._session_finished:
            window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def gaussian_curve() -> Curve:
    x = np.linspace(-5, 5, 501)
    sigma = 0.8
    y = 3.0 * np.exp(-0.5 * ((x - 0.7) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi)) + 0.15
    rng = np.random.default_rng(42)
    return Curve("Gaussian", x, y + rng.normal(0, 0.005, len(x)), sigma_y=np.full_like(x, 0.005))
