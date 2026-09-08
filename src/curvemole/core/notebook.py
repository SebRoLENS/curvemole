"""Project notes and durable descriptions keyed by object identity, not name."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from curvemole.core.project import Project


@dataclass(slots=True)
class Description:
    kind: str
    object_id: str
    curve_id: str = ""
    series_name: str = ""
    curve_name: str = ""
    name: str = ""
    function_id: str = ""
    text: str = ""
    updated_at: str = ""
    deleted: bool = False

    @property
    def key(self) -> str:
        return description_key(self.kind, self.object_id, self.curve_id)

    @property
    def title(self) -> str:
        if self.kind == "series":
            return self.name
        if self.kind == "spectrum":
            return f"{self.series_name} / {self.name}"
        return f"{self.series_name} / {self.curve_name} / {self.name} ({self.function_id})"


def description_key(kind: str, object_id: str, curve_id: str = "") -> str:
    return f"{kind}:{curve_id}:{object_id}"


@dataclass(slots=True)
class LaboratoryNotebook:
    notes: str = ""
    descriptions: dict[str, Description] = field(default_factory=dict)

    def sync(self, project: Project) -> None:
        """Refresh live labels; retain absent objects and their last known labels."""
        for key in [key for key, entry in self.descriptions.items() if not entry.text.strip()]:
            del self.descriptions[key]
        if not self.descriptions:
            return
        series_by_id = {series.id: series for series in project.dataset.series}
        curves = {curve.id: (series, curve) for series in project.dataset.series for curve in series.curves}
        for entry in self.descriptions.values():
            if entry.kind == "series":
                series = series_by_id.get(entry.object_id)
                entry.deleted = series is None
                if series is not None:
                    entry.name = entry.series_name = series.name
            elif entry.kind == "spectrum":
                context = curves.get(entry.object_id)
                entry.deleted = context is None
                if context is not None:
                    series, curve = context
                    entry.series_name = series.name
                    entry.name = entry.curve_name = curve.name
            else:
                context = curves.get(entry.curve_id)
                model = project.models.get(entry.curve_id)
                component = next((c for c in model.components if c.id == entry.object_id), None) if model else None
                entry.deleted = context is None or component is None
                if not entry.deleted:
                    series, curve = context
                    entry.series_name, entry.curve_name = series.name, curve.name
                    entry.name, entry.function_id = component.name, component.function_id

    def set_description(self, project: Project, kind: str, object_id: str, text: str, curve_id: str = "") -> None:
        if project.read_only:
            raise PermissionError("This project is open read-only.")
        key = description_key(kind, object_id, curve_id)
        if not text.strip():
            if key in self.descriptions:
                del self.descriptions[key]
                project.touch()
            return
        entry = self.descriptions.get(key)
        if entry is None:
            if kind not in {"series", "spectrum", "function"}:
                raise ValueError(f"Unknown description kind: {kind}")
            if not text.strip():
                return
            entry = Description(kind, object_id, curve_id)
            self.descriptions[key] = entry
        if entry.text == text:
            return
        entry.text = text
        entry.updated_at = datetime.now(UTC).isoformat()
        project.touch()

    def to_dict(self) -> dict[str, Any]:
        return {"notes": self.notes, "descriptions": [asdict(entry) for entry in self.descriptions.values()]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LaboratoryNotebook:
        entries = [Description(**entry) for entry in value.get("descriptions", []) if entry.get("text", "").strip()]
        return cls(str(value.get("notes", "")), {entry.key: entry for entry in entries})

    def ordered_descriptions(self) -> list[Description]:
        return sorted(self.descriptions.values(), key=lambda entry: (
            entry.deleted, entry.series_name.casefold(), entry.curve_name.casefold(),
            {"series": 0, "spectrum": 1, "function": 2}.get(entry.kind, 3), entry.name.casefold(), entry.key,
        ))

    def as_text(self, project: Project) -> str:
        self.sync(project)
        lines = ["CurveMole — Laboratory notebook", f"Project: {project.name}", "", "PROJECT NOTES", "", self.notes or "(No notes)"]
        entries = self.ordered_descriptions()
        for title, selected in (
            ("SERIES DESCRIPTIONS", [e for e in entries if not e.deleted and e.kind == "series"]),
            ("SPECTRUM DESCRIPTIONS", [e for e in entries if not e.deleted and e.kind == "spectrum"]),
            ("FUNCTION DESCRIPTIONS", [e for e in entries if not e.deleted and e.kind == "function"]),
            ("DELETED ITEMS — retained descriptions", [e for e in entries if e.deleted]),
        ):
            lines.extend(["", title, ""])
            if not selected:
                lines.append("(None)")
            for entry in selected:
                lines.extend([
                    f"{'[DELETED] ' if entry.deleted else ''}{entry.title}",
                    f"Type: {entry.kind} | ID: {entry.object_id}"
                    + (f" | Spectrum ID: {entry.curve_id}" if entry.curve_id else ""),
                    f"Description updated: {entry.updated_at}", "", entry.text or "(Empty description)", "",
                ])
        return "\n".join(lines).rstrip() + "\n"


def export_notebook(project: Project, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(project.notebook.as_text(project), encoding="utf-8")
    return destination
