"""Responsive project opening with an isolated, cancellable read worker."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog

from curvemole.core.fitting import CancellationToken


def load_project_responsive(window, path, loader, *, snapshot=False, expected_digest=None):
    """Keep the synchronous open API while processing UI events during I/O.

    The modal progress dialog blocks edits to the old session. No UI object is
    accessed by the worker, and cancellation is checked while reading members.
    """
    token = CancellationToken()
    snapshot = snapshot or expected_digest is not None
    dialog = QProgressDialog(
        window.tr("Reading and validating project…"), window.tr("Cancel"), 0, 0, window
    )
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumDuration(0)
    dialog.canceled.connect(token.cancel)
    dialog.show()
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    previous_loading = getattr(window, "_project_loading", False)
    window._project_loading = True
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="project-open") as executor:

            def read():
                if not snapshot:
                    return loader(path, cancellation=token)
                from curvemole.core.project_handoff import file_digest

                before = file_digest(path, cancellation=token)
                if expected_digest is not None and before != expected_digest:
                    raise RuntimeError("The confirmed project version has not synchronized yet.")
                project = loader(path, cancellation=token)
                if file_digest(path, cancellation=token) != before:
                    raise RuntimeError("Project changed while opening. Try opening it again.")
                return project, before

            future = executor.submit(read)
            timer.timeout.connect(lambda: loop.quit() if future.done() else None)
            timer.start()
            if not future.done():
                loop.exec()
            return future.result()
    finally:
        timer.stop()
        window._project_loading = previous_loading
        dialog.reset()
        dialog.deleteLater()
