"""BackgroundComponentsDialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curvemole.core.plugin_identity import function_tooltip
from curvemole.core.project import Project
from curvemole.core.registry import FunctionRegistry
from curvemole.gui.dialogs._shared import (
    _name_accept,
    _set_list_checked,
)
from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401


class BackgroundComponentsDialog(QDialog):
    """Choose model components that define the background to subtract."""

    def __init__(
        self,
        project: Project,
        curve_id: str,
        registry: FunctionRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.curve_id = curve_id
        self.registry = registry
        model = project.model_for(curve_id)
        marked = [component for component in model.components if component.is_background]
        self.marking_mode = not marked
        candidates = [
            component
            for component in (model.components if self.marking_mode else marked)
            if component.enabled
        ]

        self.setWindowTitle(self.tr("Subtract background"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        if self.marking_mode:
            message = self.tr(
                "No model functions are marked as background. Indicate which functions represent "
                "the background. The selected functions will be marked as background and subtracted."
            )
        else:
            message = self.tr(
                "Select which functions marked as background should be subtracted from the data."
            )
        explanation = QLabel(message)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.components = QListWidget()
        for component in candidates:
            definition = registry.get(component.function_id)
            item = QListWidgetItem(f"{component.name}  ·  {definition.display_name}")
            item.setToolTip(function_tooltip(definition))
            item.setData(Qt.ItemDataRole.UserRole, component.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Unchecked if self.marking_mode else Qt.CheckState.Checked
            )
            self.components.addItem(item)
        layout.addWidget(self.components, 1)

        selection = QHBoxLayout()
        select_all = QPushButton(self.tr("Select all"))
        deselect_all = QPushButton(self.tr("Deselect all"))
        select_all.clicked.connect(lambda: _set_list_checked(self.components, True))
        deselect_all.clicked.connect(lambda: _set_list_checked(self.components, False))
        selection.addWidget(select_all)
        selection.addWidget(deselect_all)
        selection.addStretch(1)
        layout.addLayout(selection)

        if not candidates:
            empty = QLabel(
                self.tr(
                    "There are no enabled candidate functions. Add or enable a model function first."
                )
            )
            empty.setWordWrap(True)
            layout.addWidget(empty)

        self.apply_to_all_spectra = QCheckBox(self.tr("Apply to all spectra"), self)
        self.apply_to_all_spectra.setToolTip(self.tr(
            "Off: subtract the selected background functions only from the current spectrum. "
            "On: apply subtraction to every spectrum using every enabled function already marked "
            "as background on that spectrum."))
        # With backgrounds already marked, the global mode uses all of them, so the
        # checklist is not meaningful; in first-use marking mode it still designates
        # the current spectrum's backgrounds.
        self.apply_to_all_spectra.toggled.connect(
            lambda enabled: None if self.marking_mode else self.components.setEnabled(not enabled))
        layout.addWidget(self.apply_to_all_spectra)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _name_accept(self.buttons, self.tr("Subtract"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(candidates))
        layout.addWidget(self.buttons)

    def selected_component_ids(self) -> list[str]:
        return [
            str(self.components.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.components.count())
            if self.components.item(index).checkState() == Qt.CheckState.Checked
        ]
