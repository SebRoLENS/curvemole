import json

import numpy as np
import pytest

from curvemole.core.errors import CurveMoleError
from curvemole.core.extensions import extensions
from curvemole.core.plugins import PluginManager
from curvemole.core.registry import FunctionRegistry


@pytest.fixture(autouse=True)
def isolated_extensions():
    saved = extensions.entries.copy()
    extensions.entries.clear()
    yield
    extensions.entries = saved


def candidate(tmp_path, body, name="example"):
    (tmp_path / f"{name}.py").write_text(body)
    manifest = {"identifier": name, "version": "1", "api_compatibility": "1",
                "licence": "MIT", "capabilities": ["exporters"], "module": f"{name}.py"}
    (tmp_path / f"{name}.curvemole-plugin.json").write_text(json.dumps(manifest))
    return PluginManager().discover_local(tmp_path)[0]


def test_persistence_removal_and_source_change(tmp_path):
    item = candidate(tmp_path, 'def register(api):\n api.add("exporters", "csv", "CSV", lambda ctx: "ok")\n')
    store = tmp_path / "settings"
    manager = PluginManager(FunctionRegistry(), storage=store)
    manager.load(item, trust=True)
    assert extensions.entries["example:csv"].label.startswith("◆")
    manager.disable("example")
    manager.load(item, trust=True)
    extensions.entries.clear()
    restarted = PluginManager(FunctionRegistry(), storage=store)
    restarted.autoload()
    assert "example" in restarted.loaded
    restarted.disable("example")
    restarted.load(item, trust=True)
    extensions.entries.clear()
    (tmp_path / "example.py").write_text("raise RuntimeError('must not execute changed source')")
    changed = PluginManager(FunctionRegistry(), storage=store)
    changed.autoload()
    assert not changed.loaded
    assert "source changed" in changed.installed["example"]["error"]
    changed.remove("example")
    assert not PluginManager(storage=store).installed


def test_discover_local_scans_parent_plugin_folder(tmp_path):
    first = tmp_path / "first_plugin"
    second = tmp_path / "nested" / "second_plugin"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    candidate(first, "def register(api):\n pass\n", name="first")
    candidate(second, "def register(api):\n pass\n", name="second")

    discovered = PluginManager().discover_local(tmp_path)

    assert [item.metadata.identifier for item in discovered] == ["first", "second"]


def test_manual_disable_is_not_persisted_as_plugin_error(tmp_path):
    item = candidate(tmp_path, "def register(api):\n pass\n")
    storage = tmp_path / "settings"
    manager = PluginManager(storage=storage)
    manager.load(item, trust=True)

    manager.disable("example")

    record = PluginManager(storage=storage).installed["example"]
    assert not record["enabled"]
    assert "error" not in record


def test_legacy_manual_disable_is_not_a_recovery_problem():
    from curvemole.gui.plugin_host import _plugin_recovery_problems

    installed = {
        "manual": {"enabled": False, "error": "Disabled by user"},
        "broken": {"enabled": False, "error": "Plugin source changed"},
    }

    assert _plugin_recovery_problems(installed) == ["broken: Plugin source changed"]


def test_transactional_load_and_no_override(tmp_path):
    from curvemole.core.functions import formula_definition
    registry = FunctionRegistry()
    registry.register(formula_definition("existing", "Existing", "a*x"))
    item = candidate(tmp_path, '''from curvemole.core.functions import formula_definition
 def_unused = None
'''.replace(' def_unused', 'def_unused') + '''
def register(api):
 api.add("actions", "one", "One", lambda ctx: None)
 api.register(formula_definition("existing", "Override", "a*x"), replace=True)
''')
    manager = PluginManager(registry)
    with pytest.raises(CurveMoleError):
        manager.load(item, trust=True)
    assert registry.get("existing").display_name == "Existing"
    assert not extensions.entries
    assert not manager.loaded


def test_runtime_failure_disables_restart(tmp_path):
    item = candidate(tmp_path, '''def fail(ctx):
 raise RuntimeError("broken")
def register(api):
 api.add("actions", "bad", "Bad", fail)
''')
    manager = PluginManager(storage=tmp_path / "settings")
    manager.load(item, trust=True)
    with pytest.raises(CurveMoleError, match="disabled"):
        extensions.entries["example:bad"].callback(None)
    assert not manager.installed["example"]["enabled"]


def test_abnormal_exit_and_clean_exit(tmp_path):
    from curvemole.gui.plugin_host import _plugin_recovery_problems

    manager = PluginManager(storage=tmp_path)
    manager.installed = {"test": {"enabled": True}}
    manager._save()
    (tmp_path / "session-dead.json").write_text(json.dumps({"pid": 99999999}))
    assert manager.start_session()
    assert not manager.installed["test"]["enabled"]
    assert _plugin_recovery_problems(manager.installed)
    manager.finish_session()
    restarted = PluginManager(storage=tmp_path)
    assert not restarted.start_session()
    assert restarted.autoload() == set()
    assert _plugin_recovery_problems(restarted.installed, set()) == []
    restarted.finish_session()


def test_solver_integrates_standard_fit(tmp_path):
    from curvemole.core.data import Curve
    from curvemole.core.fitting import FitPlan, FitSettings, Fitter
    from curvemole.core.models import Component, Model
    item = candidate(tmp_path, '''from scipy.optimize import least_squares
def solve(request):
 request.cancellation.raise_if_cancelled()
 return least_squares(request.residual, request.initial, bounds=request.bounds,
                      jac=request.jacobian, max_nfev=request.settings.max_nfev)
def register(api):
 api.add("fit_solvers", "solver", "Test solver", solve)
''')
    manager = PluginManager()
    manager.load(item, trust=True)
    x = np.linspace(-5, 5, 101)
    curve = Curve("test", x, 3*x+2)
    from curvemole.core.functions import formula_definition
    manager.registry.register(formula_definition("plugin_test_line", "Line", "a*x+b"))
    model = Model(components=[Component.create("plugin_test_line", registry=manager.registry)])
    result = Fitter(manager.registry).fit(
        FitPlan([curve.id], settings=FitSettings(solver="example:solver")), [curve], {curve.id: model})
    assert result.success
    assert result.statistics is not None
    manager.registry.unregister("plugin_test_line")


def test_cancel_does_not_quarantine(tmp_path):
    from curvemole.core.errors import FitCancelled
    manager = PluginManager()
    def cancel():
        raise FitCancelled("cancel")
    with pytest.raises(FitCancelled):
        manager.invoke("test", cancel)
    assert not manager.errors


def test_system_exit_during_load_is_contained(tmp_path):
    item = candidate(tmp_path, 'raise SystemExit("bad plugin")')
    with pytest.raises(CurveMoleError, match="bad plugin"):
        PluginManager().load(item, trust=True)


def test_gui_additive_menu_snapshot_undo_and_missing_function(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from curvemole import Curve, Project
    from curvemole.core.models import Component
    from curvemole.gui.dialogs import PluginManagerDialog
    from curvemole.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    project = Project()
    curve = Curve("source", np.arange(5.), np.arange(5.))
    project.add_curve(curve)
    from curvemole.core.data import CurveState
    curve.state = CurveState.FITTED
    window = MainWindow(project)
    manager = window.plugin_manager
    manager.storage = tmp_path / "settings"
    manager.storage.mkdir()
    manager.installed = {}
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    item = candidate(tmp_path, '''from curvemole import Curve
import numpy as np
def add(ctx):
 ctx.project.add_curve(Curve("copy", np.arange(5.), np.arange(5.)))
 ctx.data["note"] = "preserved"
def fail(ctx):
 ctx.project.curves[0].name = "must not escape"
 raise RuntimeError("oops")
def register(api):
 api.add("actions", "add", "Add", add)
 api.add("actions", "fail", "Fail", fail)
''')
    manager.load(item, trust=True)
    window.plugin_host.refresh()
    file_menu = next(a.menu() for a in window.menuBar().actions() if a.text().replace("&", "") == "File")
    assert window.plugins_action in file_menu.actions()
    assert window.export_action in file_menu.actions()
    assert window.plugin_host.menus["actions"].actions()[0].text().startswith("◆")
    window.plugin_host.run(extensions.entries["example:add"])
    assert len(window.project.curves) == 2
    assert window.project.ui_state["plugin_data"]["example"]["note"] == "preserved"
    window.undo_stack.undo()
    assert len(window.project.curves) == 1
    assert window.project.curves[0].state == CurveState.FITTED
    window.undo_stack.redo()
    assert len(window.project.curves) == 2
    window.plugin_host.run(extensions.entries["example:fail"])
    assert window.project.curves[0].name == "source"
    dialog = PluginManagerDialog(manager, tmp_path, window)
    assert dialog.candidates
    dialog._remove(True)
    assert "example" not in manager.installed
    # A project with an unavailable plugin function remains inspectable.
    missing = Component.create("gaussian")
    missing.function_id = "unavailable.plugin.function"
    window.project.model_for(curve.id).components.append(missing)
    window.selected_component_id = missing.id
    window.refresh_all()
    window.project.dirty = False
    window.close()
    app.processEvents()


def test_real_process_exit_recovers_without_importing_plugin(tmp_path):
    import os
    import subprocess
    import sys
    item = candidate(tmp_path, '''import os
if os.environ.get("CURVEMOLE_TEST_CRASH") == "1":
 os._exit(42)
def register(api):
 api.add("actions", "ok", "OK", lambda ctx: None)
''')
    storage = tmp_path / "settings"
    manager = PluginManager(storage=storage)
    manager.load(item, trust=True)
    code = ("from curvemole.core.plugins import PluginManager; "
            f"m=PluginManager(storage={str(storage)!r}); "
            "m.start_session(); m.autoload()")
    process = subprocess.run([sys.executable, "-c", code],
                             env={**os.environ, "CURVEMOLE_TEST_CRASH": "1"}, timeout=15)
    assert process.returncode == 42
    recovered = PluginManager(storage=storage)
    assert recovered.start_session()
    recovered.autoload()
    assert not recovered.loaded
    recovered.finish_session()


def test_panel_service_y_replacement_is_undoable(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curvemole import Curve, Project
    from curvemole.core.extensions import Contribution
    from curvemole.gui.main_window import MainWindow
    from curvemole.gui.plugin_services import PluginServices

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("CURVEMOLE_DISABLE_PLUGINS", "1")
    project = Project()
    curve = Curve("source", np.arange(5.0), np.arange(5.0))
    project.add_curve(curve)
    window = MainWindow(project)
    owner = "test.cosmic"
    extensions.entries[owner + ":panel"] = Contribution(
        owner, owner + ":panel", "Test", "panels", lambda context: None
    )
    try:
        service = PluginServices(window.plugin_host, owner)
        service.apply_y_replacement(
            curve.id, np.arange(5.0)[::-1], metadata_key="test_cleaning",
            metadata={"intervals": [[1, 2]]}, description="Clean spectrum"
        )
        assert curve.y.tolist() == [4, 3, 2, 1, 0]
        assert curve.metadata["test_cleaning"]["intervals"] == [[1, 2]]
        window.undo_stack.undo()
        assert curve.y.tolist() == [0, 1, 2, 3, 4]
        assert "test_cleaning" not in curve.metadata
        window.undo_stack.redo()
        assert curve.y.tolist() == [4, 3, 2, 1, 0]
    finally:
        extensions.entries.pop(owner + ":panel", None)
        window.project.dirty = False
        window.close()
        app.processEvents()
