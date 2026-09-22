"""Keep an already-open laboratory notebook in sync with external description edits."""

from __future__ import annotations

from curvemole.gui.main_window import MainWindow
from curvemole.gui.notebook import LaboratoryNotebookDialog


def _refresh_from_project(panel: LaboratoryNotebookDialog) -> None:
    """Synchronise notebook metadata and rebuild the description tree in place."""
    panel.project.notebook.sync(panel.project)
    panel._populate()


def _install() -> None:
    # Expose one small public refresh hook instead of making callers depend on the
    # notebook's private tree-population method directly.
    LaboratoryNotebookDialog.refresh_from_project = _refresh_from_project  # type: ignore[attr-defined]

    original = MainWindow._edit_description
    if getattr(original, "_curvemole_notebook_live_refresh", False):
        return

    def edit_description(
        window: MainWindow,
        kind: str,
        object_id: str,
        title: str,
        curve_id: str = "",
    ) -> None:
        revision_before = window.project.revision
        original(window, kind, object_id, title, curve_id)

        # Cancelling the dialog leaves the project revision untouched, so only a
        # successful description save refreshes the embedded notebook.
        if window.project.revision == revision_before:
            return
        panel = getattr(window, "_notebook_widget", None)
        if panel is None or panel.project is not window.project:
            return
        panel.refresh_from_project()

    edit_description._curvemole_notebook_live_refresh = True  # type: ignore[attr-defined]
    MainWindow._edit_description = edit_description


_install()
