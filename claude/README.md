# Claude Code CLI Hooks

Hooks for [Claude Code CLI](https://claude.ai/code) ported from the Kimi Code CLI hook suite, adapted for Claude Code's tool names and behavioral profile.

## Why These Exist

A direct session log comparison between Claude Code and Kimi Code CLI (same workloads, comparable step counts) showed:

| Metric | Claude Code | Kimi + hooks |
|--------|-------------|--------------|
| Standalone `cd` in Bash | 433 | ~0 |
| `cat`/`head`/`tail` in Bash | 271 | ~0 |
| Stale `Edit` blocks (would-fail) | not counted | 37 blocked/session |
| Context re-reads after compaction | not counted | guarded |

Claude Code already has one architectural advantage Kimi lacks: **prompt caching** (982M cache-read tokens in a typical long session). These hooks address the behavioral gaps that caching can't fix.

## Hooks

### `edit-check.py` — Edit Validation (Blocking)

**Problem:** After context compaction or parallel edits, the model's remembered `old_string` drifts from the file on disk. The Edit call fires, fails, and burns a round-trip.

**What it does:** Reads the target file before the Edit executes. If `old_string` isn't found verbatim, blocks (exit 2) with a clear error.

**Port of:** `strreplace-check.py` from the Kimi suite. Adapted for Claude Code's `Edit` tool (`file_path` + `old_string` instead of `path` + `edit.old`).

---

### `bash-check.py` — Bash Usage Coach (Non-blocking)

**Problem:** Claude Code uses Bash for `cat`, `head`, `tail`, and standalone `cd` — all cases where the native `Read` tool or inline chaining would be faster and more context-efficient.

**What it does:** Detects those patterns and emits coaching tips (stdout → shown to Claude as context before the tool runs). Always exits 0.

**Claude-specific note:** Unlike the Kimi version, this does **not** flag `grep`, `find`, or `ls` — Claude Code has no native `Grep` or `Glob` tools, so Bash is the right choice for those.

**Port of:** `shell-check.py` from the Kimi suite. Tool name changed (`Shell` → `Bash`), redirections adjusted for Claude Code's available native tools.

---

### `re-read-guard.py` — Re-read Guard (Non-blocking)

**Problem:** Claude Code compacts context aggressively (37 compactions in a typical long session). After each compaction, the model re-reads files it already has, burning tokens on unchanged data.

**What it does:** Tracks every `Read` call per session (file path + mtime). Warns if the model is about to re-read an unchanged file section it already loaded this session.

**Port of:** `re-read-guard.py` from the Kimi suite. Adapted for Claude Code's `Read` tool parameter names (`file_path`, `offset`, `limit` instead of `path`, `line_offset`, `n_lines`). State stored in `~/.claude/state/` instead of `~/.kimi/state/`.

## Installation

### 1. Copy hooks

```bash
mkdir -p ~/.claude/hooks ~/.claude/state
cp hooks/edit-check.py hooks/bash-check.py hooks/re-read-guard.py ~/.claude/hooks/
```

### 2. Add to `~/.claude/settings.json`

Merge the `PreToolUse` block from `settings.json.example` into your existing `~/.claude/settings.json`. If you already have `PreToolUse` hooks, append to the array.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/edit-check.py"}]
      },
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/bash-check.py"}]
      },
      {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/re-read-guard.py"}]
      }
    ]
  }
}
```

### 3. Start a new session

Hooks load at session start. Restart Claude Code for them to take effect.

## Key Differences from Kimi Hooks

| Aspect | Kimi Code CLI | Claude Code CLI |
|--------|---------------|-----------------|
| Edit tool | `StrReplaceFile` (exact match only) | `Edit` (fuzzy match, but still fails on drift) |
| Edit input fields | `path`, `edit.old` | `file_path`, `old_string` |
| Shell tool | `Shell` | `Bash` |
| Read tool | `ReadFile` | `Read` |
| Read params | `path`, `line_offset`, `n_lines` | `file_path`, `offset`, `limit` |
| Native search | `Grep`, `Glob` tools exist | None — use Bash grep/find |
| Config format | `~/.kimi/config.toml` `[[hooks]]` | `~/.claude/settings.json` `hooks.PreToolUse` |
| State dir | `~/.kimi/state/` | `~/.claude/state/` |
| Hook stdin `cwd` | Provided by runtime | Not provided — use absolute paths |
| Non-blocking tips | `stderr` (shown in tool result) | `stdout` (shown to Claude as context) |

## What's Not Ported

- **`swarm-nudge`/`discovery-intercept`** — Claude Code's `Agent` tool has different dispatch semantics. The nudge thresholds and patterns from the Kimi suite don't map cleanly.
- **`batch-nudge`** — Claude Code already has strong parallelization instructions in its system prompt and dispatches agents less aggressively (24 vs 79 per session). Lower priority.
- **`line-offset-enforcer`** — Claude Code's `Read` tool uses `limit` not `n_lines`, but the pattern is the same. Could be ported if large-file reads become a measured problem.
- **`shell-check-blocking`** — The blocking variant makes sense for Kimi because it has native alternatives for `grep`/`find`. For Claude Code, blocking Bash grep would leave the model with no search path.
