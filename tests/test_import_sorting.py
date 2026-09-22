from pathlib import Path
from types import SimpleNamespace

from curvemole.gui import import_sort_fix
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


def test_batch_import_preserves_importer_file_stem_names(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "sample10.txt"
    second = tmp_path / "sample2.txt"
    project = SimpleNamespace(curves=[])
    refreshes: list[bool] = []
    window = SimpleNamespace(project=project, refresh_all=lambda: refreshes.append(True))

    def fake_import(target, paths, *, preview_columns=None) -> None:
        for index, path in enumerate(paths):
            stem = Path(path).stem
            # Simulate MainWindow's legacy batch prefix after the core importer.
            target.project.curves.append(
                SimpleNamespace(
                    id=f"curve-{index}",
                    source=str(path),
                    name=f"{stem}: {stem}",
                )
            )

    monkeypatch.setattr(import_sort_fix, "_ORIGINAL_IMPORT_DATA", fake_import)

    import_sort_fix._import_data_natural_order(window, [str(first), str(second)])

    assert [curve.name for curve in project.curves] == ["sample2", "sample10"]
    assert refreshes == [True]
