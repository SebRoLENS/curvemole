"""AboutDialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from curvemole.gui.parameter_link import ParameterLinkDialog  # noqa: E402, F401
from curvemole.identifiers import CONCEPT_DOI, CONCEPT_DOI_URL, RRID, RRID_URL
from curvemole.version import __version__


class AboutDialog(QDialog):
    def __init__(self, logo_path: str | Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("About CurveMole"))
        layout = QVBoxLayout(self)
        if logo_path and Path(logo_path).is_file():
            logo = QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setPixmap(QPixmap(str(logo_path)).scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(logo)
        text = QLabel(
            f"<h2>CurveMole {__version__}</h2>"
            "<p>Modular Scientific Curve Fitting</p>"
            "<p>Sebastiano Romi<br>European Laboratory for Non-Linear Spectroscopy (LENS)<br>"
            "University of Florence (UNIFI)<br>"
            '<a href="mailto:romi@lens.unifi.it">romi@lens.unifi.it</a></p>'
            "<p><strong>Bibliography:</strong> cite the DOI of the exact version used.<br>"
            '<a href="https://github.com/SebRoLENS/curvemole/blob/main/docs/citing.md">Citation guide and BibTeX</a></p>'
            f'<p><strong>Methods:</strong> CurveMole {__version__} '
            f'(<a href="{RRID_URL}">RRID:{RRID}</a>).</p>'
            f'<p><strong>Project in general:</strong> <a href="{CONCEPT_DOI_URL}">Concept DOI: {CONCEPT_DOI}</a><br>'
            "All versions; the latest Zenodo archive may be a beta.</p>"
            "<p>GPL-3.0-or-later</p>"
            '<p><a href="https://github.com/SebRoLENS/curvemole">Project and updates</a></p>'
        )
        text.setOpenExternalLinks(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)
