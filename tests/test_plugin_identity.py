import json
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtWidgets import QApplication, QMainWindow

from curvemole.core.extensions import extensions
from curvemole.core.plugin_identity import contribution_tooltip, function_tooltip
from curvemole.core.plugins import PluginManager
from curvemole.core.registry import FunctionRegistry
from curvemole.gui.dialogs import AddComponentDialog
from curvemole.gui.plugin_host import PluginHost


def test_distinct_symbols_persist_and_explain_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "entries", {})
    registry = FunctionRegistry()
    manager = PluginManager(registry, storage=tmp_path / "settings")
    for identifier, name in (("first", "First plugin"), ("second", "Second plugin")):
        folder = tmp_path / identifier
        folder.mkdir()
        manifest = dict(identifier=identifier, name=name, version="1.0.0", api_compatibility="1",
                        licence="MIT", capabilities=["functions", "actions"], module="plugin.py")
        (folder / "plugin.curvemole-plugin.json").write_text(json.dumps(manifest))
        (folder / "plugin.py").write_text(
            'from curvemole.core.functions import formula_definition\n'
            'def register(api):\n'
            ' api.register(formula_definition(api.identifier + "_line", "Line", "a*x"))\n'
            ' api.add("actions", "action", "Action", lambda ctx: None)\n')
        manager.load(manager.discover_local(folder)[0], trust=True)
    symbols = {key: manager.symbol(key) for key in manager.loaded}
    assert len(set(symbols.values())) == 2
    for key in symbols:
        definition = registry.get(key + "_line")
        entry = extensions.entries[key + ":action"]
        assert definition.display_name.startswith(symbols[key] + " ")
        assert entry.label.startswith(symbols[key] + " ")
        assert manager.plugin_name(key) in function_tooltip(definition)
        assert symbols[key] in contribution_tooltip(entry)

    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.plugin_manager = manager
    window.project = SimpleNamespace(ui_state={})
    window.active_curve_id = None
    window.curve_tree = SimpleNamespace(selected_curve_ids=lambda: [])
    window.settings = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    for name in ("File", "Data", "Tools", "View"):
        window.menuBar().addMenu(name)
    host = PluginHost(window)
    assert host.menus["actions"].toolTipsVisible()
    actions = host.menus["actions"].actions()
    assert "First plugin" in actions[0].toolTip()
    assert "Second plugin" in actions[1].toolTip()
    dialog = AddComponentDialog(registry, None, window)
    assert "First plugin" in dialog.function.itemData(0, Qt.ItemDataRole.ToolTipRole)
    dialog.function.setCurrentIndex(1)
    assert "Second plugin" in dialog.function.toolTip()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    extensions.entries.clear()
    restarted = PluginManager(FunctionRegistry(), storage=manager.storage)
    restarted.autoload()
    assert {key: restarted.symbol(key) for key in restarted.loaded} == symbols
    restarted.disable("first")
    restarted.load(next(c for c in restarted.installed_candidates() if c.metadata.identifier == "first"), trust=True)
    assert restarted.symbol("first") == symbols["first"]
