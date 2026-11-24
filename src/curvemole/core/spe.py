"""WinSpec SPE 2.x spectra (Princeton Instruments manual, Appendix C).

Only calibrated, one-dimensional, single-ROI acquisitions are supported.
No guessing a wavelength axis for uncalibrated pixels or SPE 3 XML files.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

    from curvemole.core.data import Curve

from curvemole.core.errors import DataValidationError


def is_spe(path: str | Path) -> bool:
    with Path(path).open("rb") as stream:
        header = stream.read(3000)
    return len(header) == 3000 and struct.unpack_from("<I", header, 2996)[0] == 0x01234567


def _read_spe_layout(stream):
    h = stream.read(4100)
    if len(h) != 4100:
        raise DataValidationError("Incomplete SPE header; waiting for acquisition to finish.")

    def value(offset, fmt):
        return struct.unpack_from("<" + fmt, h, offset)[0]

    version = value(1992, "f")
    if not 2 <= version < 3:
        raise DataValidationError(
            f"SPE {version:g} is unsupported; export calibrated X/Y text or SPE 2.x."
        )
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
    if not np.all(np.isfinite(x)) or not (np.all(np.diff(x) > 0) or np.all(np.diff(x) < 0)):
        raise DataValidationError("Invalid or nonmonotonic SPE wavelength calibration.")
    count = nx * frames
    if count * np.dtype(dtype).itemsize > 256 * 1024 * 1024:
        raise DataValidationError("SPE acquisition exceeds the 256 MiB import limit.")
    itemsize = np.dtype(dtype).itemsize
    if os.fstat(stream.fileno()).st_size < 4100 + count * itemsize:
        raise DataValidationError("Incomplete SPE data; waiting for acquisition to finish.")
    return x, dtype, frames, itemsize


def read_spe_frame(path: str | Path, *, nrows: int | None = None) -> pd.DataFrame:
    import pandas as pd

    with Path(path).open("rb") as stream:
        x, dtype, frames, itemsize = _read_spe_layout(stream)
        nx = len(x)
        rows = nx if nrows is None else min(nx, max(0, nrows))
        y = []
        for frame in range(frames):
            stream.seek(4100 + frame * nx * itemsize)
            y.append(np.frombuffer(stream.read(rows * itemsize), dtype=dtype))
        x = x[:rows]
    columns = {"Wavelength [nm]": x}
    columns.update({f"Intensity {i + 1}": row.astype(float) for i, row in enumerate(y)})
    frame = pd.DataFrame(columns)
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
                x, _, _, _ = _read_spe_layout(stream)
            return np.array_equal(curve.original_x, x)
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
