from __future__ import annotations

from types import SimpleNamespace

from curvemole.gui import import_name_fix


def test_newly_imported_data_use_source_filename_stem(monkeypatch, tmp_path) -> None:
    source = tmp_path / "sample.001.txt"
    existing = SimpleNamespace(id="existing", name="Existing data", source=str(tmp_path / "old.txt"))
    imported = SimpleNamespace(id="imported", name="Intensity", source=str(source))
    project = SimpleNamespace(curves=[existing])
    refreshes: list[bool] = []
    window = SimpleNamespace(project=project, refresh_all=lambda: refreshes.append(True))

    def fake_import(target, paths=None) -> None:
        assert paths == [str(source)]
        target.project.curves.append(imported)

    monkeypatch.setattr(import_name_fix, "_ORIGINAL_IMPORT_DATA", fake_import)

    import_name_fix._import_data_with_file_names(window, [str(source)])

    assert imported.name == "sample.001"
    assert existing.name == "Existing data"
    assert refreshes == [True]


def test_import_without_source_keeps_existing_name(monkeypatch) -> None:
    imported = SimpleNamespace(id="imported", name="Calculated Y", source="")
    project = SimpleNamespace(curves=[])
    refreshes: list[bool] = []
    window = SimpleNamespace(project=project, refresh_all=lambda: refreshes.append(True))

    def fake_import(target, paths=None) -> None:
        target.project.curves.append(imported)

    monkeypatch.setattr(import_name_fix, "_ORIGINAL_IMPORT_DATA", fake_import)

    import_name_fix._import_data_with_file_names(window, None)

    assert imported.name == "Calculated Y"
    assert refreshes == []
