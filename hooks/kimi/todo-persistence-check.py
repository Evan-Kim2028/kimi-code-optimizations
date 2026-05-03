#!/usr/bin/env python3
"""PostToolUse hook that detects SetTodoList resets and encourages incremental updates.

Problem: Models frequently rebuild the entire todo list from scratch mid-session,
destroying completion history and creating plan instability.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PostToolUse"
matcher = "SetTodoList"
command = "python3 /home/evan/.kimi/hooks/todo-persistence-check.py"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Threshold: if previous list had this many done items and new list has 0, warn
RESET_THRESHOLD = 2


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"todo-persistence-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {"last_done_count": 0, "last_total": 0, "tips": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"last_done_count": 0, "last_total": 0, "tips": 0}


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)

    if data.get("tool_name") != "SetTodoList":
        sys.exit(0)

    session_id = data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    todos = tool_input.get("todos")

    # Query mode (todos=None) — ignore
    if todos is None:
        sys.exit(0)

    state = load_state(session_id)

    done_count = sum(1 for t in todos if t.get("status") == "done")
    total_count = len(todos)
    in_progress = sum(1 for t in todos if t.get("status") == "in_progress")
    pending = sum(1 for t in todos if t.get("status") == "pending")

    # Detect reset: previously had done items, now has 0 done but >0 pending/in_progress
    prev_done = state.get("last_done_count", 0)
    if prev_done >= RESET_THRESHOLD and done_count == 0 and (pending + in_progress) > 0:
        if state.get("tips", 0) < 3:
            state["tips"] = state.get("tips", 0) + 1
            save_state(session_id, state)
            print(
                f"⚠️ TODO RESET: You just replaced a list with {prev_done} completed tasks "
                f"with a fresh list of {total_count} new items. This destroys completion history. "
                f"Prefer updating individual item statuses or adding new items to the existing list. "
                f"Use SetTodoList(todos=[...]) with the FULL list including previously done items, "
                f"or add items incrementally rather than rebuilding.",
                file=sys.stderr,
            )
        sys.exit(0)

    # Detect shrink-without-done: list got smaller but done count didn't increase
    # This might indicate dropping tasks silently
    prev_total = state.get("last_total", 0)
    if prev_total > total_count + 2 and done_count == prev_done:
        if state.get("tips", 0) < 3:
            state["tips"] = state.get("tips", 0) + 1
            save_state(session_id, state)
            print(
                f"⚠️ TODO SHRINK: Your todo list shrank from {prev_total} to {total_count} items "
                f"without any new completions. Did you drop tasks? "
                f"If tasks were completed, mark them 'done'. If merged, keep the superset.",
                file=sys.stderr,
            )
        sys.exit(0)

    # Update state
    state["last_done_count"] = done_count
    state["last_total"] = total_count
    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
