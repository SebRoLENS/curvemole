"""Measure fresh desktop processes using disposable settings, data and caches.

Example: uv run python scripts/benchmark_startup.py --runs 7
--plugins executes plugins from the specified, explicitly trusted directory.
This never enables or changes plugins in the real user profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def peak_rss_mib():
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)


def prepare_plugins(directory, profile):
    records = {}
    for manifest in sorted(directory.rglob("*.curvemole-plugin.json")):
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        metadata = {key: raw[key] for key in
                    ("identifier", "version", "api_compatibility", "licence", "capabilities", "module", "name")
                    if key in raw}
        metadata["source"] = str(manifest.resolve())
        metadata.setdefault("name", "")
        source = manifest.parent / metadata["module"]
        identifier = metadata["identifier"]
        records[identifier] = dict(metadata=metadata, reference=str(manifest.resolve()),
                                   kind="local", enabled=True, symbol=f"P{len(records) + 1}",
                                   fingerprint=hashlib.sha256(manifest.read_bytes() + source.read_bytes()).hexdigest())
    storage = profile / "config" / "CurveMole" / "plugins"
    storage.mkdir(parents=True)
    (storage / "installed.json").write_text(json.dumps(records), encoding="utf-8")


def probe(plugins):
    with tempfile.TemporaryDirectory(prefix="curvemole-benchmark-") as directory:
        profile = Path(directory)
        for key, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                            ("XDG_CACHE_HOME", "cache"), ("APPDATA", "config"), ("LOCALAPPDATA", "data")):
            os.environ[key] = str(profile / folder)
        os.environ.update(QT_QPA_PLATFORM="offscreen", CURVEMOLE_SMOKE_TEST="1",
                          CURVEMOLE_DISABLE_UPDATE_CHECK="1")
        if plugins:
            prepare_plugins(plugins, profile)
        started = time.perf_counter()
        # QSettings on macOS is native, and platformdirs may use native paths.
        # Override both before importing the application, on every platform.
        import platformdirs
        from PySide6.QtCore import QEvent, QObject, QSettings, QTimer
        from PySide6.QtWidgets import QApplication
        for kind in ("config", "data", "cache"):
            def path(appname=None, *args, _kind=kind, **kwargs):
                return profile / _kind / (appname or "")
            setattr(platformdirs, f"user_{kind}_path", path)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(profile / "settings"))
        from curvemole.gui.app import create_main_window

        imported = time.perf_counter()
        app = QApplication(["curvemole-startup-benchmark"])
        window = create_main_window()
        constructed = time.perf_counter()
        result = {}

        def elapsed():
            return (time.perf_counter() - started) * 1000

        def plugins_ready():
            result["plugins_ready_ms"] = elapsed()

        if getattr(window, "_startup_pending", False):
            window.plugins_ready.connect(plugins_ready)
        else:
            plugins_ready()

        class FirstPaint(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Paint and "first_paint_ms" not in result:
                    result.update(first_paint_ms=elapsed(), first_paint_rss_mib=peak_rss_mib())
                return False

        observer = FirstPaint(window)
        window.installEventFilter(observer)

        def wait_ready():
            if not getattr(window, "_startup_pending", False):
                app.quit()
            else:
                QTimer.singleShot(10, wait_ready)

        try:
            window.show()
            QTimer.singleShot(25, wait_ready)
            QTimer.singleShot(20_000, app.quit)
            app.exec()
            if getattr(window, "_startup_pending", False) or "first_paint_ms" not in result:
                raise RuntimeError("Startup did not complete")
            result.update(import_ms=(imported - started) * 1000,
                          construct_ms=(constructed - imported) * 1000,
                          rss_mib=peak_rss_mib(),
                          scipy_modules=sum(name.startswith("scipy.") for name in sys.modules),
                          loaded_plugins=len(window.plugin_manager.loaded))
        finally:
            window._finish_session()
            window.deleteLater()
            app.processEvents()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "src")
    parser.add_argument("--plugins", type=Path, help="Execute plugins in this trusted directory in an isolated profile")
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.plugins)))
        return
    if args.runs < 1:
        parser.error("--runs must be positive")
    samples = []
    for _ in range(args.runs):
        command = [sys.executable, str(Path(__file__).resolve()), "--probe"]
        if args.plugins:
            command.extend(["--plugins", str(args.plugins.resolve())])
        process = subprocess.run(command, env=dict(os.environ, PYTHONPATH=str(args.source.resolve())),
                                 capture_output=True, text=True, timeout=60, check=True)
        samples.append(json.loads(process.stdout))
    medians = {key: statistics.median(row[key] for row in samples)
               for key in samples[0] if samples[0][key] is not None}
    print(json.dumps(dict(medians=medians, samples=samples), indent=2))


if __name__ == "__main__":
    main()
