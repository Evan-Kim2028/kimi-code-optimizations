#!/usr/bin/env python3
"""PostToolUse hook that nudges toward subagent swarm patterns — v2.

Key improvement over v1: tracks manual work SINCE LAST AGENT, not just total.
A model that dispatches 4 agents early then grinds manually for 70+ calls
is the main failure mode. v1 missed this because agent_calls > 0.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /path/to/kimi-code-optimizations/hooks/kimi/swarm-nudge-v2.py"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Thresholds
MANUAL_SINCE_AGENT_THRESHOLD = 8   # manual calls since last agent before tip
RATIO_THRESHOLD = 5.0              # manual:agent ratio before tip
TOTAL_MANUAL_THRESHOLD = 4         # total manual calls before first tip (even if no agents yet)
COOLDOWN_CALLS = 15                # calls before same tip can fire again


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"swarm-tracker-v2-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {
            "total_calls": 0,
            "agent_calls": 0,
            "manual_calls": 0,
            "manual_since_last_agent": 0,
            "last_tip_call": 0,
            "tips_this_session": 0,
        }
    try:
        return json.loads(path.read_text())
    except Exception:
        return {
            "total_calls": 0,
            "agent_calls": 0,
            "manual_calls": 0,
            "manual_since_last_agent": 0,
            "last_tip_call": 0,
            "tips_this_session": 0,
        }


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")

    if event != "PostToolUse" or not session_id:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_output = str(data.get("tool_output", ""))

    # Don't count blocked calls or errors
    if tool_output.startswith("ERROR") or tool_output.startswith("WARNING"):
        sys.exit(0)

    state = load_state(session_id)
    state["total_calls"] += 1

    # Track manual vs agent work
    is_manual = tool_name in ("ReadFile", "Grep", "Shell")
    is_agent = tool_name == "Agent"

    if is_manual:
        state["manual_calls"] += 1
        state["manual_since_last_agent"] += 1
    elif is_agent:
        state["agent_calls"] += 1
        state["manual_since_last_agent"] = 0

    tips = []
    calls_since_last_tip = state["total_calls"] - state["last_tip_call"]
    # First tip in a session fires immediately; subsequent tips need cooldown
    can_tip = (state["last_tip_call"] == 0) or (calls_since_last_tip >= COOLDOWN_CALLS)

    # Tip 1: Heavy manual work since last agent dispatch
    # This catches the "dispatched agents early, then grinded manually" pattern
    if (
        can_tip
        and state["manual_since_last_agent"] >= MANUAL_SINCE_AGENT_THRESHOLD
        and state["agent_calls"] > 0
    ):
        tips.append(
            f"TIP: You've made {state['manual_since_last_agent']}+ manual calls "
            f"(ReadFile/Grep/Shell) since your last agent dispatch. "
            f"Could this discovery/editing be delegated to parallel explore/coder agents? "
            f"Dispatch agents with run_in_background=True, then poll with TaskList/TaskOutput."
        )
        state["last_tip_call"] = state["total_calls"]
        state["tips_this_session"] += 1

    # Tip 2: High manual:agent ratio overall
    elif (
        can_tip
        and state["agent_calls"] > 0
        and state["manual_calls"] / max(state["agent_calls"], 1) >= RATIO_THRESHOLD
    ):
        ratio = state["manual_calls"] / state["agent_calls"]
        tips.append(
            f"TIP: Manual:agent ratio is {ratio:.1f}:1 ({state['manual_calls']} manual vs "
            f"{state['agent_calls']} agents). You're doing too much work yourself. "
            f"Default to parallel subagents for any subtask needing >2 tool calls."
        )
        state["last_tip_call"] = state["total_calls"]
        state["tips_this_session"] += 1

    # Tip 3: Early manual work with no agents yet (original v1 behavior, lowered threshold)
    elif (
        can_tip
        and state["agent_calls"] == 0
        and state["manual_calls"] >= TOTAL_MANUAL_THRESHOLD
    ):
        tips.append(
            f"TIP: You've made {state['manual_calls']}+ manual discovery/editing calls with no agents. "
            f"Dispatch parallel explore agents to map the codebase instead. "
            f"Research is work too — delegate it."
        )
        state["last_tip_call"] = state["total_calls"]
        state["tips_this_session"] += 1

    # Tip 4: Complex multi-step Shell with no agents in recent history
    if tool_name == "Shell" and state["manual_since_last_agent"] >= 4:
        cmd = ""
        if isinstance(tool_input, dict):
            cmd = tool_input.get("command", "")
        elif isinstance(tool_input, str):
            cmd = tool_input

        is_complex = (
            cmd.count("\n") > 2
            or cmd.count("&&") > 1
            or cmd.count(";") > 1
            or len(cmd) > 300
        )
        if is_complex and can_tip:
            tips.append(
                "TIP: Complex multi-step shell work with no recent agents. "
                "Could parts of this be parallelized via subagents? "
                "Example: one agent per directory or per concern."
            )
            state["last_tip_call"] = state["total_calls"]
            state["tips_this_session"] += 1

    save_state(session_id, state)

    if tips:
        print("\n".join(tips), file=sys.stderr)
        sys.exit(1)  # Warning only

    sys.exit(0)


if __name__ == "__main__":
    main()
