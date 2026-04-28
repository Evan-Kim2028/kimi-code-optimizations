#!/usr/bin/env python3
"""PreToolUse hook for Shell commands. Rejects file-reading via Shell."""
import json
import re
import shlex
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

# Map of banned bare commands → guidance message.
# We tokenize with shlex and only block when the token is an actual command
# (not a CLI flag like --head, not an env var like PAGER=cat, not JSON data).
BANNED = {
    "cat": (
        "Shell 'cat' is not allowed. "
        "Use ReadFile(path=<file>, line_offset=<n>, n_lines=<m>) to read specific sections. "
        "Use Glob(pattern=<glob>) to discover files."
    ),
    "head": (
        "Shell 'head'/'tail' is not allowed. "
        "Use ReadFile(path=<file>, line_offset=<start_line>, n_lines=<count>) instead."
    ),
    "tail": (
        "Shell 'head'/'tail' is not allowed. "
        "Use ReadFile(path=<file>, line_offset=<start_line>, n_lines=<count>) instead."
    ),
    "grep": (
        "Shell 'grep'/'rg' is not allowed. "
        "Use Grep(pattern=<regex>, path=<dir_or_file>, output_mode='content') for discovery. "
        "Use Grep(pattern=<regex>, path=<file>, output_mode='content', -C=3) to read matching lines with context."
    ),
    "rg": (
        "Shell 'grep'/'rg' is not allowed. "
        "Use Grep(pattern=<regex>, path=<dir_or_file>, output_mode='content') for discovery. "
        "Use Grep(pattern=<regex>, path=<file>, output_mode='content', -C=3) to read matching lines with context."
    ),
    "find": (
        "Shell 'find'/'ls' is not allowed. "
        "Use Glob(pattern=<glob>, include_dirs=True) to discover files and directories."
    ),
    "ls": (
        "Shell 'find'/'ls' is not allowed. "
        "Use Glob(pattern=<glob>, include_dirs=True) to discover files and directories."
    ),
}

try:
    tokens = shlex.split(cmd)
except ValueError:
    tokens = cmd.split()

for token in tokens:
    # Skip environment variable assignments (KEY=value, KEY+=value)
    if "=" in token and not token.startswith("="):
        continue

    # Skip CLI flags (--head, -H, --tail, etc.)
    if token.startswith("-"):
        continue

    # Skip tokens that contain structural characters (JSON, URLs, globs, etc.)
    if any(c in token for c in '{}[]"\''):
        continue

    # Strip shell metacharacters that might surround a command
    clean = token.strip("|;&()<>")

    if clean in BANNED:
        block(BANNED[clean])


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
