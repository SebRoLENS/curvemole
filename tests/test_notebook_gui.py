from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QToolBar, QTreeWidgetItemIterator

from curvemole import Component, Curve, Project, Series
from curvemole.core.notebook import description_key
from curvemole.gui.app import CurveMoleMainWindow
from curvemole.gui.dialogs import ExportBundleDialog
from curvemole.gui.notebook import DescriptionDialog, LaboratoryNotebookDialog


def test_real_context_menus_edit_series_spectrum_and_clicked_function():
    app = QApplication.instance() or QApplication([])
    project = Project()
    curves = [Curve(name, [0., 1., 2.], [1., 2., 3.]) for name in ("A", "B")]
    series = Series("Series", curves)
    project.add_series(series)
    component = Component.create("constant")
    for curve in curves:
        project.add_component(curve.id, copy.deepcopy(component))
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    seen = []

    def edit_menu(widget, item, text):
        def finish():
            dialog = app.activeModalWidget()
            if isinstance(dialog, DescriptionDialog):
                seen.append(dialog.editor.toPlainText())
                dialog.editor.setPlainText(text)
                dialog.accept()

        def choose():
            menu = app.activePopupWidget()
            if isinstance(menu, QMenu):
                try:
                    for action in menu.actions():
                        if action.text() == "Add description…":
                            QTimer.singleShot(0, finish)
                            action.trigger()
                            break
                finally:
                    menu.close()

        QTimer.singleShot(0, choose)
        widget.customContextMenuRequested.emit(widget.visualItemRect(item).center())

    tree = window.curve_tree
    tree.expandAll()
    edit_menu(tree, tree.topLevelItem(0), "Series note")
    edit_menu(tree, tree.topLevelItem(0).child(0), "Spectrum note")
    panel = window.model_panel
    panel.show_all_functions.setChecked(True)
    app.processEvents()
    # Click the second spectrum's function while the first remains selected.
    target = next(panel.components.item(i) for i in range(panel.components.count())
                  if panel.components.item(i).data(int(Qt.ItemDataRole.UserRole) + 1) == curves[1].id)
    edit_menu(panel.components, target, "Second spectrum function note")
    assert seen == ["", "", ""]
    notes = project.notebook.descriptions
    assert notes[description_key("series", series.id)].text == "Series note"
    assert notes[description_key("spectrum", curves[0].id)].text == "Spectrum note"
    assert notes[description_key("function", component.id, curves[1].id)].text == "Second spectrum function note"
    assert description_key("function", component.id, curves[0].id) not in notes
    # Editing opens the saved text, and Cancel preserves it.
    def cancel():
        dialog = app.activeModalWidget()
        if isinstance(dialog, DescriptionDialog):
            seen.append(dialog.editor.toPlainText())
            dialog.editor.setPlainText("Discarded")
            dialog.reject()
    QTimer.singleShot(0, cancel)
    window.describe_series(series.id)
    assert seen[-1] == "Series note"
    assert notes[description_key("series", series.id)].text == "Series note"
    toolbar = window.findChild(QToolBar, "Main_toolbar")
    assert toolbar.actions()[-1] == window.notebook_action
    assert not window.notebook_action.icon().isNull()
    def use_notebook():
        dialog = app.activeModalWidget()
        if isinstance(dialog, LaboratoryNotebookDialog):
            dialog.notes.setPlainText("General notes")
            dialog.reject()
    QTimer.singleShot(0, use_notebook)
    window.notebook_action.trigger()
    assert project.notebook.notes == "General notes"
    project.dirty = False
    window.close()


def test_notebook_deleted_descriptions_edit_export_and_read_only(tmp_path, monkeypatch):
    _app = QApplication.instance() or QApplication([])
    project = Project()
    series = Series("Deleted series")
    project.add_series(series)
    project.notebook.set_description(project, "series", series.id, "Retain me")
    project.dataset.series.remove(series)
    project.touch()
    dialog = LaboratoryNotebookDialog(project)
    iterator = QTreeWidgetItemIterator(dialog.tree)
    while iterator.value() and not iterator.value().data(0, Qt.ItemDataRole.UserRole):
        iterator += 1
    dialog.tree.setCurrentItem(iterator.value())
    assert "DELETED" in dialog.context.text()
    assert dialog.description.toPlainText() == "Retain me"
    dialog.description.setPlainText("Retained and amended")
    dialog.notes.setPlainText("Experiment notes")
    path = tmp_path / "notebook.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), "Text files (*.txt)"))
    dialog.export_button.click()
    assert "[DELETED] Deleted series" in path.read_text(encoding="utf-8")
    assert "Retained and amended" in path.read_text(encoding="utf-8")
    assert "Experiment notes" in path.read_text(encoding="utf-8")
    dialog.close()
    project.read_only = True
    viewer = LaboratoryNotebookDialog(project)
    assert viewer.notes.isReadOnly()
    assert viewer.description.isReadOnly()
    assert viewer.export_button.isEnabled()
    viewer.close()
    export_dialog = ExportBundleDialog(None)
    export_dialog.fit_results.setChecked(False)
    export_dialog.laboratory_notebook.setChecked(True)
    assert export_dialog.selection().any_selected()
    assert export_dialog.selection().laboratory_notebook
    export_dialog.close()


def test_click_note_icon_and_remove_empty_description():
    from PySide6.QtTest import QTest
    from curvemole.gui.note_indicators import NOTE_ROLE

    app = QApplication.instance() or QApplication([])
    project = Project()
    series = Series("Series", [Curve("A", [0., 1.], [0., 1.])])
    project.add_series(series)
    project.notebook.set_description(project, "series", series.id, "Open this note")
    window = CurveMoleMainWindow(project)
    window.show()
    app.processEvents()
    tree = window.curve_tree
    item = tree.topLevelItem(0)
    assert item.font(1).bold()
    index = tree.indexFromItem(item, 1)
    rect = tree.itemDelegate().note_rect(index)
    assert rect.isValid()
    seen = []

    def edit():
        dialog = app.activeModalWidget()
        if isinstance(dialog, DescriptionDialog):
            seen.append(dialog.editor.toPlainText())
            dialog.editor.setPlainText("   ")
            dialog.accept()

    QTimer.singleShot(0, edit)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert seen == ["Open this note"]
    assert not project.notebook.descriptions
    assert not tree.topLevelItem(0).data(1, NOTE_ROLE)
    assert "Empty description" not in project.notebook.as_text(project)
    project.dirty = False
    window.close()
