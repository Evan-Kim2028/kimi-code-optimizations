#!/usr/bin/env python3
"""UserPromptSubmit hook — push parallel fan-out at PROMPT time on weaker lanes.

Why this hook exists:
  - parallel-agent-guard.py (PreToolUse on Agent) fires AFTER the model has
    already chosen to dispatch a single Agent. It can only nudge or block
    on the SECOND call. By then the wall-clock cost is already partly paid.
  - For lanes where the per-call IQ is lower (claude-kimi, claude-glm, or a
    Claude session with effortLevel != "high"), the right move is to fan
    out HARDER, not less. More small heads beat one weak head.

What this does:
  - Reads the user's prompt at submit time.
  - If the active provider is kimi or zai, OR settings.json shows a
    non-high effortLevel, AND the prompt has plan-shape signals
    (numbered steps, multi-target verbs, "and ... and", >=3 bullets),
    inject a hookSpecificOutput.additionalContext hint telling the model
    to decompose into MULTIPLE Agent tool_use blocks in ONE assistant
    message rather than soloing the work in the parent context.

Always exits 0 (non-blocking — UserPromptSubmit hooks should never block
the user's typing).
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _provider import detect_provider, provider_label

SETTINGS_PATHS = [
    Path.home() / ".claude" / "settings.local.json",
    Path.home() / ".claude" / "settings.json",
]


def read_effort_level() -> str:
    for p in SETTINGS_PATHS:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        lvl = data.get("effortLevel")
        if lvl:
            return str(lvl).lower()
    return "high"  # default for unset


try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)

prompt = (payload.get("prompt") or "")
prompt_lc = prompt.lower()

# Cheap exit: too short to be a multi-step plan worth fanning out.
if len(prompt) < 80:
    sys.exit(0)

provider = detect_provider()
effort = read_effort_level()
is_weaker_lane = provider in ("kimi", "zai") or effort in ("low", "medium")
if not is_weaker_lane:
    sys.exit(0)

# Plan-shape detection (mirrors parallel-agent-guard.py — kept in sync).
NUMBERED = re.findall(r"(?m)(?:^|\n)\s*(?:step\s*)?[1-9][\.\)]\s+\S", prompt)
multi_numbered = len(NUMBERED) >= 2

SEQUENCERS = re.search(
    r"\b(first[, ]+.*\bthen\b|after that|then,? (?:also |next |)?(?:investigate|check|look|search|find|review|audit|verify))",
    prompt_lc, re.DOTALL,
)

MULTI_TARGET = re.search(
    r"\b(investigate|check|review|audit|examine|analy[sz]e|look at|inspect|"
    r"search|find|locate|grep|enumerate|update|fix|refactor|sweep|scan)\b"
    r"[^.\n]{0,200}\band\b[^.\n]{0,200}",
    prompt_lc,
)

bullets = re.findall(r"(?m)^\s*[-*]\s+\S", prompt)
multi_bullet = len(bullets) >= 3

if not (multi_numbered or SEQUENCERS or MULTI_TARGET or multi_bullet):
    sys.exit(0)

# Build the nudge.
why = []
if provider in ("kimi", "zai"):
    why.append(f"this session is routed to {provider_label(provider)}")
if effort in ("low", "medium"):
    why.append(f"effortLevel is {effort!r}")
why_str = " and ".join(why) if why else "this lane benefits from fan-out"

msg = (
    f"FAN-OUT NUDGE: {why_str}. Per-call reasoning here is weaker than a "
    "full-effort Opus run, so the right strategy is to DECOMPOSE this "
    "prompt across MULTIPLE parallel Agent tool_use blocks issued in a "
    "SINGLE assistant message — many small focused heads beat one weak "
    "head soloing it in the parent context. Use subagent_type=\"Explore\" "
    "for discovery legs and subagent_type=\"general-purpose\" for "
    "implementation legs. Set run_in_background=true on long-running "
    "ones. Only keep work in the parent context when it is genuinely "
    "sequential (a later step needs an earlier step's output)."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": msg,
    }
}))
sys.exit(0)
