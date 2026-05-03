#!/usr/bin/env python3
"""PreToolUse hook that intercepts manual discovery and suggests agents BEFORE the call.

Unlike PostToolUse hooks (which react after waste happens), this hook
proactively asks "should this be an agent?" before each ReadFile/Grep/Shell
call once manual work streaks get long.

Add to ~/.kimi/config.toml ABOVE the other hooks (order matters):

[[hooks]]
event = "PreToolUse"
command = "python3 /path/to/kimi-code-optimizations/hooks/kimi/discovery-intercept.py"
matcher = "ReadFile|Grep|Shell"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

STREAK_THRESHOLD = 4   # manual calls in a row before we start intercepting
AGENT_SUGGEST_COOLDOWN = 3  # only suggest every Nth intercepted call


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"discovery-intercept-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {"manual_streak": 0, "intercept_count": 0, "agents_used": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"manual_streak": 0, "intercept_count": 0, "agents_used": 0}


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")

    if event != "PreToolUse" or not session_id:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    state = load_state(session_id)

    # Reset streak on agent calls
    if tool_name == "Agent":
        state["agents_used"] += 1
        state["manual_streak"] = 0
        save_state(session_id, state)
        sys.exit(0)

    # Only intercept ReadFile, Grep, Shell
    if tool_name not in ("ReadFile", "Grep", "Shell"):
        save_state(session_id, state)
        sys.exit(0)

    state["manual_streak"] += 1

    # Check if we've crossed the threshold
    if state["manual_streak"] >= STREAK_THRESHOLD:
        state["intercept_count"] += 1

        # Fire on the FIRST crossing of the threshold, then every Nth after
        if (
            state["intercept_count"] == 1
            or state["intercept_count"] % AGENT_SUGGEST_COOLDOWN == 0
        ):
            # Build contextual message based on tool type
            if tool_name == "ReadFile":
                path = tool_input.get("path", "")
                msg = (
                    f"INTERCEPT: You're about to ReadFile '{path}' during a "
                    f"{state['manual_streak']}-call manual work streak. "
                    f"Could this (and related files) be handled by a parallel "
                    f"explore/coder agent instead? If this is part of a multi-file "
                    f"task, delegate it. If it's a single quick lookup, proceed."
                )
            elif tool_name == "Grep":
                pattern = tool_input.get("pattern", "")[:40]
                msg = (
                    f"INTERCEPT: You're about to Grep '{pattern}...' during a "
                    f"{state['manual_streak']}-call manual streak. "
                    f"For multi-concern research, dispatch parallel explore agents "
                    f"instead of sequential Greps."
                )
            elif tool_name == "Shell":
                cmd = tool_input.get("command", "")[:60]
                msg = (
                    f"INTERCEPT: You're about to Shell '{cmd}...' during a "
                    f"{state['manual_streak']}-call manual streak. "
                    f"Complex shell work often parallelizes well into subagents."
                )
            else:
                msg = ""

            save_state(session_id, state)
            if msg:
                print(msg, file=sys.stderr)
                # Exit 0 = allow the call, but the model sees the tip
                sys.exit(0)

    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
