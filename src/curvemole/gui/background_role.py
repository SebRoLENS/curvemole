"""A visible, accessible background switch, including mixed selections."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QStyle


class BackgroundSwitch(QCheckBox):
    """Retain checkbox accessibility while drawing a large labelled switch.

    Mixed is a display state, never a third role that a user can assign. A click
    from mixed selects ON for every selected function, then ON toggles to OFF.
    """

    def __init__(self, text, parent=None) -> None:
        super().__init__(text, parent)
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(40)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        state_width = max(metrics.horizontalAdvance(text)
                          for text in (self.tr("ON"), self.tr("OFF"), self.tr("Mixed")))
        return QSize(metrics.horizontalAdvance(self.text()) + state_width + 84,
                     max(40, metrics.height() + 16))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, position) -> bool:
        return self.rect().contains(position)

    def nextCheckState(self) -> None:
        self.setCheckState(Qt.CheckState.Unchecked if self.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        state = self.checkState()
        checked = state == Qt.CheckState.Checked
        mixed = state == Qt.CheckState.PartiallyChecked
        state_text = self.tr("Mixed") if mixed else self.tr("ON") if checked else self.tr("OFF")
        color = (QColor("#DAB56B" if dark else "#986400") if mixed else
                 QColor("#63D7C4" if dark else "#087565") if checked else
                 palette.color(QPalette.ColorRole.Mid))
        if not self.isEnabled():
            painter.setOpacity(0.45)

        bounds = self.contentsRect().adjusted(4, 2, -4, -2)
        logical_track = QRect(bounds.right() - 47, bounds.center().y() - 13, 48, 26)
        track = QStyle.visualRect(self.layoutDirection(), bounds, logical_track)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(track), 13, 13)
        thumb = QRectF(track.left() + 4, track.top() + 4, 18, 18)
        if mixed:
            thumb.moveLeft(track.center().x() - 8.5)
        elif checked != (self.layoutDirection() == Qt.LayoutDirection.RightToLeft):
            thumb.moveRight(track.right() - 3)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(thumb)

        state_width = max(self.fontMetrics().horizontalAdvance(text)
                          for text in (self.tr("ON"), self.tr("OFF"), self.tr("Mixed")))
        logical_state = QRect(logical_track.left() - state_width - 10, bounds.top(),
                              state_width, bounds.height())
        label = QRect(bounds.left(), bounds.top(),
                      max(0, logical_state.left() - bounds.left() - 12), bounds.height())
        painter.setPen(palette.color(QPalette.ColorRole.WindowText))
        painter.drawText(QStyle.visualRect(self.layoutDirection(), bounds, label),
                         Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.drawText(QStyle.visualRect(self.layoutDirection(), bounds, logical_state),
                         Qt.AlignmentFlag.AlignCenter, state_text)
        if self.hasFocus():
            painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight), 1,
                                Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect().adjusted(1, 1, -1, -1)), 5, 5)
