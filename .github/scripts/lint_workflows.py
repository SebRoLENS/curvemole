"""Run pinned actionlint, validating newer queue syntax not yet known to 1.7.12."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


def validate_queues(value: object) -> None:
    if isinstance(value, dict):
        concurrency = value.get("concurrency")
        if isinstance(concurrency, dict) and "queue" in concurrency:
            queue = concurrency["queue"]
            cancel = concurrency.get("cancel-in-progress", "false")
            # The single expression is deliberately explicit and covered by tests.
            dynamic = "${{ github.event_name == 'pull_request' && 'single' || 'max' }}"
            if queue not in ("single", "max", dynamic):
                raise ValueError(f"Invalid concurrency queue: {queue}")
            if queue == "max" and cancel == "true":
                raise ValueError("queue: max cannot cancel in-progress jobs")
            if queue == dynamic and cancel != "${{ github.event_name == 'pull_request' }}":
                raise ValueError("Dynamic queue and cancellation policies must agree")
        for child in value.values():
            validate_queues(child)
    elif isinstance(value, list):
        for child in value:
            validate_queues(child)


def main() -> int:
    for path in sorted(Path(".github/workflows").glob("*.yml")):
        validate_queues(yaml.load(path.read_text(), Loader=yaml.BaseLoader))
    # Only compatibility exceptions verified against current GitHub documentation.
    return subprocess.call([
        sys.argv[1], "-ignore", r'unexpected key "queue" for "concurrency" section',
        "-ignore", r'label "macos-15-intel" is unknown',
    ])


if __name__ == "__main__":
    raise SystemExit(main())
