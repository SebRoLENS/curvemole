"""Compact native plot controls with a restrained light/dark appearance."""

from importlib import resources

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy


class CoordinateReadout(QLabel):
    """Keep mouse coordinates on one line; the tooltip retains the full reading."""

    def __init__(self, text, parent):
        super().__init__(parent)
        self._reading = str(text)
        self.setObjectName("plotCoordinates")
        self.setMinimumWidth(140)
        self.setMaximumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._update_reading()

    def text(self):
        return self._reading

    def setText(self, text):
        self._reading = str(text)
        self._update_reading()

    def _update_reading(self):
        self.setToolTip(self._reading)
        width = max(0, self.contentsRect().width() - 16)
        primary = " ".join(self._reading.split("|", 1)[0].split())
        super().setText(self.fontMetrics().elidedText(primary, Qt.TextElideMode.ElideRight, width))

    def sizeHint(self):
        size = super().sizeHint()
        return QSize(160, size.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_reading()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "_reading"):
            self._update_reading()


class PlotControlStyle(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self._dark = None
        panel.installEventFilter(self)
        self.apply()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.PaletteChange:
            self.apply()
        return super().eventFilter(watched, event)

    def apply(self):
        dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
        if dark == self._dark:
            return
        self._dark = dark
        background, field, border, text, muted = (
            ("#252b32", "#20262d", "#414c59", "#e6edf5", "#aab7c7") if dark else
            ("#f7f9fc", "#ffffff", "#d8e0ea", "#26364a", "#64758b")
        )
        selected, accent, selected_border = (
            ("#193b53", "#9bd4ff", "#386684") if dark else
            ("#e7f0fd", "#155ca8", "#c3d7f2")
        )
        icons = resources.files("curvemole.resources")
        down = str(icons.joinpath("chevron-down.svg")).replace("\\", "/")
        up = str(icons.joinpath("chevron-up.svg")).replace("\\", "/")
        self.panel.setStyleSheet(f"""
            QFrame#viewControls {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}
            QFrame#viewControls QLabel {{ color: {muted}; border: none; background: transparent; }}
            QFrame#viewControls QComboBox, QFrame#viewControls QDoubleSpinBox {{
                color: {text}; background: {field}; border: 1px solid {border};
                border-radius: 5px; min-height: 22px; padding: 1px 6px;
            }}
            QFrame#viewControls QComboBox:hover, QFrame#viewControls QDoubleSpinBox:hover {{ border-color: {accent}; }}
            QFrame#viewControls QComboBox:focus, QFrame#viewControls QDoubleSpinBox:focus {{ border-color: {accent}; }}
            QFrame#viewControls QComboBox:disabled {{ color: {muted}; background: {background}; }}
            QFrame#viewControls QComboBox[primaryControl="true"] {{ font-weight: 600; color: {accent}; }}
            QFrame#viewControls QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right; width: 18px; border: none;
            }}
            QFrame#viewControls QComboBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
            QFrame#viewControls QDoubleSpinBox::up-button {{
                subcontrol-origin: border; subcontrol-position: top right; width: 14px; border: none;
            }}
            QFrame#viewControls QDoubleSpinBox::down-button {{
                subcontrol-origin: border; subcontrol-position: bottom right; width: 14px; border: none;
            }}
            QFrame#viewControls QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 8px; height: 8px; }}
            QFrame#viewControls QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 8px; height: 8px; }}
            QFrame#viewControls QRadioButton {{
                color: {muted}; padding: 4px 7px; border: 1px solid transparent; border-radius: 5px;
            }}
            QFrame#viewControls QRadioButton::indicator {{ width: 0; height: 0; border: none; background: transparent; }}
            QFrame#viewControls QRadioButton:hover {{ background: {field}; }}
            QFrame#viewControls QRadioButton:checked {{ color: {accent}; background: {selected}; border-color: {selected_border}; }}
            QFrame#viewControls QRadioButton:disabled {{ color: {muted}; background: transparent; border-color: transparent; }}
            QFrame#viewControls QCheckBox {{
                color: {text}; padding: 3px 4px; border: 1px solid transparent; border-radius: 5px;
            }}
            QFrame#viewControls QCheckBox:hover {{ background: {field}; }}
            QFrame#viewControls QCheckBox:checked {{ background: {selected}; border-color: {selected_border}; }}
            QFrame#viewControls QLabel#plotCoordinates {{ color: {muted}; background: {field}; border: 1px solid {border};
                border-radius: 5px; padding: 3px 7px; font-family: monospace; }}
        """)
