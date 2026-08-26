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
`pyproject.toml`, README, manual, lock file, and `CITATION.cff`. It runs lint, tests,
builds the Python packages and creates a versioned PDF manual. It then creates an
annotated tag and GitHub Release.

A second workflow builds and smoke-tests:

- Linux x86_64 AppImage, with GitHub artifact attestation
- Windows x86_64 standalone executable
- macOS Apple Silicon DMG
- macOS Intel x86_64 DMG
- Python wheel and source distribution

All downloadable files and `SHA256SUMS.txt` are attached to the same release.

## Zenodo

Zenodo support is dormant until the repository is connected to Zenodo. After
enabling the GitHub integration, create the repository variable
`ZENODO_ENABLED=true`. Future releases then wait for the version DOI and update the
README, `CITATION.cff`, and GitHub release notes automatically.

No Zenodo token is stored in this repository. The synchronisation uses only the
public records API and requests no more than 25 records per page.
