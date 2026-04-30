#!/usr/bin/env python3
"""PreToolUse hook on Agent — nudge parallel batching at PLAN time.

Old version fired on the second sequential Agent call — too late, the model
had already committed to serial execution. Today's data: 21 fires, 0 behavior
change (agent-blocks-per-message stayed {1: 22}).

New approach: inspect the FIRST Agent dispatch and look for plan-shape
signals in the prompt that suggest the model is about to issue more
independent dispatches sequentially. Emit a nudge BEFORE the first call,
when the model is still choosing how to structure the work — and include
copy-pasteable framing ("issue these as parallel Agent blocks in one
message").

Always exits 0 (non-blocking).
"""
import json
import re
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
prompt = (tool_input.get("prompt") or "")
description = (tool_input.get("description") or "")
combined = f"{description}\n{prompt}"
combined_lc = combined.lower()
plen = len(prompt)

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
prev_warned_plan = bool(prev.get("warned_plan"))

# Persist for next call.
state_path.write_text(json.dumps({
    "last_tool": "Agent",
    "ts": now,
    "run_in_background": bool(tool_input.get("run_in_background")),
    "warned_plan": prev_warned_plan,  # carry forward; updated below if we warn
}))


def emit(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))


# ── Signal detection ────────────────────────────────────────────────────────

# Numbered/step-shaped plans inside the prompt.
NUMBERED = re.search(
    r"(?m)(?:^|\n)\s*(?:step\s*)?[1-9][\.\)]\s+\S",
    combined,
)
multi_numbered = NUMBERED and len(re.findall(
    r"(?m)(?:^|\n)\s*(?:step\s*)?[1-9][\.\)]\s+\S", combined
)) >= 2

# Sequencing words that imply "do this, then do that".
SEQUENCERS = re.search(
    r"\b(first[, ]+.*\bthen\b|after that|once .* (?:is )?done|"
    r"step\s*1\b.*step\s*2\b|then,? (?:also |next |)?(?:investigate|check|"
    r"look|search|find|review|audit|grep|run|verify))",
    combined_lc,
    re.DOTALL,
)

# Conjunctive multi-target asks ("investigate X and Y", "find A and B and C").
MULTI_TARGET = re.search(
    r"\b(investigate|check|review|audit|examine|analy[sz]e|look at|inspect|"
    r"search|find|locate|grep|enumerate)\b[^.\n]{0,200}\band\b[^.\n]{0,200}"
    r"\b(?:also\s+)?(?:investigate|check|review|audit|examine|analy[sz]e|"
    r"look at|inspect|search|find|locate|grep|enumerate|then)?\b",
    combined_lc,
)

# Multiple bullet points with verbs at the start (parallel structure).
bullets = re.findall(r"(?m)^\s*[-*]\s+(\S+)", combined)
multi_bullet = len(bullets) >= 3

# Heavy single-task signal — suppress the nudge for review/architecture/etc.
HEAVY = re.search(
    r"\b(threat[- ]?model|architect this|deep[- ]?dive|root[- ]?cause|"
    r"end[- ]?to[- ]?end review|comprehensive audit|full security review)\b",
    combined_lc,
)

# Sequential-mode is a STRONG signal even if no plan keywords matched: the
# model is dispatching its second Agent within 60s and the prior wasn't
# backgrounded. Keep the original detector as a backstop.
sequential_backstop = (
    prev_was_agent and prev_age < 60 and not prev_bg
)

plan_signal = (
    not HEAVY
    and (multi_numbered or SEQUENCERS or MULTI_TARGET or multi_bullet)
)

# Avoid double-warning the same session for plan signals (sequential backstop
# always fires — that's a different problem worth flagging every time).
if plan_signal and not prev_warned_plan:
    state = json.loads(state_path.read_text())
    state["warned_plan"] = True
    state_path.write_text(json.dumps(state))

    emit(
        "PARALLELIZATION CHECK: this prompt describes multiple distinct "
        "investigations / steps. If the steps are independent (no step "
        "needs the output of an earlier step), issue them as MULTIPLE "
        "Agent tool_use blocks in a SINGLE assistant message — they will "
        "run concurrently. Set run_in_background=true on long-running "
        "ones so you can keep working while they finish. Only chain "
        "sequentially when a later step genuinely depends on an earlier "
        "step's result. If the steps in this prompt ARE independent, "
        "cancel this dispatch and re-issue all of them as a parallel batch."
    )
elif sequential_backstop:
    emit(
        "PARALLEL GUARD (backstop): the previous Agent dispatch was also "
        "foreground and very recent. If this dispatch does not depend on "
        "the previous one's result, you should have issued both Agent "
        "blocks in the SAME assistant message (parallel batch) instead of "
        "sequentially. For the next batch of independent dispatches, send "
        "them together with run_in_background=true."
    )

sys.exit(0)
