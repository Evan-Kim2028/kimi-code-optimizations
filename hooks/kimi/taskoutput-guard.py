#!/usr/bin/env python3
"""PreToolUse hook that ensures TaskList is called before TaskOutput polling.

Problem: Models poll TaskOutput on remembered task IDs without verifying
which background tasks are still active, wasting turns on stale/crashed tasks.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "TaskOutput"
command = "python3 /home/evan/.kimi/hooks/taskoutput-guard.py"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Window: how many tool calls back we check for a TaskList
LOOKBACK_WINDOW = 15


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"taskoutput-guard-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {"recent_calls": [], "tips_this_session": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"recent_calls": [], "tips_this_session": 0}


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)

    tool_name = data.get("tool_name", "")
    session_id = data.get("session_id", "")

    if not session_id:
        sys.exit(0)

    state = load_state(session_id)
    recent = state.get("recent_calls", [])

    # Track this call
    recent.append(tool_name)
    recent = recent[-LOOKBACK_WINDOW:]
    state["recent_calls"] = recent

    if tool_name == "TaskList":
        save_state(session_id, state)
        sys.exit(0)

    if tool_name != "TaskOutput":
        save_state(session_id, state)
        sys.exit(0)

    # Check if TaskList was called recently
    has_tasklist = "TaskList" in recent

    if not has_tasklist:
        tips = state.get("tips_this_session", 0)
        if tips < 5:
            state["tips_this_session"] = tips + 1
            save_state(session_id, state)
            print(
                "⚠️ TASK POLL GUARD: You're about to call TaskOutput without checking "
                "which tasks are active first. Call TaskList to verify running tasks, "
                "then TaskOutput only for active ones. This prevents polling stale/crashed tasks.",
                file=sys.stderr,
            )
        else:
            save_state(session_id, state)
        sys.exit(0)

    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
