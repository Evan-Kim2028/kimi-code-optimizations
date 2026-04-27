#!/usr/bin/env python3
"""
Analyze a session's wire.jsonl to measure PreToolUse hook effectiveness.

Usage:
    python3 analyze-hook-test.py <session-id>

Example:
    python3 analyze-hook-test.py 27a5a329-1899-4752-be4c-c1f169c32125
"""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


BANNED_PATTERN = re.compile(r"\b(cat|grep|rg|head|tail|find|ls)\b")


def find_session_dir(session_id: str) -> Path | None:
    base = Path.home() / ".kimi/sessions"
    for work_dir in base.iterdir():
        candidate = work_dir / session_id
        if (candidate / "wire.jsonl").exists():
            return candidate
    return None


def parse_wire(wire_path: Path) -> list[dict]:
    """Parse wire.jsonl, handling both old and new protocol formats."""
    calls = []
    with open(wire_path) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            cmd = None
            # Protocol 1.9+
            if obj.get("message", {}).get("type") == "ToolCall":
                payload = obj["message"]["payload"]
                if payload.get("type") == "function" and payload["function"]["name"] == "Shell":
                    try:
                        args = json.loads(payload["function"]["arguments"])
                        cmd = args.get("command", "")
                    except (json.JSONDecodeError, KeyError):
                        cmd = "[parse error]"
            # Older protocol
            elif obj.get("tool_name") == "Shell":
                cmd = obj.get("tool_input", {}).get("command", "")

            if cmd is not None:
                calls.append({"command": cmd, "raw": obj})
    return calls


def count_hook_blocks(session_id: str) -> int:
    """Count Hook blocked log entries for this session."""
    log_dir = Path.home() / ".kimi/logs"
    total = 0
    for log_file in log_dir.glob("kimi*.log"):
        result = subprocess.run(
            ["grep", "-c", f"Hook blocked.*{session_id}", str(log_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            total += int(result.stdout.strip())
    return total


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <session-id>")
        sys.exit(1)

    session_id = sys.argv[1]
    session_dir = find_session_dir(session_id)
    if session_dir is None:
        print(f"Session {session_id} not found in ~/.kimi/sessions", file=sys.stderr)
        sys.exit(1)

    calls = parse_wire(session_dir / "wire.jsonl")
    if not calls:
        print(f"No Shell calls found in session {session_id}")
        sys.exit(0)

    blocked_cmds = [c for c in calls if BANNED_PATTERN.search(c["command"])]
    allowed_cmds = [c for c in calls if not BANNED_PATTERN.search(c["command"])]
    hook_blocks = count_hook_blocks(session_id)

    # Breakdown by banned tool
    tool_counts = Counter()
    for c in blocked_cmds:
        for tool in ("cat", "grep", "rg", "head", "tail", "find", "ls"):
            if re.search(rf"\b{tool}\b", c["command"]):
                tool_counts[tool] += 1

    effectiveness = (hook_blocks / len(blocked_cmds) * 100) if blocked_cmds else 0

    print("=" * 65)
    print("  PRETOOLUSE HOOK EFFECTIVENESS — CONTROLLED TEST RESULTS")
    print("=" * 65)
    print(f"  Session ID:          {session_id}")
    print(f"  Session directory:   {session_dir}")
    print(f"  Wire messages:       {len(calls)}")
    print()
    print(f"  Total Shell calls:        {len(calls)}")
    print(f"  Blocked-pattern calls:    {len(blocked_cmds)}")
    print(f"  Allowed-pattern calls:    {len(allowed_cmds)}")
    print(f"  Hook blocks in logs:      {hook_blocks}")
    print()
    print(f"  Foreground effectiveness: {effectiveness:.1f}%")
    print(f"  (hook_blocks / blocked_pattern_calls)")
    print("=" * 65)

    if tool_counts:
        print("\n  Breakdown of blocked-pattern calls by tool:")
        for tool, count in tool_counts.most_common():
            print(f"    {tool:8s}: {count:3d}")

    if blocked_cmds:
        print(f"\n  Blocked-pattern commands (showing {min(15, len(blocked_cmds))} of {len(blocked_cmds)}):")
        for c in blocked_cmds[:15]:
            cmd = c["command"].replace("\n", " ")[:75]
            print(f"    • {cmd}")

    if allowed_cmds:
        print(f"\n  Allowed-pattern commands (showing {min(10, len(allowed_cmds))} of {len(allowed_cmds)}):")
        for c in allowed_cmds[:10]:
            cmd = c["command"].replace("\n", " ")[:75]
            print(f"    • {cmd}")

    print()


if __name__ == "__main__":
    main()
