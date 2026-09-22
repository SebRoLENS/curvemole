from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QLabel

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.plot_appearance import (
    DEFAULT_PLOT_APPEARANCE,
    marker_for_curve,
    normalize_plot_appearance,
    plot_mode_flags,
)


def test_plot_appearance_normalizes_invalid_values() -> None:
    settings = normalize_plot_appearance(
        {
            "data_line_width": 99,
            "data_marker": "not-a-marker",
            "grid_opacity": -8,
            "function_style": "points",
        }
    )
    assert settings["data_line_width"] == 12.0
    assert settings["data_marker"] == DEFAULT_PLOT_APPEARANCE["data_marker"]
    assert settings["grid_opacity"] == 0
    assert settings["function_style"] == "points"
    assert plot_mode_flags("lines") == (True, False)
    assert plot_mode_flags("points") == (False, True)
    assert plot_mode_flags("lines_points") == (True, True)


def test_marker_cycle_can_distinguish_spectra() -> None:
    settings = normalize_plot_appearance({"different_markers": True})
    assert marker_for_curve(settings, 0) != marker_for_curve(settings, 1)
    settings["different_markers"] = False
    assert marker_for_curve(settings, 0) == marker_for_curve(settings, 1)


def test_quick_plot_style_controls_loaded_data_and_display_layout() -> None:
    app = QApplication.instance() or QApplication([])
    project = Project("appearance")
    first = Curve("first", np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 0.0]))
    second = Curve("second", np.array([0.0, 1.0, 2.0]), np.array([1.0, 0.0, 1.0]))
    project.add_curve(first)
    project.add_curve(second)
    window = CurveMoleMainWindow(project)
    workspace = window.plot_workspace
    try:
        assert workspace.plot_style_mode is workspace.function_style_mode
        assert [
            workspace.plot_style_mode.itemText(index)
            for index in range(workspace.plot_style_mode.count())
        ] == ["Lines", "Points", "Lines + points"]
        labels = [label.text() for label in workspace.view_controls.findChildren(QLabel)]
        assert "Plot style:" in labels
        assert "Functions:" not in labels
        assert window.plot_appearance_action.text() == "Plot appearance…"

        controls_layout = workspace.view_controls.layout()
        display_row = controls_layout.itemAt(0).layout()
        autoscale_row = controls_layout.itemAt(1).layout()
        assert display_row.indexOf(workspace.x_offset) >= 0
        assert display_row.indexOf(workspace.y_offset) >= 0
        assert autoscale_row.indexOf(workspace.residual_toggle) >= 0

        workspace.plot_style_mode.setCurrentIndex(1)
        app.processEvents()
        stored = project.ui_state["plot_appearance"]
        assert stored["data_style"] == "points"
        assert stored["function_style"] == "lines"
        first_item = workspace._data_items[first.id]
        assert first_item.opts.get("symbol") is not None
        assert first_item.opts.get("pen") is None

        workspace.display_mode.setCurrentIndex(1)
        workspace.set_plot_appearance(
            {
                "data_style": "points",
                "data_point_size": 9.0,
                "different_markers": True,
                "function_style": "lines_points",
                "function_sum_line_width": 3.5,
                "grid_visible": False,
            }
        )
        app.processEvents()

        stored = project.ui_state["plot_appearance"]
        assert stored["data_style"] == "points"
        assert stored["data_point_size"] == 9.0
        assert stored["different_markers"] is True
        assert stored["function_style"] == "lines_points"
        assert stored["function_sum_line_width"] == 3.5
        assert stored["grid_visible"] is False
        assert workspace.plot_style_mode.currentData() == "points"

        symbols = [item.opts.get("symbol") for item in workspace._data_items.values()]
        assert len(symbols) == 2
        assert all(symbol is not None for symbol in symbols)
        assert symbols[0] != symbols[1]
    finally:
        project.dirty = False
        window.close()
        app.processEvents()
