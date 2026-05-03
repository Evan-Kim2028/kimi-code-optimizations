"""Detect which Anthropic-compatible provider this Claude Code session targets.

Reads `ANTHROPIC_BASE_URL` from the hook's inherited env (set by the
`claude-glm` / `claude-kimi` shell aliases) and returns a stable token.
Hooks use this to:
  - skip behavior that's Anthropic-specific (e.g. the haiku/sonnet/opus
    model tiers in `cheap-subagent-router.py` don't exist on Z.AI or Moonshot)
  - redirect Anthropic-server-side tools (WebFetch/WebSearch) to a local
    equivalent (`/browse` from gstack)
  - tailor coaching message text with the active provider's name

Recognized:
  - "anthropic" — official api.anthropic.com, or env unset (default `claude`)
  - "zai"       — api.z.ai (GLM-5.1, GLM-5-Turbo)
  - "kimi"      — api.kimi.com or api.moonshot.* (Kimi K2.6 / Kimi Code)
  - "other"     — any other base URL (CometAPI, AtlasCloud, self-hosted, etc.)
"""
import os

PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "zai": "Z.AI (GLM)",
    "kimi": "Moonshot/Kimi",
    "other": "third-party Anthropic-compatible endpoint",
}


def detect_provider() -> str:
    base = (os.environ.get("ANTHROPIC_BASE_URL") or "").lower()
    if not base or "anthropic.com" in base:
        return "anthropic"
    if "z.ai" in base or "bigmodel" in base:
        return "zai"
    if "kimi.com" in base or "moonshot" in base:
        return "kimi"
    return "other"


def provider_label(provider: str | None = None) -> str:
    return PROVIDER_LABELS.get(provider or detect_provider(), PROVIDER_LABELS["other"])
