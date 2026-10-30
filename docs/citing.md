# How to cite CurveMole

## Research using CurveMole

Cite the **exact version used** in your bibliography. The current stable reference
is for **1.1.0**:

> Romi, S. (2026). CurveMole: Modular Scientific Curve Fitting (Version 1.1.0) [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.23730744

[Download version BibTeX](citation.bib). For another version, open its
[GitHub release](https://github.com/SebRoLENS/curvemole/releases) and use the verified **Zenodo DOI**
in its release notes. Check both the version and repository tag on the Zenodo record.
While archival is pending, cite that exact GitHub release URL instead.

## Identification in the methods

Name the software, state the version you actually used, and include its SciCrunch RRID:

> Data were analysed with CurveMole version 1.1.0 (RRID:SCR_029214).

[RRID:SCR_029214](https://scicrunch.org/resolver/RRID:SCR_029214) identifies CurveMole independently of version.
Use this methods sentence alongside the version-specific bibliographic reference.
Describe your model, constraints, weighting and uncertainty method separately.

## Referring to the project in general

For an overview of CurveMole as a project, use the **Concept DOI**:

> Romi, S. (2026). CurveMole: Modular Scientific Curve Fitting [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.22113854

[Download project BibTeX](concept-citation.bib). The Concept DOI represents all
versions and resolves to the latest Zenodo archive, **including beta versions**.
It is not a pointer to the latest stable download and does not identify the exact
software that produced results. You normally need one version citation for an
analysis; the general project citation is for a different purpose.

## Older versions, betas and development builds

- For an older stable release, use its own DOI, even if a newer stable exists.
- For a published beta, use that exact beta's verified DOI in its release notes.
  Beta DOIs do not replace stable README, manual or CFF metadata.
- For an unarchived development build, record the full commit SHA and repository
  URL. Do not assign it another release's DOI.
- Record the version from **Help > About** or `curvemole --version`, independently
  of the selected Stable/Beta update channel.

## Plugins and scientific references

Cite the CurveMole host version as above. Identify any plugin and its version,
and follow the plugin author's citation instructions when provided. Scientific
papers about a calibration, model or algorithm remain separate references near
the method concerned. The software DOI, Concept DOI and RRID do not replace them.

## Metadata and documentation updates

[`CITATION.cff`](../CITATION.cff) is the source for the author, title, release,
date, version DOI, Concept DOI and RRID. README, manual citation sections,
this guide, website citations and BibTeX exports are generated from it.
Documentation and website corrections can be published for the current stable
version without a new software release. Archived release files keep their history.
