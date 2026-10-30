"""Stamp testing packages and publish optional prereleases without touching stable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def beta_version(target: str, sequence: str) -> str:
    from runpy import run_path

    validate = run_path(str(Path(__file__).with_name("release_target.py")))["version_tuple"]
    validate(target)
    if not sequence.isdecimal() or int(sequence) < 1:
        raise ValueError("Expected a positive beta sequence")
    return f"{target}b{int(sequence)}"


def stamp(version: str, root: Path = Path(".")) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+b[1-9]\d*", version):
        raise ValueError("Expected a PEP 440 beta version")
    # Dependencies remain locked; only the editable root package version changes.
    replacements = {
        "src/curvemole/version.py": (r'^__version__ = "[^"]+"', f'__version__ = "{version}"'),
        "pyproject.toml": (r'^version = "[^"]+"', f'version = "{version}"'),
        "uv.lock": (r'(name = "curvemole"\nversion = ")[^"]+("\n)', rf'\g<1>{version}\2'),
    }
    for name, (pattern, replacement) in replacements.items():
        path = root / name
        text, count = re.subn(pattern, replacement, path.read_text(encoding="utf-8"), flags=re.M)
        if count != 1:
            raise ValueError(f"Expected exactly one package version in {name}")
        path.write_text(text, encoding="utf-8")


def expected_assets(version: str) -> set[str]:
    prefix = f"CurveMole-{version}"
    return {
        f"{prefix}-linux-x86_64.AppImage", f"{prefix}-linux-x86_64.AppImage.sigstore.json",
        f"{prefix}-macos-arm64.dmg", f"{prefix}-macos-x86_64.dmg",
        f"{prefix}-windows-x86_64-setup.exe", f"{prefix}-windows-x86_64-portable.zip",
        f"curvemole-{version}-py3-none-any.whl", f"curvemole-{version}.tar.gz",
        *documentation_assets(version),
    }


def documentation_assets(version: str) -> dict[str, str]:
    """Map downloadable beta document names to their reviewed source editions."""
    if not re.fullmatch(r"\d+\.\d+\.\d+b[1-9]\d*", version):
        raise ValueError("Expected a PEP 440 beta version")
    prefix = f"CurveMole-{version}"
    return {
        f"{prefix}-User-Manual.pdf": "docs/CurveMole_User_Manual.pdf",
        f"{prefix}-User-Manual.tex": "docs/CurveMole_User_Manual.tex",
        f"{prefix}-AI-Python-Audit.md": "docs/ai-python-audit.md",
        f"{prefix}-AI-YAML-Audit.md": "docs/ai-yaml-audit.md",
    }


def prepare_documents(version: str, directory: Path, root: Path = Path(".")) -> list[Path]:
    """Package committed manuals/audits without changing stable source metadata."""
    sources = documentation_assets(version)
    payloads = {name: (root / source).read_bytes() for name, source in sources.items()}
    for name, payload in payloads.items():
        if not payload:
            raise ValueError(f"Empty beta documentation: {sources[name]}")
        if name.endswith(".pdf"):
            if not payload.startswith(b"%PDF-"):
                raise ValueError("The committed beta manual is not a PDF")
        else:
            payload.decode("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, payload in payloads.items():
        destination = directory / name
        destination.write_bytes(payload)
        outputs.append(destination)
    return outputs


def publish(version: str, directory: Path) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+b[1-9]\d*", version):
        raise ValueError("Only beta versions may use this publisher")
    # Validate all required platform artifacts before creating any public release.
    for status in directory.glob("macos-signing-*.json"):
        status.unlink()
    files = {path.name: path for path in directory.iterdir() if path.is_file()}
    if set(files) != expected_assets(version):
        raise ValueError(f"Unexpected beta assets: {set(files) ^ expected_assets(version)}")
    checks = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    checksum = directory / "SHA256SUMS.txt"
    checksum.write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(checks.items())), encoding="utf-8")
    checks[checksum.name] = hashlib.sha256(checksum.read_bytes()).hexdigest()
    files[checksum.name] = checksum
    tag = "v" + version.replace("b", "-beta.")
    repository = os.environ["GITHUB_REPOSITORY"]
    source = os.environ["GITHUB_SHA"]
    downloads = f"https://github.com/{repository}/releases/download/{tag}/CurveMole-{version}"
    # Release-specific notes are derived from the previous published beta tag.
    # No manual list or stale description can leak into another beta.
    from runpy import run_path

    history = run_path(str(Path(__file__).with_name("changelog_tools.py")))
    previous, changes = history["beta_changes"](source, version=version)
    compare = f"https://github.com/{repository}/compare/{previous}...{source}"
    notes = directory / "beta-notes.md"
    notes.write_text(
        f"CurveMole {tag[1:]} — Beta / testing channel\n\n"
        f"## Changes since {previous}\n\n{changes}\n\n"
        f"[Compare exact source changes]({compare}). "
        "The cumulative stable-cycle changes are tracked in CHANGELOG.md.\n\n"
        "Bug fixes and new features may arrive sooner. Updates may be frequent and introduce new bugs.\n\n"
        "Choose **Help > Update channel…** to switch between Beta and Stable. Switching to Stable "
        "keeps your installed version until an equal or newer stable release is available; "
        "it never downgrades automatically.\n\n"
        "Older versions are not recommended; advanced users may download and install a chosen "
        "version from the GitHub repository.\n\n"
        f"Source: `{source}` on `testing`. Verify downloads against `SHA256SUMS.txt`.\n\n"
        "Windows and macOS packages are unsigned, as with the stable channel.\n\n"
        f"**Documentation:** [Manual PDF]({downloads}-User-Manual.pdf) · "
        f"[LaTeX]({downloads}-User-Manual.tex) · "
        f"[AI Python audit]({downloads}-AI-Python-Audit.md) · "
        f"[AI YAML audit]({downloads}-AI-YAML-Audit.md).\n\n"
        "The manual retains stable baseline metadata; see the version-specific change list "
        "above for the features included in this exact beta.\n\n"
        "**Zenodo DOI:** pending archival. The beta's specific DOI is linked automatically "
        "after Zenodo has archived this release.\n",
        encoding="utf-8",
    )
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", repository,
                               "--json", "isDraft,targetCommitish"], capture_output=True, text=True)
    if existing.returncode == 0:
        release = json.loads(existing.stdout)
        if release["targetCommitish"] != source:
            raise ValueError("Beta tag belongs to a different source")
        if not release["isDraft"]:
            print("This beta is already published; retaining its immutable assets.")
            return
    else:
        # A missing release is expected; auth or API failures must not be mistaken for 404.
        if "not found" not in existing.stderr.lower() and "404" not in existing.stderr:
            raise RuntimeError(existing.stderr)
        subprocess.run(["gh", "release", "create", tag, "--repo", repository, "--target", source,
                        "--draft", "--prerelease", "--latest=false", "--title", f"CurveMole {tag[1:]} Beta",
                        "--notes-file", str(notes)], check=True)
    subprocess.run(["gh", "release", "upload", tag, "--repo", repository,
                    *map(str, files.values()), "--clobber"], check=True)
    # The list endpoint reliably includes drafts for an authenticated push token.
    response = subprocess.check_output(["gh", "api", f"repos/{repository}/releases?per_page=100"], text=True)
    current = next(item for item in json.loads(response) if item["tag_name"] == tag)
    uploaded = {asset["name"]: asset for asset in current["assets"]}
    if set(uploaded) != set(checks) or any(
        uploaded[name].get("digest") != f"sha256:{digest}"
        or uploaded[name]["state"] != "uploaded" or uploaded[name]["size"] <= 0
        for name, digest in checks.items()
    ):
        raise ValueError("Beta upload failed checksum verification")
    subprocess.run(["gh", "release", "edit", tag, "--repo", repository, "--draft=false",
                    "--prerelease", "--latest=false"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "stamp", "documents", "publish"])
    parser.add_argument("--version", default=os.environ.get("BETA_VERSION", ""))
    parser.add_argument("--directory", type=Path, default=Path("beta-assets"))
    args = parser.parse_args()
    if args.command == "plan":
        import runpy

        base = runpy.run_path("src/curvemole/version.py")["__version__"]
        targets = runpy.run_path(str(Path(__file__).with_name("release_target.py")))
        target = targets["beta_target"](base)
        version = beta_version(target, os.environ["GITHUB_RUN_NUMBER"])
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(f"version={version}\n")
    elif args.command == "stamp":
        stamp(args.version)
    elif args.command == "documents":
        for document in prepare_documents(args.version, args.directory):
            print(document)
    else:
        publish(args.version, args.directory)


if __name__ == "__main__":
    main()
