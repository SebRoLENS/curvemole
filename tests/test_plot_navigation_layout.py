from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QStyle,
    QStyleFactory,
    QStyleOptionComboBox,
)

from curvemole import Curve, Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.plot import PlotWorkspace
from curvemole.gui.scientific_axis import ScientificAxisItem


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    project = Project("Navigation")
    curve = Curve("Spectrum", [0, 1, 2, 3, 4], [0, 1, 2, 3, 1000])
    project.add_curve(curve)
    curve.add_mask("Outlier").excluded[-1] = True
    window = CurveMoleMainWindow(project)
    window.resize(1400, 850)
    window.show()
    app.processEvents()
    yield app, window
    project.dirty = False
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("button", [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton])
def test_double_click_frames_experimental_points(window, button):
    app, main = window
    workspace = main.plot_workspace
    workspace.view_box.setRange(xRange=(0, 2), yRange=(10, 20), padding=0)
    app.processEvents()
    pos = workspace.graphics.mapFromScene(workspace.view_box.mapViewToScene(QPointF(1, 15)))
    if button == Qt.MouseButton.RightButton:
        # The first click must leave the plot available for the second click.
        QTest.mouseClick(workspace.graphics.viewport(), button, pos=pos)
        assert workspace.view_box._context_menu_timer.isActive()
        assert not workspace.view_box.getMenu(None).isVisible()
    QTest.mouseDClick(workspace.graphics.viewport(), button, pos=pos)
    QTest.mouseRelease(workspace.graphics.viewport(), button, pos=pos)
    app.processEvents()
    x_range, y_range = workspace.view_box.viewRange()
    assert x_range[0] < 0
    if button == Qt.MouseButton.LeftButton:
        assert x_range[1] > 4
        assert y_range[1] > 1000
    else:
        assert 3 < x_range[1] < 4
        assert 3 < y_range[1] < 10
        assert not workspace.view_box._context_menu_timer.isActive()


@pytest.mark.parametrize("inverted", [False, True])
@pytest.mark.parametrize("locked", [False, True])
def test_right_drag_pans_without_changing_span(window, inverted, locked):
    app, main = window
    workspace = main.plot_workspace
    view = workspace.view_box
    workspace.set_reverse_x(inverted)
    workspace.set_reverse_y(inverted)
    workspace.set_view_locked(locked)
    view.setMouseMode(view.RectMode)
    view.setRange(xRange=(1, 3), yRange=(10, 20), padding=0)
    app.processEvents()
    before = np.asarray(view.viewRange())

    class Drag:
        def button(self):
            return Qt.MouseButton.RightButton

        def pos(self):
            return QPointF(220, 150)

        def lastPos(self):
            return QPointF(180, 120)

        def accept(self):
            pass

    view.mouseDragEvent(Drag())
    after = np.asarray(view.viewRange())
    np.testing.assert_allclose(np.diff(after, axis=1), np.diff(before, axis=1))
    if locked:
        np.testing.assert_allclose(after, before)
    else:
        assert not np.allclose(after, before)
        assert (after[0, 0] > before[0, 0]) == inverted


@pytest.mark.parametrize("style_name", ["Fusion", "Windows"])
@pytest.mark.parametrize("constrain_dock_width", [False, True])
def test_plot_controls_wrap_inside_resized_docks(window, style_name, constrain_dock_width):
    app, main = window
    style = QStyleFactory.create(style_name)
    if style is None:
        pytest.skip(f"{style_name} style unavailable")
    main.setStyle(style)
    workspace = main.plot_workspace
    font = workspace.view_controls.font()
    font.setPointSize(14)
    workspace.view_controls.setFont(font)
    workspace.coordinate_label.setText(
        "x: 1234.5678   y: 987654.321   |   Long spectrum name with coordinates: (1234.5, 987654.3)"
    )
    docks = [dock for dock in main.findChildren(QDockWidget)
             if main.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
             and dock.isVisible() and not dock.isFloating()]
    if constrain_dock_width:
        for dock in docks:
            dock.setFixedWidth(dock.width())
    for width in (300, 650, 300):
        main.resizeDocks(docks, [width] * len(docks), Qt.Orientation.Horizontal)
        app.processEvents()
        controls = workspace.view_controls
        assert controls.geometry().right() < workspace.width()
        assert controls.width() == workspace.width()
        for row_index in range(controls.layout().count()):
            row = controls.layout().itemAt(row_index).layout()
            for index in range(row.count()):
                widget = row.itemAt(index).widget()
                if widget.isVisible():
                    rect = widget.geometry()
                    assert controls.rect().contains(rect), (widget, rect, controls.rect())
        label = workspace.coordinate_label
        assert label.height() >= label.heightForWidth(label.width())
        assert workspace.graphics.mapTo(workspace, QPoint()).y() >= controls.geometry().bottom()

    # resizeDocks requests sizes; Qt can constrain both requests to the same
    # actual width on Windows/offscreen desktops. Verify wrapping with explicit
    # layout widths, while keeping all containment checks above for real docks.
    display_row = controls.layout().itemAt(0).layout()
    items = [display_row.itemAt(index) for index in range(display_row.count())
             if not display_row.itemAt(index).isEmpty()]
    wide = sum(item.sizeHint().width() for item in items)
    wide += display_row.spacing() * (len(items) - 1)
    narrow = display_row.minimumSize().width()
    assert display_row.hasHeightForWidth()
    assert display_row.heightForWidth(narrow) > display_row.heightForWidth(wide)


@pytest.mark.parametrize("style_name", ["Fusion", "Windows"])
@pytest.mark.parametrize("enlarged_font", [False, True])
@pytest.mark.parametrize("width", [360, 720])
def test_plot_control_text_fits_native_content_rects(style_name, enlarged_font, width):
    """Widget containment alone misses text hidden under arrows or elided axes."""
    from curvemole.core.registry import default_registry

    app = QApplication.instance() or QApplication([])
    style = QStyleFactory.create(style_name)
    if style is None:
        pytest.skip(f"{style_name} style unavailable")
    workspace = PlotWorkspace(default_registry())
    try:
        workspace.resize(width, 650)
        workspace.show()
        controls = (workspace.plot_style_mode, workspace.autoscale_mode,
                    workspace.coordinate_label)
        for control in controls:
            control.setStyle(style)
            if enlarged_font:
                # Application stylesheets can specify their own pixel font;
                # explicitly enlarge the effective control font as high-DPI
                # systems and accessibility settings do.
                control.setStyleSheet("font-size: 14pt;")
        workspace.plot_style_mode.setCurrentIndex(2)
        workspace.autoscale_mode.setCurrentIndex(1)
        app.processEvents()
        for combo in (workspace.plot_style_mode, workspace.autoscale_mode):
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            text_rect = combo.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox, option,
                QStyle.SubControl.SC_ComboBoxEditField, combo,
            )
            assert combo.fontMetrics().horizontalAdvance(combo.currentText()) <= text_rect.width(), (
                combo.currentText(), text_rect, combo.size(), combo.font().toString(),
            )

        label = workspace.coordinate_label
        coordinate_widths = []
        for x, y in (("12.5", "-0.25"), ("-1.2345678e+123", "9.8765432e-123")):
            reading = f"x: {x}   y: {y}   |   A long spectrum name: ({x}, {y})"
            label.setText(reading)
            app.processEvents()
            # CoordinateReadout.text() intentionally exposes the original full
            # reading; QLabel.text() is the string that is actually painted.
            painted = QLabel.text(label)
            assert x in painted and y in painted
            assert "…" not in painted
            assert label.toolTip() == reading
            contents = label.contentsRect()
            flags = int(label.alignment())
            if label.wordWrap():
                flags |= int(Qt.TextFlag.TextWordWrap)
            bounds = label.fontMetrics().boundingRect(contents, flags, painted)
            assert bounds.width() <= contents.width()
            assert bounds.height() <= contents.height()
            assert workspace.view_controls.rect().contains(label.geometry())
            coordinate_widths.append(label.width())
        assert len(set(coordinate_widths)) == 1  # Cursor motion must not move the control rows.
    finally:
        workspace.close()
        workspace.deleteLater()
        app.processEvents()


def test_mouse_coordinate_readout_wraps_inside_narrow_main_window(window):
    app, main = window
    workspace = main.plot_workspace
    workspace.setFixedWidth(320)
    label = workspace.coordinate_label
    label.setStyleSheet("font-size: 14pt;")
    reading = "x: -1.2345678e+123   y: 9.8765432e-123   |   Spectrum: (0, 1)"
    try:
        for theme in ("light", "dark", "light"):
            main.apply_theme(theme)
            label.setText(reading)
            app.processEvents()
            assert workspace.view_controls.width() == 320
            assert workspace.view_controls.rect().contains(label.geometry())
            painted = QLabel.text(label)
            assert "-1.2345678e+123" in painted and "9.8765432e-123" in painted
            assert "…" not in painted
            assert label.toolTip() == reading
            assert label.wordWrap()
            contents = label.contentsRect()
            bounds = label.fontMetrics().boundingRect(
                contents, int(label.alignment()) | int(Qt.TextFlag.TextWordWrap), painted,
            )
            assert bounds.width() <= contents.width()
            assert bounds.height() <= contents.height()
            assert label.height() > label.fontMetrics().height()
    finally:
        main.apply_theme("system")


@pytest.mark.parametrize("unit", ["nm", "s", "Pa"])
@pytest.mark.parametrize("magnitude", [0.0002, 0.2, 200, 1000, 10000, 1e6, 1e10])
def test_axis_preserves_original_data_units(window, unit, magnitude):
    axis = ScientificAxisItem("bottom")
    axis.setLabel("Axis", units=unit)
    axis.setRange(-magnitude, magnitude)
    assert axis.labelUnitPrefix == ""
    assert axis.autoSIPrefixScale == 1
    assert axis.labelUnits == unit
    axis.setLogMode(True)
    axis.setRange(np.log10(magnitude) - 1, np.log10(magnitude))
    assert axis.labelUnitPrefix == ""
    assert axis.autoSIPrefixScale == 1


def test_scientific_notation_depends_on_available_width(window):
    axis = ScientificAxisItem("bottom")
    axis.setLabel("Wavelength", units="nm")
    axis.setRange(0, 4e10)
    axis.resize(1800, 50)
    values = [1e10, 2e10, 3e10]
    assert axis.tickStrings(values, 1, 1e10) == ["10000000000", "20000000000", "30000000000"]
    axis.resize(240, 50)
    labels = axis.tickStrings(values, 1, 1e10)
    assert labels == ["1e+10", "2e+10", "3e+10"]
    np.testing.assert_allclose([float(label) for label in labels], values)
    assert axis.labelUnits == "nm"


def test_small_ticks_keep_distinct_scientific_values(window):
    axis = ScientificAxisItem("bottom")
    axis.setRange(0, 4e-10)
    axis.resize(240, 50)
    values = [1.1e-10, 1.2e-10, 1.3e-10]
    labels = axis.tickStrings(values, 1, 1e-11)
    assert len(set(labels)) == len(values)
    np.testing.assert_allclose([float(label) for label in labels], values, rtol=1e-12, atol=0)
    assert axis.tickStrings([0], 1, 1e-11) == ["0"]
