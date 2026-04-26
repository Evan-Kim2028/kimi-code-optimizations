#!/usr/bin/env python3
"""PreToolUse hook for Shell commands. Rejects file-reading via Shell."""
import json
import re
import sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def block(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 1. Reject local file-reading via Shell with *specific* guidance
# ---------------------------------------------------------------------------

# cat → ReadFile
if re.search(r"\bcat\b", cmd):
    block(
        "Shell 'cat' is not allowed. "
        "Use ReadFile(path=<file>, line_offset=<n>, n_lines=<m>) to read specific sections. "
        "Use Glob(pattern=<glob>) to discover files."
    )

# head / tail → ReadFile with line_offset
if re.search(r"\b(head|tail)\b", cmd):
    block(
        "Shell 'head'/'tail' is not allowed. "
        "Use ReadFile(path=<file>, line_offset=<start_line>, n_lines=<count>) instead."
    )

# grep / rg → Grep
if re.search(r"\b(grep|rg)\b", cmd):
    block(
        "Shell 'grep'/'rg' is not allowed. "
        "Use Grep(pattern=<regex>, path=<dir_or_file>, output_mode='content') for discovery. "
        "Use Grep(pattern=<regex>, path=<file>, output_mode='content', -C=3) to read matching lines with context."
    )

# find / ls → Glob
if re.search(r"\b(find|ls)\b", cmd):
    block(
        "Shell 'find'/'ls' is not allowed. "
        "Use Glob(pattern=<glob>, include_dirs=True) to discover files and directories."
    )

# ---------------------------------------------------------------------------
# 2. Reject SSH-wrapped file-reading
# ---------------------------------------------------------------------------
if re.search(r'ssh.*"(cat|head|tail|find|grep|ls|sed -n)', cmd):
    block(
        "Reading remote files over SSH is inefficient. "
        "Options: (1) scp/rsync the file locally first, then use ReadFile, "
        "(2) run a single discovery script over SSH that dumps JSON/CSV, then parse locally, "
        "or (3) batch SSH commands into one multi-line script instead of many individual calls."
    )

# ---------------------------------------------------------------------------
# 3. Warn on cd with specific alternative
# ---------------------------------------------------------------------------
if re.search(r"^cd\s", cmd):
    warn(
        "Avoid 'cd'. You are already in the correct working directory. "
        "Use absolute or relative paths directly. "
        "For git in other directories: git -C /path/to/repo <command>."
    )

sys.exit(0)
