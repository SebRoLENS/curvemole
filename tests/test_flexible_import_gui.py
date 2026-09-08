from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6", exc_type=ImportError)
pytest.importorskip("pyqtgraph", exc_type=ImportError)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu, QMessageBox

from curvemole import Project
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import ImportMappingDialog


def test_import_dialog_exposes_detected_leading_rows(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "spectrum.xy"
    path.write_text(
        "Instrument: CurveLab\n"
        "Acquisition: test\n"
        "x y\n"
        "0 1\n"
        "1 2\n",
        encoding="utf-8",
    )

    dialog = ImportMappingDialog(path)

    assert dialog.skip_rows.value() == 2
    assert dialog.config().skip_rows == 2

    dialog.close()
    app.processEvents()


@pytest.mark.parametrize("apply_all", [False, True])
def test_batch_import_series_name_and_later_rename(tmp_path, monkeypatch, apply_all):
    app = QApplication.instance() or QApplication([])
    paths = []
    for index in range(2):
        path = tmp_path / f"spectrum{index}.txt"
        path.write_text("x y\n0 1\n1 2\n2 3\n", encoding="utf-8")
        paths.append(str(path))
    window = CurveMoleMainWindow(Project())
    monkeypatch.setattr(window, "_automatic_update_check", lambda: None)
    monkeypatch.setattr(window, "_show_error", lambda title, exc: pytest.fail(f"{title}: {exc}"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail(str(args)))
    proposed = []

    def accept(dialog):
        proposed.append(dialog.series_name.text())
        dialog.series_name.setText("Raman")
        dialog.apply_all.setChecked(apply_all)
        dialog._accept()
        return dialog.result()

    monkeypatch.setattr(ImportMappingDialog, "exec", accept)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: (paths, ""))
    window.import_action.trigger()
    assert proposed == (["Series 1"] if apply_all else ["Series 1", "Raman"])
    series = window.project.dataset.series[0]
    assert series.name == "Raman"
    assert len(series.curves) == 2
    assert window._next_series_name() == "Series 2"
    tree = window.curve_tree
    window.show()
    app.processEvents()
    item = tree.topLevelItem(0)
    prompted = []

    def finish_rename():
        dialog = app.activeModalWidget()
        if isinstance(dialog, QInputDialog):
            prompted.append(dialog.textValue())
            dialog.setTextValue("Pressure scan")
            dialog.accept()

    def choose_rename():
        menu = app.activePopupWidget()
        if isinstance(menu, QMenu):
            try:
                for action in menu.actions():
                    if action.text() == "Rename series…":
                        QTimer.singleShot(0, finish_rename)
                        action.trigger()
                        break
            finally:
                menu.close()

    QTimer.singleShot(0, choose_rename)
    tree._show_context_menu(tree.visualItemRect(item).center())
    assert prompted == ["Raman"]
    assert series.name == "Pressure scan"
    assert window.curve_tree.topLevelItem(0).text(1) == "Pressure scan"
    def cancel_rename():
        dialog = app.activeModalWidget()
        if isinstance(dialog, QInputDialog):
            dialog.setTextValue("Discard this")
            dialog.reject()

    QTimer.singleShot(0, cancel_rename)
    window._prompt_rename_series(series.id)
    assert series.name == "Pressure scan"

    def default(dialog):
        assert dialog.series_name.text() == "Series 2"
        dialog._accept()
        return dialog.result()

    monkeypatch.setattr(ImportMappingDialog, "exec", default)
    window.import_data(paths[:1])
    assert [item.name for item in window.project.dataset.series] == ["Pressure scan", "Series 2"]
    window.project.dirty = False
    window.close()
    app.processEvents()
