"""Registry shared by built-in functions, formulas, and plugins."""

from __future__ import annotations

from collections.abc import Iterable

from curvemole.core.errors import DataValidationError
from curvemole.core.functions import FunctionDefinition, builtin_definitions


class FunctionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, FunctionDefinition] = {}

    def register(self, definition: FunctionDefinition, *, replace: bool = False) -> None:
        identifier = definition.identifier.strip()
        if not identifier:
            raise DataValidationError("A function identifier cannot be empty.")
        if identifier in self._definitions and not replace:
            raise DataValidationError(f"Function '{identifier}' is already registered.")
        self._definitions[identifier] = definition

    def unregister(self, identifier: str) -> None:
        if identifier not in self._definitions:
            raise KeyError(identifier)
        del self._definitions[identifier]

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
