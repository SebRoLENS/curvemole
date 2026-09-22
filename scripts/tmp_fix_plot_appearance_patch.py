from pathlib import Path

path = Path("scripts/tmp_apply_plot_appearance_patch.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '            """Render excluded samples using the current project appearance settings."""\n',
    "            # Render excluded samples using the current project appearance settings.\n",
    1,
)
start = text.index("    menu_anchor = textwrap.dedent(\n")
end = text.index("    text = replace_once(\n        text,\n        menu_anchor,", start)
menu = (
    "    menu_anchor = (\n"
    '        "        view_menu.addActions(\\n"\n'
    '        "            [\\n"\n'
    '        "                self.series_dock.toggleViewAction(),\\n"\n'
    '        "                self.model_dock.toggleViewAction(),\\n"\n'
    '        "                self.worksheet_action,\\n"\n'
    '        "                self.diagnostics_action,\\n"\n'
    '        "                self.log_action,\\n"\n'
    '        "            ]\\n"\n'
    '        "        )\\n"\n'
    "    )\n"
)
path.write_text(text[:start] + menu + text[end:], encoding="utf-8")
