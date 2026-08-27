from __future__ import annotations

from pathlib import Path

path = Path("src/curvemole/gui/main_window.py")
text = path.read_text(encoding="utf-8")
old = '''    def _series_layout_snapshot(self) -> list[tuple[str, str, dict[str, Any], list[str]]]:
        return [
            (
                series.id,
                series.name,
                copy.deepcopy(series.metadata),
                [curve.id for curve in series.curves],
            )
            for series in self.project.dataset.series
        ]

    def _restore_series_layout(
        self, snapshot: list[tuple[str, str, dict[str, Any], list[str]]]
    ) -> None:
        curve_map = {curve.id: curve for curve in self.project.curves}
        self.project.dataset.series = [
            Series(
                name=name,
                curves=[curve_map[curve_id] for curve_id in curve_ids],
                id=series_id,
                metadata=copy.deepcopy(metadata),
            )
            for series_id, name, metadata, curve_ids in snapshot
        ]
        self.project.touch()
        self.refresh_all()
'''
new = '''    def _series_layout_snapshot(self) -> list[tuple[Series, str, dict[str, Any], list[str]]]:
        return [
            (
                series,
                series.name,
                copy.deepcopy(series.metadata),
                [curve.id for curve in series.curves],
            )
            for series in self.project.dataset.series
        ]

    def _restore_series_layout(
        self, snapshot: list[tuple[Series, str, dict[str, Any], list[str]]]
    ) -> None:
        # Keep the original Series objects alive across Undo/Redo. This matters for
        # GUI and external references, and also allows a merged-away series to be
        # restored as the very same object rather than a replacement with the same id.
        curve_map = {curve.id: curve for curve in self.project.curves}
        restored: list[Series] = []
        for series, name, metadata, curve_ids in snapshot:
            series.name = name
            series.metadata = copy.deepcopy(metadata)
            series.curves = [curve_map[curve_id] for curve_id in curve_ids]
            restored.append(series)
        self.project.dataset.series = restored
        self.project.touch()
        self.refresh_all()
'''
if old not in text:
    raise SystemExit("series snapshot block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
