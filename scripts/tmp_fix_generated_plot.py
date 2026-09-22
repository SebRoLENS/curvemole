from pathlib import Path
import textwrap

path = Path("src/curvemole/gui/plot.py")
text = path.read_text(encoding="utf-8")
needle = "view_layout.addLayout(autoscale_controls)"
pos = text.index(needle)
start = text.rfind("\n", 0, pos) + 1
end_pos = text.index("offset_controls = QHBoxLayout()", pos)
end = text.index("\n", end_pos) + 1
block = textwrap.dedent(text[start:end])
block = textwrap.indent(block, "        ")
path.write_text(text[:start] + block + text[end:], encoding="utf-8")
