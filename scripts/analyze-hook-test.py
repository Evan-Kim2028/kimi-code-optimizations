#!/usr/bin/env python3
"""
Analyze a session's wire.jsonl to measure coaching hook effectiveness.

Metrics:
  - Guidance given: number of Shell calls where the hook emitted a tip
  - Guidance adopted: model switched to the suggested tool in subsequent steps
  - Native tool usage: count of Glob, ReadFile, Grep, etc.
  - Shell efficiency: average commands per Shell call, batch operation detection

Usage:
    python3 analyze-hook-test.py <session-id>
"""

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


BANNED_PATTERN = re.compile(r"\b(cat|grep|rg|head|tail|find|ls)\b")
# Tips that suggest a native tool alternative
NATIVE_TOOL_TIPS = {
    "Glob": re.compile(r"Glob\("),
    "ReadFile": re.compile(r"ReadFile\("),
    "Grep": re.compile(r"Grep\("),
}


def find_session_dir(session_id: str) -> Path | None:
    base = Path.home() / ".kimi/sessions"
    for work_dir in base.iterdir():
        candidate = work_dir / session_id
        if (candidate / "wire.jsonl").exists():
            return candidate
    return None


def parse_wire(wire_path: Path) -> list[dict]:
    """Parse wire.jsonl into a timeline of events."""
    events = []
    with open(wire_path) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = obj.get("message", {})
            t = msg.get("type")

            if t == "ToolCall":
                payload = msg["payload"]
                if payload.get("type") == "function":
                    name = payload["function"]["name"]
                    call_id = payload.get("id", obj.get("call_id", "no-id"))
                    args_str = payload["function"].get("arguments", "")
                    events.append({
                        "type": "call",
                        "tool": name,
                        "call_id": call_id,
                        "args": args_str,
                        "timestamp": obj.get("timestamp", 0),
                    })

            elif t == "ToolResult":
                payload = msg["payload"]
                call_id = payload.get("tool_call_id", obj.get("call_id", "no-id"))
                rv = payload.get("return_value", {})
                content = str(rv.get("output", ""))
                events.append({
                    "type": "result",
                    "tool": call_id,  # we don't know the tool name here, use call_id
                    "call_id": call_id,
                    "content": content,
                    "timestamp": obj.get("timestamp", 0),
                })

    # Sort by timestamp
    events.sort(key=lambda e: e["timestamp"])
    return events


def extract_shell_command(args_str: str) -> str:
    m = re.search(r'"command"\s*:\s*"(.*?)"(?:,|\})', args_str)
    if m:
        try:
            return m.group(1).encode().decode("unicode_escape")
        except UnicodeDecodeError:
            return m.group(1)
    return "[unparseable]"


def extract_tips_from_result(content: str) -> list[str]:
    """Extract coaching tips from a Shell ToolResult content."""
    tips = []
    for line in content.split("\n"):
        if line.startswith("💡") or line.startswith("✅"):
            tips.append(line.strip())
    return tips


def analyze_session(session_id: str, session_dir: Path) -> dict:
    events = parse_wire(session_dir / "wire.jsonl")

    # Build call→result mapping
    results_by_call = {}
    for e in events:
        if e["type"] == "result":
            results_by_call[e["call_id"]] = e

    # Analyze Shell calls
    shell_calls = []
    native_calls = []
    for e in events:
        if e["type"] != "call":
            continue
        if e["tool"] == "Shell":
            cmd = extract_shell_command(e["args"])
            result = results_by_call.get(e["call_id"])
            tips = extract_tips_from_result(result["content"]) if result else []
            shell_calls.append({
                "call_id": e["call_id"],
                "command": cmd,
                "timestamp": e["timestamp"],
                "tips": tips,
                "has_blocked_pattern": bool(BANNED_PATTERN.search(cmd)),
            })
        else:
            native_calls.append({
                "tool": e["tool"],
                "timestamp": e["timestamp"],
            })

    # Guidance adoption analysis:
    # For each Shell call with tips, check if the model used the suggested
    # native tool in the next 3 calls
    guidance_given = 0
    guidance_adopted = 0
    tip_details = []

    for i, sc in enumerate(shell_calls):
        if not sc["tips"]:
            continue
        guidance_given += 1

        # Determine what native tool was suggested
        suggested_tools = set()
        for tip in sc["tips"]:
            for tool, pattern in NATIVE_TOOL_TIPS.items():
                if pattern.search(tip):
                    suggested_tools.add(tool)

        # Look at next native tool calls (up to 5 calls after this Shell)
        adopted = False
        adopted_tool = None
        for nc in native_calls:
            if nc["timestamp"] > sc["timestamp"]:
                if nc["tool"] in suggested_tools:
                    adopted = True
                    adopted_tool = nc["tool"]
                    break

        if adopted:
            guidance_adopted += 1

        tip_details.append({
            "command": sc["command"][:60],
            "tips": [t[:80] for t in sc["tips"]],
            "adopted": adopted,
            "adopted_tool": adopted_tool,
        })

    # Native tool breakdown
    native_counts = Counter(nc["tool"] for nc in native_calls)

    return {
        "shell_calls": len(shell_calls),
        "native_calls": len(native_calls),
        "native_breakdown": native_counts,
        "blocked_pattern_shell": sum(1 for sc in shell_calls if sc["has_blocked_pattern"]),
        "guidance_given": guidance_given,
        "guidance_adopted": guidance_adopted,
        "tip_details": tip_details,
        "shell_commands": [sc["command"] for sc in shell_calls],
    }


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <session-id>")
        sys.exit(1)

    session_id = sys.argv[1]
    session_dir = find_session_dir(session_id)
    if session_dir is None:
        print(f"Session {session_id} not found in ~/.kimi/sessions", file=sys.stderr)
        sys.exit(1)

    stats = analyze_session(session_id, session_dir)

    print("=" * 70)
    print("  SHELL USAGE COACH — CONTROLLED TEST RESULTS")
    print("=" * 70)
    print(f"  Session ID:          {session_id}")
    print(f"  Session directory:   {session_dir}")
    print()
    print(f"  Shell calls:              {stats['shell_calls']}")
    print(f"  Native tool calls:        {stats['native_calls']}")
    print(f"  Shell with banned pattern:{stats['blocked_pattern_shell']}")
    print()
    print(f"  Guidance given:           {stats['guidance_given']}")
    print(f"  Guidance adopted:         {stats['guidance_adopted']}")
    if stats["guidance_given"]:
        rate = stats["guidance_adopted"] / stats["guidance_given"] * 100
        print(f"  Adoption rate:            {rate:.0f}%")
    print()

    if stats["native_breakdown"]:
        print("  Native tool usage breakdown:")
        for tool, count in stats["native_breakdown"].most_common():
            print(f"    {tool:12s}: {count:3d}")
        print()

    if stats["tip_details"]:
        print("  Guidance details:")
        for td in stats["tip_details"]:
            status = "✅ adopted" if td["adopted"] else "❌ not adopted"
            print(f"    Command: {td['command'][:50]}")
            for tip in td["tips"]:
                print(f"      → {tip}")
            print(f"      {status}" + (f" → {td['adopted_tool']}" if td["adopted_tool"] else ""))
            print()

    if stats["shell_commands"]:
        print(f"  All Shell commands:")
        for cmd in stats["shell_commands"]:
            print(f"    • {cmd[:80]}")
        print()

    print("=" * 70)


if __name__ == "__main__":
    main()
