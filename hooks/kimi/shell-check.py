#!/usr/bin/env python3
"""
Shell usage coach — guides the model toward optimal tool selection.

Philosophy: The model should use the best tool for the job, not be forced
away from Shell. We emit contextual tips and let the model decide.

Always exits 0 (non-blocking). Tips go to stderr so the model sees them
in the tool result.
"""

import json
import re
import sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")

def tip(msg: str) -> None:
    print(f"💡 {msg}", file=sys.stderr)

# --- Detect patterns and emit tips ---

# File discovery: ls, find → Glob
if re.search(r"\bls\b", cmd) or re.search(r"\bfind\b", cmd):
    # Try to extract the directory being listed (skip numeric args like -n 25)
    m = re.search(r"\b(?:ls|find)\s+(?:-[a-zA-Z]+\s+)*(-?\d+\s+)?(?:-[a-zA-Z]+\s+)*(\S+)", cmd)
    path = m.group(2) if m and m.group(2) else "."
    tip(f"For file discovery, try Glob(pattern='{path}/**/*', include_dirs=True) — "
        f"it returns structured file lists faster than parsing ls/find output.")

# File reading: cat, head, tail → ReadFile
if re.search(r"\bcat\b", cmd) or re.search(r"\bhead\b", cmd) or re.search(r"\btail\b", cmd):
    # Try to extract filename (last non-flag arg)
    m = re.search(r"\b(?:cat|head|tail)\s+(?:-[a-zA-Z]+\s+)*(-?\d+\s+)?(?:-[a-zA-Z]+\s+)*(\S+)", cmd)
    file = m.group(2) if m and m.group(2) else "<file>"
    if re.search(r"\bhead\b", cmd):
        tip(f"For reading the start of a file, try ReadFile(path='{file}', line_offset=1, n_lines=25) — "
            f"returns structured lines with numbers instead of raw text.")
    elif re.search(r"\btail\b", cmd):
        tip(f"For reading the end of a file, try ReadFile(path='{file}', line_offset=-25) — "
            f"returns the last 25 lines with line numbers.")
    else:
        tip(f"For reading files, try ReadFile(path='{file}') — "
            f"it handles large files gracefully and returns structured content.")

# Text search: grep, rg → Grep
if re.search(r"\bgrep\b", cmd) or re.search(r"\brg\b", cmd):
    # Try to extract pattern and path
    m = re.search(r"\b(?:grep|rg)\s+(?:-[a-zA-Z]+\s+)*['\"]?(.*?)['\"]?\s+(-?\S+)", cmd)
    pattern = m.group(1) if m else "<pattern>"
    path = m.group(2) if m and m.lastindex >= 2 else "."
    tip(f"For text search, try Grep(pattern='{pattern}', path='{path}') — "
        f"returns structured matches with line numbers and context.")

# Python-in-shell bypasses — guide toward native tools
if re.search(r"\bpython3?\s+-c\b", cmd) and re.search(r"\bos\.(listdir|walk)|glob\b", cmd):
    tip("Using Python via Shell for file discovery is possible, but Glob(pattern='**/*') "
        "is purpose-built for this and returns cleaner structured output.")

if re.search(r"\bpython3?\s+-c\b", cmd) and re.search(r"\bopen\s*\(|\.read\b", cmd):
    tip("Using Python via Shell to read files works, but ReadFile handles large files, "
        "line offsets, and returns structured content automatically.")

# cd — warn about statelessness
if re.search(r"\bcd\s+", cmd):
    tip("Note: cd in Shell doesn't persist across calls. Use absolute paths or set "
        "the working directory in the command itself (e.g., 'ls /absolute/path').")

# Positive reinforcement for good Shell usage
if re.search(r"\bpip\s+(install|show|list)\b", cmd):
    tip("✅ Good use of Shell — pip commands are best run via Shell.")

if re.search(r"\bdocker\b", cmd):
    tip("✅ Good use of Shell — docker CLI is best run via Shell.")

if re.search(r"\bgit\s+(log|diff|show|status)\b", cmd):
    tip("✅ Good use of Shell — git commands are best run via Shell.")

if re.search(r"\bcurl\b|\bwget\b", cmd):
    tip("✅ Good use of Shell — HTTP requests via curl/wget are fine, though native tools "
        "can also help parse the response.")

# Batch operations — suggest Shell when model overuses native tools
if len(cmd.split("\n")) > 3 or cmd.count("&&") > 2 or cmd.count(";") > 2:
    tip("✅ Complex multi-step pipeline — Shell is the right choice here.")

sys.exit(0)
