#!/usr/bin/env python3
"""PreToolUse hook that nudges toward line_offset for large files.

Problem: ReadFile without line_offset on a large file burns thousands of
tokens. The model often does this after Grep found a symbol on line 347.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/line-offset-enforcer.py"
timeout = 2
"""
import json
import subprocess
import sys
from pathlib import Path

LINE_THRESHOLD = 250
TIMEOUT_S = 1.5


def main():
    data = json.load(sys.stdin)

    if data.get("tool_name") != "ReadFile":
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    path_str = tool_input.get("path", "")
    line_offset = tool_input.get("line_offset")

    # If line_offset is already specified, we're good
    if line_offset is not None:
        sys.exit(0)

    if not path_str:
        sys.exit(0)

    # Resolve path
    cwd = data.get("cwd", ".")
    resolved = Path(cwd) / path_str if not Path(path_str).is_absolute() else Path(path_str)

    try:
        result = subprocess.run(
            ["wc", "-l", str(resolved)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
        if result.returncode != 0:
            sys.exit(0)
        line_count_str = result.stdout.strip().split()[0]
        line_count = int(line_count_str)
    except (Exception, subprocess.TimeoutExpired):
        # Fail open — don't block on I/O errors or timeouts
        sys.exit(0)

    if line_count > LINE_THRESHOLD:
        approx_tokens = line_count * 25  # rough heuristic
        print(
            f"⚠️ CONTEXT GUARD: '{path_str}' is {line_count} lines (~{approx_tokens:,} tokens). "
            f"Reading the entire file without line_offset wastes context. "
            f"If you only need a section, use ReadFile(path='{path_str}', line_offset=..., n_lines=...). "
            f"If you truly need the full file, proceed.",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
