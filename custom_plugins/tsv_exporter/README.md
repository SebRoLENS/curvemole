# TSV spectrum exporter

**[Download the latest validated plugin ZIP](https://github.com/SebRoLENS/curvemole/releases/download/community-plugins-latest/tsv_exporter.zip)**


Adds **File > TSV spectrum (community)** with CurveMole's ◆ plugin marker.
Exports the active spectrum's current x/y values, including masked rows, as two
tab-separated columns with a header. Existing exporters are unchanged.
Requires only CurveMole's bundled NumPy; no network access or extra packages.

Install: extract this directory, open **File > Plugin manager**, select it,
review the manifest and trust/load the plugin. Choose an output file when exporting.

Test: `python -m pytest custom_plugins/tsv_exporter/test_plugin.py`.
The test checks the actual exported header and numerical values.
