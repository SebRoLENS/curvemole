"""Previewable import of one-dimensional text, DAT, CSV, and TSV data."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from curvemole.core.data import Curve, Series
from curvemole.core.errors import DataValidationError

SUPPORTED_EXTENSIONS = {".txt", ".dat", ".csv", ".tsv"}


@dataclass(slots=True)
class ImportConfig:
    delimiter: str | None = None
    decimal: str = "."
    comment_prefixes: tuple[str, ...] = ("#", ";", "%", "!")
    header: bool | None = None
    encoding: str = "utf-8-sig"
    skip_rows: int = 0


@dataclass(slots=True)
class ColumnMapping:
    x: str | int | None = None
    y: list[str | int] = field(default_factory=list)
    pairs: list[tuple[str | int, str | int]] = field(default_factory=list)
    sigma_x: str | int | None = None
    sigma_y: str | int | None = None
    weights: str | int | None = None
    variance: str | int | None = None
    inverse_variance: str | int | None = None

    def validate(self) -> None:
        if not self.pairs and (self.x is None or not self.y):
            raise DataValidationError("Choose an x column and at least one y column, or x-y pairs.")
        uncertainty_fields = [
            self.sigma_y is not None,
            self.weights is not None,
            self.variance is not None,
            self.inverse_variance is not None,
        ]
        if sum(uncertainty_fields) > 1:
            raise DataValidationError(
                "Choose only one of sigma_y, weights, variance, or inverse variance."
            )


@dataclass(slots=True)
class FileInspection:
    path: Path
    config: ImportConfig
    columns: list[str]
    preview: pd.DataFrame
    warnings: list[str]


def inspect_file(path: str | Path, config: ImportConfig | None = None, *, rows: int = 30) -> FileInspection:
    source = Path(path)
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DataValidationError(
            f"Unsupported file extension '{source.suffix}'. Use TXT, DAT, CSV, or TSV."
        )
    if not source.is_file():
        raise DataValidationError(f"Input file does not exist: {source}")
    selected = config or detect_config(source)
    frame, warnings = _read_frame(source, selected, nrows=rows)
    return FileInspection(source, selected, [str(value) for value in frame.columns], frame, warnings)


def detect_config(path: str | Path) -> ImportConfig:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise DataValidationError(f"Cannot read '{source}': {exc}") from exc
    candidate_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "%", "!"))
    ][:20]
    if not candidate_lines:
        raise DataValidationError(f"'{source}' contains no data rows.")
    sample = "\n".join(candidate_lines)
    delimiter: str | None
    if source.suffix.lower() == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = None
    decimal = "," if delimiter in {";", "\t", "|", None} and _looks_decimal_comma(candidate_lines) else "."
    first = _split(candidate_lines[0], delimiter)
    header = any(not _is_number(value, decimal) for value in first)
    return ImportConfig(delimiter=delimiter, decimal=decimal, header=header)


def import_file(
    path: str | Path,
    mapping: ColumnMapping,
    config: ImportConfig | None = None,
) -> list[Curve]:
    mapping.validate()
    source = Path(path)
    selected = config or detect_config(source)
    frame, warnings = _read_frame(source, selected)
    pairs = mapping.pairs or [(mapping.x, y) for y in mapping.y]
    curves: list[Curve] = []
    for pair_index, (x_column, y_column) in enumerate(pairs, start=1):
        x_name = _column_name(frame, x_column)
        y_name = _column_name(frame, y_column)
        x = _numeric(frame[x_name], selected.decimal)
        y = _numeric(frame[y_name], selected.decimal)
        sigma_x = _optional_numeric(frame, mapping.sigma_x, selected.decimal)
        sigma_y = _optional_numeric(frame, mapping.sigma_y, selected.decimal)
        weights = _optional_numeric(frame, mapping.weights, selected.decimal)
        if mapping.variance is not None:
            variance = _optional_numeric(frame, mapping.variance, selected.decimal)
            assert variance is not None
            with np.errstate(invalid="ignore"):
                sigma_y = np.sqrt(variance)
        if mapping.inverse_variance is not None:
            weights = _optional_numeric(frame, mapping.inverse_variance, selected.decimal)
        name = str(y_name).strip() or f"{source.stem} {pair_index}"
        curve = Curve(
            name=name,
            original_x=x,
            original_y=y,
            sigma_x=sigma_x,
            sigma_y=sigma_y,
            weights=weights,
            weights_are_inverse_variance=mapping.weights is None,
            x_label=str(x_name),
            y_label=str(y_name),
            source=str(source.resolve()),
            metadata={
                "import": {
                    "file_name": source.name,
                    "delimiter": selected.delimiter or "whitespace",
                    "decimal": selected.decimal,
                    "header": selected.header,
                    "x_column": str(x_name),
                    "y_column": str(y_name),
                    "warnings": warnings,
                }
            },
        )
        curves.append(curve)
    return curves


def import_many(
    paths: Iterable[str | Path],
    mapping: ColumnMapping,
    *,
    config: ImportConfig | None = None,
    series_name: str = "Imported series",
) -> Series:
    paths = list(paths)
    series = Series(series_name)
    for path in paths:
        for curve in import_file(path, mapping, config):
            if len(paths) > 1 and curve.name.lower() in {"y", "signal", "intensity"}:
                curve.name = f"{Path(path).stem}: {curve.name}"
            series.add(curve)
    return series


def _read_frame(
    path: Path, config: ImportConfig, *, nrows: int | None = None
) -> tuple[pd.DataFrame, list[str]]:
    lines = path.read_text(encoding=config.encoding, errors="replace").splitlines()
    filtered: list[str] = []
    comments = 0
    for index, line in enumerate(lines):
        if index < config.skip_rows:
            continue
        stripped = line.lstrip()
        if not stripped:
            continue
        if any(stripped.startswith(prefix) for prefix in config.comment_prefixes):
            comments += 1
            continue
        filtered.append(line)
        if nrows is not None and len(filtered) >= nrows + 1:
            break
    if not filtered:
        raise DataValidationError(f"'{path}' contains no readable table rows.")
    separator = config.delimiter if config.delimiter is not None else r"\s+"
    from io import StringIO

    try:
        frame = pd.read_csv(
            StringIO("\n".join(filtered)),
            sep=separator,
            engine="python",
            header=0 if config.header else None,
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            nrows=nrows,
        )
    except Exception as exc:
        raise DataValidationError(f"Cannot parse '{path.name}': {exc}") from exc
    if frame.shape[1] < 2:
        raise DataValidationError(
            f"'{path.name}' produced only one column. Check delimiter and decimal settings."
        )
    if not config.header:
        frame.columns = [f"Column {index + 1}" for index in range(frame.shape[1])]
    frame.columns = _unique_columns([str(value).strip() or f"Column {i + 1}" for i, value in enumerate(frame.columns)])
    warnings = [f"Ignored {comments} comment line(s)."] if comments else []
    return frame, warnings


def _column_name(frame: pd.DataFrame, column: str | int | None) -> str:
    if column is None:
        raise DataValidationError("A required column was not selected.")
    if isinstance(column, int):
        if not 0 <= column < frame.shape[1]:
            raise DataValidationError(f"Column index {column} is outside the table.")
        return str(frame.columns[column])
    if column not in frame.columns:
        raise DataValidationError(f"Column '{column}' does not exist.")
    return column


def _optional_numeric(frame: pd.DataFrame, column: str | int | None, decimal: str) -> np.ndarray | None:
    if column is None:
        return None
    return _numeric(frame[_column_name(frame, column)], decimal)


def _numeric(series: pd.Series, decimal: str) -> np.ndarray:
    values = series.astype(str).str.strip()
    if decimal == ",":
        values = values.str.replace(",", ".", regex=False)
    return pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)


def _split(line: str, delimiter: str | None) -> list[str]:
    return re.split(r"\s+", line.strip()) if delimiter is None else line.split(delimiter)


def _is_number(value: str, decimal: str) -> bool:
    try:
        float(value.strip().replace(",", ".") if decimal == "," else value.strip())
        return True
    except ValueError:
        return False


def _looks_decimal_comma(lines: list[str]) -> bool:
    matches = sum(bool(re.search(r"[+-]?\d+,\d+(?:[eE][+-]?\d+)?", line)) for line in lines)
    return matches >= max(1, len(lines) // 2)


def _unique_columns(columns: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for column in columns:
        count = counts.get(column, 0)
        counts[column] = count + 1
        result.append(column if count == 0 else f"{column} [{count + 1}]")
    return result
