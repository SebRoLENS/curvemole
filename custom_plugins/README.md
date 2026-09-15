# Community plugins for CurveMole

Users can contribute plugins here through a pull request. Each plugin lives in
its own directory. Submissions remain proposals until reviewed and merged;
this source directory is **not itself a validation badge**.

## Find and install validated plugins

Open [Community plugins checks](https://github.com/SebRoLENS/curvemole/actions/workflows/community-plugins.yml),
select a successful **main** run and download **validated-community-plugins** from
Artifacts (GitHub login required). This bundle and its `catalog.json` are produced
only after manifest, load/unload and functional tests pass on Linux, Windows and
macOS. Failed runs cannot publish a bundle. Artifacts expire after 90 days; a
maintainer can run the workflow again to rebuild the catalog against current main.
Check the run date and commit: an older successful bundle does not certify newer code.

Extract the bundle, then open **File > Plugin manager**, select the chosen plugin's
folder, review and load it. Its additions carry the ◆ marker; built-in actions are
not replaced. Plugins remain installed across restarts and can be disabled/removed
in the manager. No plugin is downloaded, installed or trusted automatically.

## Submit a plugin

1. Fork CurveMole. Copy `custom_plugins/tsv_exporter` into a new directory with a
   simple unique name. Do not upload directly to main.
2. Rename the module and manifest, assign your own identifier, and implement
   `register(api)` using the [plugin author guide](../docs/plugins.md).
3. Include exactly one `*.curvemole-plugin.json`, the Python module, `README.md`,
   `LICENSE`, and a test file. See the field table below.
4. Write functional tests that execute each added feature and verify its result:
   exporter output, importer columns, known solver result, etc. Merely checking
   that the module imports is insufficient. Keep tests deterministic, offline,
   without interactive dialogs or dependencies beyond CurveMole's bundled stack.
5. Run `python scripts/validate_community_plugins.py` from the repository root,
   then open a PR describing the feature and the tests. GitHub repeats the checks
   on all three platforms. A maintainer reviews code and test quality before merge.

| Manifest field | Requirement |
| --- | --- |
| `identifier` | Unique stable identifier, e.g. `org.yourlab.tsv-exporter` |
| `name`, `description`, `author` | Nonempty human-readable strings |
| `version` | `major.minor.patch`; increment when changing the plugin |
| `api_compatibility` | String `"1"` |
| `licence` | Licence identifier; include its text in `LICENSE` |
| `capabilities` | Nonempty list of actual registered contribution kinds, without duplicates |
| `module` | Local filename such as `exporter.py`; no paths outside the folder |
| `test_file` | Local pytest filename such as `test_plugin.py` |

Allowed capabilities: `functions`, `importers`, `exporters`, `transformations`,
`analysis`, `actions`, `workflows`, `panels`, `plot_layers`, `hooks`, `fit_solvers`.
Unknown fields are allowed for author metadata. Registration must match the declared
capabilities. Empty test suites, failing tests, timeouts, invalid manifests,
syntax errors, duplicate identifiers, symlinks and changed files during validation
fail the checks. Each plugin has 60 seconds for load/unload and 120 seconds for tests.
The generated catalog records a SHA-256 fingerprint of every submitted plugin folder.

## Repository settings for maintainers

In GitHub **Settings > Rules > Rulesets**, protect `main`, require a pull request,
review approval, an up-to-date branch, and these required status checks:

- `Validate plugins / ubuntu-22.04`
- `Validate plugins / windows-2022`
- `Validate plugins / macos-14`

Also retain the normal CI checks. Require owner review for the workflow, validator,
and community submissions. Workflow files alone cannot make checks mandatory or
prevent an administrator from merging directly. The catalog job remains gated by
all three platform jobs, independently of branch protection.

Tests establish tested compatibility, not absence of every bug or malicious code.
Python plugins execute with the user's permissions. CI uses disposable hosted workers,
read-only repository permissions, no persisted checkout credentials, no secrets and
no cache shared with privileged jobs. Do not switch to `pull_request_target` to execute
submission code. Review all code and tests before accepting a plugin.
