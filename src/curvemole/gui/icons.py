"""Palette-aware vector icons, including checked and disabled states."""

from __future__ import annotations

import re
from importlib import resources

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

DARK_COLOURS = {
    "#172735": "#E6EDF3",  # axes, outlines, experimental points
    "#0877F9": "#66B5FF",
    "#FF7A00": "#FFAD5C",
    "#DDF3FF": "#26445B",
    "#F5FBFF": "#323D48",
    "#CBD1D8": "#505B67",  # active Mask remains grey
    "#536170": "#F0F3F6",
    "#ADB6C1": "#687585",
    "#7A8694": "#C9D2DC",
}


class PaletteIconEngine(QIconEngine):
    def __init__(self, source: str, checked_source: str | None = None):
        super().__init__()
        self.source = source
        self.checked_source = checked_source
        self.renderers = {}

    def clone(self):
        return PaletteIconEngine(self.source, self.checked_source)

    def paint(self, painter, rect, mode, state):
        palette = QApplication.palette()
        dark = palette.color(QPalette.ColorRole.Button).lightness() < 128
        disabled = mode == QIcon.Mode.Disabled
        checked = state == QIcon.State.On and self.checked_source is not None
        key = dark, disabled, checked
        if key not in self.renderers:
            source = self.checked_source if checked else self.source
            if disabled:
                # Explicit muted colours keep disabled actions legible without
                # making them look enabled on either palette.
                fills = {"#DDF3FF", "#F5FBFF", "#CBD1D8", "#ADB6C1"}

                def colour(match):
                    is_fill = match.group().upper() in fills
                    return ("#414950" if is_fill else "#87939E") if dark else (
                        "#E1E5E9" if is_fill else "#929CA6"
                    )

                source = re.sub(r"#[0-9a-fA-F]{6}", colour, source)
            elif dark:
                source = re.sub(
                    r"#[0-9a-fA-F]{6}",
                    lambda match: DARK_COLOURS.get(match.group().upper(), match.group()),
                    source,
                )
            self.renderers[key] = QSvgRenderer(source.encode())
        self.renderers[key].render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, pixmap.rect(), mode, state)
        painter.end()
        return pixmap

    def scaledPixmap(self, size, mode, state, scale):
        pixmap = self.pixmap(
            QSize(round(size.width() * scale), round(size.height() * scale)), mode, state
        )
        pixmap.setDevicePixelRatio(scale)
        return pixmap


def vector_icon(filename: str, checked_filename: str | None = None) -> QIcon:
    root = resources.files("curvemole.resources")
    source = root.joinpath(filename).read_text(encoding="utf-8")
    checked = root.joinpath(checked_filename).read_text(encoding="utf-8") if checked_filename else None
    return QIcon(PaletteIconEngine(source, checked))
