"""Architectural guardrails for the desktop extensions (see curvemole.gui.__init__)."""
import subprocess
import sys
import textwrap


def _run(code):
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"}, check=True).stdout


def test_importing_the_gui_never_replaces_core_functions():
    output = _run("""
        import inspect, curvemole.core as core, pkgutil, importlib
        modules = [importlib.import_module(f"curvemole.core.{m.name}")
                   for m in pkgutil.iter_modules(core.__path__)]
        before = {(m.__name__, name): value for m in modules for name, value in vars(m).items()
                  if inspect.isfunction(value) and value.__module__ == m.__name__}
        import curvemole.gui  # noqa: F401
        changed = [f"{module}.{name}" for (module, name), value in before.items()
                   if getattr(importlib.import_module(module), name) is not value]
        print(changed)
    """)
    assert output.strip() == "[]"


def test_core_and_cli_do_not_load_qt_or_the_gui():
    output = _run("""
        import sys, pkgutil, importlib, curvemole.core as core, curvemole.cli  # noqa: F401
        for m in pkgutil.iter_modules(core.__path__):
            importlib.import_module(f"curvemole.core.{m.name}")
        print(sorted(name for name in sys.modules
                     if name.startswith(("PySide6", "pyqtgraph", "curvemole.gui"))))
    """)
    assert output.strip() == "[]"


def test_main_window_has_the_application_behaviour_without_importing_gui_app():
    output = _run("""
        from curvemole.gui.main_window import MainWindow  # noqa: F401
        from curvemole.gui.plot import PlotWorkspace
        print(PlotWorkspace.set_context.__module__)
    """)
    assert output.strip() == "curvemole.gui.app"


def test_runtime_class_patching_does_not_grow():
    # Methods installed on MainWindow by other modules. Lower this ceiling when
    # an extension becomes a real method or controller; never raise it.
    output = _run("""
        from PySide6.QtCore import Signal
        from curvemole.gui.main_window import MainWindow
        print(sum(1 for value in vars(MainWindow).values()
                  if callable(value) and not isinstance(value, Signal)
                  and getattr(value, "__module__", MainWindow.__module__) != MainWindow.__module__))
    """)
    assert int(output) <= 26


def test_building_blocks_do_not_import_the_window_or_its_extensions():
    """Plot, panels and shared helpers must not depend on the modules that patch
    MainWindow; that dependency formed an 11-module import cycle (issue #130)."""
    import ast
    from pathlib import Path

    gui = Path(__file__).resolve().parents[1] / "src" / "curvemole" / "gui"
    building_blocks = ["plot", "plot_placement", "plot_scene", "plot_view_state", "panels", "dialogs",
                       "render_controller", "data_point_editor", "edit_function_points",
                       "background_display", "point_initialisation", "model_selection", "updates",
                       "updates_windows", "update_platform"]
    forbidden = {"curvemole.gui.main_window", "curvemole.gui.background_navigation",
                 "curvemole.gui.manual_points", "curvemole.gui.manual_points_live",
                 "curvemole.gui.model_multiselect", "curvemole.gui.windows_update_fix"}
    offenders = []
    sources = []
    for name in building_blocks:
        path = gui / name
        sources += sorted(path.glob("*.py")) if path.is_dir() else [gui / f"{name}.py"]
    for source in sources:
        name = source.relative_to(gui).with_suffix("").as_posix()
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden:
                offenders.append(f"{name} -> {node.module}")
            elif isinstance(node, ast.ImportFrom) and node.module == "curvemole.gui":
                offenders += [f"{name} -> curvemole.gui.{alias.name}" for alias in node.names
                              if f"curvemole.gui.{alias.name}" in forbidden]
    assert offenders == []


def test_background_commands_are_native_window_methods():
    output = _run("""
        from curvemole.gui.main_window import MainWindow
        print(sorted({getattr(MainWindow, name).__module__ for name in
                      ("subtract_background", "subtract_all_backgrounds", "revert_backgrounds")}))
    """)
    assert output.strip() == "['curvemole.gui.main_window']"


def test_window_building_stages_are_extended_through_the_registry():
    output = _run("""
        from curvemole.gui.main_window import MainWindow
        names = ("_build_actions", "_build_menus", "_build_toolbar", "_connect_signals", "export_spectra_data")
        print(sorted({getattr(MainWindow, name).__module__ for name in names}))
    """)
    assert output.strip() == "['curvemole.gui.main_window']"


def test_undo_commands_are_pushed_only_through_the_undo_service():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "src" / "curvemole"
    offenders = [str(path.relative_to(source)) for path in source.rglob("*.py")
                 if path.name != "undo_service.py" and "undo_stack.push(" in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_fit_flow_is_native_and_the_fit_dialog_is_not_patched():
    output = _run("""
        from curvemole.gui.dialogs import FitPlanDialog
        from curvemole.gui.main_window import MainWindow
        names = ("_fit_finished", "quick_fit", "resume_sequence", "terminate_sequence", "_task_done",
                 "_run_background", "refresh_all", "apply_theme", "start_uncertainty")
        modules = {getattr(MainWindow, name).__module__ for name in names}
        modules |= {value.__module__.rsplit(".fit_plan_dialog", 1)[0] for value in vars(FitPlanDialog).values()
                    if callable(value) and hasattr(value, "__module__")}
        print(sorted(modules))
    """)
    assert output.strip() == "['curvemole.gui.dialogs', 'curvemole.gui.main_window']"
