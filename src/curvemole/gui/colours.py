"""Colour policy shared by CurveMole spectrum and model rendering."""

from __future__ import annotations

import colorsys

MODEL_SUM_COLOUR = "#D62728"
DEFAULT_SERIES_PALETTE = "Colourblind"
SERIES_PALETTES: dict[str, tuple[str, ...]] = {
    "Colourblind": (
        "#0072B2", "#009E73", "#CC79A7", "#E69F00",
        "#56B4E9", "#F0E442", "#332288", "#88CCEE",
    ),
    "Ocean": (
        "#003F5C", "#2F4B7C", "#007C91", "#00A6A6",
        "#4C78A8", "#72B7B2", "#5B8FF9", "#6C5CE7",
    ),
    "Viridis": (
        "#440154", "#482878", "#3E4989", "#31688E", "#26828E",
        "#1F9E89", "#6CCE59", "#B6DE2B", "#FDE725",
    ),
    "Pastel": (
        "#6BAED6", "#74C476", "#9E9AC8", "#9ECAE1",
        "#A1D99B", "#BCBDDC", "#FDD0A2", "#BDBDBD",
    ),
    "Grayscale": (
        "#111111", "#333333", "#555555", "#777777",
        "#999999", "#BBBBBB", "#DDDDDD",
    ),
}


def spectrum_colour_allowed(value: str) -> bool:
    """Return False for saturated red hues reserved for the model sum."""

    text = value.strip().lstrip("#")
    if len(text) != 6:
        return False
    try:
        red, green, blue = (int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return False
    hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
    degrees = hue * 360.0
    return not (saturation >= 0.25 and (degrees <= 15.0 or degrees >= 345.0))
