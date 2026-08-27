# Automated releases

CurveMole releases use semantic versioning: `MAJOR.MINOR.PATCH`.

## Normal development

A push to `main` that changes application source, packaging, dependencies, or
`.release-trigger` starts the release workflow. The default increment is `PATCH`.

- ordinary commit: `0.1.0` → `0.1.1`
- commit message containing `[minor]`: `0.1.1` → `0.2.0`
- commit message containing `[major]`: `0.2.0` → `1.0.0`
- a version manually raised in both source and `pyproject.toml` is respected

The workflow can also be started from GitHub Actions with an explicit patch, minor,
or major choice. To publish without changing code, modify `.release-trigger`.

## Release pipeline

Before publishing, GitHub Actions synchronises the version in the Python package,
`pyproject.toml`, README, manual, lock file, and `CITATION.cff`. It runs lint and
tests, builds the Python packages, and generates LaTeX and PDF manuals from
`docs/manual.md`. It then creates an annotated tag and GitHub Release.

A second workflow builds and smoke-tests:

- Linux x86_64 AppImage, with GitHub artifact attestation
- Windows x86_64 standalone executable
- macOS Apple Silicon DMG
- macOS Intel x86_64 DMG
- Python wheel and source distribution
- versioned LaTeX and PDF user manuals

All downloadable files and `SHA256SUMS.txt` are attached to the same release.

## Documentation-only updates

`docs/manual.md` is the sole hand-edited manual source. Run:

```bash
python scripts/build_manual.py
```

to validate it and regenerate `docs/CurveMole_User_Manual.tex` and
`docs/CurveMole_User_Manual.pdf`. The documentation workflow performs the same build
for pull requests and documentation changes. A documentation-only commit should use
`[skip release]` when it must update the current manual without incrementing the
software version.

## Zenodo

The repository is connected to Zenodo. Future releases wait for the version DOI and
update the README, `CITATION.cff`, and GitHub release notes automatically. Commits
containing `[skip release]` can update release infrastructure or citation metadata
without creating a new software version.

No Zenodo token is stored in this repository. The synchronisation uses only the
public records API and requests no more than 25 records per page.
