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
                   for m in pkgutil.iter_modules(core.__path__) if m.name != "packaging_smoke"]
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
            if m.name != "packaging_smoke":
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
        from curvemole.gui.main_window import MainWindow
        print(sum(1 for value in vars(MainWindow).values()
                  if callable(value) and getattr(value, "__module__", MainWindow.__module__) != MainWindow.__module__))
    """)
    assert int(output) <= 44
