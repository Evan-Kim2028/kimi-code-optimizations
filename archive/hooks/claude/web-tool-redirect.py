#!/usr/bin/env python3
"""PreToolUse hook on WebFetch / WebSearch.

WebFetch and WebSearch are Anthropic-server-side tools — the actual fetch
and search execute inside Anthropic's API, not in Claude Code's harness.
When the session is routed through a third-party Anthropic-compatible
endpoint (Z.AI, Moonshot, AtlasCloud, etc.), these tools typically error
or return empty, and the model burns a turn discovering that.

If the active provider is anything other than Anthropic, this hook blocks
the call (exit 2) with a directive to use `/browse` (gstack) instead.
Plain `claude` (Anthropic) sessions are unaffected — exit 0 immediately.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _provider import detect_provider, provider_label

provider = detect_provider()
if provider == "anthropic":
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool_name = data.get("tool_name") or "WebFetch/WebSearch"
label = provider_label(provider)

print(
    f"ERROR: {tool_name} is an Anthropic-hosted tool and will not function "
    f"against {label}. Use `/browse` (gstack) for web fetching/searching, or "
    f"switch to plain `claude` (Anthropic) if you specifically need {tool_name}.",
    file=sys.stderr,
)
sys.exit(2)
