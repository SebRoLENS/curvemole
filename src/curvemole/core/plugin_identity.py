"""Consistent plugin provenance labels, independent of Qt."""
SYMBOLS = ("◆", "●", "▲", "■", "★", "⬟", "▼", "◉", "✚", "◈", "◐", "✦")


def provenance(symbol: str, name: str, identifier: str) -> str:
    return f"{symbol} This feature belongs to plugin {name} ({identifier})."


def function_tooltip(definition) -> str:
    metadata = definition.custom_metadata
    owner = metadata.get("plugin_owner")
    if not owner:
        return definition.description
    return provenance(metadata.get("plugin_symbol", "◆"), metadata.get("plugin_name", owner), owner) + (
        "\n" + definition.description if definition.description else "")


def contribution_tooltip(entry) -> str:
    return provenance(entry.symbol, entry.plugin_name or entry.owner, entry.owner) + (
        "\n" + entry.description if entry.description else "")
