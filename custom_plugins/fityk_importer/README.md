# Fityk project importer

Adds **File → Plugins: Importers → Fityk project (.fit)**. Choose a Fityk
project saved with **Save state** / `info state > project.fit`. The import adds
one CurveMole series containing the saved spectra. It does not run the Fityk
script or modify the original file. Import is one CurveMole undo step.

The importer reads embedded X/Y points, positive point standard deviations,
the Fityk active-point flag (as a CurveMole mask), titles and supported models:
Gaussian, Lorentzian, PseudoVoigt, Constant and Linear. It preserves the
supported numeric values and simple bounds. The three peak profiles are
converted from Fityk height/HWHM to CurveMole area/width parameters, including
the area-based PseudoVoigt mixing fraction.

An older script referencing a separate plain text X/Y file also works if that
file is available relative to the script; basic column selectors are supported.
For reliable import, save a **state** in Fityk so the points are embedded.

Fityk `Voigt`, custom functions, expression links, zero-shift functions, data
transformations and script-defined active ranges are not converted. Their
omission is reported in the import result (up to 12 messages) and stored under
`ui_state.plugin_data[...].last_import.warnings`. The original Fityk file remains
the authoritative record for these parts. CurveMole does not inherit Fityk fit
statistics; fit again after checking the imported model.

Installation: In CurveMole open **File → Plugin Manager → Choose folder**,
choose this folder (or its parent) and **Scan**, then review and trust the plugin.
The code uses only CurveMole's installed dependencies.
