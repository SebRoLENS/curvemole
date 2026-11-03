"""Responsive project opening with an isolated, cancellable read worker."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from curvemole.core.archive_validation import ArchiveLimits
from curvemole.core.errors import FitCancelled, ProjectResourceLimitError
from curvemole.core.fitting import CancellationToken


def load_project_responsive(window, path, loader, *, snapshot=False, expected_digest=None):
    """Keep the synchronous open API while processing UI events during I/O.

    The modal progress dialog blocks edits to the old session. No UI object is
    accessed by the worker, and cancellation is checked while reading members.
    """
    token = CancellationToken()
    limits = None
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
                options = {"cancellation": token}
                if limits is not None:
                    options["limits"] = limits
                if not snapshot:
                    return loader(path, **options)
                from curvemole.core.project_handoff import file_digest

                before = file_digest(path, cancellation=token)
                if expected_digest is not None and before != expected_digest:
                    raise RuntimeError("The confirmed project version has not synchronized yet.")
                project = loader(path, **options)
                if file_digest(path, cancellation=token) != before:
                    raise RuntimeError("Project changed while opening. Try opening it again.")
                return project, before

            future = None
            timer.timeout.connect(lambda: loop.quit() if future.done() else None)
            timer.start()
            while True:
                future = executor.submit(read)
                if not future.done():
                    loop.exec()
                try:
                    return future.result()
                except ProjectResourceLimitError as exc:
                    token.raise_if_cancelled()
                    dialog.hide()
                    labels = {
                        "members": window.tr("Archive entries"),
                        "expanded_bytes": window.tr("Total uncompressed content"),
                        "array_bytes": window.tr("Single numerical array"),
                        "manifest_bytes": window.tr("Uncompressed metadata"),
                    }
                    details = []
                    for name, size in exc.required_limits.items():
                        limit = exc.current_limits[name]
                        if name == "members":
                            detail = window.tr("{label}: {size:,} (automatic threshold: {limit:,})")
                        else:
                            size, limit = size / 1024**2, limit / 1024**2
                            detail = window.tr(
                                "{label}: {size:,.1f} MiB (automatic threshold: {limit:,.1f} MiB)"
                            )
                        details.append(detail.format(label=labels[name], size=size, limit=limit))
                    answer = QMessageBox.warning(
                        window,
                        window.tr("Project memory use"),
                        window.tr(
                            "This project exceeds an automatic loading threshold:\n{details}\n\n"
                            "This does not mean it is damaged. Older projects may store "
                            "numerical results and fit history in their metadata.\n\n"
                            "Opening it may use substantially more memory, slow down "
                            "your computer or exhaust available memory. Continue only "
                            "if you trust this file and accept that risk.\n\n"
                            "Try opening it anyway? File integrity and structural "
                            "validation will remain enabled."
                        ).format(details="\n".join(details)),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        raise FitCancelled("Project opening cancelled.") from exc
                    limits = replace(limits or ArchiveLimits(), **exc.required_limits)
                    dialog.show()
    finally:
        timer.stop()
        window._project_loading = previous_loading
        dialog.reset()
        dialog.deleteLater()
