from pathlib import Path

from curvemole.gui.import_sort_fix import sort_import_paths


def test_import_paths_use_natural_numeric_filename_order() -> None:
    paths = [
        "/data/8AMAZO.9_ABS.txt",
        "/data/8AMAZO.8_ABS.txt",
        "/data/8AMAZO.7_ABS.txt",
        "/data/8AMAZO.70_ABS.txt",
        "/data/8AMAZO.6_ABS.txt",
        "/data/8AMAZO.69_ABS.txt",
        "/data/8AMAZO.68_ABS.txt",
        "/data/8AMAZO.61_ABS.txt",
        "/data/8AMAZO.60_ABS.txt",
    ]

    ordered = [Path(path).name for path in sort_import_paths(paths)]

    assert ordered == [
        "8AMAZO.6_ABS.txt",
        "8AMAZO.7_ABS.txt",
        "8AMAZO.8_ABS.txt",
        "8AMAZO.9_ABS.txt",
        "8AMAZO.60_ABS.txt",
        "8AMAZO.61_ABS.txt",
        "8AMAZO.68_ABS.txt",
        "8AMAZO.69_ABS.txt",
        "8AMAZO.70_ABS.txt",
    ]


def test_import_sort_uses_filename_not_parent_directory() -> None:
    paths = [
        "/z/spectrum10.txt",
        "/a/spectrum2.txt",
        "/m/spectrum1.txt",
    ]

    assert [Path(path).name for path in sort_import_paths(paths)] == [
        "spectrum1.txt",
        "spectrum2.txt",
        "spectrum10.txt",
    ]


def _import(tmp_path, files, separated=False):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from curvemole import Project
    from curvemole.gui.app import CurveMoleMainWindow
    from curvemole.gui.dialogs import ImportMappingDialog

    app = QApplication.instance() or QApplication([])
    paths = []
    for name, text in files.items():
        path = tmp_path / name
        path.write_text(text)
        paths.append(str(path))
    window = CurveMoleMainWindow(Project())
    window._show_error = lambda title, exc: (_ for _ in ()).throw(exc)

    def accept(dialog):
        if separated:
            dialog.separated_files.setChecked(True)
            dialog.y_columns.item(2).setCheckState(Qt.CheckState.Checked)
        dialog._accept()
        return dialog.result()

    original = ImportMappingDialog.exec
    ImportMappingDialog.exec = accept
    try:
        window.import_data(paths)
    finally:
        ImportMappingDialog.exec = original
    names = [curve.name for curve in window.project.curves]
    window.project.dirty = False
    window.close()
    app.processEvents()
    return names


def test_batch_import_names_spectra_after_their_files(tmp_path: Path) -> None:
    data = "x,y\n0,1\n1,2\n2,3\n"
    assert _import(tmp_path, {"sample10.csv": data, "sample2.csv": data}) == ["sample2", "sample10"]


def test_separated_column_import_keeps_column_names(tmp_path: Path) -> None:
    files = {"measurement.csv": "x,Sample A,Sample B\n0,10,20\n1,11,21\n2,12,22\n"}
    assert _import(tmp_path, files, separated=True) == ["Sample A", "Sample B"]
