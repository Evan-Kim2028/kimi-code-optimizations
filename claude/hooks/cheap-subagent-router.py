#!/usr/bin/env python3
"""PreToolUse hook on Agent — suggest haiku/sonnet/opus per dispatch.

Claude Code's Agent tool accepts a `model` override:
  "haiku" | "sonnet" | "opus"

When omitted, the subagent inherits the parent session's model (often Opus),
which is overkill for cheap discovery. This hook does NOT block. It emits a
coaching tip when the dispatch looks like it would be served better by a
smaller model — or stays silent when Opus is the right choice.

Tips are emitted as JSON hookSpecificOutput.additionalContext on stdout
so Claude Code injects them into the model's context.

Triage:
  - `model` already set → silent (respect explicit choice)
  - Explore subagent OR short prompt with discovery verbs
       → suggest model="haiku"
  - Implementation/synthesis
       → suggest model="sonnet"
  - Review / architecture / security / design audit
       → silent (let Opus stand)
  - Default
       → suggest model="sonnet"

The point is to make Opus a *conscious choice*, not an *inherited default*.

Note (2026-05-02): an earlier version of this hook also suggested an
`effort` parameter on the Agent tool. The Agent tool has no `effort`
parameter — `effortLevel` is a session-wide settings.json key, not a
per-dispatch arg. Suggesting it produced InputValidationError on the
first attempt and trained the model to ignore the COST ROUTER tip
entirely (0/28 explicit-model dispatches in 24h of production data).
The effort suggestions are gone.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _provider import detect_provider

# The haiku/sonnet/opus tiers and `effort` param are Anthropic-specific.
# Z.AI, Moonshot, and other Anthropic-compatible providers serve a single
# model id and ignore (or 404 on) tier names. Skip the coaching tip there.
if detect_provider() != "anthropic":
    sys.exit(0)


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
model_set = bool(tool_input.get("model"))

# Already chosen — fully respect explicit configuration.
if model_set:
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


def build_tip(model_suggestion: str, rationale: str) -> str:
    return (
        f"COST ROUTER: {rationale} Consider passing "
        f'`model: "{model_suggestion}"` to the Agent tool.'
    )


tip: str | None = None

if is_heavy:
    # Silent: Opus is the right default for review/architecture/security.
    pass
elif is_discovery and not is_heavy:
    tip = build_tip(
        "haiku",
        "this looks like a discovery/lookup task — read-only search, file "
        "location, grep-style work. Haiku 4.5 is ~10x cheaper than Opus and "
        "handles this class of task well.",
    )
elif is_impl:
    tip = build_tip(
        "sonnet",
        "this looks like a focused implementation task. Sonnet 4.6 is "
        "meaningfully cheaper than Opus and strong at scoped code edits. "
        "Promote to Opus only if the task needs cross-file reasoning, tricky "
        "correctness arguments, or design choices.",
    )
else:
    tip = build_tip(
        "sonnet",
        "model is unset, so this subagent will inherit the parent model "
        "(Opus). If the task is well-scoped, pick a smaller model consciously.",
    )

if tip:
    emit(tip)

sys.exit(0)
