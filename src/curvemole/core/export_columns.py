"""Lossless column naming shared by numeric spectrum exports."""
from __future__ import annotations


class ExportColumns(dict):
    """Allocate names without overwriting earlier numeric fields."""

    def __init__(self):
        super().__init__()
        self.roles = {}

    def add(self, label, values, *, role=None):
        name = label
        number = 2
        while name in self:
            name = f"{label}__{number}"
            number += 1
        super().__setitem__(name, values)
        if role is not None:
            self.roles[role] = name
        return name

    def __setitem__(self, label, values):
        self.add(label, values)
