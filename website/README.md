# CurveMole website

Public website: https://sebrolens.github.io/curvemole/

The website is buildless HTML, CSS and JavaScript in `website/dist/`.
Develop changes on `testing` with `[skip release]`. Publish the reviewed website
and documentation changes on `main` when explicitly requested. Release news has a narrow
exception: `[website only] [skip release]` publishes tested news directly from
`testing` over the stable `main` website snapshot, without writing `main` or
creating a desktop release. Each successful beta publication refreshes that news too. Automatic publication through
`.github/workflows/website.yml` waits for successful CI (including the manual),
a published release matching the application version, all expected release assets,
and a matching Zenodo DOI in release notes, CITATION.cff and README.
Website-only changes do not trigger a desktop software release. GitHub Pages must use **GitHub Actions** as its publishing source
in the repository settings. For standalone publication, open **Actions → Publish CurveMole website → Run workflow**
on `main`. Manual runs are independent of the full desktop CI, but still require
complete release metadata and pass the website tests and screenshot generation
before deploying.

## Local preview

From the repository root:

```sh
python3 website/scripts/preview.py
```

Open http://127.0.0.1:8765/ . No JavaScript installation or build is required.
Keep asset URLs relative so the site works under the `/curvemole/` project path.

## Pages

- `index.html`: introduction, workspace captures, methods and worked examples.
- `download.html`: desktop packages, installation guidance, Stable/Beta and Python.
- `documentation.html`: manual and PDF, quick start, references and a link to the Quick start page.
- `quick-start.html`: illustrated Raman tutorial with downloadable practice data,
  project checkpoints, uncertainty analysis, exports and a cosmic-ray removal plugin exercise.
- `news.html`: full changelogs for the current stable minor series (for example
  1.2.0, 1.2.1 and 1.2.2), plus a separate cumulative preview of the latest
  published beta since its stable baseline. New minor or major versions move the
  earlier series to linked archives automatically. Stable and Beta advance independently.
- `news-archive.html`: archive index, linking generated pages per minor and channel.
  Stable pages retain each patch changelog; beta pages offer expandable cumulative
  notes for every published beta. Draft/withdrawn betas and Unreleased changes are
  excluded. The catalog comes from GitHub and the notes from immutable Git tags,
  with reviewed historical annotations in `changelog_tools.py` where necessary.
- `contact.html`: developer contact, issue reporting, version DOI and copyable citation.

All pages share navigation with the current page marked, including on small
screens. The snapshot assembler updates metadata across every page. The homepage
Quick start buttons and documentation card open the illustrated tutorial directly.

## Assets and scientific examples

Real GUI screenshots are generated in the publishing job from the same checkout
as the website, after readiness checks and before the Pages artifact is uploaded. Animations support pause
and reduced-motion preferences.

The downloadable scientific examples use synthetic data fitted with CurveMole
0.46.0 (commit `2e71f82b8e679003908f231b674bf020a9b3acb9`). Static figures were
rendered using Matplotlib with website-specific styling; the hero animation
renders saved fit results in browser SVG. Neither is an application screenshot
or experimental validation.

With that CurveMole version and Matplotlib installed, reproduce the examples:

```sh
python website/dist/examples/generate_scientific_examples.py --output website/dist/examples
```

The website and bundled CurveMole assets are covered by the repository's
GPL-3.0-or-later license.

## Application screenshots

The first application example shows the renamed experimental fluorescence project:
five pseudo-Voigt bands multiplied by filter transmittance, with residuals and saved
parameter results visible. It introduces multi-component fitting before display options.
The numerical-methods overview and downloadable synthetic examples follow it.

Overlay / Waterfall / Fit tabs use the original Raman example from
scripts/generate_screenshots.py, captured in the actual GUI. Every workspace tab
uses dark mode. The matching light/dark comparison is a later display-options
section, after the fitting examples, controlled by an accessible comparison slider.
website/scripts/render_demo_screenshots.py regenerates these four Raman assets
when the app or original example changes. The website retains one experimental
screenshot, without an experimental notebook, uncertainty or trend gallery.

The deployment bundles CITATION.cff, updates the HTML citation and pins download
links to the verified release tag. The Manual PDF download uses the versioned PDF
asset from that same release and is updated automatically for each publication.
It never fetches citation metadata from a newer
main revision. publication.json records the source SHA, tag SHA, DOI and CI run.

Every non-release push to main validates the development manual, so a later
website-only commit cannot bypass an earlier manual failure.

Successful CI and Automatic release runs request publication. DOI synchronisation
explicitly dispatches publication in integrated mode after its metadata write job
has succeeded (or was skipped because metadata was already complete). This also
retries publication on hourly DOI runs without relying on a second workflow-run event.
If the DOI is still pending, deployment is skipped and the previous site remains
online; a workflow warning reports the skip and the hourly DOI synchronisation retries. Manual publication and the legacy
screenshot entry point use standalone mode: they do not wait for the full CI.
They still check the published release, tag, packages/manual and DOI, and execute
the website tests and render fresh screenshots. Automatic publication keeps the
full-CI requirement. A source superseded during
rendering is rejected. Screenshot generation no longer writes a competing commit
or starts a deploy independently.
The decorative signal background can be paused; the curve-reveal hero animation
remains removed.

## Illustrated Raman quick start

`quick-start.html` follows one reproducible analysis of synthetic Raman data:
an isolated band, two partly overlapping bands and a nonlinear background. It
shows import, masking an injected cosmic-ray spike, a polynomial background
initialised from selected points and then subtracted, three Gaussian components,
the first Quick Fit, uncertainty and band correlations, numeric and parameter
exports, and loading the specific cosmic-ray removal plugin.

Generate the screenshots and practice files with the stable app dependencies
installed from its lockfile:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python website/scripts/render_quick_start_screenshots.py
```

Every screenshot is captured in dark mode from a real CurveMole Qt widget. The generator
isolates settings and caches, disables update checks, and replays the GUI commands;
it does not draw substitute interfaces or retouch the captured results.
Generated tutorial screenshots and downloads are excluded from Git; publication
creates them together from the verified stable app before assembling the Pages artifact.

For an unpublished preview whose tutorial code lives on `testing`, select a
read-only checkout of the current stable release explicitly:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python website/scripts/render_quick_start_screenshots.py \
  --app-source /path/to/stable-checkout --output /path/to/preview/website/dist
```

`--app-source` selects the actual app source used for capture without changing
that checkout. The output directory receives `assets/quick-start/` and
`quick-start-data/`. The latter contains the input spectrum, simulation truth and
reference metadata, `.fitproj` checkpoints, the completed analysis, exported curve
and parameter tables, the plugin bundle, a standalone replotting script and a
`practice-pack.zip` for offline use. The synthetic truth documents the exercise;
it is not experimental validation of the software.

`assets/quick-start/manifest.json` records the stable CurveMole version and source
SHA, input-data hash, screenshot list, fitting and correlation results, plugin
details and numerical/GUI dependency versions. The page reads the generated capture
manifest so its displayed results describe the same run as the downloads and images.

Both full website publication and news-only publication regenerate this tutorial
before uploading the Pages artifact. `.github/scripts/quick_start_publication.py`
checks the app version and verified stable source SHA, removes stale generated
assets, runs the stable renderer and checks the new manifest, PNGs and downloads.
The news path uses a detached checkout and dependencies from the verified stable
source, never the beta app used to prepare release news. Stable websites predating
the illustrated guide can skip this step; once the guide marker is present, a
missing stable renderer or incomplete capture fails publication rather than
silently reusing old screenshots. A superseded source also prevents deployment.

## Search engine verification

Google Search Console ownership is verified using `website/dist/google06874d56da4b828b.html`. Keep this file in the published `website/dist/` directory so verification remains valid.

The home page identifies CurveMole in its title and main heading, with the software
downloads as its primary action. Keep its canonical URL set to
`https://sebrolens.github.io/curvemole/`, and use that same official website URL
in the repository’s About section, README and archival records. Download links
point to GitHub releases; Zenodo links identify archived versions for citation. The citation card also
links the version-independent SciCrunch resource identifier, RRID:SCR_029214,
and the all-version Concept DOI (10.5281/zenodo.22113854) beside the release DOI.

## Customization examples

The customization section uses real GUI captures of composite-model controls,
the Function Builder with a damped-cosine formula, and the Plugin Manager with
the bundled TSV exporter discovered but not loaded. Regenerate them with:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python website/scripts/render_customization_screenshots.py
```

The capture script uses temporary settings, reads the experimental project without
resaving it, and never loads plugin code. Source paths are displayed relative to
the repository. Publication regenerates these screenshots from the deployed checkout.

## Citation presentation

The `contact.html#citation` section gives priority to the exact version used in research. The
methods sentence identifies the version and RRID; the general project reference
uses the Concept DOI (10.5281/zenodo.22113854), which can resolve to a beta.
Each purpose has a separate copy action. Version and project BibTeX are separate
downloads, and the footer and navigation lead to the human-readable section.

Run `python .github/scripts/citation_metadata.py` after editing `CITATION.cff`.
This regenerates the README/manual citation sections, citation guide, website
section and BibTeX files. Pages assembly repeats generation from the verified
stable metadata. It never reads a newer remote CFF at runtime.
Documentation-only corrections are published for the existing stable release;
they do not wait for a new software release. The PDF link follows the revised
stable manual in the exact published source snapshot.

## Sitemap

Submit https://sebrolens.github.io/curvemole/sitemap.xml to Google Search Console.
It includes all canonical public pages, including generated release archives.
Publication also generates an equivalent UTF-8 `sitemap.txt`, one absolute URL
per line, a format officially supported by Google. A separate submission of that
file can help diagnose XML-URL fetch failures without removing the existing
submission or its history. An accepted submission is not evidence of successful
processing: verify the report's status and discovered-page count separately.

## Release-news publication

The reusable website workflow is called only after testing validation succeeds and
a beta publishes, or for an explicit `[website only]` push. It overlays only
`news.html`, the archive index template and `style.css` on a fresh `origin/main`
snapshot. The stable release must still have complete published packages/manual
and matching DOI metadata. Citations, downloads, manual links and existing screenshots
remain pinned to stable source; the illustrated quick-start assets and practice
files are regenerated from that verified stable app before uploading.
`publication.json` records both the stable
`source_sha` and tested `news_source_sha`. No software release is created.

Both publication paths share the Pages lock. A changed stable source or any newer
unvalidated testing work blocks deployment; later bot-only changelog ledger writes
are allowed. Full stable publication retains its CI and screenshot gates.

The sitemap is regenerated from the canonical URLs of the complete artifact,
including every archive page; invalid project paths fail publication. Submit
`https://sebrolens.github.io/curvemole/sitemap.xml` to the URL-prefix property
`https://sebrolens.github.io/curvemole/` in Search Console. The project-level
`robots.txt` also advertises this URL. Google reads robots rules at the host
root, so a project-level robots file alone is not a substitute for submission.
