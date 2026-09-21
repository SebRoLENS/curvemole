# Automated releases

CurveMole releases use semantic versioning: `MAJOR.MINOR.PATCH`.

The project policy is:

- bug fixes and maintenance corrections increment `PATCH` (`x.x.y`)
- new backward-compatible features increment `MINOR` (`x.y.x`)
- incompatible or major-line changes increment `MAJOR` (`y.x.x`)

## Normal development

A push to `main` that changes application source, packaging, dependencies, or
`.release-trigger` starts the release workflow. The default increment is `PATCH`, so
ordinary corrective commits are treated as bug-fix releases.

- ordinary/bug-fix commit: `0.1.0` → `0.1.1`
- feature commit with `[minor]`: `0.1.1` → `0.2.0`
- incompatible change with `[major]`: `0.2.0` → `1.0.0`
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

## macOS signing and notarization

The macOS build supports Developer ID code signing, hardened runtime, Apple
notarization, ticket stapling, and Gatekeeper verification for both Apple Silicon and
Intel packages. The signing helper is `packaging/macos/package_and_notarize.sh`.

Add these repository secrets under **Settings → Secrets and variables → Actions**:

- `MACOS_CERTIFICATE`: the base64-encoded `.p12` containing a **Developer ID Application** certificate and its private key
- `MACOS_CERTIFICATE_PASSWORD`: the password used when exporting that `.p12`
- `APPLE_ID`: the Apple ID used for notarization
- `APPLE_APP_SPECIFIC_PASSWORD`: an app-specific password for that Apple ID
- `APPLE_TEAM_ID`: the Apple Developer Team ID associated with the Developer ID certificate

A convenient way to encode the certificate without line breaks is:

```bash
openssl base64 -A -in DeveloperIDApplication.p12
```

Copy the complete output into `MACOS_CERTIFICATE`. Never commit the `.p12`, its
password, the app-specific password, or other signing credentials to the repository.

When all five secrets are configured, GitHub Actions:

1. imports the certificate into a temporary keychain;
2. signs `CurveMole.app` with hardened runtime and a trusted timestamp;
3. notarizes and staples the application bundle;
4. creates and signs the DMG;
5. notarizes and staples the DMG;
6. validates both artifacts with Apple's Gatekeeper tooling.

The temporary keychain and certificate are deleted at the end of the job. If one or
more secrets are absent, the workflow deliberately falls back to the previous unsigned
DMG build and emits a GitHub Actions warning instead of breaking development builds.

A Developer ID certificate suitable for public distribution requires membership in
Apple's Developer Program. Without a Developer ID identity, macOS cannot provide the
same Gatekeeper-clean first-launch experience to downloaded third-party builds.

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
