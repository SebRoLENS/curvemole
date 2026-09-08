"""Plain-text project notebook with grouped, editable object descriptions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.notebook import Description, export_notebook
from curvemole.core.project import Project


class DescriptionDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Add description"))
        self.resize(620, 380)
        layout = QVBoxLayout(self)
        label = QLabel(title)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(self.tr("Sample details, preparation, interpretation, fitting choices…"))
        self.editor.setPlainText(text)
        layout.addWidget(self.editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LaboratoryNotebookDialog(QDialog):
    def __init__(self, project: Project, parent=None, *, editable: bool = True):
        super().__init__(parent)
        self.project = project
        self.editable = editable and not project.read_only
        self.current_key: str | None = None
        project.notebook.sync(project)
        self.setWindowTitle(self.tr("Laboratory notebook") + " — " + project.name)
        self.resize(950, 640)
        layout = QVBoxLayout(self)
        hint = QLabel(self.tr("Notes are kept in the project. Save the project to preserve them on disk.")
                      if self.editable else self.tr("Read-only view. Notes cannot be edited while a task is running or in a read-only project."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tabs = QTabWidget()
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText(self.tr("Experimental conditions, observations, decisions and next steps…"))
        self.notes.setPlainText(project.notebook.notes)
        self.notes.setReadOnly(not self.editable)
        self.notes.textChanged.connect(self._notes_changed)
        self.tabs.addTab(self.notes, self.tr("Project notes"))

        descriptions = QWidget()
        desc_layout = QVBoxLayout(descriptions)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search names and descriptions…"))
        self.search.textChanged.connect(self._populate)
        desc_layout.addWidget(self.search)
        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([self.tr("Series / spectrum / function")])
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._select)
        splitter.addWidget(self.tree)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.context = QLabel(self.tr("Select a description on the left."))
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.context.setWordWrap(True)
        detail_layout.addWidget(self.context)
        self.description = QPlainTextEdit()
        self.description.setReadOnly(True)
        self.description.textChanged.connect(self._description_changed)
        detail_layout.addWidget(self.description)
        splitter.addWidget(detail)
        splitter.setSizes([340, 560])
        desc_layout.addWidget(splitter)
        self.tabs.addTab(descriptions, self.tr("Series, spectra & functions"))
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.export_button = QPushButton(self.tr("Save notebook as text…"))
        self.export_button.clicked.connect(self._export)
        buttons.addButton(self.export_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _notes_changed(self):
        if self.editable:
            self.project.notebook.notes = self.notes.toPlainText()
            self.project.touch()

    def _populate(self, *_):
        selected_key = self.current_key
        self.tree.clear()
        self.current_key = None
        groups = {}
        selected = None
        query = self.search.text().casefold().strip()
        for entry in self.project.notebook.ordered_descriptions():
            if query and query not in (entry.title + "\n" + entry.text).casefold():
                continue
            group_name = self.tr("Deleted items — descriptions retained") if entry.deleted else entry.series_name
            group_key = (entry.deleted, group_name)
            if group_key not in groups:
                groups[group_key] = QTreeWidgetItem(self.tree, [group_name])
            parent = groups[group_key]
            if entry.kind in {"spectrum", "function"} and not entry.deleted:
                curve_key = (False, group_name, entry.object_id if entry.kind == "spectrum" else entry.curve_id)
                if curve_key not in groups:
                    groups[curve_key] = QTreeWidgetItem(parent, [entry.curve_name])
                parent = groups[curve_key]
            title = entry.title if entry.deleted else (
                self.tr("Series description") if entry.kind == "series" else (
                    self.tr("Spectrum description") if entry.kind == "spectrum" else f"{entry.name} ({entry.function_id})"
                )
            )
            item = QTreeWidgetItem(parent, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.key)
            if entry.key == selected_key:
                selected = item
        self.tree.expandAll()
        if selected is not None:
            self.tree.setCurrentItem(selected)
        elif not groups:
            self.context.setText(self.tr("No descriptions. Right-click a series, spectrum or added fit function and choose Add description."))

    def _select(self, item, _previous):
        self.current_key = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        entry = self.project.notebook.descriptions.get(self.current_key)
        self.description.blockSignals(True)
        self.description.setPlainText(entry.text if entry else "")
        self.description.blockSignals(False)
        self.description.setReadOnly(not (entry and self.editable))
        self.context.setText(self._context(entry) if entry else self.tr("Select a description on the left."))

    def _context(self, entry: Description) -> str:
        state = self.tr("DELETED — this description has been retained.") if entry.deleted else self.tr("Present in the project")
        return f"{entry.title}\n{state}\n{self.tr('Description updated:')} {entry.updated_at}"

    def _description_changed(self):
        if self.editable and self.current_key:
            entry = self.project.notebook.descriptions[self.current_key]
            self.project.notebook.set_description(self.project, entry.kind, entry.object_id,
                                                  self.description.toPlainText(), entry.curve_id)
            if self.current_key not in self.project.notebook.descriptions:
                self._populate()
                return
            self.context.setText(self._context(entry))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save laboratory notebook"),
                                             "laboratory_notebook.txt", self.tr("Text files (*.txt)"))
        if not path:
            return
        try:
            export_notebook(self.project, path)
        except OSError as exc:
            QMessageBox.warning(self, self.tr("Export failed"), str(exc))
