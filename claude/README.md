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

> **Note (April 2026):** The original `bash-check.py` hook (cat/head/tail → Read tool nudges) was **removed** after one full day of production use. Per-call eval across 220 sessions: 327 fires, ~79% of which were false positives — the regex matched `\b(cat|head|tail)\b` whether the verb was reading a file or consuming piped output (`grep ... | head -50`, `gh pr view ... | tail -1`). The "fix" suggestion (`Read(file_path='-50;')`) was nonsense in those cases and the noise drowned out the legitimate hits. The hook would need a real pipe/flag-detector before it's worth re-adding. See "Empirical Note: When a Hook Earns Removal" below.

## Hooks

### `edit-check.py` — Edit Validation (Blocking)

**Problem:** After context compaction or parallel edits, the model's remembered `old_string` drifts from the file on disk. The Edit call fires, fails, and burns a round-trip.

**What it does:** Reads the target file before the Edit executes. If `old_string` isn't found verbatim, blocks (exit 2) with a clear error.

**Port of:** `strreplace-check.py` from the Kimi suite. Adapted for Claude Code's `Edit` tool (`file_path` + `old_string` instead of `path` + `edit.old`).

---

### `re-read-guard.py` — Re-read Guard (Non-blocking)

**Problem:** Claude Code compacts context aggressively (37 compactions in a typical long session). After each compaction, the model re-reads files it already has, burning tokens on unchanged data.

**What it does:** Tracks every `Read` call per session (file path + mtime). Warns if the model is about to re-read an unchanged file section it already loaded this session.

**Port of:** `re-read-guard.py` from the Kimi suite. Adapted for Claude Code's `Read` tool parameter names (`file_path`, `offset`, `limit` instead of `path`, `line_offset`, `n_lines`). State stored in `~/.claude/state/` instead of `~/.kimi/state/`.

**Note:** Claude Code also has a *native* read-dedup that fires inside subagents and emits "File unchanged since last read." That's a separate, complementary mechanism — this hook still adds value in the parent context where the native dedup is less aggressive across compaction boundaries.

---

### `parallel-agent-guard.py` — Parallel Agent Dispatch Coach (Non-blocking)

**Problem:** In a sample of 15 long Claude Code sessions, **817 of 817 `Agent` dispatches were solo turns** — the model never sent multiple `Agent` tool_use blocks in a single assistant message, even when tasks were independent. Sequential dispatch wastes wall-clock time and keeps each subagent's prompt in the parent context longer than necessary.

**What it does (v2 — fires at plan time):** Inspects the FIRST `Agent` dispatch's prompt for plan-shape signals — numbered/step-shaped plans, sequencer phrases (`first ... then`, `after that`), multi-target verbs (`investigate X and Y`), or three-plus parallel bullet points. When detected, emits a directive nudge before the dispatch runs: *"if these steps are independent, cancel this dispatch and re-issue all of them as a parallel batch with `run_in_background=true`."* Suppresses the nudge for clearly-heavy single-task work (threat-modeling, deep-dive, full audit). Fires once per session for plan signals.

**Sequential backstop:** If the previous Agent call was foreground and <60s old, the hook still emits a separate "you should have batched these" tip — the original v1 behavior, kept as a fallback.

**Why the rewrite:** v1 (a soft tip on the second sequential dispatch) ran for one full day and produced **0 behavioral change** — the agent-blocks-per-message histogram stayed `{1: N}` across 22 dispatches and 21 hook fires. The fix is to nudge at *plan time* (before the first call) when the model is still choosing how to structure the work, with copy-pasteable framing rather than advisory framing.

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
cp hooks/edit-check.py hooks/re-read-guard.py \
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
| Non-blocking tips | `stderr` (shown in tool result) | JSON `hookSpecificOutput.additionalContext` on stdout (plain stdout is silently dropped) |

## Empirical Note: Hook Output Format Matters (Plain `print` Is Silently Dropped)

Verified by canary logging on April 29 2026: a PreToolUse hook that prints plain text to stdout will execute, exit cleanly, write its state file — and produce **zero observable effect on Claude's behavior**, because the parent never sees the tip text. The kimi-style `print(f"💡 ...")` pattern that works on Kimi CLI is silently swallowed by Claude Code's harness.

The fix is to emit a structured JSON envelope on stdout:

```python
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": "💡 your tip here",
    }
}))
```

When formatted this way, the tip appears to the model as a `<system-reminder>` block right before the tool result — exactly the channel coaching hooks need. All five hooks in this directory use this format.

**If you migrated an earlier version of these hooks (or any kimi-style hook), update the output format.** The plain-`print` version of `bash-check`, `re-read-guard`, etc., were technically running for days on at least one install but had zero behavioral impact. Only `edit-check` worked, because it relies on `exit 2` + stderr (which still functions as a blocking error).

## Empirical Note: Hooks Run Inside Subagents but Output Is Dropped

Same canary verification: when a parent dispatches an `Agent`, the subagent's `Bash` and `Read` tool calls **do** trigger PreToolUse hooks (separate PID, parent's `session_id`, shared state file). But the subagent transcript does **not** receive `additionalContext` from those hook runs. The hook fires, the state mutates, the tip vanishes.

What this means for hook design on Claude Code:
- **Coach the parent, not the subagent.** Tips only influence the parent's behavior. The subagent is on its own — though Claude Code's *native* read-dedup does fire inside subagents and provides some coverage.
- **State-mutating hooks still work cross-context** because they share `~/.claude/state/`. `re-read-guard` writes the subagent's reads into the parent's state file, so the parent sees the dedup on its next read.
- **`parallel-agent-guard` and `cheap-subagent-router` are unaffected** — they trigger on the parent's `Agent` dispatch, which is the parent's own tool call.

If you find a way to inject context into subagent transcripts (PostToolUse + tool_response shaping, perhaps), open a PR.

## What's Not Ported

- **`swarm-nudge`/`discovery-intercept`** — could be ported. Bigger blocker is the subagent-stdout drop above: tips would only reach the parent. Worth experimenting with PostToolUse variants.
- **`batch-nudge`** — Claude Code's system prompt already pushes parallel tool calls. The bigger lever is `parallel-agent-guard` (now ported) which targets the *Agent dispatch* pattern specifically.
- **`line-offset-enforcer`** — Claude Code's `Read` tool uses `limit` not `n_lines`, but the pattern is the same. Could be ported if large-file reads become a measured problem.
- **`shell-check-blocking`** — The blocking variant makes sense for Kimi because it has native alternatives for `grep`/`find`. For Claude Code, blocking Bash grep would leave the model with no search path.

## Empirical Note: When a Hook Earns Removal

`bash-check.py` was removed on April 30 2026 after one full production day with all five hooks active. Per-hook firing tally across 220 sessions:

| Hook | Fires | Verdict |
|---|---|---|
| `cheap-subagent-router` | 19 → **15/22 (68%) of `Agent` calls set explicit `model`** (9 haiku, 6 sonnet) vs. prior 0% baseline | **Clear win — direct cost saving.** |
| `edit-check` | 3 blocks | **Small but real win** — 3 saved round-trips, no false positives. |
| `re-read-guard` | 18 warnings | **Plausibly useful**, hard to prove without a counterfactual. No false-positive surface. |
| `parallel-agent-guard` (v1) | 21 fires | **No behavioral effect** — agent-blocks-per-message stayed `{1: 22}`. Rewritten as v2 (plan-time nudge). |
| `bash-check` | 211 tip fires (115 "start" + 73 "end" + 23 "files") | **Removed.** ~79% false-positive rate from `\b(cat\|head\|tail)\b` matching piped use. Suggested fixes (`Read(file_path='-50;')`) were nonsense. |

The lesson: **measure each hook by behavioral delta, not by activity.** A hook that fires 211 times and produces noise is worse than one that never runs. A hook that fires 19 times and shifts 68% of subagent dispatches off Opus is doing real work. The eval bar should be "did the model's downstream behavior change," not "did the hook trigger."

For `bash-check` to earn its way back in, the regex needs to detect:
- Pipe input (`|` precedes the verb) → skip
- Flag-only invocation (first non-flag arg starts with `-` or is numeric) → skip
- Real filename argument (path-like or matches `.*\.\w+$`) → fire

Until that exists, the hook is net negative.
