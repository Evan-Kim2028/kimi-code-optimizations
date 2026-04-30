#!/usr/bin/env python3
"""PostToolUse hook that guards against excessive same-turn file re-reads.

Problem: Models re-read the same files multiple times within a single turn,
burning context tokens unnecessarily. The session-level re-read-guard.py handles
across-session re-reads; this catches intra-turn storms.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PostToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/re-read-turn-guard.py"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Warn after this many reads of the same file in the current turn
REREAD_THRESHOLD = 3


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"turn-reads-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {"turn_reads": {}, "last_turn_tools": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"turn_reads": {}, "last_turn_tools": 0}


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

    if not path_str:
        sys.exit(0)

    state = load_state(session_id)
    turn_reads = state.get("turn_reads", {})

    # Approximate turn boundary: if we've seen many non-ReadFile tools since last ReadFile,
    # assume new turn. Simpler heuristic: reset on every N tools.
    # Actually, we can approximate using tool_call_id or just count calls.
    # Better: use a simple call counter and reset every time we see a non-ReadFile tool.
    # But as a PostToolUse hook on ReadFile, we only fire on ReadFile.
    # We approximate turn by tracking the "last non-read tool" via a separate small state file
    # that other hooks could update... but that's complex.
    #
    # Simpler approach: track reads in a sliding window of N recent ReadFile calls.
    # If the same file appears >threshold times in the window, warn.

    # Use a sliding window approach
    reads_list = turn_reads.get("__recent__", [])
    reads_list.append({"path": path_str, "offset": line_offset})
    reads_list = reads_list[-20:]  # sliding window of last 20 ReadFile calls
    turn_reads["__recent__"] = reads_list

    # Count occurrences of this exact path in the window
    path_counts = {}
    for r in reads_list:
        p = r["path"]
        path_counts[p] = path_counts.get(p, 0) + 1

    count = path_counts.get(path_str, 0)

    if count == REREAD_THRESHOLD:
        # Only warn once per threshold crossing
        print(
            f"⚠️ TURN REREAD GUARD: You've read '{path_str}' {count} times in recent calls. "
            f"Are you re-reading because you forgot the content? "
            f"Store key findings in your reasoning or use line_offset for targeted sections. "
            f"Repeated full-file reads waste context.",
            file=sys.stderr,
        )

    state["turn_reads"] = turn_reads
    save_state(session_id, state)
    sys.exit(0)


if __name__ == "__main__":
    main()
