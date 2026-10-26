# CurveMole development and release channels

- All CurveMole development must happen exclusively on `testing`: features, bug
  fixes, documentation, workflow and configuration changes. This is a standing user
  instruction, not a default that may be changed for convenience. Check the branch
  before editing and switch to `testing` without discarding any existing work.
- `main` is only the stable publication branch. Never develop directly on `main`,
  merge or push changes to it, or publish a stable release during ordinary work.
  Promotion is authorized only by the user explicitly requesting it or manually
  launching **Automatic release** with the `testing` branch selected. Merely asking
  to create, maintain or test the promotion workflow does not authorize running it.
- New `testing` pushes run tests and build beta packages. They normally publish
  prereleases without changing the latest stable release or the website. Include
  `[beta artifacts only]` in the commit message when the user wants a downloadable
  trial without creating any release. Do not remove this marker while an
  artifacts-only task is in progress.
- Beta versions are stamped at build time by `.github/scripts/beta_release.py`.
  Keep tracked source, citation and stable manual version metadata unchanged until
  stable release preparation. Do not hand-edit a beta version into those files.
- Preserve the reversible Stable/Beta setting. Switching to Stable waits for an
  equal or newer final version and never downgrades automatically. The status badge
  must identify the installed beta independently of the selected channel.
- For release and channel work, run the relevant update, release-channel and
  workflow tests and lint the GitHub workflows. See `docs/releasing.md` for promotion
  and synchronization steps.
