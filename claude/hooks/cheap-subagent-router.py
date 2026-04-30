#!/usr/bin/env python3
"""PreToolUse hook on Agent — suggest haiku/sonnet/opus + effort level.

Claude Code's Agent tool accepts two cost-relevant overrides:
  - `model`:  "haiku" | "sonnet" | "opus"
  - `effort`: "low" | "medium" | "high" | "xhigh" | "max"

When omitted, both inherit from the parent session (often Opus + medium),
which is overkill for cheap discovery. This hook does NOT block. It emits
a coaching tip when the dispatch looks like it would be served better by
a smaller model and/or lower effort — or stays silent when Opus is the
right choice.

Tips are emitted as JSON hookSpecificOutput.additionalContext on stdout
so Claude Code injects them into the model's context.

Triage:
  - both `model` and `effort` already set → silent (respect explicit choice)
  - Explore subagent OR short prompt with discovery verbs
       → suggest model="haiku", effort="low"
  - Implementation/synthesis
       → suggest model="sonnet", effort="medium"
  - Review / architecture / security / design audit
       → silent (let Opus + inherited effort stand)
  - Default
       → suggest model="sonnet" (effort silent — let it inherit)

The point is to make Opus and high effort *consciously chosen*, not
*accidentally inherited*.
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
model_set = bool(tool_input.get("model"))
effort_set = bool(tool_input.get("effort"))

# Both already chosen — fully respect explicit configuration.
if model_set and effort_set:
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


def build_tip(model_suggestion: str | None, effort_suggestion: str | None,
              rationale: str) -> str | None:
    """Build a tip suggesting only the unset parameter(s)."""
    parts: list[str] = []
    if model_suggestion and not model_set:
        parts.append(f'`model: "{model_suggestion}"`')
    if effort_suggestion and not effort_set:
        parts.append(f'`effort: "{effort_suggestion}"`')
    if not parts:
        return None
    joined = " + ".join(parts)
    return f"COST ROUTER: {rationale} Consider passing {joined} to the Agent tool."


tip: str | None = None

if is_heavy:
    # Silent: Opus + inherited effort is the right default for review/architecture/security.
    pass
elif is_discovery and not is_heavy:
    tip = build_tip(
        "haiku", "low",
        "this looks like a discovery/lookup task — read-only search, file location, "
        "grep-style work. Haiku 4.5 with low effort is ~10x cheaper than Opus and "
        "handles this class of task well.",
    )
elif is_impl:
    tip = build_tip(
        "sonnet", "medium",
        "this looks like a focused implementation task. Sonnet 4.6 with medium "
        "effort is meaningfully cheaper than Opus and strong at scoped code edits. "
        "Promote to Opus only if the task needs cross-file reasoning, tricky "
        "correctness arguments, or design choices.",
    )
else:
    # Generic dispatch — nudge model toward Sonnet; leave effort to inherit.
    tip = build_tip(
        "sonnet", None,
        "model is unset, so this subagent will inherit the parent model (Opus). "
        "If the task is well-scoped, pick a smaller model consciously.",
    )

if tip:
    emit(tip)

sys.exit(0)
