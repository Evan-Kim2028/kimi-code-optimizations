#!/usr/bin/env python3
"""PreToolUse hook on Agent — suggest haiku/sonnet/opus based on task shape.

Claude Code's Agent tool accepts an optional `model` override
("haiku" | "sonnet" | "opus"). When omitted, the subagent inherits the
parent's model (often Opus 4.7), which is overkill for cheap discovery.

This hook does NOT block. It emits a coaching tip when the dispatch looks
like it would be served better by a smaller model — or stays silent when
Opus is the right choice.

Tips are emitted as JSON hookSpecificOutput.additionalContext on stdout
so Claude Code injects them into the model's context.

Triage:
  - `model` already set         → silent (respect explicit choice)
  - Explore subagent OR short
    prompt with discovery verbs → suggest model="haiku"
  - Implementation/synthesis    → suggest model="sonnet"
  - Review / architecture /
    security / design audit     → silent (let Opus default stand)
  - Default                     → suggest model="sonnet" as the middle path

The point is to make Opus *consciously chosen*, not *accidentally inherited*.
"""
import json
import re
import sys


def emit(msg: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        }
    }))


try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool_input = data.get("tool_input", {}) or {}

# Respect explicit model choice — silent.
if tool_input.get("model"):
    sys.exit(0)

subagent_type = (tool_input.get("subagent_type") or "").lower()
prompt = tool_input.get("prompt") or ""
description = tool_input.get("description") or ""
combined = f"{description}\n{prompt}".lower()
plen = len(prompt)

DISCOVERY_VERBS = (
    r"\b(find|locate|grep|search for|list|which files?|where is|where are|"
    r"look for|enumerate|count|identify (?:the |all )?(?:files?|usages?|"
    r"references?|callers?|imports?))\b"
)
HEAVY_VERBS = (
    r"\b(review|audit|architect|design|threat[- ]?model|security|"
    r"refactor strategy|migrate|cross[- ]?reference|analy[sz]e trade[- ]?offs?)\b"
)
IMPL_VERBS = (
    r"\b(implement|write|edit|fix|build|add|update|port|refactor|"
    r"rename|extract|inline|wire up|hook up)\b"
)

is_discovery = (
    subagent_type == "explore"
    or (plen < 600 and re.search(DISCOVERY_VERBS, combined))
)
is_heavy = bool(re.search(HEAVY_VERBS, combined)) or "code-reviewer" in subagent_type
is_impl = bool(re.search(IMPL_VERBS, combined))

if is_discovery and not is_heavy:
    emit(
        'COST ROUTER: this looks like a discovery/lookup task. Consider passing '
        '`model: "haiku"` to the Agent tool — Haiku 4.5 is ~5-10x cheaper than '
        "Opus and handles read-only search, file location, and grep-style work "
        "well. Reserve Opus for synthesis, review, and architecture."
    )
elif is_heavy:
    # Silent: Opus is the right default for review/architecture/security.
    pass
elif is_impl:
    emit(
        'COST ROUTER: this looks like a focused implementation task. Consider '
        '`model: "sonnet"` — Sonnet 4.6 is meaningfully cheaper than Opus and '
        "strong at scoped code edits. Promote to Opus only if the task needs "
        "cross-file reasoning, tricky correctness arguments, or design choices."
    )
else:
    # Generic dispatch — nudge toward Sonnet as the middle path.
    emit(
        'COST ROUTER: model is unset, so this subagent will inherit the parent '
        "model (Opus). If the task is well-scoped, pass "
        '`model: "sonnet"` (or `"haiku"` for pure discovery). Choose Opus '
        "consciously when you need it."
    )

sys.exit(0)
