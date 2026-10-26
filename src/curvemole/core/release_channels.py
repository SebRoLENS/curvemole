"""Release ordering and channel selection, independent of GUI and network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, order=True)
class ReleaseVersion:
    major: int
    minor: int
    patch: int
    final: bool
    beta: int = 0

    @classmethod
    def parse(cls, value: str) -> ReleaseVersion | None:
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:(?:-beta\.|b)(\d+))?", value.strip())
        if match is None:
            return None
        major, minor, patch, beta = match.groups()
        return cls(int(major), int(minor), int(patch), beta is None, int(beta or 0))

    @property
    def numbers(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    @property
    def text(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.final else f"{base}-beta.{self.beta}"

    @property
    def label(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if self.final else f"{base} Beta {self.beta}"


def default_channel(version: str) -> str:
    parsed = ReleaseVersion.parse(version)
    return "beta" if parsed is not None and not parsed.final else "stable"


def select_release(payload: Any, channel: str) -> dict[str, Any] | None:
    """Choose by version, never API ordering; stable excludes all prereleases."""
    if channel not in {"stable", "beta"}:
        raise ValueError("Unknown update channel")
    if isinstance(payload, dict):
        candidates = [payload] if "tag_name" in payload else []
    elif isinstance(payload, list):
        candidates = payload
    else:
        raise ValueError("GitHub returned invalid release data")
    eligible = []
    for release in candidates:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        version = ReleaseVersion.parse(str(release.get("tag_name", "")))
        if version is None:
            continue
        if channel == "stable" and (release.get("prerelease") or not version.final):
            continue
        # A numeric stable tag marked as a prerelease belongs to another channel.
        if version.final and release.get("prerelease"):
            continue
        eligible.append((version, release))
    return max(eligible, key=lambda item: item[0])[1] if eligible else None
