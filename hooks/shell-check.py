#!/usr/bin/env python3
"""PreToolUse hook for Shell commands. Rejects file-reading via Shell.

Usage:
    echo '{"tool_input":{"command":"grep foo bar"}}' | python3 shell-check.py

Exits 0 = allow, 2 = block.
"""
import json
import re
import sys


def main() -> int:
    data = json.load(sys.stdin)
    cmd = data.get("tool_input", {}).get("command", "")

    # Reject local file-reading via Shell
    if re.search(r"\b(cat|head|tail|find|grep|rg)\b", cmd):
        print(
            "ERROR: Use ReadFile, Grep, or Glob instead of Shell for file operations. "
            "Shell is for git, tests, builds, and package managers only.",
            file=sys.stderr,
        )
        return 2

    # Reject SSH-wrapped file-reading
    if re.search(r'ssh.*"(cat|head|tail|find|grep|ls|sed-n)', cmd):
        print(
            "ERROR: Reading remote files over SSH is inefficient. "
            "Options: (1) scp/rsync locally first, "
            "(2) run a single discovery script over SSH and capture output, "
            "or (3) batch commands into one SSH session.",
            file=sys.stderr,
        )
        return 2

    # Warn on cd (print to stderr but don't block)
    if re.search(r"^cd\s", cmd):
        print(
            "WARNING: Avoid cd. Use absolute or relative paths directly.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
