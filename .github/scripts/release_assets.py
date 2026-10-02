"""Publish complete releases and restore manuals strictly from their tagged source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def run(*args: str) -> str:
    return subprocess.check_output(list(args), text=True).strip()


def api(path: str) -> dict | list[dict]:
    return json.loads(run("gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/{path}"))


def release(tag: str) -> dict | None:
    process = subprocess.run(["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/releases/tags/{tag}"],
                             capture_output=True, text=True)
    if process.returncode == 0:
        return json.loads(process.stdout)
    if "HTTP 404" in process.stderr:
        # The tag endpoint only returns published releases. Authenticated list
        # requests also expose drafts to users/tokens with repository push access.
        page = 1
        while True:
            releases = api(f"releases?per_page=100&page={page}")
            for current in releases:
                if current["tag_name"] == tag:
                    return current
            if len(releases) < 100:
                return None
            page += 1
    raise RuntimeError(process.stderr)


def version_for_tag(tag: str) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("A release requires an exact vMAJOR.MINOR.PATCH tag")
    return tag[1:]


def expected_assets(version: str) -> set[str]:
    prefix = f"CurveMole-{version}"
    return {
        f"{prefix}-linux-x86_64.AppImage", f"{prefix}-linux-x86_64.AppImage.sigstore.json",
        f"{prefix}-macos-arm64.dmg", f"{prefix}-macos-x86_64.dmg",
        f"{prefix}-windows-x86_64-setup.exe", f"{prefix}-windows-x86_64-portable.zip",
        f"curvemole-{version}-py3-none-any.whl", f"curvemole-{version}.tar.gz",
        f"{prefix}-User-Manual.pdf", f"{prefix}-User-Manual.tex",
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checksum_text(checks: dict[str, str]) -> str:
    return "".join(f"{value}  {name}\n" for name, value in sorted(checks.items()))


def notes(version: str, ready: bool, signing: dict | None = None) -> str:
    text = Path("CHANGELOG.md").read_text()
    section = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text)
    changes = section.group(1).strip() if section else "Maintenance release."
    status = ("All desktop packages, Python distributions and the versioned manual are attached. "
              "SHA-256 checksums have been verified." if ready else
              "Release preparation is in progress. This draft is published only after validation and packaging.")
    repository = os.environ["GITHUB_REPOSITORY"]
    root = f"https://github.com/{repository}/releases/download/v{version}/CurveMole-{version}"
    table = "\n".join([
        "| Platform | Recommended download |", "|---|---|",
        f"| Windows x86_64 | [Installer]({root}-windows-x86_64-setup.exe) |",
        f"| Windows portable | [Portable ZIP]({root}-windows-x86_64-portable.zip) |",
        f"| Linux x86_64 | [AppImage]({root}-linux-x86_64.AppImage) |",
        f"| macOS Apple Silicon | [DMG]({root}-macos-arm64.dmg) |",
        f"| macOS Intel | [DMG]({root}-macos-x86_64.dmg) |",
    ])
    signing_note = ""
    if signing is not None:
        unsigned = [arch for arch in ("arm64", "x86_64") if not signing.get(arch)]
        signing_note = ("\n\nApple Developer ID signing and notarization are unavailable for "
                        + ", ".join(unsigned) + "; these macOS downloads are unsigned." if unsigned else
                        "\n\nBoth macOS downloads are signed with Apple Developer ID and notarized.")
    return (f"## CurveMole v{version}\n\n{changes}\n\n{status}{signing_note}\n\n{table}\n\n"
            "**Zenodo DOI:** pending archival or repository integration.\n")


def ensure_tag(tag: str, sha: str) -> None:
    refs = run("git", "tag", "--list", tag)
    if refs:
        if run("git", "rev-parse", f"{tag}^{{commit}}") != sha:
            raise ValueError("Existing release tag belongs to a different commit")
        return
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email",
                    "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "tag", "-a", tag, sha, "-m", f"CurveMole {tag}"], check=True)
    subprocess.run(["git", "push", "origin", f"refs/tags/{tag}"], check=True)


def draft(tag: str) -> None:
    version = version_for_tag(tag)
    sha = run("git", "rev-parse", "HEAD")
    ensure_tag(tag, sha)
    current = release(tag)
    if current is not None:
        print("Release already exists; retaining its metadata and publication state.")
        return
    Path("release-notes.md").write_text(notes(version, False))
    subprocess.run(["gh", "release", "create", tag, "--draft", "--verify-tag",
                    "--title", f"CurveMole {tag}", "--notes-file", "release-notes.md"], check=True)


def verify(current: dict, version: str, checks: dict[str, str]) -> None:
    expected = expected_assets(version) | {"SHA256SUMS.txt"}
    assets = {item["name"]: item for item in current["assets"]}
    if set(assets) != expected:
        raise ValueError(f"Release assets differ: missing={expected-set(assets)}, extra={set(assets)-expected}")
    if set(checks) != expected:
        raise ValueError("Checksum manifest must cover every expected release asset")
    for name, value in checks.items():
        asset = assets[name]
        if asset["state"] != "uploaded" or asset["size"] <= 0 or asset.get("digest") != f"sha256:{value}":
            raise ValueError(f"Release asset checksum/state mismatch: {name}")


def finalize(tag: str, directory: Path) -> None:
    version = version_for_tag(tag)
    current = release(tag)
    if current is None:
        raise ValueError("Release draft is missing")
    if not current["draft"]:
        raise ValueError("Refusing to rebuild or overwrite an already published release")
    signing = {}
    for arch in ("arm64", "x86_64"):
        status = directory / f"macos-signing-{arch}.json"
        signing[arch] = json.loads(status.read_text())["signed"]
        status.unlink()
    for ext in ("pdf", "tex"):
        (directory / f"CurveMole-{version}-User-Manual.{ext}").write_bytes(
            Path(f"docs/CurveMole_User_Manual.{ext}").read_bytes())
    files = {p.name: p for p in directory.iterdir() if p.is_file()}
    if set(files) != expected_assets(version):
        raise ValueError("Build did not produce the exact expected set of release files")
    checks = {name: digest(path) for name, path in files.items()}
    checksum = directory / "SHA256SUMS.txt"
    checksum.write_text(checksum_text(checks))
    checks[checksum.name] = digest(checksum)
    # The attested Linux files were already uploaded by their originating job.
    upload = [str(p) for name, p in files.items() if "-linux-x86_64.AppImage" not in name]
    subprocess.run(["gh", "release", "upload", tag, *upload, str(checksum), "--clobber"], check=True)
    verify(release(tag), version, checks)
    body = notes(version, True, signing)
    # Preserve a DOI if a previous retry already supplied one to the draft.
    doi = re.search(r"(?m)^\*\*Zenodo DOI:\*\* https://doi.org/10\.5281/zenodo\.\d+.*$", current["body"] or "")
    if doi:
        body = re.sub(r"(?m)^\*\*Zenodo DOI:\*\*.*$", doi.group(), body)
    Path("release-notes.md").write_text(body)
    subprocess.run(["gh", "release", "edit", tag, "--notes-file", "release-notes.md",
                    "--draft=false", "--latest"], check=True)
    print(f"Published {tag}: all 11 assets and their checksums verified.")


def repair_manual(tag: str, directory: Path) -> None:
    version = version_for_tag(tag)
    if run("git", "rev-parse", "HEAD") != run("git", "rev-parse", f"{tag}^{{commit}}"):
        raise ValueError("Manual restoration must use the exact release tag checkout")
    current = release(tag)
    if current is None or current["draft"]:
        raise ValueError("Manual restoration requires an existing published release")
    assets = {a["name"]: a for a in current["assets"]}
    if set(assets) != expected_assets(version) | {"SHA256SUMS.txt"}:
        raise ValueError("Refusing to repair an incomplete or unexpected release")
    directory.mkdir(parents=True, exist_ok=True)
    checks = {}
    for name in sorted(expected_assets(version)):
        value = assets[name].get("digest") or ""
        if (not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                or assets[name]["state"] != "uploaded" or assets[name]["size"] <= 0):
            raise ValueError(f"Missing verified GitHub asset digest: {name}")
        checks[name] = value[7:]
    manuals = []
    for ext in ("pdf", "tex"):
        destination = directory / f"CurveMole-{version}-User-Manual.{ext}"
        destination.write_bytes(Path(f"docs/CurveMole_User_Manual.{ext}").read_bytes())
        checks[destination.name] = digest(destination)
        manuals.append(str(destination))
    checksum = directory / "SHA256SUMS.txt"
    checksum.write_text(checksum_text(checks))
    checks[checksum.name] = digest(checksum)
    if any(assets[name].get("digest") != f"sha256:{value}" for name, value in checks.items()):
        subprocess.run(["gh", "release", "upload", tag, *manuals, str(checksum), "--clobber"], check=True)
    verify(release(tag), version, checks)
    print(f"Restored original {tag} manuals and verified every asset checksum.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["draft", "preflight", "finalize", "repair-manual"])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--directory", type=Path, default=Path("release-assets"))
    args = parser.parse_args()
    if args.command == "draft":
        draft(args.tag)
    elif args.command == "preflight":
        version_for_tag(args.tag)
        current = release(args.tag)
        if current is None:
            raise ValueError("Create a release draft before building a release tag")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(f"build={str(current['draft']).lower()}\n")
    elif args.command == "finalize":
        finalize(args.tag, args.directory)
    else:
        repair_manual(args.tag, args.directory)


if __name__ == "__main__":
    main()
