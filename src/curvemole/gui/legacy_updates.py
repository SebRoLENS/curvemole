"""Historical update helper API, retained solely for external integrations.

Application code uses updates.should_notify and updates.asset_suffixes. Keep
these legacy entry points importable from their original modules; they preserve
historical semantics and are not policies for the current update controller.
"""
from __future__ import annotations


def _update_notification_due(
    latest: str,
    last_notified_version: str,
    last_notified_at: float,
    now: float,
) -> bool:
    if latest != last_notified_version:
        return True
    return now - last_notified_at >= 10 * 24 * 60 * 60


def asset_suffix(system: str, machine: str) -> str | None:
    """Return the release asset suffix that can safely self-replace this build."""
    architecture = machine.lower()
    if architecture not in {"x86_64", "amd64"}:
        return None
    if system == "Linux":
        return "-linux-x86_64.AppImage"
    if system == "Windows":
        return "-windows-x86_64.exe"
    return None
