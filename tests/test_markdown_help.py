import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtGui import QFont, QImage, QTextDocument, QTextTable
from PySide6.QtWidgets import QApplication, QMainWindow

from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.core.registry import FunctionRegistry
from curvemole.gui.documentation import MarkdownDialog, plugin_manuals, show_markdown_document
from curvemole.gui.plugin_host import PluginHost


@pytest.fixture
def help_window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(extensions, 'entries', {})
    window = QMainWindow()
    for name in ('File', 'Data', 'Tools', 'View', 'Help'):
        window.menuBar().addMenu(name)
    yield app, window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_reader_renders_markdown_and_navigates_local_links(help_window, tmp_path, monkeypatch):
    app, window = help_window
    image = QImage(12, 12, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)
    image.save(str(tmp_path / 'diagram.png'))
    path = tmp_path / 'README.md'
    path.write_text('# Plugin manual\n\n**Bold text** and *italic*.\n\n'
                    '| Setting | Value |\n| --- | --- |\n| Mode | Auto |\n\n'
                    '![Diagram](diagram.png)\n\n[Next](details.md)\n', encoding='utf-8')
    (tmp_path / 'details.md').write_text('# Details\n\nCaffè and λ.\n', encoding='utf-8')
    dialog = show_markdown_document(window, path, 'Plugin manual')
    assert dialog.isVisible()
    assert 'Plugin manual' in dialog.browser.toPlainText()
    assert '**Bold text**' not in dialog.browser.toPlainText()
    cursor = dialog.browser.document().find('Bold text')
    assert cursor.charFormat().fontWeight() >= QFont.Weight.Bold
    assert any(isinstance(frame, QTextTable)
               for frame in dialog.browser.document().rootFrame().childFrames())
    resource = dialog.browser.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl.fromLocalFile(str(tmp_path / 'diagram.png'))
    )
    assert resource is not None and not resource.isNull()
    dialog.browser.anchorClicked.emit(QUrl('details.md'))
    assert 'Caffè and λ.' in dialog.browser.toPlainText()
    assert dialog.back.isEnabled()
    dialog.back.click()
    assert Path(dialog.browser.source().toLocalFile()) == path
    assert dialog.forward.isEnabled()
    dialog.forward.click()
    dialog.search.setText('Caffè')
    dialog.find_next()
    assert dialog.browser.textCursor().selectedText() == 'Caffè'
    dialog.find_next()  # Wrap around at the end of the manual.
    assert dialog.browser.textCursor().selectedText() == 'Caffè'
    opened = []
    monkeypatch.setattr('curvemole.gui.documentation.QDesktopServices.openUrl', opened.append)
    dialog.browser.anchorClicked.emit(QUrl('https://example.org/manual'))
    assert [url.toString() for url in opened] == ['https://example.org/manual']
    dialog.close()
    app.processEvents()


def test_help_menu_tracks_active_plugins_and_multiple_manuals(help_window, tmp_path, monkeypatch):
    _, window = help_window
    manager = PluginManager(FunctionRegistry(), storage=tmp_path / 'storage')
    window.plugin_manager = manager
    for identifier in ('first', 'second', 'missing'):
        folder = tmp_path / identifier
        folder.mkdir()
        manifest = folder / 'plugin.curvemole-plugin.json'
        manifest.write_text(json.dumps(dict(
            identifier=identifier, name=identifier.title(), version='1.0.0',
            api_compatibility='1', licence='MIT', capabilities=[], module='plugin.py'
        )))
        (folder / 'plugin.py').write_text('def register(api):\n pass\n')
        manager.load(manager.discover_local(folder)[0], trust=True)
        if identifier != 'missing':
            (folder / 'README.md').write_text('# ' + identifier)
    (tmp_path / 'second' / 'docs').mkdir()
    (tmp_path / 'second' / 'docs' / 'usage.md').write_text('# Usage')
    host = PluginHost(window)
    assert not host.help_menu.actions()  # Filesystem discovery waits for the menu.
    host.help_menu.aboutToShow.emit()
    actions = host.help_menu.actions()
    assert len(actions) == 3
    assert 'First' in actions[0].text()
    assert not actions[1].isEnabled()
    submenu = actions[2].menu()
    assert [action.text() for action in submenu.actions()] == [
        'README.md', str(Path('docs') / 'usage.md')
    ]
    opened = []
    monkeypatch.setattr('curvemole.gui.plugin_host.show_markdown_document',
                        lambda parent, path, title: opened.append(path))
    actions[0].trigger()
    submenu.actions()[1].trigger()
    assert opened == [tmp_path / 'first' / 'README.md', tmp_path / 'second' / 'docs' / 'usage.md']
    manager.disable('first')
    manager.errors['second'] = 'Failed callback'
    host.refresh()
    host.help_menu.aboutToShow.emit()
    assert len(host.help_menu.actions()) == 1
    assert 'Missing' in host.help_menu.actions()[0].text()
    manager.disable('missing')
    host.refresh()
    assert not host.help_menu.isEnabled()
    manager.errors.clear()
    manager.load(manager.discover_local(tmp_path / 'first')[0], trust=True)
    host.refresh()
    assert host.help_menu.isEnabled()
    host.help_menu.aboutToShow.emit()
    assert len(host.help_menu.actions()) == 2


@pytest.mark.parametrize('name', ['quick-start.md', 'manual.md'])
@pytest.mark.parametrize('packaged', [False, True])
def test_application_help_opens_internal_reader(help_window, tmp_path, monkeypatch, name, packaged):
    from curvemole.gui import main_window

    _, window = help_window
    external = []
    window._open_external = external.append
    if packaged:
        path = tmp_path / name
        path.write_text('# Packaged manual', encoding='utf-8')
        monkeypatch.setattr(main_window, '__file__', str(tmp_path / 'a' / 'b' / 'c' / 'window.py'))
        monkeypatch.setattr(main_window, '_resource_path', lambda value: path)
    main_window.MainWindow.open_documentation(window, name)
    dialogs = window.findChildren(MarkdownDialog)
    assert len(dialogs) == 1 and dialogs[0].isVisible()
    assert Path(dialogs[0].browser.source().toLocalFile()).name == name
    assert not external


def test_manual_discovery_and_missing_file_errors(help_window, tmp_path, monkeypatch):
    _, window = help_window
    assert plugin_manuals('Python entry point: example:register') == []
    warnings = []
    monkeypatch.setattr('curvemole.gui.documentation.QMessageBox.warning',
                        lambda *args: warnings.append(args))
    assert show_markdown_document(window, tmp_path / 'gone.md', 'Missing') is None
    assert len(warnings) == 1
