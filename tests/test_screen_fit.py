from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
)

from curvemole.gui.screen_fit import available_size, install


def _tall_dialog():
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    for index in range(80):
        label = QLabel(f"Option {index}")
        label.setMinimumHeight(24)
        layout.addWidget(label)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(buttons)
    return dialog, buttons


def test_tall_dialog_scrolls_and_keeps_its_buttons_on_screen(monkeypatch):
    monkeypatch.setenv("CURVEMOLE_SCREEN_FIT", "1")
    app = QApplication.instance() or QApplication([])
    install(app)
    dialog, buttons = _tall_dialog()
    dialog.resize(500, 3000)
    dialog.show()
    app.processEvents()
    limit = available_size(dialog)
    assert dialog.height() <= limit.height()
    assert dialog.findChild(QScrollArea) is not None
    assert buttons.parent() is dialog and buttons.isVisible()
    assert not dialog.findChild(QScrollArea).isAncestorOf(buttons)
    dialog.close()


def test_small_dialog_is_left_alone(monkeypatch):
    monkeypatch.setenv("CURVEMOLE_SCREEN_FIT", "1")
    app = QApplication.instance() or QApplication([])
    install(app)
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(QLabel("Short"))
    dialog.resize(300, 200)
    dialog.show()
    app.processEvents()
    assert dialog.findChild(QScrollArea) is None
    assert (dialog.width(), dialog.height()) == (300, 200)
    dialog.close()


def test_headless_platform_keeps_requested_sizes_by_default(monkeypatch):
    monkeypatch.delenv("CURVEMOLE_SCREEN_FIT", raising=False)
    app = QApplication.instance() or QApplication([])
    if app.platformName() != "offscreen":
        return
    dialog, _ = _tall_dialog()
    assert available_size(dialog) is None
