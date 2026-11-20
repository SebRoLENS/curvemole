"""Colour policy shared by CurveMole spectrum and model rendering."""

from __future__ import annotations

MODEL_SUM_COLOUR = "#D62728"
_FIT_COLOUR_DISTANCE = 12
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


def _rgb(value: str) -> bytes | None:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        channels = bytes.fromhex(text)
    except ValueError:
        return None
    return channels if len(channels) == 3 else None


def spectrum_colour_allowed(value: str, model_sum_colour: str | None = MODEL_SUM_COLOUR) -> bool:
    """Allow valid RGB colours outside a small radius around the model-sum colour."""
    spectrum = _rgb(value)
    if spectrum is None:
        return False
    model_sum = _rgb(model_sum_colour) if model_sum_colour is not None else None
    return model_sum is None or sum(
        (channel - reference) ** 2 for channel, reference in zip(spectrum, model_sum, strict=True)
    ) > _FIT_COLOUR_DISTANCE ** 2
