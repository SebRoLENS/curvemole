"""Internal Markdown manuals with local navigation, search and zoom."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from curvemole.gui.windowing import secondary_window_parent


class MarkdownDialog(QDialog):
    def __init__(self, path: Path, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 760)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.browser = QTextBrowser(self)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDocumentMargin(20)
        self.browser.document().setDefaultStyleSheet(
            "h1, h2, h3 { margin-top: 20px; }"
            "pre { white-space: pre-wrap; }"
            "td, th { padding: 6px; }"
        )
        self.back = QPushButton(self.tr("Back"))
        self.forward = QPushButton(self.tr("Forward"))
        self.back.clicked.connect(self.browser.backward)
        self.forward.clicked.connect(self.browser.forward)
        self.browser.backwardAvailable.connect(self.back.setEnabled)
        self.browser.forwardAvailable.connect(self.forward.setEnabled)
        self.back.setEnabled(False)
        self.forward.setEnabled(False)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Find in this manual…"))
        self.search.returnPressed.connect(self.find_next)
        find = QPushButton(self.tr("Find next"))
        find.clicked.connect(self.find_next)
        smaller = QPushButton("−")
        larger = QPushButton("+")
        smaller.setToolTip(self.tr("Zoom out"))
        larger.setToolTip(self.tr("Zoom in"))
        smaller.clicked.connect(lambda: self.browser.zoomOut(1))
        larger.clicked.connect(lambda: self.browser.zoomIn(1))
        for widget in (self.back, self.forward, self.search, find, smaller, larger):
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)
        layout.addWidget(self.browser, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.close)
        layout.addWidget(close)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.search.setFocus)
        self.browser.anchorClicked.connect(self.open_link)
        self.open_path(path)

    def open_path(self, path: Path, fragment: str = "") -> None:
        # Readability is checked here so missing plugin files produce a useful error.
        path.read_text(encoding="utf-8")
        url = QUrl.fromLocalFile(str(path.resolve()))
        if fragment:
            url.setFragment(fragment)
        self.browser.setSource(url, QTextDocument.ResourceType.MarkdownResource)

    def open_link(self, link: QUrl) -> None:
        url = self.browser.source().resolved(link)
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".md", ".markdown"}:
            try:
                self.open_path(Path(url.toLocalFile()), url.fragment())
            except (OSError, UnicodeError) as exc:
                QMessageBox.warning(self, self.tr("Open manual"), str(exc))
        elif url.scheme() in {"https", "http", "mailto", "file"}:
            QDesktopServices.openUrl(url)

    def find_next(self) -> None:
        text = self.search.text()
        if text and not self.browser.find(text):
            self.browser.moveCursor(QTextCursor.MoveOperation.Start)
            self.browser.find(text)


def show_markdown_document(parent: QWidget, path: Path, title: str) -> MarkdownDialog | None:
    owner = secondary_window_parent(parent)
    try:
        dialog = MarkdownDialog(path, title, owner)
    except (OSError, UnicodeError) as exc:
        QMessageBox.warning(owner, "Open manual", str(exc))
        return None
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    if owner is not parent and owner.isModal():
        dialog.exec()
    else:
        dialog.show()
    return dialog


def plugin_manuals(source: str) -> list[Path]:
    """Find bundled manuals beside a local manifest, including its docs folder."""
    manifest = Path(source)
    if not manifest.is_file():
        return []
    root = manifest.parent
    names = {"readme", "manual", "help", "user_manual", "user-manual"}
    paths = [path for path in root.iterdir()
             if path.is_file() and path.suffix.lower() in {".md", ".markdown"}
             and path.stem.lower() in names]
    docs = root / "docs"
    if docs.is_dir():
        paths.extend(path for path in docs.rglob("*")
                     if path.is_file() and path.suffix.lower() in {".md", ".markdown"})
    return sorted(paths, key=lambda path: (path.stem.lower() != "readme", str(path).casefold()))
