#!/usr/bin/env python3
"""Detect sequential similar tool calls and suggest batching.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /path/to/kimi-code-optimizations/hooks/batch-nudge.py"
timeout = 2

This hook maintains a sliding window of recent tool calls per session.
After 3+ sequential calls of the same tool type, it emits a warning
so the model learns to batch in real time.
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SIZE = 5


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"batch-tracker-{session_id}.json"


def load_window(session_id: str) -> list[dict]:
    path = get_state_path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_window(session_id: str, window: list[dict]):
    path = get_state_path(session_id)
    # Keep only last WINDOW_SIZE entries
    path.write_text(json.dumps(window[-WINDOW_SIZE:], indent=2))


def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")

    if event != "PostToolUse" or not session_id:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_output = data.get("tool_output", "")

    # Don't count blocked calls or errors in the nudge
    if (
        isinstance(tool_output, str)
        and (tool_output.startswith("ERROR") or tool_output.startswith("WARNING"))
    ):
        sys.exit(0)

    window = load_window(session_id)
    window.append({"tool": tool_name, "id": data.get("tool_call_id", "")})
    save_window(session_id, window)

    # Look at last 3 calls
    recent = [w["tool"] for w in window[-3:]]
    if len(recent) < 3 or len(set(recent)) != 1:
        sys.exit(0)

    tips = {
        "ReadFile": (
            "TIP: You just made 3+ sequential ReadFile calls. "
            "Batch them in parallel next time — pass all ReadFile calls in one turn. "
            "Even better: use Grep to find exact line numbers first, then ReadFile with line_offset."
        ),
        "Grep": (
            "TIP: You just made 3+ sequential Grep calls. "
            "Batch them in parallel next time — make all Grep calls in one turn."
        ),
        "Shell": (
            "TIP: You just made 3+ sequential Shell calls. "
            "Can they be combined into one multi-line script? "
            "Or replaced with native tools (ReadFile, Grep, Glob)?"
        ),
        "Agent": (
            "TIP: You just dispatched 3+ agents sequentially. "
            "Use run_in_background=true and poll them in parallel instead."
        ),
        "StrReplaceFile": (
            "TIP: You just made 3+ sequential StrReplaceFile calls. "
            "For multi-file changes, consider apply-patch or WriteFile. "
            "For multi-hunk in one file, use apply-patch."
        ),
    }

    tip = tips.get(tool_name)
    if tip:
        print(tip, file=sys.stderr)
        sys.exit(1)  # Warning only (exit 1, not 2)

    sys.exit(0)


if __name__ == "__main__":
    main()
