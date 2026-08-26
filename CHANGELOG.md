# Changelog

All notable changes follow Keep a Changelog and Semantic Versioning.

## [0.2.0] - 2026-08-26

### Added

- Click-drag placement of initial peak centre and FWHM.
- Point-by-point cubic-spline background placement with a live preview.
- Direct interval masking by right-dragging the graph.

### Fixed

- Recursive component-panel refresh that crashed when a model component was selected.
- Quick Start, update, and issue links launched from the Linux AppImage now use the
  host desktop libraries instead of the bundled Qt/C++ runtime.

## [0.1.1] - 2026-08-26

### Fixed

- Export-manifest path handling is portable between Windows, Linux, and macOS.
- Windows frozen-application smoke testing now waits for the GUI process correctly.

## [0.1.0] - 2026-08-26

### Added

- Initial scientific data, model, fitting, uncertainty, project, and export engine.
- Initial single-window Qt desktop application.
- Python API, command-line interface, YAML workflows, and extension registry.
- Cross-platform test and packaging workflows.
