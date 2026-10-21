"""Compact native plot controls with a restrained light/dark appearance."""

from importlib import resources
from math import ceil

from PySide6.QtCore import QEvent, QObject, QPointF, QSize, Qt
from PySide6.QtGui import QPainter, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QSizePolicy


class CoordinateReadout(QLabel):
    """Show complete mouse coordinates; keep spectrum details in the tooltip."""

    # Reserve space for the longest finite .8g readings used by the plot. A
    # stable width also prevents the rows moving as the cursor changes digits.
    _RESERVED_READING = "x: -1.2345678e-308   y: -1.2345678e-308"

    def __init__(self, text, parent):
        super().__init__(parent)
        self._reading = str(text)
        self.setObjectName("plotCoordinates")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._update_reading()

    def text(self):
        return self._reading

    def setText(self, text):
        self._reading = str(text)
        self._update_reading()

    def _update_reading(self):
        self.setToolTip(self._reading)
        primary = " ".join(self._reading.split("|", 1)[0].split())
        # Keep each axis beside its number when a narrow plot needs two lines.
        super().setText(primary.replace(": ", ":\N{NO-BREAK SPACE}"))
        self.updateGeometry()

    def sizeHint(self):
        margins = self.contentsMargins()
        metrics = self.fontMetrics()
        width = max(metrics.horizontalAdvance(self._RESERVED_READING),
                    metrics.horizontalAdvance(QLabel.text(self)))
        width += margins.left() + margins.right() + 2 * self.margin() + 2
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance("x:")
        width += margins.left() + margins.right() + 2 * self.margin() + 2
        height = self.fontMetrics().height() + margins.top() + margins.bottom() + 2 * self.margin()
        return QSize(width, height)

    def _text_layout(self, width):
        layout = QTextLayout(QLabel.text(self), self.font(), self)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setTextDirection(Qt.LayoutDirection.LeftToRight)
        layout.setTextOption(option)
        layout.beginLayout()
        height = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout, ceil(max(height, self.fontMetrics().height()))

    def heightForWidth(self, width):
        margins = self.contentsMargins()
        text_width = width - margins.left() - margins.right() - 2 * self.margin()
        _, height = self._text_layout(text_width)
        return height + margins.top() + margins.bottom() + 2 * self.margin()

    def paintEvent(self, event):
        # QLabel's word wrap can still clip a single long scientific value.
        # Use the same text layout for measurement and painting, allowing a
        # character break only when even one complete axis cannot fit.
        QFrame.paintEvent(self, event)
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect().adjusted(self.margin(), self.margin(),
                                           -self.margin(), -self.margin())
        layout, height = self._text_layout(rect.width())
        painter.setClipRect(rect)
        layout.draw(painter, QPointF(rect.x(), rect.y() + max(0, (rect.height() - height) / 2)))


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
