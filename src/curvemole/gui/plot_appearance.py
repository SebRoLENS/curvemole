"""Project-scoped plot appearance settings and editor dialog."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from curvemole.gui.colours import MODEL_SUM_COLOUR

PLOT_STYLES: tuple[tuple[str, str], ...] = (
    ("lines", "Lines"),
    ("points", "Points"),
    ("lines_points", "Lines + points"),
)
LINE_STYLES: tuple[tuple[str, str], ...] = (
    ("solid", "Solid"),
    ("dash", "Dashed"),
    ("dot", "Dotted"),
    ("dash_dot", "Dash-dot"),
)
MARKERS: tuple[tuple[str, str], ...] = (
    ("o", "Circle"),
    ("s", "Square"),
    ("t", "Triangle"),
    ("d", "Diamond"),
    ("+", "Plus"),
    ("x", "Cross"),
    ("p", "Pentagon"),
    ("h", "Hexagon"),
    ("star", "Star"),
)
MARKER_CYCLE: tuple[str, ...] = tuple(symbol for symbol, _ in MARKERS)

DEFAULT_PLOT_APPEARANCE: dict[str, Any] = {
    "data_style": "lines",
    "function_style": "lines",
    "residual_style": "lines",
    "data_line_width": 1.0,
    "data_point_size": 6.0,
    "data_marker": "o",
    "different_markers": False,
    "data_line_style": "solid",
    "data_opacity": 100,
    "function_sum_line_width": 2.2,
    "function_component_line_width": 0.8,
    "function_selected_line_width": 1.7,
    "function_point_size": 5.0,
    "function_sum_line_style": "solid",
    "function_component_line_style": "dash",
    "function_opacity": 100,
    "model_sum_colour": MODEL_SUM_COLOUR,
    "component_colour": "#777777",
    "selected_component_colour": "#CC79A7",
    "residual_line_width": 1.0,
    "residual_point_size": 4.0,
    "residual_line_style": "solid",
    "residual_opacity": 100,
    "masked_point_size": 3.5,
    "masked_opacity": 29,
    "grid_visible": True,
    "grid_opacity": 15,
}


def normalize_plot_appearance(raw: Any) -> dict[str, Any]:
    """Return a complete, type-safe appearance mapping."""

    source = raw if isinstance(raw, dict) else {}
    result = dict(DEFAULT_PLOT_APPEARANCE)

    valid_plot_styles = {value for value, _ in PLOT_STYLES}
    valid_line_styles = {value for value, _ in LINE_STYLES}
    valid_markers = {value for value, _ in MARKERS}
    for key in ("data_style", "function_style", "residual_style"):
        value = str(source.get(key, result[key]))
        if value in valid_plot_styles:
            result[key] = value
    for key in ("data_line_style", "function_sum_line_style", "function_component_line_style", "residual_line_style"):
        value = str(source.get(key, result[key]))
        if value in valid_line_styles:
            result[key] = value
    marker = str(source.get("data_marker", result["data_marker"]))
    if marker in valid_markers:
        result["data_marker"] = marker

    result["different_markers"] = bool(source.get("different_markers", result["different_markers"]))
    result["grid_visible"] = bool(source.get("grid_visible", result["grid_visible"]))

    ranges = {
        "data_line_width": (0.1, 12.0),
        "data_point_size": (1.0, 30.0),
        "function_sum_line_width": (0.1, 12.0),
        "function_component_line_width": (0.1, 12.0),
        "function_selected_line_width": (0.1, 16.0),
        "function_point_size": (1.0, 30.0),
        "residual_line_width": (0.1, 12.0),
        "residual_point_size": (1.0, 30.0),
        "masked_point_size": (1.0, 30.0),
    }
    for key, (minimum, maximum) in ranges.items():
        try:
            value = float(source.get(key, result[key]))
        except (TypeError, ValueError):
            continue
        result[key] = min(max(value, minimum), maximum)

    for key in ("data_opacity", "function_opacity", "residual_opacity", "masked_opacity", "grid_opacity"):
        try:
            value = int(source.get(key, result[key]))
        except (TypeError, ValueError):
            continue
        result[key] = min(max(value, 0), 100)

    for key in ("model_sum_colour", "component_colour", "selected_component_colour"):
        colour = QColor(str(source.get(key, result[key])))
        if colour.isValid():
            result[key] = colour.name().upper()
    return result


def plot_mode_flags(mode: str) -> tuple[bool, bool]:
    """Return (draw_lines, draw_points) for a plot style identifier."""

    return mode in {"lines", "lines_points"}, mode in {"points", "lines_points"}


def qt_pen_style(style: str) -> Qt.PenStyle:
    return {
        "dash": Qt.PenStyle.DashLine,
        "dot": Qt.PenStyle.DotLine,
        "dash_dot": Qt.PenStyle.DashDotLine,
    }.get(style, Qt.PenStyle.SolidLine)


def colour_with_opacity(value: str | QColor, opacity: int) -> QColor:
    colour = QColor(value)
    colour.setAlphaF(min(max(float(opacity) / 100.0, 0.0), 1.0))
    return colour


def marker_for_curve(settings: dict[str, Any], index: int) -> str:
    if settings.get("different_markers", False):
        return MARKER_CYCLE[index % len(MARKER_CYCLE)]
    return str(settings.get("data_marker", "o"))


class _ColourButton(QPushButton):
    def __init__(self, colour: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colour = QColor(colour)
        self.clicked.connect(self._choose)
        self._refresh()

    def colour(self) -> str:
        return self._colour.name().upper()

    def set_colour(self, value: str) -> None:
        colour = QColor(value)
        if colour.isValid():
            self._colour = colour
            self._refresh()

    def _choose(self) -> None:
        colour = QColorDialog.getColor(self._colour, self, self.tr("Choose colour"))
        if colour.isValid():
            self._colour = colour
            self._refresh()

    def _refresh(self) -> None:
        text_colour = "#000000" if self._colour.lightnessF() > 0.55 else "#FFFFFF"
        self.setText(self._colour.name().upper())
        self.setStyleSheet(
            f"QPushButton {{ background:{self._colour.name()}; color:{text_colour}; padding:4px 10px; }}"
        )


class PlotAppearanceDialog(QDialog):
    """Edit project-scoped rendering settings without changing scientific data."""

    def __init__(self, settings: dict[str, Any] | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Plot appearance"))
        self.setMinimumWidth(520)
        self._build_ui()
        self.set_settings(normalize_plot_appearance(settings))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            self.tr(
                "These settings affect only how spectra and fitted functions are drawn. "
                "They are stored with the current project."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        data_group = QGroupBox(self.tr("Experimental data"))
        data_form = QFormLayout(data_group)
        self.data_style = self._choice(PLOT_STYLES)
        self.data_line_style = self._choice(LINE_STYLES)
        self.data_line_width = self._float_spin(0.1, 12.0, 0.1)
        self.data_point_size = self._float_spin(1.0, 30.0, 0.5)
        self.data_marker = self._choice(MARKERS, reverse=True)
        self.different_markers = QCheckBox(self.tr("Cycle through different symbols for different spectra"))
        self.data_opacity = self._percent_spin()
        data_form.addRow(self.tr("Draw as:"), self.data_style)
        data_form.addRow(self.tr("Line style:"), self.data_line_style)
        data_form.addRow(self.tr("Line width:"), self.data_line_width)
        data_form.addRow(self.tr("Point size:"), self.data_point_size)
        data_form.addRow(self.tr("Point symbol:"), self.data_marker)
        data_form.addRow("", self.different_markers)
        data_form.addRow(self.tr("Opacity:"), self.data_opacity)
        layout.addWidget(data_group)

        function_group = QGroupBox(self.tr("Fit / model functions"))
        function_form = QFormLayout(function_group)
        self.function_style = self._choice(PLOT_STYLES)
        self.function_point_size = self._float_spin(1.0, 30.0, 0.5)
        self.function_sum_line_width = self._float_spin(0.1, 12.0, 0.1)
        self.function_component_line_width = self._float_spin(0.1, 12.0, 0.1)
        self.function_selected_line_width = self._float_spin(0.1, 16.0, 0.1)
        self.function_sum_line_style = self._choice(LINE_STYLES)
        self.function_component_line_style = self._choice(LINE_STYLES)
        self.function_opacity = self._percent_spin()
        self.model_sum_colour = _ColourButton(MODEL_SUM_COLOUR)
        self.component_colour = _ColourButton("#777777")
        self.selected_component_colour = _ColourButton("#CC79A7")
        function_form.addRow(self.tr("Draw functions as:"), self.function_style)
        function_form.addRow(self.tr("Point size:"), self.function_point_size)
        function_form.addRow(self.tr("Model-sum width:"), self.function_sum_line_width)
        function_form.addRow(self.tr("Component width:"), self.function_component_line_width)
        function_form.addRow(self.tr("Selected component width:"), self.function_selected_line_width)
        function_form.addRow(self.tr("Model-sum line style:"), self.function_sum_line_style)
        function_form.addRow(self.tr("Component line style:"), self.function_component_line_style)
        function_form.addRow(self.tr("Model-sum colour:"), self.model_sum_colour)
        function_form.addRow(self.tr("Component colour:"), self.component_colour)
        function_form.addRow(self.tr("Selected component colour:"), self.selected_component_colour)
        function_form.addRow(self.tr("Opacity:"), self.function_opacity)
        layout.addWidget(function_group)

        residual_group = QGroupBox(self.tr("Residuals and masked data"))
        residual_form = QFormLayout(residual_group)
        self.residual_style = self._choice(PLOT_STYLES)
        self.residual_line_style = self._choice(LINE_STYLES)
        self.residual_line_width = self._float_spin(0.1, 12.0, 0.1)
        self.residual_point_size = self._float_spin(1.0, 30.0, 0.5)
        self.residual_opacity = self._percent_spin()
        self.masked_point_size = self._float_spin(1.0, 30.0, 0.5)
        self.masked_opacity = self._percent_spin()
        residual_form.addRow(self.tr("Residuals as:"), self.residual_style)
        residual_form.addRow(self.tr("Residual line style:"), self.residual_line_style)
        residual_form.addRow(self.tr("Residual line width:"), self.residual_line_width)
        residual_form.addRow(self.tr("Residual point size:"), self.residual_point_size)
        residual_form.addRow(self.tr("Residual opacity:"), self.residual_opacity)
        residual_form.addRow(self.tr("Masked point size:"), self.masked_point_size)
        residual_form.addRow(self.tr("Masked opacity:"), self.masked_opacity)
        layout.addWidget(residual_group)

        grid_group = QGroupBox(self.tr("Grid"))
        grid_form = QFormLayout(grid_group)
        self.grid_visible = QCheckBox(self.tr("Show plot grid"))
        self.grid_opacity = self._percent_spin()
        grid_form.addRow("", self.grid_visible)
        grid_form.addRow(self.tr("Grid opacity:"), self.grid_opacity)
        layout.addWidget(grid_group)

        footer = QHBoxLayout()
        reset = QPushButton(self.tr("Reset defaults"))
        reset.clicked.connect(lambda: self.set_settings(DEFAULT_PLOT_APPEARANCE))
        footer.addWidget(reset)
        footer.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    @staticmethod
    def _choice(options: tuple[tuple[str, str], ...], *, reverse: bool = False) -> QComboBox:
        combo = QComboBox()
        for value, label in options:
            combo.addItem(label if not reverse else label, value)
        return combo

    @staticmethod
    def _float_spin(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSingleStep(step)
        return spin

    @staticmethod
    def _percent_spin() -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setSuffix(" %")
        return spin

    @staticmethod
    def _set_choice(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def set_settings(self, settings: dict[str, Any]) -> None:
        values = normalize_plot_appearance(settings)
        for combo, key in (
            (self.data_style, "data_style"),
            (self.data_line_style, "data_line_style"),
            (self.data_marker, "data_marker"),
            (self.function_style, "function_style"),
            (self.function_sum_line_style, "function_sum_line_style"),
            (self.function_component_line_style, "function_component_line_style"),
            (self.residual_style, "residual_style"),
            (self.residual_line_style, "residual_line_style"),
        ):
            self._set_choice(combo, str(values[key]))
        for spin, key in (
            (self.data_line_width, "data_line_width"),
            (self.data_point_size, "data_point_size"),
            (self.function_sum_line_width, "function_sum_line_width"),
            (self.function_component_line_width, "function_component_line_width"),
            (self.function_selected_line_width, "function_selected_line_width"),
            (self.function_point_size, "function_point_size"),
            (self.residual_line_width, "residual_line_width"),
            (self.residual_point_size, "residual_point_size"),
            (self.masked_point_size, "masked_point_size"),
        ):
            spin.setValue(float(values[key]))
        for spin, key in (
            (self.data_opacity, "data_opacity"),
            (self.function_opacity, "function_opacity"),
            (self.residual_opacity, "residual_opacity"),
            (self.masked_opacity, "masked_opacity"),
            (self.grid_opacity, "grid_opacity"),
        ):
            spin.setValue(int(values[key]))
        self.different_markers.setChecked(bool(values["different_markers"]))
        self.grid_visible.setChecked(bool(values["grid_visible"]))
        self.model_sum_colour.set_colour(str(values["model_sum_colour"]))
        self.component_colour.set_colour(str(values["component_colour"]))
        self.selected_component_colour.set_colour(str(values["selected_component_colour"]))

    def settings(self) -> dict[str, Any]:
        return normalize_plot_appearance(
            {
                "data_style": self.data_style.currentData(),
                "function_style": self.function_style.currentData(),
                "residual_style": self.residual_style.currentData(),
                "data_line_width": self.data_line_width.value(),
                "data_point_size": self.data_point_size.value(),
                "data_marker": self.data_marker.currentData(),
                "different_markers": self.different_markers.isChecked(),
                "data_line_style": self.data_line_style.currentData(),
                "data_opacity": self.data_opacity.value(),
                "function_sum_line_width": self.function_sum_line_width.value(),
                "function_component_line_width": self.function_component_line_width.value(),
                "function_selected_line_width": self.function_selected_line_width.value(),
                "function_point_size": self.function_point_size.value(),
                "function_sum_line_style": self.function_sum_line_style.currentData(),
                "function_component_line_style": self.function_component_line_style.currentData(),
                "function_opacity": self.function_opacity.value(),
                "model_sum_colour": self.model_sum_colour.colour(),
                "component_colour": self.component_colour.colour(),
                "selected_component_colour": self.selected_component_colour.colour(),
                "residual_line_width": self.residual_line_width.value(),
                "residual_point_size": self.residual_point_size.value(),
                "residual_line_style": self.residual_line_style.currentData(),
                "residual_opacity": self.residual_opacity.value(),
                "masked_point_size": self.masked_point_size.value(),
                "masked_opacity": self.masked_opacity.value(),
                "grid_visible": self.grid_visible.isChecked(),
                "grid_opacity": self.grid_opacity.value(),
            }
        )
