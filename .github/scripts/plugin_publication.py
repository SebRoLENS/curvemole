"""Prepare and check a one-plugin update to the public CurveMole catalog."""

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from zipfile import ZipFile

SLUG = r"[A-Za-z0-9][A-Za-z0-9_-]*"
CATEGORIES = ("by_main_developer", "by_community")


def version(entry):
    value = entry["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError(f"Invalid plugin version: {value}")
    return tuple(map(int, value.split(".")))


def catalog(path):
    entries = {}
    for plugin in json.loads(path.read_text(encoding="utf-8"))["plugins"]:
        folder = plugin["folder"]
        if (not re.fullmatch(SLUG, folder) or plugin["category"] not in CATEGORIES
                or folder in entries):
            raise ValueError(f"Invalid or duplicate plugin folder: {folder}")
        entries[folder] = plugin
    return entries


def prepare(archive, previous, source, destination, folder):
    if not re.fullmatch(SLUG, folder):
        raise ValueError("Enter the plugin's folder name")
    matching = [source / category / folder for category in CATEGORIES
                if (source / category / folder).is_dir()]
    if len(matching) != 1:
        raise ValueError(f"Expected exactly one plugin folder named {folder} on testing")

    with ZipFile(archive) as bundle:
        if bundle.read("catalog.json") != previous.read_bytes():
            raise ValueError("The public bundle and catalog differ. Retry after publication finishes.")
        bundle.extractall(destination)
    plugins = destination / "custom_plugins"
    plugins.mkdir()
    for category in CATEGORIES:
        directory = destination / category
        if directory.exists():
            directory.rename(plugins / category)
        (plugins / category).mkdir(exist_ok=True)
    (destination / "README.md").rename(plugins / "README.md")

    old = catalog(previous).get(folder)
    if old:
        shutil.rmtree(plugins / old["category"] / folder)
    selected = matching[0]
    shutil.copytree(selected, plugins / selected.parent.name / folder, symlinks=True)


def check_update(previous, candidate, folder):
    before, after = catalog(previous), catalog(candidate)
    old = before.pop(folder, None)
    new = after.pop(folder)
    if before != after:
        raise ValueError("The update also changed another plugin in the public catalog")
    if old:
        if new["identifier"] != old["identifier"]:
            raise ValueError("The update changed the existing plugin's identifier")
        if old != new and version(new) <= version(old):
            raise ValueError(f"Bump the version of {folder} before publishing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("select")
    update = commands.add_parser("prepare")
    for name in ("archive", "previous", "source", "destination"):
        update.add_argument(name, type=Path)
    update.add_argument("folder")
    check = commands.add_parser("check")
    check.add_argument("previous", type=Path)
    check.add_argument("candidate", type=Path)
    check.add_argument("folder")
    args = parser.parse_args()

    if args.command == "select":
        if os.environ["GITHUB_EVENT_NAME"] == "push":
            message = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["head_commit"]["message"]
            matches = re.findall(rf"\[publish plugin: ({SLUG})\]", message)
            if len(matches) != 1 or "[skip release]" not in message:
                raise ValueError("Use one [publish plugin: folder] marker with [skip release]")
            folder = matches[0]
        else:
            folder = os.environ["PLUGIN"]
        if not re.fullmatch(SLUG, folder):
            raise ValueError("Enter the plugin's folder name")
        print(f"folder={folder}")
    elif args.command == "prepare":
        prepare(args.archive, args.previous, args.source, args.destination, args.folder)
    else:
        check_update(args.previous, args.candidate, args.folder)


if __name__ == "__main__":
    main()
