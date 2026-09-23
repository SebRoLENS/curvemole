# Community plugins for CurveMole

**Created your own plugin? [Start here: submit your plugin](#submit-a-plugin).**

The destination in this repository is **`custom_plugins/your_plugin/`**.
For example, a plugin called My Exporter belongs in `custom_plugins/my_exporter/`.
To use a private plugin only on your own computer, use **File > Plugin manager >
Choose plugin folder...** instead; you do not need to submit it to GitHub.

Users can contribute plugins here through a pull request. Each plugin lives in
its own directory. Submissions remain proposals until reviewed and merged;
this source directory is **not itself a validation badge**.

## Find and install validated plugins

**[Download all plugins — ZIP](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/validated-community-plugins.zip)**

| Plugin | Direct download |
| --- | --- |
| Cosmic-ray removal | [cosmic_ray_removal.zip](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/cosmic_ray_removal.zip) |
| Fityk project importer | [fityk_importer.zip](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/fityk_importer.zip) |
| Ruby fluorescence pressure monitor | [ruby_fluo_pressure_monitor.zip](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/ruby_fluo_pressure_monitor.zip) |
| TSV exporter | [tsv_exporter.zip](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/tsv_exporter.zip) |

These stable links download the latest published ZIP directly, without a GitHub
account. [Package details and validation provenance](https://github.com/SebRoLENS/curvemole/releases/tag/community-plugins-latest)
include the tested commit, catalog and checksums. This rolling plugin release is
separate from the application's latest release and does not expire after 90 days.
Publication happens only from main after manifest, load/unload and functional tests
pass on Linux, Windows and macOS. Failed checks leave the previous download in place;
unmerged pull requests are never offered through these links.

Extract the bundle, then open **File > Plugin manager**, select the chosen plugin's
folder, review and load it. Its additions carry a plugin-specific symbol; hover over it to see the plugin name.
Built-in actions are
not replaced. Plugins remain installed across restarts and can be disabled/removed
in the manager. No plugin is downloaded, installed or trusted automatically.

## Submit a plugin

### Where to upload, using GitHub in the browser

1. Open [this repository](https://github.com/SebRoLENS/curvemole) and use **Fork** to
   create your own copy. An ordinary contributor does not upload directly to main.
2. In **your fork**, open `custom_plugins`, then **Add file > Upload files**.
   Upload your complete plugin folder, for example `my_exporter`, containing the
   files listed below. Do not scatter its files directly inside `custom_plugins`.
3. Commit the uploaded files in your fork. Then choose **Contribute > Open pull
   request**, targeting `SebRoLENS/curvemole`, branch `main`. Describe what the plugin
   does and how you tested it.
4. The pull request's **Checks** tab shows the automatic validation results.
   Fix any failures in your fork; pushing the correction updates the same PR.
   A maintainer reviews and merges the contribution.
5. After the merged code passes the main workflow, the plugin is included in the
   **validated-community-plugins** download. Opening a PR or uploading to a fork
   alone does not make it part of that catalog.

### What your plugin folder must contain


1. Fork CurveMole. Copy `custom_plugins/tsv_exporter` into a new directory with a
   simple unique name. Do not upload directly to main.
2. Rename the module and manifest, assign your own identifier, and implement
   `register(api)` using the [plugin author guide](https://github.com/SebRoLENS/curvemole/blob/main/docs/plugins.md).
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
`analysis`, `actions`, `workflows`, `import_processors`, `panels`, `plot_layers`, `hooks`, `fit_solvers`.
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
