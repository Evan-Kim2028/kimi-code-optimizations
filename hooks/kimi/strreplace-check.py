#!/usr/bin/env python3
"""Pre-validate StrReplaceFile 'old' strings against actual file content.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "StrReplaceFile"
command = "python3 /path/to/kimi-code-optimizations/hooks/kimi/strreplace-check.py"
timeout = 3
"""
import json
import sys
from pathlib import Path

data = json.load(sys.stdin)
tool_input = data.get("tool_input", {})

# Only run for StrReplaceFile
if data.get("tool_name") != "StrReplaceFile":
    sys.exit(0)

path = tool_input.get("path", "")

# Handle single edit or list of edits
edits = tool_input.get("edit")
if edits is None:
    edits = tool_input.get("edits", [])
if isinstance(edits, dict):
    edits = [edits]

if not path or not edits:
    sys.exit(0)

# Resolve path relative to cwd if needed
cwd = data.get("cwd", ".")
resolved = Path(cwd) / path if not Path(path).is_absolute() else Path(path)

try:
    content = resolved.read_text(encoding="utf-8")
except Exception as e:
    # Fail open if we can't read the file
    sys.exit(0)

failures = []
for idx, edit in enumerate(edits):
    old = edit.get("old", "")
    if not old:
        continue
    if old not in content:
        failures.append(idx)

if failures:
    plural = "s" if len(failures) > 1 else ""
    indices = ", ".join(str(i + 1) for i in failures)
    print(
        f"ERROR: StrReplaceFile edit{plural} [{indices}] 'old' string not found in {path}. "
        "The replacement will fail. "
        "Re-read the file to get the exact current text. "
        "Common causes: whitespace differences, line endings, or the file changed since you last read it.",
        file=sys.stderr,
    )
    sys.exit(2)

sys.exit(0)
