from curvemole.core.importers import ColumnMapping, detect_config, import_file


def _import(path):
    config = detect_config(path)
    return config, import_file(path, ColumnMapping(x=0, y=[1]), config)[0]


def test_last_comment_line_with_column_names_becomes_the_header(tmp_path):
    path = tmp_path / "raman.txt"
    path.write_text("# Instrument: demo\n# Raman shift (cm-1)\tIntensity (counts)\n100\t5\n101\t6\n102\t7\n")
    config, curve = _import(path)
    assert config.header and config.delimiter == "\t"
    assert (curve.x_label, curve.y_label) == ("Raman shift (cm-1)", "Intensity (counts)")
    assert curve.original_x.tolist() == [100.0, 101.0, 102.0]


def test_descriptive_comments_are_not_mistaken_for_a_header(tmp_path):
    path = tmp_path / "plain.txt"
    path.write_text("# measured at 300 K with a long description\n1 2\n3 4\n5 6\n")
    config, curve = _import(path)
    assert not config.header
    assert curve.original_x.tolist() == [1.0, 3.0, 5.0]


def test_csv_comment_header(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("% wavelength (nm),absorbance\n400,0.1\n401,0.2\n402,0.3\n")
    config, curve = _import(path)
    assert config.header
    assert curve.x_label == "wavelength (nm)"
    assert len(curve) == 3
