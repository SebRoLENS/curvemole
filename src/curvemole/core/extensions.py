"""Additive, owner-scoped extension contracts. No Qt dependency."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from typing import Any

from curvemole.core.errors import CurveMoleError

KINDS = frozenset({"importers", "exporters", "transformations", "analysis", "actions",
                   "workflows", "import_processors", "panels", "plot_layers", "hooks", "fit_solvers"})


@dataclass(frozen=True)
class Contribution:
    owner: str
    identifier: str
    label: str
    kind: str
    callback: Callable[..., Any]
    description: str = ""
    auto_show: bool = False


class ExtensionRegistry:
    def __init__(self) -> None:
        self.entries: dict[str, Contribution] = {}

    def values(self, kind: str) -> tuple[Contribution, ...]:
        return tuple(entry for entry in self.entries.values() if entry.kind == kind)

    def remove_owner(self, owner: str) -> None:
        self.entries = {key: value for key, value in self.entries.items() if value.owner != owner}


extensions = ExtensionRegistry()


class PluginAPI:
    """Registration facade; legacy register(FunctionDefinition) is additive too."""
    version = "1"

    def __init__(self, manager: Any, owner: str) -> None:
        self._manager = manager
        self.identifier = owner

    def register(self, definition: Any, *, replace: bool = False) -> None:
        if replace:
            raise CurveMoleError("Plugins cannot replace registered functions.")
        if definition.identifier in self._manager.registry.identifiers():
            raise CurveMoleError(f"Function already registered: {definition.identifier}")
        original = definition.evaluator
        def evaluate(*args: Any, **kwargs: Any) -> Any:
            return self._manager.invoke(self.identifier, original, *args, **kwargs)
        marked = dataclass_replace(
            definition, display_name=f"◆ {definition.display_name}", evaluator=evaluate,
            custom_metadata={**definition.custom_metadata, "plugin_owner": self.identifier})
        self._manager.registry.register(marked)
        self._manager.function_owners[definition.identifier] = self.identifier

    def add(self, kind: str, identifier: str, label: str, callback: Callable[..., Any],
            *, description: str = "", auto_show: bool = False) -> str:
        if kind not in KINDS or not identifier.strip() or not callable(callback):
            raise CurveMoleError("Invalid extension kind, identifier or callback.")
        key = f"{self.identifier}:{identifier}"
        if key in extensions.entries:
            raise CurveMoleError(f"Extension already registered: {key}")
        def checked(*args: Any, **kwargs: Any) -> Any:
            result = callback(*args, **kwargs)
            if kind == "fit_solvers":
                import numpy as np
                request = args[0]
                vector = np.asarray(result.x, dtype=float)
                lower, upper = request.bounds
                if (vector.shape != request.initial.shape or not np.all(np.isfinite(vector))
                        or np.any(vector < lower) or np.any(vector > upper)
                        or int(result.nfev) != result.nfev or result.nfev < 0):
                    raise CurveMoleError("Invalid solver result vector, bounds or evaluation count.")
                # Check the complete protocol while still within the guarded boundary.
                bool(result.success), int(result.status), str(result.message)
            return result

        def guarded(*args: Any, **kwargs: Any) -> Any:
            return self._manager.invoke(self.identifier, checked, *args, **kwargs)
        extensions.entries[key] = Contribution(self.identifier, key, f"◆ {label}", kind,
                                               guarded, description, auto_show)
        return key
