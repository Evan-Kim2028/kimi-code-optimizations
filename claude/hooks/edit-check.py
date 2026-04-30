#!/usr/bin/env python3
"""Pre-validate Edit tool old_string against actual file content.

Prevents wasted round-trips when old_string has drifted from reality
(after context compaction, parallel edits, or refactors).

Claude Code PreToolUse hook for the Edit tool.
Exit 2 blocks the call; exit 0 allows it.

Add to ~/.claude/settings.json:
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": "python3 /path/to/hooks/edit-check.py"}]
      }
    ]
  }
}
"""
import json
import sys
from pathlib import Path

data = json.load(sys.stdin)
tool_input = data.get("tool_input", {})

file_path = tool_input.get("file_path", "")
old_string = tool_input.get("old_string", "")

if not file_path or not old_string:
    sys.exit(0)

resolved = Path(file_path) if Path(file_path).is_absolute() else Path.cwd() / file_path

try:
    content = resolved.read_text(encoding="utf-8")
except Exception:
    sys.exit(0)  # fail-open on I/O errors

if old_string not in content:
    print(
        f"ERROR: Edit old_string not found in {file_path}. "
        "The edit will fail. Re-read the file to get the exact current text. "
        "Common causes: whitespace differences, line endings, or the file changed since you last read it."
    )
    sys.exit(2)

sys.exit(0)
