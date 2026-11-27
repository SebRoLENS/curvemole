"""Registry of contributions to the main window's actions, menus, toolbar and signals.

Extension modules used to wrap ``MainWindow._build_actions``, ``_build_menus``,
``_build_toolbar`` and ``_connect_signals`` to add their own commands. They now
register a contribution for the corresponding stage instead; MainWindow runs
the contributions of each stage, in registration order, right after building
its own part of that stage.

    from curvemole.gui import window_extensions

    def add_actions(window):
        window.my_action = QAction(window.tr("My command"), window)

    def add_menus(window):
        window_extensions.insert_menu_action(window, "File", window.my_action,
                                             before=window.export_parameters_action)

    window_extensions.register("actions", add_actions)
    window_extensions.register("menus", add_menus)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

STAGES = ("actions", "menus", "toolbar", "signals")
_contributions: dict[str, list[tuple[str, Callable[[Any], None]]]] = {stage: [] for stage in STAGES}


def register(stage: str, contribution: Callable[[Any], None], *, key: str | None = None) -> None:
    """Add ``contribution(window)`` to ``stage``; re-registering a key replaces it in place."""
    if stage not in STAGES:
        raise ValueError(f"Unknown window extension stage {stage!r}; expected one of {', '.join(STAGES)}.")
    key = key or f"{contribution.__module__}.{contribution.__qualname__}"
    entries = _contributions[stage]
    for index, (existing, _) in enumerate(entries):
        if existing == key:
            entries[index] = (key, contribution)
            return
    entries.append((key, contribution))


def contributions(stage: str) -> list[str]:
    """Registered contribution keys of ``stage``, in execution order."""
    return [key for key, _ in _contributions[stage]]


def run(window: Any, stage: str) -> None:
    for _, contribution in list(_contributions[stage]):
        contribution(window)


def find_menu(window: Any, title: str) -> Any:
    wanted = window.tr(title)
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and menu.title().replace("&", "") == wanted:
            return menu
    return None


def insert_menu_action(window: Any, menu_title: str, action: Any, *, before: Any = None) -> None:
    """Insert ``action`` into a top-level menu, before ``before`` when it is present."""
    menu = find_menu(window, menu_title)
    if menu is None:
        return
    if before is not None and before in menu.actions():
        menu.insertAction(before, action)
    else:
        menu.addAction(action)
