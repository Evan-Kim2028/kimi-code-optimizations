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

**Note:** Claude Code also has a *native* read-dedup that fires inside subagents and emits "File unchanged since last read." That's a separate, complementary mechanism — this hook still adds value in the parent context where the native dedup is less aggressive across compaction boundaries.

---

### `parallel-agent-guard.py` — Parallel Agent Dispatch Coach (Non-blocking)

**Problem:** In a sample of 15 long Claude Code sessions, **817 of 817 `Agent` dispatches were solo turns** — the model never sent multiple `Agent` tool_use blocks in a single assistant message, even when tasks were independent. Sequential dispatch wastes wall-clock time and keeps each subagent's prompt in the parent context longer than necessary.

**What it does:** Tracks the last tool call per session in `~/.claude/state/`. When the previous call was an `Agent` (not backgrounded) and the current call is also an `Agent` within ~60 seconds, emits a tip recommending parallel batching: send both `Agent` blocks in the same assistant message and set `run_in_background=true` on each.

**Port of:** `parallel-agent-guard.py` from the Kimi suite. The Kimi README originally said this hook didn't map cleanly to Claude Code; session-log analysis showed the opposite — the dispatch problem is even more pronounced.

---

### `cheap-subagent-router.py` — Model Cost Triage (Non-blocking)

**Problem:** Claude Code's `Agent` tool accepts an optional `model` parameter (`"haiku" | "sonnet" | "opus"`). When omitted, the subagent inherits the parent model — typically Opus 4.7. Across 817 dispatches, the breakdown was 335 `general-purpose` and 82 `Explore`; most of the `Explore` calls were cheap discovery (find/grep/locate) that Haiku 4.5 handles fine at roughly an order-of-magnitude lower cost.

**What it does:** Reads the dispatch's `subagent_type`, `description`, and `prompt`, and emits a coaching tip:

| Signal | Suggestion |
|--------|------------|
| `subagent_type == "Explore"` or short prompt with discovery verbs (find / locate / grep / list / which file / search for) | `model: "haiku"` |
| Implementation verbs (implement / write / edit / fix / refactor / port / wire up) | `model: "sonnet"` |
| Review / audit / architecture / threat-model / security / cross-reference | **silent** — Opus default is the right call |
| Generic dispatch with no strong signal | `model: "sonnet"` (middle path) |
| `model` already set | **silent** — respect explicit choice |

The point is to make Opus a *conscious choice*, not an *inherited default*. The hook never blocks; the model is free to ignore the tip and stick with Opus when the task warrants it.

**No Kimi equivalent.** Kimi CLI does not expose per-subagent model selection, so this hook is Claude-Code-specific.

## Installation

### 1. Copy hooks

```bash
mkdir -p ~/.claude/hooks ~/.claude/state
cp hooks/edit-check.py hooks/bash-check.py hooks/re-read-guard.py \
   hooks/parallel-agent-guard.py hooks/cheap-subagent-router.py ~/.claude/hooks/
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
      },
      {
        "matcher": "Agent",
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/hooks/parallel-agent-guard.py"},
          {"type": "command", "command": "python3 ~/.claude/hooks/cheap-subagent-router.py"}
        ]
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

## Empirical Note: Hooks Run Inside Subagents but Stdout Is Dropped

Verified by canary logging in April 2026: when a parent dispatches an `Agent`, the subagent's `Bash` and `Read` tool calls **do** trigger the parent's PreToolUse hooks (separate PID, parent's `session_id`, shared state file). However, the subagent's transcript does **not** receive the hook's stdout — coaching tips like `💡 use Read instead of cat` are silently discarded.

What this means for hook design on Claude Code:
- **Coach the parent, not the subagent.** Hooks that depend on the model seeing a stdout tip (`bash-check`, `re-read-guard` warnings) only influence the parent's behavior. The subagent is on its own — though Claude Code's *native* read-dedup does fire inside subagents and provides some coverage.
- **State-mutating hooks still work cross-context** because they share `~/.claude/state/`. `re-read-guard` writes the subagent's reads into the parent's state file, so the parent sees the dedup on its next read of the same file.
- **The new `parallel-agent-guard` and `cheap-subagent-router` are unaffected** — they trigger on the parent's `Agent` dispatch, where the parent does see hook stdout.

If you find a way to get hook stdout into subagent transcripts (PostToolUse + tool_response injection, perhaps), open a PR.

## What's Not Ported

- **`swarm-nudge`/`discovery-intercept`** — could be ported. Bigger blocker is the subagent-stdout drop above: tips would only reach the parent. Worth experimenting with PostToolUse variants.
- **`batch-nudge`** — Claude Code's system prompt already pushes parallel tool calls. The bigger lever is `parallel-agent-guard` (now ported) which targets the *Agent dispatch* pattern specifically.
- **`line-offset-enforcer`** — Claude Code's `Read` tool uses `limit` not `n_lines`, but the pattern is the same. Could be ported if large-file reads become a measured problem.
- **`shell-check-blocking`** — The blocking variant makes sense for Kimi because it has native alternatives for `grep`/`find`. For Claude Code, blocking Bash grep would leave the model with no search path.
