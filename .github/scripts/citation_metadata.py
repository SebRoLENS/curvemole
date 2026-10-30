"""Generate human-readable citations from the repository's CITATION.cff.

The reader handles the scalar fields and flat author/identifier lists used by
CurveMole's CFF, without requiring dependencies in release/discovery jobs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).resolve().parents[2]
replace_section = run_path(str(Path(__file__).with_name("readme_sections.py")))["replace_section"]
GENERATED = (
    "README.md", "docs/manual.md", "docs/citing.md", "docs/citation.bib",
    "docs/concept-citation.bib", "website/dist/contact.html",
    "website/dist/citation.bib", "website/dist/concept-citation.bib",
)


def scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value.split(" #", 1)[0].strip()


def field(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:[ \t]*(.+)$", text, re.M)
    return scalar(match[1]) if match else ""


def records(text: str, name: str) -> list[dict[str, str]]:
    section = re.search(rf"^{re.escape(name)}:\n((?:[ \t].*\n|\n)*)", text, re.M)
    result: list[dict[str, str]] = []
    for line in section[1].splitlines() if section else []:
        match = re.fullmatch(r"  (- |  )([\w-]+):[ \t]*(.*)", line)
        if match:
            if match[1] == "- ":
                result.append({})
            if result:
                result[-1][match[2]] = scalar(match[3])
    return result


def metadata(text: str, version: str = "") -> dict:
    source_version = field(text, "version")
    version = version or source_version
    authors = records(text, "authors")
    identifiers = records(text, "identifiers")
    concept = next((item["value"] for item in identifiers
                    if item.get("type") == "doi" and "concept" in item.get("description", "").lower()), "")
    rrid = next((item["value"] for item in identifiers
                 if item.get("value", "").startswith("RRID:")), "")
    if not authors or not concept or not rrid or not field(text, "title"):
        raise ValueError("CITATION.cff needs authors, title, Concept DOI and RRID identifiers")
    year = (field(text, "date-released") if version == source_version else dt.date.today().isoformat())[:4]
    doi = field(text, "doi") if version == source_version else ""
    repository = field(text, "repository-code")
    author = "; ".join(
        item["family-names"] + ", " + " ".join(part[0] + "." for part in item["given-names"].split())
        for item in authors
    )
    title = field(text, "title")
    url = f"https://doi.org/{doi}" if doi else f"{repository}/releases/tag/v{version}"
    publisher = "Zenodo" if doi else "GitHub"
    return {
        "version": version, "year": year, "authors": authors, "title": title,
        "doi": doi, "url": url, "repository": repository,
        "concept_doi": concept, "concept_url": f"https://doi.org/{concept}",
        "rrid": rrid, "rrid_url": f"https://scicrunch.org/resolver/{rrid}",
        "citation": f"{author} ({year}). {title} (Version {version}) [Computer software]. {publisher}.",
        "project_citation": f"{author} ({year}). {title} [Computer software]. Zenodo.",
        "methods": f"Data were analysed with CurveMole version {version} ({rrid}).",
    }


def version_reference(data: dict) -> str:
    return f'> {data["citation"]}\n> {data["url"]}\n'


def pending(data: dict) -> str:
    return ("Zenodo archival is pending; use this version's GitHub release until its DOI is available.\n\n"
            if not data["doi"] else "")


def readme_section(data: dict) -> str:
    return f'''## How to cite

**Research using CurveMole:** cite the exact version used. The reference below is
for **{data["version"]}**; for another version, use its own release DOI.

{pending(data)}{version_reference(data)}
**In the methods:** {data["methods"]}

**The project in general:** use the [Concept DOI]({data["concept_url"]})
({data["concept_doi"]}). It represents all versions and can resolve to a beta.

[Citation guide](docs/citing.md) · [Version BibTeX](docs/citation.bib) ·
[RRID record]({data["rrid_url"]}) · [Citation metadata](CITATION.cff).
GitHub's **Cite this repository** also uses `CITATION.cff`.
'''


def manual_section(data: dict) -> str:
    return f'''### 20.3 Citation

#### 20.3.1 Research using CurveMole

Cite the exact software version used in your bibliography. This manual describes
**CurveMole {data["version"]}**, whose reference is:

{pending(data)}{version_reference(data)}
If you used another release, including a beta, use that release's own version DOI
from its GitHub release notes or Zenodo record. Never substitute the current
stable DOI for a different version.

#### 20.3.2 Identification in the methods

Use the software name, exact version and version-independent SciCrunch RRID:

> {data["methods"]}

[{data["rrid"]}]({data["rrid_url"]}) identifies the software; the version DOI
identifies the archived release. The methods sentence accompanies the bibliographic reference.

#### 20.3.3 Referring to the project in general

Use the **Concept DOI** when discussing CurveMole as a project across versions:

> {data["project_citation"]}
> {data["concept_url"]}

The Concept DOI ({data["concept_doi"]}) represents all versions. It resolves to
the latest Zenodo archive, which may be a beta, and does not identify the version
used for an analysis or the latest stable download.

The [citation guide](citing.md) explains historical versions and plugin references.
[Version BibTeX](citation.bib), [project BibTeX](concept-citation.bib) and
GitHub's **Cite this repository** are generated from `CITATION.cff`.
'''


def guide(data: dict) -> str:
    return f'''# How to cite CurveMole

## Research using CurveMole

Cite the **exact version used** in your bibliography. The current stable reference
is for **{data["version"]}**:

{pending(data)}{version_reference(data)}
[Download version BibTeX](citation.bib). For another version, open its
[GitHub release]({data["repository"]}/releases) and use the verified **Zenodo DOI**
in its release notes. Check both the version and repository tag on the Zenodo record.
While archival is pending, cite that exact GitHub release URL instead.

## Identification in the methods

Name the software, state the version you actually used, and include its SciCrunch RRID:

> {data["methods"]}

[{data["rrid"]}]({data["rrid_url"]}) identifies CurveMole independently of version.
Use this methods sentence alongside the version-specific bibliographic reference.
Describe your model, constraints, weighting and uncertainty method separately.

## Referring to the project in general

For an overview of CurveMole as a project, use the **Concept DOI**:

> {data["project_citation"]}
> {data["concept_url"]}

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
'''


def bibtex(data: dict, *, project: bool = False) -> str:
    def escape(value: str) -> str:
        return value.replace("\\", r"\textbackslash{}").replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")

    authors = " and ".join(f'{a["family-names"]}, {a["given-names"]}' for a in data["authors"])
    fields = {"author": authors, "title": data["title"], "year": data["year"],
              "publisher": "Zenodo" if project or data["doi"] else "GitHub"}
    if not project:
        fields["version"] = data["version"]
    doi = data["concept_doi"] if project else data["doi"]
    if doi:
        fields["doi"] = doi
    fields["url"] = data["concept_url"] if project else data["url"]
    key = "curvemole_project" if project else "curvemole_" + data["version"].replace(".", "_")
    return f"@software{{{key},\n" + "".join(f"  {k} = {{{escape(v)}}},\n" for k, v in fields.items()) + "}\n"


def website_section(data: dict) -> str:
    e = html.escape
    label = "Version DOI: " + data["doi"] if data["doi"] else "Version record (GitHub)"
    return f'''<!-- BEGIN CITATION -->
<section class="citation-section" id="citation" aria-labelledby="citation-title">
<div class="section-top"><div><span class="eyebrow">CITE CURVEMOLE</span><h2 id="citation-title">Citing the version used</h2></div><p>The references below identify the latest stable release.</p></div>
<p class="citation-guidance"><strong>Cite the CurveMole version actually used in your analysis.</strong> The version DOI below identifies the latest stable release. For an earlier release or a beta, use the matching DOI in its <a href="https://github.com/SebRoLENS/curvemole/releases">GitHub release notes ↗</a>; check the version number and repository tag.</p>
<div class="citation-grid">
<article class="citation-card citation-primary"><span class="eyebrow">01 / RESEARCH USING CURVEMOLE</span><h3>Cite your software version</h3><p>The reference below is for <strong>CurveMole {e(data["version"])}</strong>. If you used another version, cite that release's own DOI.</p><blockquote id="citationText">{e(data["citation"])}</blockquote><a id="citationDoi" href="{e(data["url"])}">{e(label)} ↗</a><div class="citation-actions"><button id="copyCitation" type="button" data-copy="version">Copy version citation</button><a href="citation.bib" download>Download BibTeX ↓</a></div><span id="citationStatus" class="citation-status" role="status"></span></article>
<article class="citation-card"><span class="eyebrow">02 / IDENTIFICATION IN THE METHODS</span><h3>Name the software you used</h3><blockquote id="citationMethods">{e(data["methods"])}</blockquote><p>The RRID identifies CurveMole across versions. Include the actual version and keep its DOI in your bibliography.</p><a id="citationRrid" href="{e(data["rrid_url"])}">{e(data["rrid"])} ↗</a><div class="citation-actions"><button id="copyMethods" type="button" data-copy="methods">Copy methods sentence</button></div><span id="methodsStatus" class="citation-status" role="status"></span></article>
<article class="citation-card"><span class="eyebrow">03 / THE PROJECT IN GENERAL</span><h3>Refer to CurveMole as a project</h3><p>Use this reference when discussing the project across versions.</p><blockquote id="citationConceptText">{e(data["project_citation"])}</blockquote><a id="citationConceptDoi" href="{e(data["concept_url"])}">Concept DOI: {e(data["concept_doi"])} ↗</a><p class="citation-note">The Concept DOI follows the latest Zenodo archive, which may be a beta. For research results, use the exact version DOI above.</p><div class="citation-actions"><button id="copyProjectCitation" type="button" data-copy="project">Copy project citation</button><a href="concept-citation.bib" download>Download BibTeX ↓</a></div><span id="projectCitationStatus" class="citation-status" role="status"></span></article>
</div><p class="citation-links"><a href="{e(data["repository"])}/blob/main/docs/citing.md">Full citation guide ↗</a><a href="CITATION.cff">Citation metadata ↗</a><a href="{e(data["repository"])}/releases">Find another version ↗</a></p>
</section>
<!-- END CITATION -->'''


def write_website(root: Path, data: dict) -> None:
    dist = root / "website/dist"
    index = dist / "contact.html"
    if index.exists():
        source, count = re.subn(r"<!-- BEGIN CITATION -->.*?<!-- END CITATION -->",
                                lambda _: website_section(data), index.read_text(encoding="utf-8"), flags=re.S)
        if count != 1:
            raise ValueError("Missing or ambiguous website citation section")
        index.write_text(source, encoding="utf-8")
        (dist / "citation.bib").write_text(bibtex(data), encoding="utf-8")
        (dist / "concept-citation.bib").write_text(bibtex(data, project=True), encoding="utf-8")


def write_extras(root: Path, data: dict) -> None:
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    for name, content in (("citing.md", guide(data)), ("citation.bib", bibtex(data)),
                          ("concept-citation.bib", bibtex(data, project=True))):
        (docs / name).write_text(content, encoding="utf-8")
    write_website(root, data)


def refresh(root: Path = ROOT) -> None:
    data = metadata((root / "CITATION.cff").read_text(encoding="utf-8"))
    for name, heading, next_heading, render in (
        ("README.md", "## How to cite", "## License", readme_section),
        ("docs/manual.md", "### 20.3 Citation", "### 20.4 Author and contact", manual_section),
    ):
        path = root / name
        if path.exists():
            path.write_text(replace_section(path.read_text(encoding="utf-8"), heading,
                                            next_heading, render(data)), encoding="utf-8")
    write_extras(root, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    refresh()
