"""Registry shared by built-in functions, formulas, and plugins."""

from __future__ import annotations

from collections.abc import Iterable

from curvemole.core.errors import DataValidationError
from curvemole.core.functions import FunctionDefinition, builtin_definitions, formula_definition


class FunctionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, FunctionDefinition] = {}
        self._project_originals: dict[str, FunctionDefinition | None] = {}

    def register(self, definition: FunctionDefinition, *, replace: bool = False) -> None:
        identifier = definition.identifier.strip()
        if not identifier:
            raise DataValidationError("A function identifier cannot be empty.")
        if identifier in self._definitions and not replace:
            raise DataValidationError(f"Function '{identifier}' is already registered.")
        self._definitions[identifier] = definition

    def register_custom(self, definition: FunctionDefinition, *, replace: bool = False) -> None:
        identifier = definition.identifier.strip()
        if ("formula" in definition.custom_metadata
                and identifier in {d.identifier for d in builtin_definitions()}):
            raise DataValidationError(f"Custom function '{identifier}' collides with a builtin function.")
        self.register(definition, replace=replace)

    def copy(self) -> FunctionRegistry:
        """Isolate a session without copying immutable evaluator callables."""
        result = FunctionRegistry()
        result._definitions = self._definitions.copy()
        result._project_originals = self._project_originals.copy()
        return result

    def set_project_functions(self, specifications) -> None:
        """Validate all definitions before atomically replacing the project layer."""
        definitions = []
        probe = self.copy()
        seen = set()
        for value in specifications:
            identifier = value["identifier"]
            if identifier in seen:
                raise DataValidationError(f"Duplicate project function: {identifier}")
            seen.add(identifier)
            definition = formula_definition(
                identifier, value.get("display_name", identifier), value["formula"],
                kind=value.get("kind", "generic"), defaults=value.get("defaults"),
                bounds={key: tuple(bounds) for key, bounds in value.get("bounds", {}).items()},
                derived_formulas=value.get("derived_formulas", {}))
            probe.register_custom(definition, replace=True)
            definitions.append(definition)
        for identifier, original in self._project_originals.items():
            if original is None:
                self._definitions.pop(identifier, None)
            else:
                self._definitions[identifier] = original
        self._project_originals.clear()
        for definition in definitions:
            self._project_originals[definition.identifier] = self._definitions.get(definition.identifier)
            self.register(definition, replace=True)

    def unregister(self, identifier: str) -> None:
        if identifier not in self._definitions:
            raise KeyError(identifier)
        del self._definitions[identifier]
        # Explicit removal must not be undone by clearing a project override.
        if identifier in self._project_originals:
            self._project_originals[identifier] = None

    def remove_owner(self, owner: str) -> None:
        """Remove a plugin's visible and shadowed definitions, preserving formulas."""
        for identifier, definition in list(self._definitions.items()):
            if definition.custom_metadata.get("plugin_owner") == owner:
                self._definitions.pop(identifier)
        for identifier, definition in self._project_originals.items():
            if definition is not None and definition.custom_metadata.get("plugin_owner") == owner:
                self._project_originals[identifier] = None

    def get(self, identifier: str) -> FunctionDefinition:
        try:
            return self._definitions[identifier]
        except KeyError as exc:
            raise DataValidationError(f"Unknown function: {identifier}") from exc

    def values(self) -> tuple[FunctionDefinition, ...]:
        return tuple(self._definitions.values())

    def identifiers(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def extend(self, definitions: Iterable[FunctionDefinition]) -> None:
        for definition in definitions:
            self.register(definition)


_DEFAULT: FunctionRegistry | None = None


def default_registry() -> FunctionRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FunctionRegistry()
        _DEFAULT.extend(builtin_definitions())
    return _DEFAULT
