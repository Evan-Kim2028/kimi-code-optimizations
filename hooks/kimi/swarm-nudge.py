#!/usr/bin/env python3
"""PostToolUse hook that nudges toward subagent swarm patterns.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /path/to/kimi-code-optimizations/hooks/kimi/swarm-nudge.py"
timeout = 2

This hook tracks per-session tool usage and emits tips when the model
is doing complex work manually that could be better handled by parallel
explore/coder agents.
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Thresholds
DISCOVERY_THRESHOLD = 6     # ReadFile/Grep calls before suggesting explore agents
COMPLEXITY_THRESHOLD = 12   # Total tool calls before suggesting swarm decomposition
AGENT_SEQ_THRESHOLD = 3     # Sequential agent calls before suggesting background dispatch


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"swarm-tracker-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {
            "total_calls": 0,
            "agent_calls": 0,
            "discovery_calls": 0,
            "sequential_agents": 0,
            "last_agent_was_background": False,
            "tips_given": set(),
        }
    try:
        data = json.loads(path.read_text())
        data["tips_given"] = set(data.get("tips_given", []))
        return data
    except Exception:
        return {
            "total_calls": 0,
            "agent_calls": 0,
            "discovery_calls": 0,
            "sequential_agents": 0,
            "last_agent_was_background": False,
            "tips_given": set(),
        }


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    out = dict(state)
    out["tips_given"] = list(out["tips_given"])
    path.write_text(json.dumps(out, indent=2))


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

    tips = []

    # Track agent calls and whether they're backgrounded
    if tool_name == "Agent":
        state["agent_calls"] += 1
        args = tool_input if isinstance(tool_input, dict) else {}
        is_background = args.get("run_in_background", False)

        if is_background:
            state["sequential_agents"] = 0
            state["last_agent_was_background"] = True
        else:
            state["sequential_agents"] += 1
            state["last_agent_was_background"] = False

        if (
            state["sequential_agents"] >= AGENT_SEQ_THRESHOLD
            and "sequential_agents" not in state["tips_given"]
        ):
            tips.append(
                "TIP: You dispatched 3+ agents sequentially. "
                "Use run_in_background=true and poll them in parallel instead. "
                "Sequential agent dispatch wastes time when subtasks are independent."
            )
            state["tips_given"].add("sequential_agents")
    else:
        # Reset sequential agent counter on non-agent calls
        state["sequential_agents"] = 0

    # Track discovery work (manual exploration)
    if tool_name in ("ReadFile", "Grep"):
        state["discovery_calls"] += 1

    # Tip 1: Heavy manual discovery without agents
    if (
        state["discovery_calls"] >= DISCOVERY_THRESHOLD
        and state["agent_calls"] == 0
        and "heavy_discovery" not in state["tips_given"]
    ):
        tips.append(
            "TIP: You've made 6+ manual discovery calls (ReadFile/Grep) with no agents. "
            "Consider dispatching parallel explore agents to map the codebase instead. "
            "Let subagents do the discovery while you orchestrate."
        )
        state["tips_given"].add("heavy_discovery")

    # Tip 2: High overall complexity with minimal agent usage
    if (
        state["total_calls"] >= COMPLEXITY_THRESHOLD
        and state["agent_calls"] <= 1
        and "complexity" not in state["tips_given"]
    ):
        tips.append(
            "TIP: This task has 12+ tool calls with minimal agent usage. "
            "Could independent parts be delegated to parallel coder/explore agents? "
            "Swarm-first: if a subtask needs >2 tool calls, give it to a subagent."
        )
        state["tips_given"].add("complexity")

    # Tip 3: Complex Shell work without agents
    if tool_name == "Shell":
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
        if (
            is_complex
            and state["agent_calls"] == 0
            and "complex_shell" not in state["tips_given"]
        ):
            tips.append(
                "TIP: Complex multi-step shell work detected with no agents deployed. "
                "Could parts of this workflow be parallelized via subagents? "
                "Example: dispatch one agent per directory or per concern."
            )
            state["tips_given"].add("complex_shell")

    save_state(session_id, state)

    if tips:
        print("\n".join(tips), file=sys.stderr)
        sys.exit(1)  # Warning only

    sys.exit(0)


if __name__ == "__main__":
    main()
