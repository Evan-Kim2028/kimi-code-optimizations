#!/usr/bin/env python3
"""PreToolUse hook that intercepts sequential Agent dispatch and nudges toward parallel background dispatch.

Problem: Models dispatch Agent calls sequentially when they should be parallel.
run_in_background=true saves wall-clock time and keeps the parent context lean.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "Agent"
command = "python3 /home/evan/.kimi/hooks/parallel-agent-guard.py"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"parallel-agent-guard-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {"last_tool": None, "last_agent_time": 0, "last_agent_bg": False}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"last_tool": None, "last_agent_time": 0, "last_agent_bg": False}


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)

    if data.get("tool_name") != "Agent":
        sys.exit(0)

    session_id = data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    run_in_background = tool_input.get("run_in_background", False)

    state = load_state(session_id)

    # If this agent is already background, we're good — record and exit
    if run_in_background:
        state["last_tool"] = "Agent"
        state["last_agent_bg"] = True
        save_state(session_id, state)
        sys.exit(0)

    # If the last tool was also Agent and it was NOT background, suggest parallel dispatch
    if state.get("last_tool") == "Agent" and not state.get("last_agent_bg", False):
        print(
            "⚠️ PARALLEL GUARD: You're about to dispatch an agent sequentially. "
            "If this agent is independent of the previous one, set run_in_background=true "
            "and dispatch them together in the same turn. "
            "Sequential agent dispatch wastes wall-clock time and keeps both agent prompts "
            "in parent context longer than necessary.",
            file=sys.stderr,
        )

    # Update state
    state["last_tool"] = "Agent"
    state["last_agent_bg"] = False
    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
