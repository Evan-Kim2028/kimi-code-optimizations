#!/usr/bin/env python3
"""PreToolUse hook on Agent — nudge sequential dispatch toward parallel batching.

Observed in session logs: 817 Agent dispatches across 15 sessions, 100% solo
(histogram {1: 817}). The model rarely sends multiple Agent tool blocks in a
single assistant message even when tasks are independent.

Heuristic: keep a tiny state file with the last tool call type per session.
If the previous call was an Agent and the current call is also an Agent, and
the previous one was not backgrounded, emit a tip. Otherwise pass through.

Always exits 0 (non-blocking).
"""
import json
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

session_id = data.get("session_id", "unknown")
tool_input = data.get("tool_input", {}) or {}
state_path = STATE_DIR / f"parallel-agent-{session_id}.json"

prev = {}
if state_path.exists():
    try:
        prev = json.loads(state_path.read_text())
    except Exception:
        prev = {}

now = time.time()
prev_was_agent = prev.get("last_tool") == "Agent"
prev_age = now - prev.get("ts", 0)
prev_bg = bool(prev.get("run_in_background"))

# Update state for next call
state_path.write_text(json.dumps({
    "last_tool": "Agent",
    "ts": now,
    "run_in_background": bool(tool_input.get("run_in_background")),
}))

# Tip when this is the second sequential Agent within ~60s and the previous
# one wasn't backgrounded — strong signal of serial dispatch instead of
# sending both Agent tool_use blocks in the same assistant message.
if prev_was_agent and prev_age < 60 and not prev_bg:
    msg = (
        "PARALLEL GUARD: the previous tool call was also an Agent dispatch. "
        "If these subagents are independent, send them in a single assistant "
        "message with multiple Agent tool_use blocks (and set "
        "run_in_background=true on each) so they run concurrently. "
        "Sequential dispatch wastes wall-clock time and parent context."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))

sys.exit(0)
