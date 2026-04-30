#!/usr/bin/env python3
"""PreToolUse hook that intercepts sequential Agent dispatch and nudges toward parallel background dispatch.

v2 improvements over v1:
- Timestamp-based same-turn detection (avoids false positives when agents are
  legitimately dispatched in parallel within the same turn)
- Stronger messaging that explicitly recommends batching multiple agents
- Tracks consecutive sequential agent count for escalating warnings

Add to ~/.kimi/config.toml (replaces parallel-agent-guard.py):

[[hooks]]
event = "PreToolUse"
matcher = "Agent"
command = "python3 /home/evan/.kimi/hooks/parallel-agent-guard-v2.py"
timeout = 2
"""
import json
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# If two Agent calls arrive within this window (seconds), assume same turn / parallel
SAME_TURN_WINDOW_S = 3.0


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"parallel-agent-guard-v2-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {
            "last_tool": None,
            "last_agent_time": 0,
            "last_agent_bg": False,
            "consecutive_sequential": 0,
        }
    try:
        return json.loads(path.read_text())
    except Exception:
        return {
            "last_tool": None,
            "last_agent_time": 0,
            "last_agent_bg": False,
            "consecutive_sequential": 0,
        }


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
    now = time.time()

    # If this agent is already background, we're good
    if run_in_background:
        state["last_tool"] = "Agent"
        state["last_agent_time"] = now
        state["last_agent_bg"] = True
        state["consecutive_sequential"] = 0
        save_state(session_id, state)
        sys.exit(0)

    # If the last tool was also Agent, check if it was within the same-turn window
    if state.get("last_tool") == "Agent" and not state.get("last_agent_bg", False):
        time_since_last = now - state.get("last_agent_time", 0)

        if time_since_last <= SAME_TURN_WINDOW_S:
            # Likely same turn — allow without warning, but still record
            state["last_tool"] = "Agent"
            state["last_agent_time"] = now
            state["last_agent_bg"] = False
            save_state(session_id, state)
            sys.exit(0)

        # Sequential across turns — this is the bad pattern
        state["consecutive_sequential"] = state.get("consecutive_sequential", 0) + 1
        seq_count = state["consecutive_sequential"]

        if seq_count >= 3:
            msg = (
                f"⚠️ PARALLEL GUARD (urgent): You've dispatched {seq_count} agents sequentially "
                f"in a row. This is extremely inefficient. "
                f"BATCH them: put multiple Agent blocks in ONE assistant message, "
                f"each with run_in_background=true. Then poll results with TaskList."
            )
        elif seq_count == 2:
            msg = (
                "⚠️ PARALLEL GUARD: Second sequential agent dispatch detected. "
                "If these agents are independent, dispatch them TOGETHER in one turn "
                "with run_in_background=true. Example:\n"
                "  Agent(run_in_background=True, description='Fix auth')\n"
                "  Agent(run_in_background=True, description='Fix billing')"
            )
        else:
            msg = (
                "⚠️ PARALLEL GUARD: You're about to dispatch an agent sequentially. "
                "If this agent is independent of the previous one, set run_in_background=true "
                "and dispatch them together in the same turn. "
                "Sequential agent dispatch wastes wall-clock time and keeps both agent prompts "
                "in parent context longer than necessary."
            )

        print(msg, file=sys.stderr)

    # Update state
    state["last_tool"] = "Agent"
    state["last_agent_time"] = now
    state["last_agent_bg"] = False
    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
