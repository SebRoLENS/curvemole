"""Persistent update channel choice with an explanation of beta tradeoffs."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)


class UpdateChannelDialog(QDialog):
    def __init__(self, channel: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Update channel"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        self.stable = QRadioButton(self.tr("Stable — recommended"), self)
        self.stable.setObjectName("stable_channel")
        self.beta = QRadioButton(self.tr("Beta — testing"), self)
        self.beta.setObjectName("beta_channel")
        layout.addWidget(self.stable)
        stable_text = QLabel(self.tr("Receive stable releases approved for normal use."), self)
        stable_text.setWordWrap(True)
        layout.addWidget(stable_text)
        layout.addSpacing(12)
        layout.addWidget(self.beta)
        beta_text = QLabel(self.tr(
            "The beta channel receives bug fixes sooner and may get additional features "
            "earlier. It may update very frequently and introduce new bugs."
        ), self)
        beta_text.setWordWrap(True)
        layout.addWidget(beta_text)
        layout.addSpacing(12)
        note = QLabel(self.tr(
            "You can change this choice at any time. Switching to Stable stops beta updates; "
            "your installed version stays in place until an equal or newer stable release "
            "is available. The version badge continues to identify an installed beta."
        ), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        advanced = QLabel(self.tr(
            "Going back to an older version is not recommended, but if you are an advanced "
            "user and know what you are doing, you can download and install any version "
            "from the GitHub repository."
        ), self)
        advanced.setWordWrap(True)
        layout.addWidget(advanced)
        releases = QLabel('<a href="https://github.com/SebRoLENS/curvemole/releases">'
                          + self.tr("Browse GitHub downloads") + '</a>', self)
        releases.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        layout.addWidget(releases)
        (self.beta if channel == "beta" else self.stable).setChecked(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_channel(self) -> str:
        return "beta" if self.beta.isChecked() else "stable"
