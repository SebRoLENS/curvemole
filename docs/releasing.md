# Automated releases

CurveMole releases use semantic versioning: `MAJOR.MINOR.PATCH`.

The project policy is:

- bug fixes and maintenance corrections increment `PATCH` (`x.x.y`)
- new backward-compatible features increment `MINOR` (`x.y.x`)
- incompatible or major-line changes increment `MAJOR` (`y.x.x`)

## Normal development

Work on `testing`. Each push runs validation and builds Linux, Windows, macOS and
Python beta packages. Build versions are stamped only in the package workspace,
for example `1.0.2b1` / `v1.0.2-beta.1` from the `1.0.1` stable baseline. The beta
sequence is the Testing builds workflow run number. Source version metadata stays
stable so promoting the code does not propagate a beta version into stable releases.

The bootstrap commit contains `[beta artifacts only]`: it builds downloadable Actions
artifacts but creates no tag or GitHub Release. The same marker can be used on future
pushes for an unpublished trial. Later pushes without that marker publish verified
prereleases with `--latest=false`. They do not change the stable release, website,
DOI, manual version, or `main`. Manual Testing builds default to artifacts only;
publishing must be explicitly selected. Windows/macOS signing follows the stable
pipeline. Beta packages bundle the stable baseline manual; the updated Markdown
manual and in-app channel dialog describe the beta channel changes.

To promote testing, review a pull request from `testing` into `main`, let the tests
pass, and merge only when the maintainer approves the tested code. Use a merge title
without `[skip release]`; `[minor]`, `[major]`, or `[release X.Y.Z]` select the stable
release increment. After the release preparation commit, merge `main` back into
`testing` so the next beta starts above the new stable version. Never reset testing
or force-push over unpublished work. No automatic testing-to-main promotion occurs.

The app's **Help > Update channel…** setting is reversible. Switching to Stable
waits for a stable version at least as new as the installed beta. Updates never
downgrade. A matching final version sorts after its beta, beta sequences compare
numerically, and all prereleases are excluded from the Stable feed. The installed
version badge identifies beta packages independently of the channel preference.

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
- Windows x86_64 per-user installer and portable ZIP
- macOS Apple Silicon DMG
- macOS Intel x86_64 DMG
- Python wheel and source distribution
- versioned LaTeX and PDF user manuals

All downloadable files and `SHA256SUMS.txt` are attached to the same release.
The Linux AppImage and its detached signature are attached directly to the tagged
release. They are downloaded briefly to calculate the release checksums, without
creating a separate Actions AppImage artifact. A downloadable Actions AppImage test
artifact is built from a human-triggered `main` commit containing `[skip release]`,
or as part of a `testing` beta build.

The first installer-enabled release also publishes the legacy raw Windows executable
so older self-updaters can reach the transition release. Remove that raw executable
from the Windows artifact upload after the transition release succeeds; current
portable builds update from the ZIP and installed builds update through the installer.

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

The repository is connected to Zenodo. Releases start DOI synchronization after
creating the GitHub release, without blocking desktop builds on archival. When the
version DOI is available, the README, `CITATION.cff`, and GitHub release notes are
updated automatically. Commits
containing `[skip release]` can update release infrastructure or citation metadata
without creating a new software version.

No Zenodo token is stored in this repository. The synchronisation uses only the
public records API and requests no more than 25 records per page.

### Official website and downloads in archived records

`CITATION.cff` is the single source for software metadata used by the GitHub–Zenodo
integration. Its `abstract` starts with the official website and latest-download
URLs, followed by a software description and the purpose of the archived release.
Its `url` always points to the official website; the separate `version` and `doi`
fields continue to identify the exact release. Release preparation and DOI
synchronisation preserve these links. GitHub release notes also begin with links
to the website and latest downloads, followed by installation instructions and
downloads pinned to that release.

Do not add `.zenodo.json` merely to repeat this description: Zenodo would ignore
the entire `CITATION.cff` when both files are present. See
[Zenodo's supported CFF fields](https://help.zenodo.org/docs/github/describe-software/citation-file/).
The revised metadata is picked up when a future GitHub release is archived; it
does not update records that have already been published.

For an existing record, sign into its owning Zenodo account, choose **Edit** from
the record or **My dashboard → My uploads**, and prepend these links to the
description, keeping the release's existing description below them:

```html
<p><strong>Official website:</strong>
<a href="https://sebrolens.github.io/curvemole/">CurveMole</a><br>
<strong>Download the latest version:</strong>
<a href="https://github.com/SebRoLENS/curvemole/releases/latest">Windows, macOS and Linux downloads</a></p>
```

Choose **Publish** to make the metadata correction visible. This preserves the
record's DOI and files; do not create a new version for a description correction.
See [Zenodo's instructions for editing published records](https://help.zenodo.org/docs/deposit/manage-records/#edit-published-records).
For many records, the authenticated
[Zenodo deposition API](https://developers.zenodo.org/#deposition-actions) supports
an edit, metadata update and publish cycle for each owned deposition. Any bulk
update must retain every record's version, DOI, files and other metadata, change
only the description prefix, and be idempotent. It requires the owner's Zenodo
credentials; the public DOI synchronisation workflow cannot perform these edits.
