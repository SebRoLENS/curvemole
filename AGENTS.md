# CurveMole development and release channels

- `main` is the stable publication branch. Develop and fix bugs on `testing` by
  default. Do not merge or push changes to `main`, publish a stable release, or
  promote testing unless the user explicitly asks for that promotion.
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
