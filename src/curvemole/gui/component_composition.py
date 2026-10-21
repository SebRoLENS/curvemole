"""Inline composition controls that preserve function selection and note icons."""

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QVBoxLayout,
)
from shiboken6 import isValid

from curvemole.gui.function_composition import OPERATORS
from curvemole.gui.note_indicators import NoteIndicatorDelegate

COMPOSITION_ROLE = int(Qt.ItemDataRole.UserRole) + 22
_CURVE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def add_composition_actions(menu, panel, curve_id, component_id):
    model = panel.project.model_for(curve_id)
    component = model.component(component_id)
    menu.setToolTipsVisible(True)
    for operator, symbol, label in OPERATORS:
        action = menu.addAction(symbol + " " + panel.tr(label))
        action.setData(operator)
        action.setCheckable(True)
        action.setChecked(component.operator == operator)
        allowed = not panel.project.read_only
        reason = panel.tr("Set this function's global role. Calculation order chooses when factors and convolutions act.")
        try:
            model.clone().set_component_operator(component_id, operator)
        except Exception as exc:
            allowed = False
            reason = str(exc)
        action.setEnabled(allowed)
        action.setToolTip(reason)
        action.triggered.connect(
            lambda checked=False, op=operator: panel.compositionRequested.emit(curve_id, component_id, op)
        )


class ComponentCompositionDelegate(NoteIndicatorDelegate):
    def __init__(self, panel):
        super().__init__(panel.components, panel.noteRequested.emit)
        self.panel = panel

    def composition_rect(self, index):
        rect = self.view.visualRect(index)
        width = max(self.view.fontMetrics().horizontalAdvance(symbol + " " + operator)
                    for operator, symbol, _ in OPERATORS) + 34
        right = min(rect.right(), self.view.viewport().rect().right()) - 3
        height = min(rect.height() - 2, self.view.fontMetrics().height() + 10)
        return QRect(max(rect.left(), right - width), rect.center().y() - height // 2, width, height)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(COMPOSITION_ROLE):
            size.setHeight(max(size.height(), self.view.fontMetrics().height() + 14))
        return size

    def paint(self, painter, option, index):
        operator = index.data(COMPOSITION_ROLE)
        if not operator:
            return super().paint(painter, option, index)
        rect = self.composition_rect(index)
        text_option = QStyleOptionViewItem(option)
        text_option.rect.setRight(rect.left() - 4)
        super().paint(painter, text_option, index)
        combo = QStyleOptionComboBox()
        combo.rect = rect
        combo.palette = self.view.palette()
        combo.fontMetrics = option.fontMetrics
        combo.currentText = next((symbol for op, symbol, _ in OPERATORS if op == operator), "") + " " + operator
        combo.state = QStyle.StateFlag.State_Active
        if self.panel.project and not self.panel.project.read_only:
            combo.state |= QStyle.StateFlag.State_Enabled
        style = self.view.style()
        style.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, combo, painter, self.view)
        style.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, combo, painter, self.view)

    def _open_menu(self, index):
        if not index.isValid() or not index.data(COMPOSITION_ROLE):
            return False
        menu = QMenu(self.view)
        add_composition_actions(menu, self.panel, str(index.data(_CURVE_ROLE)),
                                str(index.data(Qt.ItemDataRole.UserRole)))
        menu.aboutToHide.connect(menu.deleteLater)
        self._menu = menu
        menu.popup(self.view.viewport().mapToGlobal(self.composition_rect(index).bottomLeft()))
        return True

    def eventFilter(self, watched, event):
        if isValid(self.view) and watched is self.view.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                point = event.position().toPoint()
                index = self.view.indexAt(point)
                if index.data(COMPOSITION_ROLE) and self.composition_rect(index).contains(point):
                    return self._open_menu(index)
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F4:
                return self._open_menu(self.view.currentIndex())
        return super().eventFilter(watched, event)


def update_composition_summary(panel):
    refs = panel.selected_component_refs()
    curves = {ref[0] for ref in refs}
    curve_id = next(iter(curves)) if len(curves) == 1 else panel.curve_id
    panel._composition_curve_id = curve_id
    panel.calculation_order_button.setEnabled(bool(panel.project and curve_id and not panel.project.read_only))
    if not panel.project or not curve_id:
        panel.composition_summary.clear()
        return
    model = panel.project.model_for(curve_id)
    mode = panel.tr("Global roles") if model.composition_mode == "global" else panel.tr("Saved ordered model")
    text = mode + ": " + model.calculation_expression()
    panel.composition_summary.setText(text)
    panel.composition_summary.setToolTip(text)
    panel.calculation_order_button.setToolTip(panel.tr("Calculation order for ") + panel.project.dataset.curve(curve_id).name)


class CalculationOrderDialog(QDialog):
    def __init__(self, model, spectrum_name, parent=None):
        super().__init__(parent)
        self.model = model.clone()
        self.setWindowTitle(self.tr("Calculation order — ") + spectrum_name)
        self.resize(640, 500)
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Global function roles (independent of insertion order)"), "global")
        self.mode.addItem(self.tr("Saved ordered composition (legacy projects)"), "ordered")
        self.mode.setCurrentIndex(self.mode.findData(model.composition_mode))
        layout.addWidget(self.mode)
        note = QLabel(self.tr(
            "Global roles: Add and Subtract form the starting sum. Arrange Multiply, Divide "
            "and Convolve below in the order you want them applied, from top to bottom. "
            "This order is separate from the function list. Saved ordered models keep their "
            "original calculation until you explicitly switch to global roles."
        ))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.operations = QListWidget()
        self.operations.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for component in model.ordered_operations:
            text = component.name + " — " + component.operator
            if not component.enabled:
                text += self.tr(" (disabled)")
            item = QListWidgetItem(text, self.operations)
            item.setData(Qt.ItemDataRole.UserRole, component.id)
        layout.addWidget(self.operations)
        row = QHBoxLayout()
        for label, offset in ((self.tr("Move up"), -1), (self.tr("Move down"), 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, step=offset: self._move(step))
            row.addWidget(button)
        layout.addLayout(row)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._refresh)
        self.operations.model().rowsMoved.connect(self._refresh)
        self._refresh()

    def _move(self, offset):
        row = self.operations.currentRow()
        destination = row + offset
        if row < 0 or not 0 <= destination < self.operations.count() or self.mode.currentData() != "global":
            return
        item = self.operations.takeItem(row)
        self.operations.insertItem(destination, item)
        self.operations.setCurrentRow(destination)
        self._refresh()

    def choices(self):
        return self.mode.currentData(), [self.operations.item(i).data(Qt.ItemDataRole.UserRole)
                                         for i in range(self.operations.count())]

    def _refresh(self, *_args):
        self.model.composition_mode, self.model.operation_order = self.choices()
        self.operations.setEnabled(self.model.composition_mode == "global")
        self.preview.setText(self.tr("Resulting model: ") + self.model.calculation_expression())
