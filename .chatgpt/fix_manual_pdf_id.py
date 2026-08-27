from __future__ import annotations

from pathlib import Path

path = Path("scripts/build_manual.py")
text = path.read_text(encoding="utf-8")
old = 'PDF_ID_RE = re.compile(rb"/ID\\[<[0-9A-Fa-f]{32}><[0-9A-Fa-f]{32}>\\]")'
new = 'PDF_ID_RE = re.compile(rb"/ID\\s*\\[\\s*<[0-9A-Fa-f]+>\\s*<[0-9A-Fa-f]+>\\s*\\]")'
if old not in text:
    raise SystemExit("Expected PDF_ID_RE definition not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
