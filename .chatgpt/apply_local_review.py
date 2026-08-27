#!/usr/bin/env python3
"""Apply the reviewed CurveMole diff by exact context matching."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Hunk:
    path: str
    old: str
    new: str


def parse_review_diff(path: Path) -> list[Hunk]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    hunks: list[Hunk] = []
    current_path: str | None = None
    old: list[str] | None = None
    new: list[str] | None = None

    def flush() -> None:
        nonlocal old, new
        if current_path is not None and old is not None and new is not None and old:
            hunks.append(Hunk(current_path, "".join(old), "".join(new)))
        old = new = None

    for line in lines:
        if line.startswith("diff --git "):
            flush()
            parts = line.rstrip("\n").split()
            current_path = parts[3][2:]
            continue
        if line.startswith("@@"):
            flush()
            old, new = [], []
            continue
        if old is None or new is None:
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("+"):
            new.append(line[1:])
        elif line.startswith("-"):
            old.append(line[1:])
        elif line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
        elif line == "\n":
            old.append(line)
            new.append(line)
        else:
            old.append(line)
            new.append(line)
    flush()
    return hunks


def apply(root: Path, diff: Path) -> None:
    hunks = parse_review_diff(diff)
    if not hunks:
        raise SystemExit("No hunks found in review diff")
    grouped: dict[str, list[Hunk]] = {}
    for hunk in hunks:
        grouped.setdefault(hunk.path, []).append(hunk)
    for rel_path, file_hunks in grouped.items():
        target = root / rel_path
        text = target.read_text(encoding="utf-8")
        cursor = 0
        for number, hunk in enumerate(file_hunks, 1):
            pos = text.find(hunk.old, cursor)
            if pos < 0:
                positions: list[int] = []
                start = 0
                while True:
                    found = text.find(hunk.old, start)
                    if found < 0:
                        break
                    positions.append(found)
                    start = found + 1
                if len(positions) == 1:
                    pos = positions[0]
                else:
                    raise SystemExit(
                        f"Cannot apply hunk {number} to {rel_path}: expected source context not found uniquely"
                    )
            text = text[:pos] + hunk.new + text[pos + len(hunk.old):]
            cursor = pos + len(hunk.new)
        target.write_text(text, encoding="utf-8")
        print(f"PATCH OK: {rel_path} ({len(file_hunks)} hunks)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--diff", type=Path, required=True)
    args = parser.parse_args()
    apply(args.checkout.resolve(), args.diff.resolve())
