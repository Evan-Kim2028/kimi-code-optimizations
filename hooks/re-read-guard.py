#!/usr/bin/env python3
"""PreToolUse hook that guards against re-reading unchanged files.

Problem: After context compaction, the model forgets file contents and
re-reads them, burning tokens on unchanged files.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/re-read-guard.py"
timeout = 3
"""
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"file-reads-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)

    if data.get("tool_name") != "ReadFile":
        sys.exit(0)

    session_id = data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    path_str = tool_input.get("path", "")
    line_offset = tool_input.get("line_offset")
    n_lines = tool_input.get("n_lines")

    if not path_str:
        sys.exit(0)

    # Resolve path
    cwd = data.get("cwd", ".")
    resolved = Path(cwd) / path_str if not Path(path_str).is_absolute() else Path(path_str)

    try:
        mtime = resolved.stat().st_mtime
        size = resolved.stat().st_size
    except (OSError, FileNotFoundError):
        # File doesn't exist or unreadable — let the tool handle the error
        sys.exit(0)

    state = load_state(session_id)
    key = str(resolved.resolve())

    previous = state.get(key)
    if previous is not None:
        prev_mtime = previous.get("mtime", 0)
        prev_offset = previous.get("line_offset")
        prev_n_lines = previous.get("n_lines")

        # Check if file changed
        if abs(mtime - prev_mtime) < 0.001 and size == previous.get("size", -1):
            # File unchanged. Check if this is a re-read of the same section.
            same_section = False
            if line_offset is None and prev_offset is None:
                same_section = True
            elif line_offset is not None and prev_offset is not None:
                # Consider it a re-read if the windows overlap significantly
                curr_start = line_offset if line_offset > 0 else max(1, abs(line_offset))
                curr_end = curr_start + (n_lines or 1000)
                prev_start = prev_offset if prev_offset > 0 else max(1, abs(prev_offset))
                prev_end = prev_start + (prev_n_lines or 1000)

                overlap_start = max(curr_start, prev_start)
                overlap_end = min(curr_end, prev_end)
                if overlap_end > overlap_start:
                    overlap = overlap_end - overlap_start
                    smaller = min(curr_end - curr_start, prev_end - prev_start)
                    if overlap >= 0.5 * smaller:
                        same_section = True

            if same_section:
                print(
                    f"⚠️ CONTEXT GUARD: You already read '{path_str}' earlier in this session "
                    f"(lines {prev_offset or 'full file'}). "
                    f"The file has not changed since then. "
                    f"Re-reading it wastes ~{size // 4:,} tokens of context. "
                    f"Only re-read if you need a *different* section (use line_offset).",
                    file=sys.stderr,
                )
                # Non-blocking tip — allow the call but make the model think twice
                sys.exit(0)

    # Record this read
    state[key] = {
        "mtime": mtime,
        "size": size,
        "line_offset": line_offset,
        "n_lines": n_lines,
    }
    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
