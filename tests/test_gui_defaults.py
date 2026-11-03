from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QLocale
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from curvemole.gui.app import _configure_gui_defaults


def test_gui_defaults_use_decimal_point() -> None:
    _configure_gui_defaults()
    assert QLocale().decimalPoint() == "."


def test_gui_defaults_use_single_button_mouse_mode() -> None:
    _configure_gui_defaults()
    assert pg.getConfigOption("leftButtonPan") is False


def test_gui_defaults_keep_dark_controls_consistent_with_native_fonts() -> None:
    from curvemole.gui.app import create_main_window

    app = QApplication.instance() or QApplication([])
    previous_palette, previous_stylesheet = app.palette(), app.styleSheet()
    app.setStyle("Windows")
    native_font = app.font()
    _configure_gui_defaults()
    assert app.style().objectName().lower() == "fusion"
    assert app.font() == native_font
    window = create_main_window()
    previous_theme = window.settings.value("theme", "system")
    try:
        for theme in ("system", "light", "dark"):
            window.apply_theme(theme)
            assert window.settings.value("theme") == theme
        assert window.palette().color(QPalette.ColorRole.Window).lightness() < 128
        assert window.model_panel.palette().color(QPalette.ColorRole.Text).lightness() > 128
    finally:
        window.apply_theme(previous_theme)
        window.close()
        app.setPalette(previous_palette)
        app.setStyleSheet(previous_stylesheet)
        app.processEvents()
