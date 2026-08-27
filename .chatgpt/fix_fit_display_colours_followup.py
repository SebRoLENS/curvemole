from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:140]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Ruff import ordering after the primary patch.
replace_once(
    "src/curvemole/gui/plot.py",
    '''from curvemole.core.models import component_height\nfrom curvemole.gui.colours import MODEL_SUM_COLOUR\nfrom curvemole.core.project import Project\nfrom curvemole.core.registry import FunctionRegistry\n''',
    '''from curvemole.core.models import component_height\nfrom curvemole.core.project import Project\nfrom curvemole.core.registry import FunctionRegistry\nfrom curvemole.gui.colours import MODEL_SUM_COLOUR\n''',
)
replace_once(
    "tests/test_fit_display_and_colours.py",
    '''from curvemole.gui.main_window import MainWindow, PALETTE\n''',
    '''from curvemole.gui.main_window import PALETTE, MainWindow\n''',
)

# Existing projects may already contain a red spectrum from older palettes/custom choices.
# Migrate those colours when a project is loaded so red is unambiguously Model sum.
path = "src/curvemole/gui/main_window.py"
replace_once(
    path,
    '''        self._load_custom_functions()\n        self._normalise_component_names()\n        self._restore_layout()\n''',
    '''        self._load_custom_functions()\n        self._normalise_component_names()\n        self._normalise_spectrum_colours()\n        self._restore_layout()\n''',
)
replace_once(
    path,
    '''            self._load_custom_functions()\n            self._normalise_component_names()\n            self.refresh_all()\n''',
    '''            self._load_custom_functions()\n            self._normalise_component_names()\n            self._normalise_spectrum_colours()\n            self.refresh_all()\n''',
)
replace_once(
    path,
    '''    def _commit_component(self, component: Component, curve_id: str) -> None:\n''',
    '''    def _normalise_spectrum_colours(self) -> None:\n        changed = False\n        fallback = SERIES_PALETTES[DEFAULT_SERIES_PALETTE]\n        for series in self.project.dataset.series:\n            palette = SERIES_PALETTES.get(str(series.metadata.get("palette", "")), fallback)\n            for index, curve in enumerate(series.curves):\n                if spectrum_colour_allowed(curve.colour):\n                    continue\n                curve.colour = palette[index % len(palette)]\n                changed = True\n        if changed and not self.project.read_only:\n            self.project.touch()\n\n    def _commit_component(self, component: Component, curve_id: str) -> None:\n''',
)

# Regression test for migration of pre-existing red spectra.
test_path = Path("tests/test_fit_display_and_colours.py")
text = test_path.read_text(encoding="utf-8")
text += '''\n\ndef test_existing_red_spectrum_is_migrated_on_open() -> None:\n    app = QApplication.instance() or QApplication([])\n    project = Project("old red")\n    curve = Curve("legacy", [0.0, 1.0], [0.0, 1.0])\n    curve.colour = "#FF0000"\n    project.add_curve(curve)\n    project.dirty = False\n    window = MainWindow(project)\n    assert spectrum_colour_allowed(curve.colour)\n    assert curve.colour.upper() != MODEL_SUM_COLOUR.upper()\n    project.dirty = False\n    window.close()\n    app.processEvents()\n'''
test_path.write_text(text, encoding="utf-8")
