# CurveMole website

Public website: https://sebrolens.github.io/curvemole/

The website is buildless HTML, CSS and JavaScript in `website/dist/`.
Edit those files and merge into `main` to publish through
`.github/workflows/website.yml`. Website-only changes do not trigger a desktop
software release. GitHub Pages must use **GitHub Actions** as its publishing source
in the repository settings. The workflow also supports manual runs on `main`.

## Local preview

From the repository root:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory website/dist
```

Open http://127.0.0.1:8000/ . No JavaScript installation or build is required.
Keep asset URLs relative so the site works under the `/curvemole/` project path.

## Assets and scientific examples

Real GUI screenshots follow the known screenshot paths on this repository's
`main` branch, with bundled images as offline fallbacks. Animations support pause
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

The main workspace and Overlay / Waterfall / Fit tabs use the original application
screenshots, refreshed from docs/screenshots on main with bundled fallbacks.
One additional dark screenshot of the renamed experimental project illustrates
the complexity of a full workspace. The website has no experimental notebook,
modelling-notes, uncertainty or trend gallery, and no theme comparison slider.

The download section reads the current release citation and DOI from the root
CITATION.cff on page load, retaining a verified HTML fallback when offline.
The decorative signal background can be paused; the curve-reveal hero animation
remains removed.
