"""Keep windows and dialogs inside the available screen area.

Many dialogs request a generous default size, and some have more content than a
1366x768 laptop can show. Without help their OK/Cancel buttons end up below the
bottom of the screen. An application-wide event filter clamps every top-level
window when it is first shown and, when a dialog's content cannot fit
vertically, moves that content into a scroll area while keeping the dialog's
button box fixed at the bottom.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_SCREEN_FRACTION = 0.92


def _enabled() -> bool:
    # The headless "offscreen" platform reports an arbitrary 800x800 screen;
    # tests and CI lay windows out at their requested sizes unless asked.
    return (QApplication.platformName() != "offscreen"
            or os.environ.get("CURVEMOLE_SCREEN_FIT") == "1")


def available_size(widget: QWidget) -> QSize | None:
    if not _enabled():
        return None
    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        return None
    area = screen.availableGeometry()
    return QSize(int(area.width() * _SCREEN_FRACTION), int(area.height() * _SCREEN_FRACTION))


def default_window_size(widget: QWidget, preferred: QSize) -> QSize:
    """The preferred size, reduced to fit the screen the widget is on."""
    limit = available_size(widget)
    return preferred if limit is None else preferred.boundedTo(limit)


def _contains_button_box(layout: QLayout) -> bool:
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if isinstance(item.widget(), QDialogButtonBox):
            return True
        if item.layout() is not None and _contains_button_box(item.layout()):
            return True
    return False


def _take_footer(layout: QLayout):
    """Remove the trailing button box, or the footer layout that holds it."""
    for index in range(layout.count() - 1, -1, -1):
        item = layout.itemAt(index)
        if isinstance(item.widget(), QDialogButtonBox):
            widget = item.widget()
            layout.removeWidget(widget)
            return widget
        if item.layout() is not None and _contains_button_box(item.layout()):
            footer = layout.takeAt(index).layout()
            footer.setParent(None)
            return footer
        if item.widget() is not None or item.layout() is not None:
            return None  # only a trailing footer stays outside the scroll area
    return None


def make_scrollable(dialog: QDialog) -> bool:
    """Wrap a dialog's layout in a scroll area, keeping its buttons visible."""
    layout = dialog.layout()
    if layout is None or getattr(dialog, "_curvemole_scrollable", False):
        return False
    footer = _take_footer(layout)
    margins = layout.contentsMargins()
    content = QWidget()
    content.setLayout(layout)  # reparents the layout and every managed widget
    scroll = QScrollArea(dialog)
    scroll.setObjectName("screenFitScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    bar = scroll.verticalScrollBar().sizeHint().width()
    scroll.setMinimumWidth(content.minimumSizeHint().width() + bar)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(scroll, 1)
    if footer is not None:
        holder = QVBoxLayout()
        holder.setContentsMargins(margins.left(), 0, margins.right(), margins.bottom())
        if isinstance(footer, QWidget):
            holder.addWidget(footer)
        else:
            holder.addLayout(footer)
        outer.addLayout(holder)
    dialog._curvemole_scrollable = True
    return True


def fit_to_screen(widget: QWidget) -> None:
    limit = available_size(widget)
    if limit is None:
        return
    if isinstance(widget, QDialog):
        needed = widget.sizeHint().expandedTo(widget.minimumSizeHint())
        if needed.height() > limit.height() or needed.width() > limit.width():
            make_scrollable(widget)
    widget.setMinimumSize(widget.minimumSize().boundedTo(limit))
    if widget.width() > limit.width() or widget.height() > limit.height():
        widget.resize(widget.size().boundedTo(limit))
    screen = (widget.screen() or QApplication.primaryScreen()).availableGeometry()
    frame = widget.frameGeometry()
    if not screen.contains(frame):
        x = min(max(frame.x(), screen.left()), max(screen.left(), screen.right() - frame.width()))
        y = min(max(frame.y(), screen.top()), max(screen.top(), screen.bottom() - frame.height()))
        widget.move(x, y)


class ScreenFitFilter(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._busy = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        # Called for every event in the application: stay cheap, never raise and
        # never re-enter (resizing a window sends further events).
        if self._busy:
            return False
        try:
            if event.type() != QEvent.Type.Show or not isinstance(watched, QWidget):
                return False
            if not watched.isWindow() or getattr(watched, "_curvemole_screen_fitted", False):
                return False
            watched._curvemole_screen_fitted = True
            self._busy = True
            try:
                fit_to_screen(watched)
            finally:
                self._busy = False
        except Exception:  # noqa: BLE001 - a layout helper must not break event delivery
            return False
        return False


def uninstall(app: QApplication) -> None:
    screen_fit = getattr(app, "_curvemole_screen_fit", None)
    if screen_fit is not None:
        app.removeEventFilter(screen_fit)
        app._curvemole_screen_fit = None


def install(app: QApplication) -> None:
    if getattr(app, "_curvemole_screen_fit", None) is None:
        app._curvemole_screen_fit = ScreenFitFilter(app)
        app.installEventFilter(app._curvemole_screen_fit)
        # Remove it before interpreter shutdown destroys the Python wrappers.
        app.aboutToQuit.connect(lambda: uninstall(app))
        import atexit

        atexit.register(uninstall, app)
