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
