"""Keep original data units and compact tick labels only when space requires it."""

import math

import pyqtgraph as pg
from PySide6.QtGui import QFontMetricsF


class ScientificAxisItem(pg.AxisItem):
    def __init__(self, orientation: str, **kwargs) -> None:
        super().__init__(orientation, **kwargs)
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        if self.logMode:
            return self.logTickStrings(values, scale, spacing)
        step = abs(spacing * scale)
        places = max(0, math.ceil(-math.log10(step))) if step else 0
        metrics = QFontMetricsF(self.style.get("tickFont") or self.font())
        if self.orientation in ("bottom", "top"):
            span = abs(self.range[1] - self.range[0])
            budget = self.width() * abs(spacing) / span * 0.85 if span else self.width()
        else:
            view = self.linkedView()
            # Leave the spectrum most of the pane, even when Y values are long.
            budget = min(metrics.horizontalAdvance("0000000000"),
                         view.width() * 0.15 if view is not None else self.width())
        labels = []
        for value in values:
            number = value * scale
            plain = "0" if number == 0 else f"{number:.{places}f}"
            if metrics.horizontalAdvance(plain) > budget and number != 0 and math.isfinite(number):
                # Retain enough significant digits to distinguish adjacent ticks.
                precision = max(0, math.floor(math.log10(abs(number))) + places)
                mantissa, exponent = f"{number:.{precision}e}".split("e")
                mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
                scientific = f"{mantissa}e{int(exponent):+d}"
                if len(scientific) < len(plain):
                    plain = scientific
            labels.append(plain)
        return labels
