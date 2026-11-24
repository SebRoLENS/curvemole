"""Calibrated single-region 1D spectra from WinSpec SPE 2.x and LightField SPE 3.0."""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

    from curvemole.core.data import Curve

from curvemole.core.errors import DataValidationError

HEADER_SIZE = 4100
VERSION_OFFSET = 1992
FOOTER_OFFSET = 678
MAX_DATA_BYTES = 256 * 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
SPE3_NAMESPACE = "{http://www.princetoninstruments.com/spe/2009}"
SPE3_DTYPES = {
    "MonochromeUnsigned16": np.dtype("<u2"),
    "MonochromeUnsigned32": np.dtype("<u4"),
    "MonochromeFloating32": np.dtype("<f4"),
}


def is_spe(path: str | Path) -> bool:
    with Path(path).open("rb") as stream:
        header = stream.read(3000)
    if len(header) < 3000:
        return False
    # In SPE 3.0 the version and XML offset are the only required header fields.
    if struct.unpack_from("<I", header, 2996)[0] == 0x01234567:
        return True
    version = struct.unpack_from("<f", header, VERSION_OFFSET)[0]
    footer = struct.unpack_from("<Q", header, FOOTER_OFFSET)[0]
    return version == 3.0 and footer >= HEADER_SIZE


def _read_spe2_layout(h, file_size):
    def value(offset, fmt):
        return struct.unpack_from("<" + fmt, h, offset)[0]

    nx, ny, frames = value(42, "H"), value(656, "H"), value(1446, "i")
    dtype = {0: "<f4", 1: "<i4", 2: "<i2", 3: "<u2"}.get(value(108, "h"))
    if not dtype or nx < 2 or ny != 1 or not 1 <= frames <= 10000 or value(1510, "h") > 1:
        raise DataValidationError(
            "SPE import requires 1D spectra, one ROI and a supported pixel type."
        )
    if not value(3098, "B") or value(3101, "B") > 5:
        raise DataValidationError("SPE has no valid polynomial wavelength calibration.")
    if value(3100, "B") != 4:
        raise DataValidationError(
            "SPE polynomial axis must be in nanometres. Export calibrated X/Y text."
        )
    start, end, group = struct.unpack_from("<3H", h, 1512)
    if group < 1 or end < start or (end - start + 1) // group != nx:
        raise DataValidationError("Unsupported or inconsistent SPE X ROI.")
    # Calibration pixel coordinates are one-based detector positions;
    # binned samples are located at the centre of their pixel group.
    pixels = start + (group - 1) / 2 + np.arange(nx) * group
    coefficients = struct.unpack_from("<6d", h, 3263)
    x = np.polynomial.polynomial.polyval(pixels, coefficients[: value(3101, "B") + 1])
    stride = nx * np.dtype(dtype).itemsize
    data_bytes = stride * frames
    if data_bytes > MAX_DATA_BYTES:
        raise DataValidationError("SPE acquisition exceeds the 256 MiB import limit.")
    if file_size < HEADER_SIZE + data_bytes:
        raise DataValidationError("Incomplete SPE data; waiting for acquisition to finish.")
    return x, dtype, frames, stride, True


class _SpeXmlTree(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise DataValidationError("SPE 3.0 XML footers cannot contain a document type declaration.")


def _selected_calibration(calibrations, block, namespace, name):
    candidates = [] if calibrations is None else calibrations.findall(namespace + name)
    links = block.get("calibrations")
    if links is not None:
        identifiers = {value.strip() for value in links.split(",")}
        candidates = [element for element in candidates if element.get("id") in identifiers]
    if len(candidates) > 1:
        raise DataValidationError(f"Ambiguous SPE 3.0 {name} calibration.")
    return candidates[0] if candidates else None


def _orientation(element):
    if element is None:
        return set()
    flags = {key.strip() for key in element.get("orientation", "Normal").split(",")} - {"Normal"}
    if not flags <= {"FlippedHorizontally", "FlippedVertically", "RotatedClockwise"}:
        raise DataValidationError("Unsupported SPE 3.0 calibration orientation.")
    return flags


def _read_spe3_wavelengths(root, namespace, frame, region, width):
    calibrations = root.find(namespace + "Calibrations")
    mapping = _selected_calibration(calibrations, frame, namespace, "WavelengthMapping")
    if mapping is None:
        raise DataValidationError("SPE 3.0 file has no wavelength calibration in nanometres.")
    wavelength = mapping.findtext(namespace + "Wavelength")
    wavelength_error = mapping.findtext(namespace + "WavelengthError")
    try:
        if wavelength:
            x = np.array([float(value) for value in wavelength.split(",")])
        elif wavelength_error:
            pairs = [tuple(map(float, pair.split())) for pair in wavelength_error.split(",")]
            x, _ = np.asarray(pairs).T  # Calibration errors are not intensity errors.
        else:
            raise ValueError("missing wavelengths")
    except ValueError as exc:
        raise DataValidationError("Invalid SPE 3.0 wavelength calibration.") from exc
    if len(x) < 2 or not np.all(np.isfinite(x)):
        raise DataValidationError("Invalid SPE 3.0 wavelength calibration.")

    sensor = _selected_calibration(calibrations, region, namespace, "SensorInformation")
    sensor_mapping = _selected_calibration(calibrations, region, namespace, "SensorMapping")
    data_orientation, calibration_orientation = _orientation(sensor), _orientation(mapping)
    different = data_orientation ^ calibration_orientation
    if "RotatedClockwise" in different:
        raise DataValidationError("SPE 3.0 wavelength and sensor axes have different rotations.")
    horizontal_flip = (
        "FlippedVertically" if "RotatedClockwise" in data_orientation else "FlippedHorizontally"
    )
    if horizontal_flip in different:
        x = x[::-1]
    if sensor_mapping is None:
        if len(x) != width:
            raise DataValidationError("SPE 3.0 wavelength count does not match the spectrum width.")
        # The wavelengths can be used directly. There is no confirmed sensor sampling geometry.
        return x, False

    try:
        start = int(sensor_mapping.attrib["x"])
        span = int(sensor_mapping.attrib["width"])
        binning = int(sensor_mapping.attrib["xBinning"])
    except (KeyError, ValueError) as exc:
        raise DataValidationError("Invalid SPE 3.0 sensor mapping.") from exc
    if start < 0 or binning < 1 or span != width * binning or start + span > len(x):
        raise DataValidationError("SPE 3.0 sensor mapping does not match the wavelength calibration.")
    # The XML table gives wavelengths at physical pixel centres. For even bin sizes,
    # interpolate the two wavelengths either side of the grouped sample's centre.
    samples = start + (binning - 1) / 2 + np.arange(width) * binning
    return np.interp(samples, np.arange(len(x)), x), True


def _read_spe3_layout(stream, h, file_size):
    footer = struct.unpack_from("<Q", h, FOOTER_OFFSET)[0]
    if footer < HEADER_SIZE or footer >= file_size:
        raise DataValidationError("SPE 3.0 XML footer is missing or incomplete.")
    if footer - HEADER_SIZE > MAX_DATA_BYTES or file_size - footer > MAX_XML_BYTES:
        raise DataValidationError("SPE 3.0 data or XML footer exceeds the import limit.")
    stream.seek(footer)
    try:
        root = ET.fromstring(stream.read(file_size - footer), parser=ET.XMLParser(target=_SpeXmlTree()))
    except ET.ParseError as exc:
        raise DataValidationError("Invalid or incomplete SPE 3.0 XML footer.") from exc
    if root.tag not in {"SpeFormat", SPE3_NAMESPACE + "SpeFormat"} or root.get("version") != "3.0":
        raise DataValidationError("SPE 3.0 XML footer does not match the binary header.")
    namespace = SPE3_NAMESPACE if root.tag.startswith("{") else ""
    frames = root.findall(f"{namespace}DataFormat/{namespace}DataBlock")
    if len(frames) != 1 or frames[0].get("type") != "Frame":
        raise DataValidationError("SPE 3.0 requires exactly one frame layout.")
    frame = frames[0]
    regions = frame.findall(namespace + "DataBlock")
    if len(regions) != 1 or regions[0].get("type") != "Region":
        raise DataValidationError("SPE 3.0 import requires a single-region 1D spectrum.")
    region = regions[0]
    try:
        nframes = int(frame.attrib["count"])
        dtype = SPE3_DTYPES[frame.attrib["pixelFormat"]]
        frame_size, frame_stride = int(frame.attrib["size"]), int(frame.attrib["stride"])
        width, height = int(region.attrib["width"]), int(region.attrib["height"])
        nregions = int(region.attrib["count"])
        region_size, region_stride = int(region.attrib["size"]), int(region.attrib["stride"])
    except (KeyError, ValueError) as exc:
        raise DataValidationError("Unsupported SPE 3.0 pixel format or invalid binary layout.") from exc
    if height != 1 or nregions != 1 or width < 2 or not 1 <= nframes <= 10_000:
        raise DataValidationError("SPE 3.0 import requires a single-region 1D spectrum.")
    if (width * dtype.itemsize != region_size or region_size != frame_size
            or not region_size <= region_stride <= frame_stride
            or HEADER_SIZE + nframes * frame_stride > footer):
        raise DataValidationError("SPE 3.0 binary layout is inconsistent with the XML footer.")
    x, detector_grid = _read_spe3_wavelengths(root, namespace, frame, region, width)
    return x, dtype, nframes, frame_stride, detector_grid


def _read_spe_layout(stream):
    h = stream.read(HEADER_SIZE)
    if len(h) != HEADER_SIZE:
        raise DataValidationError("Incomplete SPE header; waiting for acquisition to finish.")
    version = struct.unpack_from("<f", h, VERSION_OFFSET)[0]
    file_size = os.fstat(stream.fileno()).st_size
    if 2 <= version < 3:
        layout = _read_spe2_layout(h, file_size)
    elif version == 3.0:
        layout = _read_spe3_layout(stream, h, file_size)
    else:
        raise DataValidationError(f"Unsupported SPE version {version:g}.")
    x = layout[0]
    steps = np.diff(x)
    if not np.all(np.isfinite(x)) or not (np.all(steps > 0) or np.all(steps < 0)):
        raise DataValidationError("Invalid or nonmonotonic SPE wavelength calibration.")
    return layout


def read_spe_frame(path: str | Path, *, nrows: int | None = None) -> pd.DataFrame:
    import pandas as pd

    with Path(path).open("rb") as stream:
        x, dtype, frames, stride, detector_grid = _read_spe_layout(stream)
        rows = len(x) if nrows is None else min(len(x), max(0, nrows))
        row_bytes = rows * np.dtype(dtype).itemsize
        y = []
        for frame in range(frames):
            stream.seek(HEADER_SIZE + frame * stride)
            payload = stream.read(row_bytes)
            if len(payload) != row_bytes:
                raise DataValidationError("Incomplete SPE frame; waiting for acquisition to finish.")
            y.append(np.frombuffer(payload, dtype=dtype))
        x = x[:rows]
    columns = {"Wavelength [nm]": x}
    columns.update({f"Intensity {i + 1}": row.astype(float) for i, row in enumerate(y)})
    frame = pd.DataFrame(columns)
    if detector_grid:
        frame.attrs["sample_grid"] = "spe_detector"
    return frame


def _matches_original_spe_grid(curve: Curve) -> bool:
    """SPE ROI samples are equally spaced in detector order before wavelength calibration."""
    # Older projects did not save the detector grid. Verify their original wavelength array
    # against the source, since neither a filename nor a column label proves SPE provenance.
    if not curve.source:
        return False
    try:
        if Path(curve.source).is_file() and is_spe(curve.source):
            with Path(curve.source).open("rb") as stream:
                x, _, _, _, detector_grid = _read_spe_layout(stream)
            return detector_grid and np.array_equal(curve.original_x, x)
    except (OSError, DataValidationError):
        pass
    return False


def restore_spe_detector_grid(curve: Curve) -> None:
    imported = curve.metadata.get("import")
    if (isinstance(imported, dict) and "sample_grid" not in imported
            and imported.get("x_column") == "Wavelength [nm]"
            and imported.get("y_column") != "Wavelength [nm]"
            and _matches_original_spe_grid(curve)):
        imported["sample_grid"] = "spe_detector"
