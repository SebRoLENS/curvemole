"""Collapse dock areas without changing their arrangement or open tools."""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QScrollArea,
    QToolButton,
    QWidget,
)

Area = Qt.DockWidgetArea


class DockViewport(QScrollArea):
    """Keep a tool's content minimum out of the shared dock geometry."""

    def __init__(self, content: QWidget, dock: QDockWidget) -> None:
        super().__init__(dock)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setWidget(content)


@dataclass
class CollapsedDocks:
    names: list[str]
    active: list[str]


class DockCollapseControls(QWidget):
    """Keep a small, permanent reopen button for each occupied dock area."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.collapsed: dict[Area, CollapsedDocks] = {}
        self._watched: set[QDockWidget] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._sync)
        self._buttons: dict[Area, QToolButton] = {}
        self._labels = {
            Area.LeftDockWidgetArea: self.tr("Left panels"),
            Area.RightDockWidgetArea: self.tr("Right panels"),
            Area.BottomDockWidgetArea: self.tr("Bottom panels"),
            Area.TopDockWidgetArea: self.tr("Top panels"),
        }
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)
        self.setStyleSheet("""
            QToolButton {
                border: 1px solid palette(mid);
                border-radius: 6px;
                background: palette(button);
                padding: 2px 7px;
            }
            QToolButton:hover, QToolButton:focus {
                border-color: palette(highlight);
            }
            QToolButton:pressed { background: palette(midlight); }
        """)
        for area, label in self._labels.items():
            button = QToolButton(self)
            button.setText(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda checked=False, area=area: self.toggle(area))
            layout.addWidget(button)
            self._buttons[area] = button
        for dock in window.findChildren(QDockWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            self.watch(dock)
        self._timer.start(0)

    def watch(self, dock: QDockWidget) -> None:
        if dock in self._watched:
            return
        self._watched.add(dock)
        dock.destroyed.connect(lambda: self._watched.discard(dock))
        dock.visibilityChanged.connect(self._queue_sync)
        dock.dockLocationChanged.connect(self._queue_sync)
        dock.topLevelChanged.connect(self._queue_sync)
        self._queue_sync()

    def _queue_sync(self, *_args) -> None:
        self._timer.start(0)

    def _docks(self, area: Area) -> list[QDockWidget]:
        return [
            dock for dock in self.window.findChildren(
                QDockWidget, options=Qt.FindChildOption.FindDirectChildrenOnly,
            )
            if not dock.isFloating() and self.window.dockWidgetArea(dock) == area
        ]

    def toggle(self, area: Area) -> None:
        if area in self.collapsed:
            self._expand(area)
        else:
            docks = [dock for dock in self._docks(area) if not dock.isHidden()]
            if not docks:
                return
            self.collapsed[area] = CollapsedDocks(
                [dock.objectName() for dock in docks],
                [dock.objectName() for dock in docks if not dock.visibleRegion().isEmpty()],
            )
            for dock in docks:
                dock.hide()
        self._sync()

    def _expand(self, area: Area, opened: list[QDockWidget] | None = None) -> None:
        state = self.collapsed.pop(area)
        docks = {dock.objectName(): dock for dock in self._docks(area)}
        for name in state.names:
            if name in docks:
                docks[name].show()
        for name in state.active:
            if name in docks:
                docks[name].raise_()
        for dock in opened or ():
            dock.raise_()

    def _sync(self) -> None:
        for area, button in self._buttons.items():
            shown = [dock for dock in self._docks(area) if not dock.isHidden()]
            if shown and area in self.collapsed:
                # Opening a tool from the menu also reopens its dock area.
                self._expand(area, shown)
            collapsed = area in self.collapsed
            button.setVisible(bool(shown) or collapsed)
            tooltip = (
                self.tr("Expand {panels}") if collapsed else self.tr("Collapse {panels}")
            ).format(panels=self._labels[area].lower())
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setIcon(self._icon(area, collapsed))

    def save(self) -> dict:
        return {
            area.name: {"names": state.names, "active": state.active}
            for area, state in self.collapsed.items()
        }

    def restore(self, data: dict) -> None:
        self.collapsed.clear()
        for area in self._buttons:
            state = data.get(area.name)
            if not state:
                continue
            docks = self._docks(area)
            hidden = {dock.objectName() for dock in docks if dock.isHidden()}
            names = [name for name in state["names"] if name in hidden]
            if names and all(dock.isHidden() for dock in docks):
                self.collapsed[area] = CollapsedDocks(names, state["active"])
        self._sync()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_timer"):
            self._queue_sync()

    def _icon(self, area: Area, collapsed: bool) -> QIcon:
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(round(18 * ratio), round(18 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(9, 9)
        painter.rotate({
            Area.LeftDockWidgetArea: 0,
            Area.TopDockWidgetArea: 90,
            Area.RightDockWidgetArea: 180,
            Area.BottomDockWidgetArea: 270,
        }[area])
        palette = self.palette()
        outline = palette.color(QPalette.ColorRole.ButtonText)
        accent = palette.color(QPalette.ColorRole.Highlight)
        painter.setPen(QPen(outline, 1.2))
        painter.drawRoundedRect(QRectF(-7, -6, 14, 12), 2, 2)
        painter.fillRect(QRectF(-5.7, -4.4, 3.1 if not collapsed else 1.2, 8.8), accent)
        chevron = QPen(accent, 1.3)
        chevron.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(chevron)
        tip, tail = (4, 1) if collapsed else (0, 3)
        painter.drawLine(tail, -2, tip, 0)
        painter.drawLine(tip, 0, tail, 2)
        painter.end()
        return QIcon(pixmap)
