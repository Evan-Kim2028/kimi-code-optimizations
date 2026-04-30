#!/usr/bin/env python3
"""Bash usage coach — redirects cat/head/tail to the Read tool, warns on standalone cd.

Unlike Kimi Code CLI, Claude Code has no native Grep or Glob tools, so
grep/find/ls in Bash are legitimate and not flagged here.

Key redirections:
  cat/head/tail  →  Read tool (structured output, line numbers, handles large files)
  standalone cd  →  warn: state doesn't persist across Bash calls

Always exits 0 (non-blocking). Tips are emitted as JSON
hookSpecificOutput.additionalContext on stdout — Claude Code injects this
into the model's context before the tool executes.
"""
import json
import re
import sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")

tips: list[str] = []


def tip(msg: str) -> None:
    tips.append(f"💡 {msg}")


# File reading: cat, head, tail → Read tool
if re.search(r"\bcat\b", cmd) or re.search(r"\bhead\b", cmd) or re.search(r"\btail\b", cmd):
    m = re.search(r"\b(?:cat|head|tail)\s+(?:-[a-zA-Z0-9]+\s+)*(\S+)", cmd)
    file = m.group(1) if m else "<file>"
    if re.search(r"\bhead\b", cmd):
        tip(
            f"For reading the start of a file, use the Read tool: "
            f"Read(file_path='{file}', limit=25) — structured lines with numbers, no subshell."
        )
    elif re.search(r"\btail\b", cmd):
        tip(
            f"For reading the end of a file, use the Read tool with offset: "
            f"Read(file_path='{file}', offset=<line_number>, limit=25)."
        )
    else:
        tip(
            f"For reading files, use the Read tool: Read(file_path='{file}') — "
            f"handles large files gracefully with structured line-numbered output."
        )

# Standalone cd (not chained) — the directory change is lost on the next Bash call
stripped = cmd.strip()
if re.match(r"^cd\s+\S", stripped) and not re.search(r"&&|;|\|", stripped):
    tip(
        "Standalone cd is lost between Bash calls. "
        "Chain your actual command inline: 'cd /path && your-command', "
        "or use absolute paths directly."
    )

if tips:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "\n".join(tips),
        }
    }))

sys.exit(0)
