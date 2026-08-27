#!/usr/bin/env python3
"""Build the CurveMole LaTeX and PDF manuals from the Markdown source."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "manual.md"
DEFAULT_TEX = ROOT / "docs" / "CurveMole_User_Manual.tex"
DEFAULT_PDF = ROOT / "docs" / "CurveMole_User_Manual.pdf"
PREAMBLE = ROOT / "docs" / "manual-preamble.tex"
VERSION_FILE = ROOT / "src" / "curvemole" / "version.py"
LOGO = Path("src/curvemole/resources/curvemole.png")

SEMVER = r"\d+\.\d+\.\d+"
PACKAGE_VERSION_RE = re.compile(rf'^__version__\s*=\s*"({SEMVER})"', re.MULTILINE)
TITLE_RE = re.compile(rf"^# CurveMole User Manual - Preview ({SEMVER})$", re.MULTILINE)
MANUAL_VERSION_RE = re.compile(
    rf"^\*\*Current manual version: ({SEMVER})\*\*$", re.MULTILINE
)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
UNICODE_DASHES = "\u2010\u2011\u2012\u2013\u2014"
PDF_ID_RE = re.compile(rb"/ID\[<[0-9A-Fa-f]{32}><[0-9A-Fa-f]{32}>\]")


def read_package_version() -> str:
    match = PACKAGE_VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"Could not read a semantic version from {VERSION_FILE}")
    return match.group(1)


def validate_source(source: Path, expected_version: str) -> str:
    text = source.read_text(encoding="utf-8")
    title = TITLE_RE.search(text)
    marker = MANUAL_VERSION_RE.search(text)
    if not title or not marker:
        raise SystemExit(
            "The manual must contain its version in both the title and the "
            "'Current manual version' line."
        )
    if title.group(1) != marker.group(1):
        raise SystemExit("The two manual version declarations do not agree.")
    if title.group(1) != expected_version:
        raise SystemExit(
            f"Manual version {title.group(1)} does not match CurveMole {expected_version}."
        )
    found_dash = next((character for character in UNICODE_DASHES if character in text), None)
    if found_dash:
        raise SystemExit(
            f"The manual contains Unicode dash U+{ord(found_dash):04X}; use an ASCII hyphen."
        )
    validate_local_links(text, source.parent)
    return text


def validate_local_links(text: str, base: Path) -> None:
    missing: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        relative = target.split("#", 1)[0]
        if relative and not (base / relative).resolve().exists():
            missing.append(target)
    if missing:
        raise SystemExit("Broken local link(s) in the manual: " + ", ".join(sorted(set(missing))))


def prepare_pandoc_source(text: str) -> str:
    """Remove the GitHub title block and promote body headings for PDF chapters."""

    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or not TITLE_RE.fullmatch(lines[0]):
        raise SystemExit("The manual title must be the first non-empty line.")
    lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or not MANUAL_VERSION_RE.fullmatch(lines[0]):
        raise SystemExit("The manual version marker must immediately follow the title.")
    lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)

    promoted: list[str] = []
    in_fence = False
    for line in lines:
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            promoted.append(line)
            continue
        if not in_fence and re.match(r"^#{2,6}\s", line):
            line = line[1:]
        promoted.append(line)
    return "\n".join(promoted).rstrip() + "\n"


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    process = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if process.returncode:
        raise SystemExit(
            f"Command failed ({process.returncode}): {' '.join(command)}\n{process.stdout}"
        )


def normalise_pdf_document_id(pdf: Path, tex: Path) -> None:
    """Replace xdvipdfmx's random document ID with one derived from the source."""

    data = pdf.read_bytes()
    document_id = hashlib.sha256(tex.read_bytes()).hexdigest()[:32].encode("ascii")
    replacement = b"/ID[<" + document_id + b"><" + document_id + b">]"
    data, count = PDF_ID_RE.subn(replacement, data, count=1)
    if count != 1:
        raise SystemExit("Could not normalise the generated PDF document ID.")
    pdf.write_bytes(data)


def build(source: Path, tex_output: Path, pdf_output: Path) -> None:
    version = read_package_version()
    text = validate_source(source, version)
    for executable in ("pandoc", "latexmk", "xelatex"):
        if shutil.which(executable) is None:
            raise SystemExit(f"Required executable not found: {executable}")
    if not PREAMBLE.is_file() or not (ROOT / LOGO).is_file():
        raise SystemExit("The manual preamble or CurveMole logo is missing.")

    tex_output.parent.mkdir(parents=True, exist_ok=True)
    pdf_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="curvemole-manual-") as temporary:
        temporary_root = Path(temporary)
        prepared_source = temporary_root / "manual-body.md"
        prepared_source.write_text(prepare_pandoc_source(text), encoding="utf-8")
        prepared_header = temporary_root / "manual-preamble.tex"
        header = PREAMBLE.read_text(encoding="utf-8")
        header = header.replace("@@CURVEMOLE_VERSION@@", version)
        header = header.replace("@@CURVEMOLE_LOGO@@", LOGO.as_posix())
        prepared_header.write_text(header, encoding="utf-8")

        run(
            [
                "pandoc",
                str(prepared_source),
                "--from=markdown+pipe_tables+fenced_code_blocks+tex_math_dollars+smart",
                "--to=latex",
                "--standalone",
                "--toc",
                "--toc-depth=3",
                "--top-level-division=chapter",
                "--fail-if-warnings",
                "--resource-path=" + os.pathsep.join((str(ROOT), str(source.parent))),
                "--include-in-header=" + str(prepared_header),
                "--metadata=title:CurveMole User Manual",
                f"--metadata=subtitle:Preview {version}",
                "--metadata=author:Sebastiano Romi",
                f"--metadata=date:Updated for CurveMole {version}",
                "--metadata=toc-title:Contents",
                "--variable=documentclass:scrreprt",
                "--variable=classoption:oneside",
                "--variable=fontsize:10pt",
                "--variable=papersize:a4",
                "--variable=geometry:top=24mm,bottom=25mm,left=25mm,right=25mm",
                "--variable=mainfont:DejaVu Serif",
                "--variable=sansfont:DejaVu Sans",
                "--variable=monofont:DejaVu Sans Mono",
                "--variable=colorlinks:true",
                "--variable=linkcolor:teal",
                "--variable=urlcolor:teal",
                "--output=" + str(tex_output),
            ],
            cwd=ROOT,
        )

        build_directory = temporary_root / "latex-build"
        build_directory.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                # Use a fixed UTC epoch supported by xdvipdfmx. This stabilises
                # PDF metadata across local and CI builds.
                "SOURCE_DATE_EPOCH": "946684800",
                "FORCE_SOURCE_DATE": "1",
                "TZ": "UTC",
            }
        )
        run(
            [
                "latexmk",
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-outdir=" + str(build_directory),
                str(tex_output),
            ],
            cwd=ROOT,
            env=environment,
        )
        built_pdf = build_directory / f"{tex_output.stem}.pdf"
        if not built_pdf.is_file() or built_pdf.stat().st_size == 0:
            raise SystemExit("LaTeX completed without producing a PDF manual.")
        shutil.copy2(built_pdf, pdf_output)
        normalise_pdf_document_id(pdf_output, tex_output)

    print(f"Built {tex_output.relative_to(ROOT)}")
    print(f"Built {pdf_output.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--tex-output", type=Path, default=DEFAULT_TEX)
    parser.add_argument("--pdf-output", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    build(args.source.resolve(), args.tex_output.resolve(), args.pdf_output.resolve())


if __name__ == "__main__":
    main()
