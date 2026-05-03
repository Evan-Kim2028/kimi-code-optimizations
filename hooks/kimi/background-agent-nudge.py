#!/usr/bin/env python3
"""PreToolUse hook that nudges toward run_in_background=true for discovery/independent tasks.

Problem: Models default to foreground agents even for clearly independent work
like exploration, analysis, and audits. Foreground agents block the parent.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "Agent"
command = "python3 /home/evan/.kimi/hooks/background-agent-nudge.py"
timeout = 2
"""
import json
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".kimi" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Keywords in description/prompt that strongly suggest independence
DISCOVERY_KEYWORDS = [
    "explore", "investigate", "find", "audit", "analyze", "check",
    "discover", "map", "search", "locate", "identify", "review",
    "examine", "inspect", "survey", "scout", "trace", "track down",
]

# Keywords suggesting the agent needs to return before parent can proceed
DEPENDENT_KEYWORDS = [
    "fix", "implement", "edit", "change", "refactor", "migrate",
    "then", "after that", "once done", "upon completion", "next",
    "before proceeding", "blocking", "depends on",
]


def get_state_path(session_id: str) -> Path:
    return STATE_DIR / f"background-agent-nudge-{session_id}.json"


def load_state(session_id: str) -> dict:
    path = get_state_path(session_id)
    if not path.exists():
        return {"tips_this_session": 0}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"tips_this_session": 0}


def save_state(session_id: str, state: dict):
    path = get_state_path(session_id)
    path.write_text(json.dumps(state, indent=2))


def score_independence(description: str, prompt: str) -> tuple[int, str]:
    """Score how likely this agent is to be independent work.

    Returns (score, reason) where higher score means more independent.
    """
    text = f"{description} {prompt}".lower()

    discovery_hits = [k for k in DISCOVERY_KEYWORDS if k in text]
    dependent_hits = [k for k in DEPENDENT_KEYWORDS if k in text]

    score = len(discovery_hits) * 2 - len(dependent_hits)

    reason = ""
    if discovery_hits:
        reason = f"discovery keywords: {', '.join(discovery_hits[:3])}"
    return score, reason


def main():
    data = json.load(sys.stdin)

    if data.get("tool_name") != "Agent":
        sys.exit(0)

    session_id = data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    run_in_background = tool_input.get("run_in_background", False)

    # Already background — nothing to do
    if run_in_background:
        sys.exit(0)

    description = tool_input.get("description", "")
    prompt = tool_input.get("prompt", "")

    score, reason = score_independence(description, prompt)

    # Tip threshold: score >= 2 means strongly independent
    if score >= 2:
        state = load_state(session_id)
        # Cap tips to avoid spam
        if state.get("tips_this_session", 0) < 5:
            state["tips_this_session"] = state.get("tips_this_session", 0) + 1
            save_state(session_id, state)

            print(
                f"💡 BACKGROUND NUDGE: This agent looks like independent {reason}. "
                f"Consider run_in_background=true so the parent can continue working "
                f"or dispatch other agents while it runs. "
                f"Exploration, audits, and analysis are almost always safe to background.",
                file=sys.stderr,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
