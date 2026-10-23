# CurveMole website

Public website: https://sebrolens.github.io/curvemole/

The website is buildless HTML, CSS and JavaScript in `website/dist/`.
Edit those files and merge into `main`. Automatic publication through
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
python3 -m http.server 8000 --bind 127.0.0.1 --directory website/dist
```

Open http://127.0.0.1:8000/ . No JavaScript installation or build is required.
Keep asset URLs relative so the site works under the `/curvemole/` project path.

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
links to the verified release tag. It never fetches citation metadata from a newer
main revision. publication.json records the source SHA, tag SHA, DOI and CI run.

Every non-release push to main validates the development manual, so a later
website-only commit cannot bypass an earlier manual failure.

Successful CI, Automatic release and Sync Zenodo DOI runs request publication.
If the DOI is still pending, deployment is skipped and the previous site remains
online; the hourly DOI synchronisation retries. Manual publication and the legacy
screenshot entry point use standalone mode: they do not wait for the full CI.
They still check the published release, tag, packages/manual and DOI, and execute
the website tests and render fresh screenshots. Automatic publication keeps the
full-CI requirement. A source superseded during
rendering is rejected. Screenshot generation no longer writes a competing commit
or starts a deploy independently.
The decorative signal background can be paused; the curve-reveal hero animation
remains removed.

## Search engine verification

Google Search Console ownership is verified using `website/dist/google06874d56da4b828b.html`. Keep this file in the published `website/dist/` directory so verification remains valid.
