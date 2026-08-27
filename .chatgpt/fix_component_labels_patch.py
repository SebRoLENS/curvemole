from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/curvemole/gui/main_window.py",
    '''        def redo() -> None:
            for curve_id, *_ in records:
                try:
                    self.project.remove_curve(curve_id)
                except KeyError:
                    pass
            if self.active_curve_id in selected:
''',
    '''        def redo() -> None:
            existing_ids = {curve.id for curve in self.project.curves}
            for curve_id, *_ in records:
                if curve_id in existing_ids:
                    self.project.remove_curve(curve_id)
            if self.active_curve_id in selected:
''',
)

replace_once(
    "src/curvemole/gui/main_window.py",
    '''    def _normalise_component_names(self) -> None:
        for model in self.project.models.values():
            counters: dict[str, int] = {}
            for component in model.components:
                counters[component.function_id] = counters.get(component.function_id, 0) + 1
                component.name = (
                    f"{self._component_base_name(component)}{counters[component.function_id]}"
                )
''',
    '''    def _normalise_component_names(self) -> None:
        for model in self.project.models.values():
            used: dict[str, set[int]] = {}
            pending: list[Component] = []
            for component in model.components:
                base = self._component_base_name(component)
                match = re.fullmatch(rf"{re.escape(base)}(\\d+)", component.name)
                number = int(match.group(1)) if match else 0
                numbers = used.setdefault(component.function_id, set())
                if number > 0 and number not in numbers:
                    numbers.add(number)
                else:
                    pending.append(component)
            for component in pending:
                numbers = used.setdefault(component.function_id, set())
                number = max(numbers, default=0) + 1
                numbers.add(number)
                component.name = f"{self._component_base_name(component)}{number}"
''',
)

replace_once(
    "tests/test_curve_labels_and_removal.py",
    '''    assert [label.toPlainText() for label in window.plot_workspace._component_labels] == ["Voigt1", "Voigt2"]
''',
    '''    assert [label.textItem.toPlainText() for label in window.plot_workspace._component_labels] == ["Voigt1", "Voigt2"]
''',
)
