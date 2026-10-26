"""Lightweight desktop launcher; secondary processes only forward open requests."""
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None, *, instance_directory: Path | None = None) -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    arguments = list(argv) if argv is not None else sys.argv
    if len(arguments) == 3 and arguments[1] == "--run-automation-job":
        from curvemole.core.automation_job import run_job
        return run_job(arguments[2])

    from PySide6.QtCore import QCoreApplication, QLocale, Qt

    from curvemole.single_instance import DesktopInstance, NativeFileOpenFilter, absolute_paths
    from curvemole.version import __version__

    instance = DesktopInstance(instance_directory)
    if not instance.acquire():
        app = QCoreApplication(arguments)
        instance.forward(arguments[1:])
        # Keep the event dispatcher alive until synchronous forwarding is done.
        del app
        return 0

    try:
        from PySide6.QtWidgets import QApplication
        QLocale.setDefault(QLocale.c())
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app = QApplication(arguments)
        QCoreApplication.setOrganizationName("CurveMole")
        QCoreApplication.setApplicationName("CurveMole")
        QCoreApplication.setApplicationVersion(__version__)
        native_filter = NativeFileOpenFilter()
        app.installEventFilter(native_filter)
        # Queue IPC alongside native events before any heavy imports or window
        # construction can run a nested event loop. Nothing is dropped at startup.
        instance.paths_received.connect(native_filter.enqueue)
        instance.listen()
        app.aboutToQuit.connect(instance.close)
        from curvemole.gui.app import run_primary
        return run_primary(app, absolute_paths(arguments[1:]), instance, native_filter)
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
