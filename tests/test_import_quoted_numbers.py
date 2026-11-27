from curvemole.core.importers import ColumnMapping, detect_config, import_file


def test_fully_quoted_numeric_csv_keeps_its_first_row(tmp_path):
    path = tmp_path / "quoted.csv"
    path.write_text('"1.0","10.0"\n"2.0","20.0"\n"3.0","30.0"\n"4.0","40.0"\n')
    config = detect_config(path)
    assert config.header is False
    (curve,) = import_file(path, ColumnMapping(x=0, y=[1]), config)
    assert curve.original_x.tolist() == [1.0, 2.0, 3.0, 4.0]


def test_quoted_header_is_still_detected(tmp_path):
    path = tmp_path / "header.csv"
    path.write_text('"x","y"\n"1.0","10.0"\n"2.0","20.0"\n"3.0","30.0"\n')
    assert detect_config(path).header is True
