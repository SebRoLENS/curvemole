import pytest

from curvemole.gui import window_extensions


def test_contributions_run_in_registration_order_and_keys_replace_in_place(monkeypatch):
    monkeypatch.setattr(window_extensions, "_contributions", {stage: [] for stage in window_extensions.STAGES})
    calls = []
    window_extensions.register("actions", lambda window: calls.append("first"), key="a")
    window_extensions.register("actions", lambda window: calls.append("second"), key="b")
    window_extensions.register("actions", lambda window: calls.append("first again"), key="a")
    window_extensions.run(object(), "actions")
    assert calls == ["first again", "second"]
    assert window_extensions.contributions("actions") == ["a", "b"]
    with pytest.raises(ValueError, match="Unknown window extension stage"):
        window_extensions.register("menu", lambda window: None)


def test_main_window_runs_registered_contributions():
    from PySide6.QtWidgets import QApplication

    from curvemole.gui.app import CurveMoleMainWindow

    app = QApplication.instance() or QApplication([])
    window = CurveMoleMainWindow()
    try:
        file_menu = window_extensions.find_menu(window, "File")
        assert window.export_spectra_action in file_menu.actions()  # spectrum_export_ui contribution
        assert window.quick_add_button is not None  # quick_function_library toolbar contribution
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()
