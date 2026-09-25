"""Settings for numbering automatically named functions in one spectrum."""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from curvemole.core.models import Model
from curvemole.core.registry import FunctionRegistry

_KEY = "model/reorder_rules"


def load_reorder_rules(settings: QSettings) -> dict[str, str]:
    try:
        value = json.loads(str(settings.value(_KEY, "{}")))
        return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


class ReorderRulesDialog(QDialog):
    def __init__(self, model: Model, registry: FunctionRegistry, rules: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Advanced reorder rules"))
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        description = QLabel(self.tr(
            "Choose the parameter used to number each function type, from lowest to highest. "
            "Custom function names are never changed."))
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.fields: dict[str, QComboBox] = {}
        groups = {}
        for component in model.components:
            if not component.metadata.get("custom_name"):
                groups.setdefault(component.function_id, []).append(component)
        for function_id, components in groups.items():
            available = set(components[0].parameters)
            for component in components[1:]:
                available.intersection_update(component.parameters)
            if not available:
                continue
            options = list(components[0].parameters)
            options = [name for name in options if name in available]
            combo = QComboBox()
            combo.addItems(options)
            default = rules.get(function_id, "center")
            combo.setCurrentText(default if default in options else
                                 ("center" if "center" in options else options[0]))
            form.addRow(registry.get(function_id).display_name, combo)
            self.fields[function_id] = combo
        layout.addLayout(form)
        if not self.fields:
            layout.addWidget(QLabel(self.tr("No automatically named functions have sortable parameters.")))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def rules(self) -> dict[str, str]:
        return {function_id: combo.currentText() for function_id, combo in self.fields.items()}
