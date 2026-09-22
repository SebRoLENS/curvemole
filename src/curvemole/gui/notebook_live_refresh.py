"""Keep an already-open laboratory notebook in sync with object descriptions."""

from __future__ import annotations

from curvemole.core.notebook import description_key
from curvemole.gui.main_window import MainWindow
from curvemole.gui.notebook import LaboratoryNotebookDialog


def _refresh_from_project(panel: LaboratoryNotebookDialog) -> None:
    """Synchronise notebook metadata and rebuild the description tree in place."""
    panel.project.notebook.sync(panel.project)
    panel._populate()


def _focus_description(
    panel: LaboratoryNotebookDialog,
    kind: str,
    object_id: str,
    curve_id: str = "",
) -> bool:
    """Show an existing description while the notebook description tab is active."""
    if panel.tabs.currentIndex() != 1:
        return False

    panel.project.notebook.sync(panel.project)
    key = description_key(kind, object_id, curve_id)
    entry = panel.project.notebook.descriptions.get(key)
    if entry is None or entry.deleted:
        return False

    # A search must not prevent direct navigation to the object the user clicked.
    if panel.search.text():
        panel.search.blockSignals(True)
        panel.search.clear()
        panel.search.blockSignals(False)

    panel.current_key = key
    panel._populate()
    return panel.current_key == key


def _window_focus_description(
    window: MainWindow,
    kind: str,
    object_id: str | None,
    curve_id: str = "",
) -> None:
    if not object_id:
        return
    panel = getattr(window, "_notebook_widget", None)
    if panel is None or panel.project is not window.project:
        return
    # Only drive notebook navigation when the notebook has actually been opened.
    if window.notebook_dock.isHidden():
        return
    panel.focus_description(kind, str(object_id), curve_id)


def _install() -> None:
    # Public hooks keep callers independent of the notebook's private tree methods.
    LaboratoryNotebookDialog.refresh_from_project = _refresh_from_project  # type: ignore[attr-defined]
    LaboratoryNotebookDialog.focus_description = _focus_description  # type: ignore[attr-defined]

    original_edit = MainWindow._edit_description
    if not getattr(original_edit, "_curvemole_notebook_live_refresh", False):

        def edit_description(
            window: MainWindow,
            kind: str,
            object_id: str,
            title: str,
            curve_id: str = "",
        ) -> None:
            revision_before = window.project.revision
            original_edit(window, kind, object_id, title, curve_id)

            # Cancelling the dialog leaves the project revision untouched, so only a
            # successful description save refreshes the embedded notebook.
            if window.project.revision == revision_before:
                return
            panel = getattr(window, "_notebook_widget", None)
            if panel is None or panel.project is not window.project:
                return
            if not panel.focus_description(kind, object_id, curve_id):
                panel.refresh_from_project()

        edit_description._curvemole_notebook_live_refresh = True  # type: ignore[attr-defined]
        MainWindow._edit_description = edit_description

    original_connect = MainWindow._connect_signals
    if getattr(original_connect, "_curvemole_notebook_selection_sync", False):
        return

    def connect_signals(window: MainWindow) -> None:
        original_connect(window)

        # Follow the user's current object only while the notebook is open on its
        # descriptions tab. Objects without descriptions leave the notebook alone.
        window.curve_tree.activeCurveChanged.connect(
            lambda curve_id, window=window: _window_focus_description(
                window, "spectrum", curve_id
            )
        )
        window.curve_tree.seriesActivated.connect(
            lambda series_id, window=window: _window_focus_description(
                window, "series", series_id
            )
        )

        def focus_component(component_id: str, *, window: MainWindow = window) -> None:
            if window.active_curve_id:
                _window_focus_description(
                    window, "function", component_id, window.active_curve_id
                )

        window.model_panel.componentSelected.connect(focus_component)
        window.plot_workspace.componentSelected.connect(focus_component)

    connect_signals._curvemole_notebook_selection_sync = True  # type: ignore[attr-defined]
    MainWindow._connect_signals = connect_signals


_install()
