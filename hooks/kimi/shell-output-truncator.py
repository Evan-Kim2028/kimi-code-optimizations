#!/usr/bin/env python3
"""PreToolUse hook that detects Shell commands likely to produce unbounded output.

Problem: Commands like git log, journalctl, docker logs, find, pip list, npm ls
produce massive unstructured output that silently burns context.

This is different from shell-check.py (which guards against wrong-tool-for-the-job).
This guards against right-tool-wrong-flags.

Add to ~/.kimi/config.toml:

[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "python3 /home/evan/.kimi/hooks/shell-output-truncator.py"
timeout = 2
"""
import json
import re
import sys


def main():
    data = json.load(sys.stdin)

    if data.get("tool_name") != "Shell":
        sys.exit(0)

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        sys.exit(0)

    warnings = []

    # git log without line limits
    if re.search(r"\bgit\s+log\b", cmd):
        if not re.search(r"-\d+|--max-count|--oneline|-n\s+\d+", cmd):
            warnings.append(
                "git log without -n or --oneline can produce thousands of lines. "
                "Use git log --oneline -n 20 to limit output."
            )

    # journalctl without bounds
    if re.search(r"\bjournalctl\b", cmd):
        if not re.search(r"-n\s+\d+|--lines=\d+|--since|--follow|-f\b", cmd):
            warnings.append(
                "journalctl without -n or --since can dump the entire system log. "
                "Use journalctl -n 50 --since '1 hour ago' to limit output."
            )

    # docker logs without tail
    if re.search(r"\bdocker\s+logs?\b", cmd):
        if not re.search(r"--tail\b|-n\s+\d+", cmd):
            warnings.append(
                "docker logs without --tail can stream the entire container history. "
                "Use docker logs --tail 50 to limit output."
            )

    # find without maxdepth
    if re.search(r"\bfind\b", cmd):
        if not re.search(r"-maxdepth\b", cmd) and not re.search(r"-type f\b.*-name", cmd):
            warnings.append(
                "find without -maxdepth can traverse the entire filesystem. "
                "Use find . -maxdepth 3 ... to limit output."
            )

    # Package listing commands
    if re.search(r"\bpip\s+list\b|\bnpm\s+ls\b|\bpnpm\s+ls\b|\byarn\s+list\b", cmd):
        warnings.append(
            "Package list commands produce verbose tree output. "
            "Use pip list | head -20 or npm ls --depth=0 to limit output."
        )

    # ps aux (full process list)
    if re.search(r"\bps\s+aux\b|\bps\s+-ef\b", cmd):
        if not re.search(r"\bgrep\b|\bhead\b|\btail\b", cmd):
            warnings.append(
                "ps aux dumps every process on the system. "
                "Use ps aux | grep <pattern> | head -20 to limit output."
            )

    # dmesg
    if re.search(r"\bdmesg\b", cmd):
        if not re.search(r"\bhead\b|\btail\b|-n\s+\d+", cmd):
            warnings.append(
                "dmesg can produce thousands of kernel log lines. "
                "Use dmesg | tail -20 to limit output."
            )

    # kubectl logs without tail
    if re.search(r"\bkubectl\s+logs?\b", cmd):
        if not re.search(r"--tail\b|-n\s+\d+", cmd):
            warnings.append(
                "kubectl logs without --tail can stream the entire pod history. "
                "Use kubectl logs --tail 50 to limit output."
            )

    # ls -R (recursive ls)
    if re.search(r"\bls\s+.*-R\b|\bls\s+.*--recursive", cmd):
        warnings.append(
            "ls -R recursively lists every file. Use Glob(pattern='**/*') instead for structured output."
        )

    if warnings:
        print(
            "⚠️ OUTPUT GUARD: This Shell command may produce unbounded output:\n"
            + "\n".join(f"  • {w}" for w in warnings)
            + "\nUnbounded command output silently burns context. Add filters before proceeding.",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
