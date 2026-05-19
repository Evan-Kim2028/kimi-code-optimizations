#!/usr/bin/env python3
"""PreToolUse hook on Agent — parallel-batch enforcement.

History:
  v1 (Apr 2026): polite tip on the second sequential Agent call. Result:
    21 fires, 0 behavioral change.
  v2 (Apr 2026): plan-time nudge on the first Agent call when the prompt
    showed multi-step shape. Result over 24h: 19 sessions with hook fires,
    histogram of Agent-blocks-per-message stayed {1: 28} (0% parallel).
  v3 (this version, May 2026): keep the v2 plan-time tip, but ESCALATE to
    exit-2 BLOCKING when the model issues a second solo Agent dispatch in
    a row with no user turn between — and the most-recent two are both
    cheap discovery types (Explore / general-purpose). At that point the
    polite path has demonstrably failed and the only remaining gradient
    step the model feels is a refused tool call.

Detection of "sequential solo" uses the transcript file when available
(authoritative — sees the assistant message structure) and falls back to
the in-memory state file otherwise.
"""
import json
import os
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
transcript_path = data.get("transcript_path") or ""
tool_input = data.get("tool_input", {}) or {}
prompt = (tool_input.get("prompt") or "")
description = (tool_input.get("description") or "")
subagent_type = (tool_input.get("subagent_type") or "").lower()
combined = f"{description}\n{prompt}"
combined_lc = combined.lower()

state_path = STATE_DIR / f"parallel-agent-{session_id}.json"
prev: dict = {}
if state_path.exists():
    try:
        prev = json.loads(state_path.read_text())
    except Exception:
        prev = {}

now = time.time()
prev_was_agent = prev.get("last_tool") == "Agent"
prev_age = now - prev.get("ts", 0)
prev_bg = bool(prev.get("run_in_background"))
prev_subagent = (prev.get("subagent_type") or "").lower()
prev_warned_plan = bool(prev.get("warned_plan"))
prev_blocked_count = int(prev.get("blocked_count", 0))


def emit(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))


def save(extra: dict | None = None) -> None:
    s = {
        "last_tool": "Agent",
        "ts": now,
        "run_in_background": bool(tool_input.get("run_in_background")),
        "subagent_type": subagent_type,
        "warned_plan": prev_warned_plan,
        "blocked_count": prev_blocked_count,
    }
    if extra:
        s.update(extra)
    state_path.write_text(json.dumps(s))


def transcript_says_solo_consecutive() -> bool:
    """True iff the previous assistant message had exactly one Agent tool_use
    AND no user turn (real text, not tool_result) has happened since.

    Authoritative check — the in-memory state can't distinguish a parallel
    sibling (same message, ms apart) from a true sequential dispatch.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return False
    try:
        lines = Path(transcript_path).read_text().splitlines()
    except Exception:
        return False
    last_assistant_agents = None  # count of Agent blocks in most recent assistant msg
    user_text_since = False
    for line in lines:
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            content = (ev.get("message") or {}).get("content") or []
            n_agents = sum(
                1 for c in content
                if isinstance(c, dict)
                and c.get("type") == "tool_use"
                and c.get("name") == "Agent"
            )
            if n_agents > 0:
                last_assistant_agents = n_agents
                user_text_since = False
        elif t == "user":
            content = (ev.get("message") or {}).get("content") or []
            is_real_user = isinstance(content, str) or (
                isinstance(content, list)
                and any(isinstance(c, dict) and c.get("type") == "text" for c in content)
            )
            if is_real_user:
                user_text_since = True
    return (last_assistant_agents == 1) and not user_text_since


# ── Signal detection (plan-time, v2 carry-over) ─────────────────────────────

NUMBERED = re.search(
    r"(?m)(?:^|\n)\s*(?:step\s*)?[1-9][\.\)]\s+\S",
    combined,
)
multi_numbered = NUMBERED and len(re.findall(
    r"(?m)(?:^|\n)\s*(?:step\s*)?[1-9][\.\)]\s+\S", combined
)) >= 2

SEQUENCERS = re.search(
    r"\b(first[, ]+.*\bthen\b|after that|once .* (?:is )?done|"
    r"step\s*1\b.*step\s*2\b|then,? (?:also |next |)?(?:investigate|check|"
    r"look|search|find|review|audit|grep|run|verify))",
    combined_lc,
    re.DOTALL,
)

MULTI_TARGET = re.search(
    r"\b(investigate|check|review|audit|examine|analy[sz]e|look at|inspect|"
    r"search|find|locate|grep|enumerate)\b[^.\n]{0,200}\band\b[^.\n]{0,200}"
    r"\b(?:also\s+)?(?:investigate|check|review|audit|examine|analy[sz]e|"
    r"look at|inspect|search|find|locate|grep|enumerate|then)?\b",
    combined_lc,
)

bullets = re.findall(r"(?m)^\s*[-*]\s+(\S+)", combined)
multi_bullet = len(bullets) >= 3

HEAVY = re.search(
    r"\b(threat[- ]?model|architect this|deep[- ]?dive|root[- ]?cause|"
    r"end[- ]?to[- ]?end review|comprehensive audit|full security review)\b",
    combined_lc,
)

plan_signal = (
    not HEAVY
    and (multi_numbered or SEQUENCERS or MULTI_TARGET or multi_bullet)
)

# ── v3 BLOCKING path ────────────────────────────────────────────────────────

# Cheap-discovery subagent classes are the most clear-cut parallel batches.
# Implementation/heavy work is more likely to actually depend on the prior
# step's findings — don't block those.
CHEAP_TYPES = {"explore", "general-purpose", "default", ""}
both_cheap = (subagent_type in CHEAP_TYPES) and (prev_subagent in CHEAP_TYPES)

# Authoritative same-conversation-turn check from transcript; in-memory state
# is the fallback (and may misfire on true parallel siblings, so we require
# the transcript to confirm before BLOCKING).
solo_consec_confirmed = transcript_says_solo_consecutive()
solo_consec_inferred = prev_was_agent and prev_age < 600

if both_cheap and solo_consec_confirmed and prev_blocked_count < 2:
    save({"blocked_count": prev_blocked_count + 1, "warned_plan": True})
    print(
        "PARALLEL BATCH REQUIRED: this is the second consecutive solo "
        f"Agent dispatch ({prev_subagent or 'agent'} → {subagent_type or 'agent'}) "
        "with no user turn between, and both are cheap discovery types. "
        "If these dispatches are independent, REISSUE BOTH (and any "
        "remaining siblings) as MULTIPLE Agent tool_use blocks in a "
        "SINGLE assistant message — they will run concurrently. Only "
        "chain sequentially when this dispatch genuinely needs the prior "
        "dispatch's output. Set run_in_background=true on long-running "
        "ones. (This block fires at most twice per session; after that the "
        "hook reverts to a soft tip so you are never deadlocked.)",
        file=sys.stderr,
    )
    sys.exit(2)

# ── Soft-tip paths (plan signal, sequential backstop) ───────────────────────

if plan_signal and not prev_warned_plan:
    save({"warned_plan": True})
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
elif solo_consec_inferred and not prev_bg:
    save()
    emit(
        "PARALLEL GUARD (backstop): the previous Agent dispatch was also "
        "foreground and recent. If this dispatch does not depend on the "
        "previous one's result, you should have issued both Agent blocks "
        "in the SAME assistant message (parallel batch) instead of "
        "sequentially. For the next batch of independent dispatches, send "
        "them together with run_in_background=true."
    )
else:
    save()

sys.exit(0)
