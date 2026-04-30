#!/usr/bin/env python3
"""PreToolUse hook that warns when Claude re-reads an unchanged file.

Problem: After context compaction (37 compactions in a typical long session),
Claude forgets file contents and re-reads them — burning tokens on stale data.

Tracks every Read call per session (keyed by file path + mtime). Warns if
the model is about to re-read a file section it already saw this session and
the file hasn't changed on disk.

Always exits 0 (non-blocking). The model sees the warning and can skip
the re-read or proceed if it genuinely needs a different section.

Add to ~/.claude/settings.json:
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": "python3 /path/to/hooks/re-read-guard.py"}]
      }
    ]
  }
}
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "state"
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


def save_state(session_id: str, state: dict) -> None:
    get_state_path(session_id).write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)

    session_id = data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path_str = tool_input.get("file_path", "")
    offset = tool_input.get("offset")   # Claude Code uses 'offset' (not 'line_offset')
    limit = tool_input.get("limit")     # Claude Code uses 'limit' (not 'n_lines')

    if not file_path_str:
        sys.exit(0)

    resolved = (
        Path(file_path_str)
        if Path(file_path_str).is_absolute()
        else Path.cwd() / file_path_str
    )

    try:
        stat = resolved.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    except OSError:
        sys.exit(0)

    state = load_state(session_id)
    key = str(resolved.resolve())
    previous = state.get(key)

    if previous is not None:
        prev_mtime = previous.get("mtime", 0)
        prev_offset = previous.get("offset")
        prev_limit = previous.get("limit")

        file_unchanged = abs(mtime - prev_mtime) < 0.001 and size == previous.get("size", -1)

        if file_unchanged:
            same_section = False
            if offset is None and prev_offset is None:
                # Both are full-file reads
                same_section = True
            elif offset is not None and prev_offset is not None:
                # Check if the requested windows overlap significantly
                curr_start = offset if offset > 0 else max(1, abs(offset))
                curr_end = curr_start + (limit or 2000)
                prev_start = prev_offset if prev_offset > 0 else max(1, abs(prev_offset))
                prev_end = prev_start + (prev_limit or 2000)
                overlap = min(curr_end, prev_end) - max(curr_start, prev_start)
                if overlap > 0:
                    smaller = min(curr_end - curr_start, prev_end - prev_start)
                    if overlap >= 0.5 * smaller:
                        same_section = True

            if same_section:
                msg = (
                    f"⚠️ CONTEXT GUARD: You already read '{file_path_str}' earlier this session "
                    f"({'lines ' + str(prev_offset) if prev_offset else 'full file'}). "
                    f"The file has not changed (~{size // 4:,} tokens). "
                    f"Skip the re-read unless you need a different section (use offset)."
                )
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": msg,
                    }
                }))
                sys.exit(0)

    state[key] = {"mtime": mtime, "size": size, "offset": offset, "limit": limit}
    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
