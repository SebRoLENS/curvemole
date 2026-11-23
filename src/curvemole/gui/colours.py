"""Colour policy shared by CurveMole spectrum and model rendering."""

from __future__ import annotations

MODEL_SUM_COLOUR = "#D62728"
_FIT_COLOUR_DISTANCE = 12
_PALETTE_FIT_DISTANCE = 64
DEFAULT_SERIES_PALETTE = "Neon"
SERIES_PALETTES: dict[str, tuple[str, ...]] = {
    "Colourblind": (
        "#2084C6", "#009E73", "#CC79A7", "#E69F00",
        "#56B4E9", "#F0E442", "#8C76DC", "#88CCEE",
    ),
    "Ocean": (
        "#56B4E9", "#FF6F7E", "#7ED9C3", "#678AD7",
        "#4C9DDB", "#72B7B2", "#5B8FF9", "#9F94FF",
        "#13AE61", "#E3F9FF",
    ),
    "Viridis": (
        "#9575D1", "#FF7888", "#6385D7", "#3898AE", "#3BB498",
        "#49C578", "#8FD649", "#B6DE2B", "#FDE725",
        "#CCD5FF", "#169451",
    ),
    "Pastel": (
        "#6BAED6", "#FF98A2", "#74C476", "#9E9AC8", "#9ECAE1",
        "#A1D99B", "#BCBDDC", "#FDD0A2", "#BDBDBD",
        "#C7FFFF", "#F588F2",
    ),
    "Grayscale": (
        "#777777", "#8B8B8B", "#9F9F9F", "#B3B3B3",
        "#C7C7C7", "#DBDBDB", "#EFEFEF",
    ),
    "Neon": (
        "#55E9FD", "#FF6278", "#D6FA54", "#B49CFF",
        "#FFBA49", "#52F5B0", "#FF91F5", "#F5EB84",
        "#E800FF", "#1687FF", "#12C53A", "#C08C10",
    ),
    "Sunset": (
        "#FFBF64", "#FF6F7E", "#B49BFD", "#FF9CCA",
        "#68CFE1", "#EADB84", "#FF9A53", "#BEE68B",
        "#476FFF", "#D820C5",
    ),
    "Jewel": (
        "#42D8C3", "#FA738A", "#9D8AF3", "#EAC762",
        "#70BBFF", "#DA91E8", "#88DD87", "#F5AC79",
        "#D13BDF", "#127CD0", "#D57324", "#F5F953",
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


def _colour_is_distinct(value: str, model_sum: bytes | None, distance: int) -> bool:
    spectrum = _rgb(value)
    if spectrum is None:
        return False
    return model_sum is None or sum(
        (channel - reference) ** 2 for channel, reference in zip(spectrum, model_sum, strict=True)
    ) > distance ** 2


def spectrum_colour_allowed(value: str, model_sum_colour: str | None = MODEL_SUM_COLOUR) -> bool:
    """Allow valid RGB colours outside a small radius around the model-sum colour."""
    model_sum = _rgb(model_sum_colour) if model_sum_colour is not None else None
    return _colour_is_distinct(value, model_sum, _FIT_COLOUR_DISTANCE)


def series_palette_colours(name: str, model_sum_colour: str) -> tuple[str, ...]:
    """Keep automatic colours farther from the fit than individual choices."""
    model_sum = _rgb(model_sum_colour)
    return tuple(
        colour for colour in SERIES_PALETTES.get(name, ())
        if _colour_is_distinct(colour, model_sum, _PALETTE_FIT_DISTANCE)
    )
