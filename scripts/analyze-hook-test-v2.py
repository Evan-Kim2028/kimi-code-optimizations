#!/usr/bin/env python3
"""
Analyze a session's wire.jsonl to measure swarm and discovery-intercept hook effectiveness.

Metrics:
  - Agent bait-and-switch detection: manual work streaks between agents
  - Manual:Agent ratio with grade
  - Discovery pattern analysis: sequential runs, parallel batching, slow discovery
  - Original shell-check metrics (banned patterns, cd commands)

Usage:
    python3 analyze-hook-test-v2.py <session-id>
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

BANNED_PATTERN = re.compile(r"\b(cat|grep|rg|head|tail|find|ls)\b")
MANUAL_TOOLS = {"ReadFile", "Grep", "Shell"}


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
                payload = msg.get("payload", {})
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
                payload = msg.get("payload", {})
                call_id = payload.get("tool_call_id", obj.get("call_id", "no-id"))
                rv = payload.get("return_value", {})
                content = str(rv.get("output", ""))
                events.append({
                    "type": "result",
                    "tool": call_id,
                    "call_id": call_id,
                    "content": content,
                    "timestamp": obj.get("timestamp", 0),
                })

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


def is_agent_call(event: dict) -> bool:
    return event["type"] == "call" and event["tool"] == "Agent"


def is_manual_call(event: dict) -> bool:
    return event["type"] == "call" and event["tool"] in MANUAL_TOOLS


def parse_agent_background(args_str: str) -> bool | None:
    try:
        args = json.loads(args_str)
        return args.get("run_in_background")
    except json.JSONDecodeError:
        m = re.search(r'"run_in_background"\s*:\s*(true|false)', args_str)
        if m:
            return m.group(1) == "true"
    return None


def compute_batches(events: list[dict]) -> list[list[dict]]:
    """Group consecutive ToolCall events (no ToolResult between them) into batches."""
    batches = []
    i = 0
    while i < len(events):
        if events[i]["type"] == "call":
            batch = []
            j = i
            while j < len(events) and events[j]["type"] == "call":
                batch.append(events[j])
                j += 1
            batches.append(batch)
            i = j
        else:
            i += 1
    return batches


def analyze_session(session_id: str, session_dir: Path) -> dict:
    events = parse_wire(session_dir / "wire.jsonl")
    calls = [e for e in events if e["type"] == "call"]
    batches = compute_batches(events)

    # --- Agent usage ---
    agent_calls = [c for c in calls if is_agent_call(c)]
    total_agents = len(agent_calls)
    background_agents = sum(
        1 for c in agent_calls if parse_agent_background(c["args"]) is True
    )
    foreground_agents = sum(
        1 for c in agent_calls if parse_agent_background(c["args"]) is False
    )
    unknown_bg_agents = total_agents - background_agents - foreground_agents

    # --- Manual work streaks (consecutive manual calls between agents) ---
    manual_streaks = []
    current_streak = 0

    for c in calls:
        if is_agent_call(c):
            if current_streak > 0:
                manual_streaks.append(current_streak)
                current_streak = 0
        elif is_manual_call(c):
            current_streak += 1

    if current_streak > 0:
        manual_streaks.append(current_streak)

    longest_streak = max(manual_streaks) if manual_streaks else 0
    avg_streak = sum(manual_streaks) / len(manual_streaks) if manual_streaks else 0.0
    severe_streaks = sum(1 for s in manual_streaks if s >= 8)

    # Distribution buckets
    dist = {
        "1": sum(1 for s in manual_streaks if s == 1),
        "2-3": sum(1 for s in manual_streaks if 2 <= s <= 3),
        "4-7": sum(1 for s in manual_streaks if 4 <= s <= 7),
        "8+": sum(1 for s in manual_streaks if s >= 8),
    }

    # --- Manual:Agent ratio ---
    total_manual = sum(1 for c in calls if is_manual_call(c))
    ratio = total_manual / total_agents if total_agents else float("inf")

    if ratio < 2:
        grade = "good"
        grade_emoji = "🟢"
    elif ratio <= 5:
        grade = "moderate"
        grade_emoji = "🟡"
    else:
        grade = "poor"
        grade_emoji = "🔴"

    # --- Discovery pattern analysis ---
    # Sequential manual runs of 3+ anywhere in a streak
    discovery_streaks = sum(1 for s in manual_streaks if s >= 3)

    # Parallel vs sequential native tool batching
    parallel_batches = 0
    sequential_batches = 0
    for batch in batches:
        manual_in_batch = sum(1 for c in batch if is_manual_call(c))
        if manual_in_batch == 0:
            continue
        if manual_in_batch >= 2:
            parallel_batches += 1
        else:
            sequential_batches += 1

    # Slow discovery: manual calls before first agent dispatch
    manual_before_first_agent = 0
    for c in calls:
        if is_agent_call(c):
            break
        if is_manual_call(c):
            manual_before_first_agent += 1
    slow_discovery = manual_before_first_agent > 5

    # --- Original shell-check metrics ---
    shell_calls = [c for c in calls if c["tool"] == "Shell"]
    shell_count = len(shell_calls)
    banned_shell = 0
    cd_commands = 0
    for c in shell_calls:
        cmd = extract_shell_command(c["args"])
        if BANNED_PATTERN.search(cmd):
            banned_shell += 1
        if re.search(r'\bcd\b', cmd):
            cd_commands += 1

    native_counts = Counter(c["tool"] for c in calls if c["tool"] in MANUAL_TOOLS)

    return {
        "session_id": session_id,
        "session_dir": session_dir,
        "total_agents": total_agents,
        "background_agents": background_agents,
        "foreground_agents": foreground_agents,
        "unknown_bg_agents": unknown_bg_agents,
        "manual_streaks": manual_streaks,
        "longest_streak": longest_streak,
        "avg_streak": avg_streak,
        "severe_streaks": severe_streaks,
        "dist": dist,
        "total_manual": total_manual,
        "total_agent": total_agents,
        "ratio": ratio,
        "grade": grade,
        "grade_emoji": grade_emoji,
        "discovery_streaks": discovery_streaks,
        "parallel_batches": parallel_batches,
        "sequential_batches": sequential_batches,
        "slow_discovery": slow_discovery,
        "manual_before_first_agent": manual_before_first_agent,
        "shell_count": shell_count,
        "banned_shell": banned_shell,
        "cd_commands": cd_commands,
        "native_counts": native_counts,
    }


def print_report(stats: dict) -> None:
    print("=" * 42)
    print("  SWARM & DISCOVERY ANALYSIS")
    print("=" * 42)
    print(f"  Session ID: {stats['session_id']}")
    print()

    print("  AGENT USAGE")
    print("  -----------")
    print(f"  Total agents dispatched:     {stats['total_agents']}")
    print(f"  Background agents:           {stats['background_agents']}")
    print(f"  Foreground agents:           {stats['foreground_agents']}")
    if stats["unknown_bg_agents"]:
        print(f"  Unknown background status:   {stats['unknown_bg_agents']}")
    print()

    print("  MANUAL WORK STREAKS")
    print("  -------------------")
    streak_emoji = (
        "🔴" if stats["longest_streak"] >= 8 else
        "🟡" if stats["longest_streak"] >= 3 else "🟢"
    )
    print(f"  Longest streak:              {stats['longest_streak']} calls {streak_emoji}")
    print(f"  Average streak:              {stats['avg_streak']:.1f}")
    print(f"  Total streaks:               {len(stats['manual_streaks'])}")
    severe_emoji = "🔴" if stats["severe_streaks"] > 0 else "🟢"
    print(f"  Severe streaks (>=8):        {stats['severe_streaks']} {severe_emoji}")
    print("  Distribution:")
    for bucket, count in stats["dist"].items():
        print(f"    {bucket:>3s}: {count}")
    print()

    print("  RATIO")
    print("  -----")
    print(f"  Manual calls:                {stats['total_manual']}")
    print(f"  Agent calls:                 {stats['total_agent']}")
    ratio_str = f"{stats['ratio']:.1f}:1" if stats["ratio"] != float("inf") else "∞:1"
    print(f"  Ratio:                       {ratio_str} {stats['grade_emoji']} ({stats['grade']})")
    print()

    print("  DISCOVERY PATTERNS")
    print("  ------------------")
    print(f"  Sequential manual runs (3+): {stats['discovery_streaks']}")
    print(f"  Parallel batches:            {stats['parallel_batches']}")
    print(f"  Sequential batches:          {stats['sequential_batches']}")
    sd_emoji = "🔴" if stats["slow_discovery"] else "🟢"
    print(
        f"  Slow discovery (>5 manual):  "
        f"{'Yes' if stats['slow_discovery'] else 'No'} "
        f"({stats['manual_before_first_agent']} calls) {sd_emoji}"
    )
    print()

    print("  SHELL CHECK")
    print("  -----------")
    print(f"  Shell calls:                 {stats['shell_count']}")
    banned_emoji = "🔴" if stats["banned_shell"] > 0 else "🟢"
    print(f"  Banned patterns:             {stats['banned_shell']} {banned_emoji}")
    cd_emoji = "🔴" if stats["cd_commands"] > 0 else "🟢"
    print(f"  cd commands:                 {stats['cd_commands']} {cd_emoji}")
    print()

    if stats["native_counts"]:
        print("  Native tool breakdown:")
        for tool, count in stats["native_counts"].most_common():
            print(f"    {tool:12s}: {count:3d}")
        print()

    print("=" * 42)


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
    print_report(stats)


if __name__ == "__main__":
    main()
