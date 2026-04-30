# Agent Harness Optimizations

A productivity toolkit for AI coding-agent CLIs — enforcing efficient tool usage, parallel dispatch, and cost-aware subagent routing through harness-level hooks. Currently covers [Kimi Code CLI](https://github.com/moonshot-ai/kimi-cli) and [Claude Code CLI](https://claude.ai/code); the patterns generalize to any harness with a PreToolUse/PostToolUse hook system (Codex, Cursor, Gemini CLI, OpenHands).

> Repo name is historical (`kimi-code-optimizations`) — the scope is broader now. New harnesses welcome via PR.

## What's This?

AI coding agents are powerful, but they burn turns on inefficient patterns: cat'ing files instead of using a structured Read tool, dispatching subagents serially instead of in parallel, defaulting to the most expensive model for cheap discovery work. The patterns differ by harness, but the fix is the same: **hooks as in-conversation training signals** that redirect behavior in real time.

This repo covers two harnesses today:

- **[`hooks/`](#kimi-code-cli-hooks) + [`bin/`](#helper-scripts)** — Kimi Code CLI suite (Shell coaching, StrReplaceFile validation, swarm nudges, context guards)
- **[`claude/`](claude/README.md)** — Claude Code CLI hooks (Edit validation, Bash coaching, re-read guard, parallel-agent guard, cost-aware subagent router)

---

## Kimi Code CLI Hooks

Kimi's inefficient patterns:
- `ls -R` + `cat` instead of native `Grep`/`ReadFile`
- `cd` loops because subagents don't inherit working directory
- SSH sessions used as slow REPLs for remote file reading
- Fragile `StrReplaceFile` exact-match edits that fail on any context drift

This repo gives you:
1. **`AGENTS.md`** — Project-level rules that guide the model toward efficient patterns
2. **`hooks/shell-check.py`** — PreToolUse hook that coaches the model away from `cat`/`grep`/`cd` in Shell calls (tips, non-blocking)
2b. **`hooks/shell-check-blocking.py`** — Aggressive variant that **blocks** `cat`/`grep`/`cd` entirely (exit 2)
3. **`hooks/strreplace-check.py`** — PreToolUse hook that validates `StrReplaceFile` `old` strings exist before the tool fires (blocks guaranteed-fail turns)
4. **`hooks/batch-nudge.py`** — PostToolUse hook that detects sequential similar calls and emits real-time batching tips
5. **`hooks/swarm-nudge.py`** — PostToolUse hook that detects complex manual work and nudges toward subagent swarm decomposition
6. **`hooks/swarm-nudge-v2.py`** — Improved swarm nudge that tracks manual work *since last agent* (catches the "agent bait-and-switch" pattern where models dispatch agents early then grind manually)
7. **`hooks/discovery-intercept.py`** — PreToolUse hook that intercepts ReadFile/Grep/Shell calls during long manual streaks and asks "should this be an agent?" *before* the call fires
8. **`hooks/re-read-guard.py`** — PreToolUse hook that warns when the model re-reads an unchanged file this session
9. **`hooks/line-offset-enforcer.py`** — PreToolUse hook that nudges toward `line_offset` on large file reads
10. **`bin/apply-patch`** — Safe unified-diff application with built-in dry-run
11. **`bin/make-patch`** — Converts `old`/`new` text pairs into valid unified diffs (no manual line-number math)
12. **`bin/multi-read`** — Reads multiple files in one Shell call (bypasses N sequential ReadFile calls for small files)

---

## Claude Code CLI Hooks

Claude Code has one architectural advantage Kimi lacks: **prompt caching**. The Anthropic API caches context across compaction events, so re-reading tokens after a compaction is cheap (cache hits). But session log analysis against Kimi+hooks reveals clear behavioral gaps that caching doesn't fix:

| Pattern | Claude Code (observed) | Kimi + hooks |
|---------|------------------------|--------------|
| Standalone `cd` in Bash | 433/session | ~0 |
| `cat`/`head`/`tail` in Bash | 271/session | ~0 |
| Stale `Edit` calls (would fail) | unguarded | 37 blocked/session |
| Re-reads after compaction | unguarded | guarded |

Claude also has no native `Grep` or `Glob` tools (unlike Kimi), so Bash grep and find are legitimate and not flagged here.

Four hooks live in [`claude/`](claude/README.md):

1. **`claude/hooks/edit-check.py`** — PreToolUse on `Edit`. Reads the target file and blocks (exit 2) if `old_string` isn't found verbatim. Eliminates the stale-edit round-trip that fires after context compaction or parallel edits. *Port of `strreplace-check.py`.*

2. **`claude/hooks/re-read-guard.py`** — PreToolUse on `Read`. Tracks file path + mtime per session; warns when Claude is about to re-read an unchanged file it already loaded. *Port of `re-read-guard.py`, adapted for Claude's `offset`/`limit` parameter names.*

3. **`claude/hooks/parallel-agent-guard.py`** — PreToolUse on `Agent`. In a sample of 15 long sessions, **817/817 `Agent` dispatches were solo turns** (zero parallel batching). v2 of this hook (April 2026) inspects the *first* dispatch's prompt for plan-shape signals — numbered steps, sequencer phrases (`first ... then`), multi-target verbs — and emits a directive nudge at plan time recommending multiple `Agent` blocks in a single assistant message with `run_in_background=true`. v1 fired on the *second* sequential dispatch and produced zero behavioral change in production; v2 moves the nudge upstream to where the planning happens. *Evolved from `parallel-agent-guard.py`.*

4. **`claude/hooks/cheap-subagent-router.py`** — PreToolUse on `Agent`. Claude Code's `Agent` tool accepts `model: "haiku" | "sonnet" | "opus"`; when omitted the subagent inherits the parent (often Opus). This hook triages the dispatch and suggests Haiku for discovery, Sonnet for scoped implementation, and stays silent on review/architecture/security tasks where Opus is the right default. Makes Opus a *conscious choice*, not an *inherited default*. Production data after one full day: 68% of subagent dispatches set an explicit model (vs 0% baseline). **Claude-Code-specific** — Kimi has no equivalent.

> A fifth hook (`bash-check.py`, cat/head/tail → Read tool nudge) shipped in the original release and was **removed** on April 30 2026 after a per-hook eval — ~79% false-positive rate on piped use. See [`claude/README.md`](claude/README.md#empirical-note-when-a-hook-earns-removal) for the data.

See [`claude/README.md`](claude/README.md) for installation instructions, a diff table of Kimi vs Claude Code tool names, and an empirical note on hook-stdout propagation into subagents (it doesn't — coach the parent).

## The Aha: In-Conversation Training Signals

The big insight here is that **hooks are real-time training signals**.

Traditional approaches try to fix LLM behavior upfront — better system prompts, fine-tuning, or AGENTS.md rules. Those work, but they're static. The model either remembers them or it doesn't.

Hooks are different. They're **dynamic feedback loops that shape behavior within a single conversation**:

- The model makes a sequential `ReadFile` call → the `batch-nudge` hook fires in the result → the model sees the tip → its *next* turn batches in parallel.
- The model tries a stale `StrReplaceFile` → the `strreplace-check` hook blocks it → the model re-reads the file → learns to verify before editing.
- The model grinds through 6 manual discovery calls → the `swarm-nudge-v2` hook suggests explore agents → the model delegates → discovers faster.
- The model is about to fire a 5th sequential `ReadFile` during a manual streak → the `discovery-intercept` hook asks "should this be an agent?" → the model stops and delegates before wasting the turn.

**Each tip is a gradient step.** Over the course of one session, the model encounters dozens of these micro-signals and adaptively shifts its strategy. The conversation *trains itself*.

This is why we measure adoption rate (42% of tipped sessions show reduced Shell usage after the tip) and why the tips taper off as the model learns. The hooks aren't guardrails — they're a **tutoring layer**.

### Why This Matters: Models Have No Cross-Session Memory

An independent [analysis of exfiltrated system prompts](https://www.dbreunig.com/2026/02/10/system-prompts-define-the-agent-as-much-as-the-model.html) across six CLI coding agents (Claude Code, Cursor, Gemini CLI, Codex CLI, OpenHands, and Kimi CLI) found that **all of them need explicit system-prompt instructions to parallelize**:

> "System prompts also repeatedly specify that tool calls should be parallel whenever possible. Claude should, 'maximize use of parallel tool calls where possible.' Cursor is sternly told, 'CRITICAL INSTRUCTION: involve all relevant tools concurrently… DEFAULT TO PARALLEL.' **Kimi adopts all-caps as well, stating, 'you are HIGHLY RECOMMENDED to make [tool calls] in parallel.'**
>
> This likely reflects the fact that most post-training reasoning and agentic examples are **serial** in nature… system prompts need to override this training."

The system prompt *suggests* parallelism. Hooks **enforce** it with tactile feedback the model sees in-context.

Additionally, comparisons with memory-first agents explicitly note that **Kimi CLI has no learning between sessions**:

> **Kimi CLI** (Session-Based)
> - Sessions are independent
> - **No learning between sessions**
> - Context = messages in the current session + `AGENTS.md`
> - Relationship: Every conversation is like meeting a new contractor
> — *[Letta Code comparison](https://github.com/letta-ai/letta-code)*

This means **hooks are the only tutoring channel available.** There is no persistent memory, no fine-tuning, no "the model learned from last time." If we don't shape behavior within the session, it doesn't get shaped at all.

## Quick Start

### 1. Clone / Copy

```bash
git clone https://github.com/YOUR_USERNAME/kimi-code-optimizations.git
cd kimi-code-optimizations
```

### 2. Install Hooks

```bash
# Copy hook scripts to ~/.kimi/hooks/
mkdir -p ~/.kimi/hooks ~/.kimi/state
cp hooks/shell-check.py hooks/strreplace-check.py hooks/batch-nudge.py \
   hooks/swarm-nudge-v2.py hooks/discovery-intercept.py \
   hooks/re-read-guard.py hooks/line-offset-enforcer.py \
   hooks/parallel-agent-guard.py hooks/shell-output-truncator.py ~/.kimi/hooks/

# Add to your ~/.kimi/config.toml
cat >> ~/.kimi/config.toml << 'EOF'

[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "python3 /home/evan/.kimi/hooks/shell-check.py"
timeout = 5

[[hooks]]
event = "PreToolUse"
matcher = "StrReplaceFile"
command = "python3 /home/evan/.kimi/hooks/strreplace-check.py"
timeout = 3

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile|Grep|Shell"
command = "python3 /home/evan/.kimi/hooks/discovery-intercept.py"
timeout = 2

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/re-read-guard.py"
timeout = 3

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/line-offset-enforcer.py"
timeout = 2

[[hooks]]
event = "PreToolUse"
matcher = "Agent"
command = "python3 /home/evan/.kimi/hooks/parallel-agent-guard.py"
timeout = 2

[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "python3 /home/evan/.kimi/hooks/shell-output-truncator.py"
timeout = 2

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /home/evan/.kimi/hooks/batch-nudge.py"
timeout = 2

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /home/evan/.kimi/hooks/swarm-nudge-v2.py"
timeout = 2
EOF

# Validate TOML
python3 -c "import tomllib; tomllib.load(open('/home/evan/.kimi/config.toml', 'rb')); print('Valid')"
```

> **Note:** Hooks load at session start. Start a **new** `kimi` conversation for them to take effect.

### 3. Install Helper Scripts

```bash
mkdir -p ~/bin
cp bin/apply-patch bin/make-patch bin/multi-read ~/bin/
chmod +x ~/bin/apply-patch ~/bin/make-patch ~/bin/multi-read

# Verify they're in PATH
echo $PATH | grep -q "$HOME/bin" || echo 'Add ~/bin to your PATH in ~/.bashrc'
```

### 4. Add AGENTS.md to Your Project

```bash
# Copy to your project root (or any directory you want these rules to apply)
cp AGENTS.md /path/to/your/project/
```

AGENTS.md is automatically read by Kimi Code CLI for all operations under its directory tree.

## What Each Piece Does

### AGENTS.md

Rules enforced at the prompt level:
- **File Discovery** → `Grep` first, `ReadFile` with `line_offset`, never `cat`/`grep` via Shell
- **Shell** → git/tests/builds only, never `cd`, use `git -C <path>` for cross-directory git
- **Batching** → Make parallel `Grep`/`ReadFile` calls in a single turn
- **Subagent Scope** → `coder` = one file/function, `explore` = one directory/concern
- **Swarm Pattern** → explore → chunk → parallel dispatch → poll → integrate
- **SSH** → Batch commands, no remote file reading, use `rsync` for editing
- **File Editing** → Decision table for when to use `StrReplaceFile` vs `WriteFile` vs `apply-patch`

### Hook: `shell-check.py` (Coaching — Recommended)

A PreToolUse hook that intercepts every `Shell` tool call and emits contextual 💡 tips to stderr:
- **Tips** on `cat`, `head`, `tail`, `find`, `grep`, `rg` → suggests `ReadFile` / `Glob` / `Grep`
- **Tips** on `cd` → suggests absolute paths or `git -C`
- **Positive reinforcement** for good Shell usage (`git`, `docker`, `pip`, complex pipelines)

Always exits 0 (non-blocking). The model sees the tip in the tool result and learns in real time.

**Quantitative results from 5h of sessions:**
- Tips fire on ~9% of Shell calls
- Sessions referencing AGENTS.md show **+10.3pp higher native tool usage** (44.6% vs 34.3%)
- **42% of tipped sessions** show reduced Shell usage after receiving a tip

### Hook: `shell-check-blocking.py` (Blocking — Aggressive)

The original blocking variant. Same detection logic but exits 2 to hard-reject:
- **Blocks** `cat`, `head`, `tail`, `find`, `grep`, `rg` (local file reading)
- **Blocks** `ssh host "cat file"` (remote file reading)
- **Warns** on `cd`

Use this if you want enforcement rather than coaching. Swap the filename in `config.toml` to switch modes.

### Hook: `strreplace-check.py`

A PreToolUse hook that intercepts every `StrReplaceFile` tool call:
- **Reads** the target file and checks whether the `old` string actually exists
- **Blocks** the call (exit 2) if the text is missing, with guidance to re-read the file
- **Fail-open** if the file can't be read (doesn't block on I/O errors)

This eliminates wasted turns where the model's remembered copy of a file has drifted from reality.

### Hook: `batch-nudge.py`

A PostToolUse hook that maintains a sliding window of recent tool calls per session:
- **Detects** 3+ sequential calls of the same tool type (`ReadFile`, `Grep`, `Shell`, `Agent`, `StrReplaceFile`)
- **Emits** a warning to stderr suggesting parallel batching
- **State** is stored in `~/.kimi/state/batch-tracker-<session_id>.json` (auto-cleaned, no persistent bloat)

This provides tactile feedback so the model learns to batch in real time.

### Hook: `swarm-nudge.py` (v1)

A PostToolUse hook that tracks overall session complexity and nudges toward subagent decomposition:
- **Detects** 6+ manual discovery calls (`ReadFile`/`Grep`) with no agents → suggests parallel `explore` agents
- **Detects** 12+ total tool calls with ≤1 agent → suggests swarm decomposition into `coder`/`explore` agents
- **Detects** 3+ sequential `Agent` calls without `run_in_background=true` → suggests parallel dispatch
- **Detects** complex multi-step `Shell` with no agents → suggests parallelizing via subagents
- **State** is stored in `~/.kimi/state/swarm-tracker-<session_id>.json`

This trains the model to think *swarm-first*: before doing work manually, ask "Can I delegate this to parallel subagents?"

### Hook: `swarm-nudge-v2.py` (Recommended)

An improved PostToolUse hook that fixes v1's biggest blind spot: **models that dispatch agents early, then fall back to manual work.**

**Why v1 fails:** In today's session logs, a model dispatched 4 background explore agents initially (good!), then did **72 sequential manual calls** afterward. v1 never fired because `agent_calls > 0`. The ratio was 15:1 manual-to-agent.

**What v2 tracks:**
- **Manual calls since last agent** — tips after 8+ manual calls in a row, even if agents were used earlier
- **Manual:agent ratio** — tips when ratio exceeds 5:1
- **Repeatable tips** — with cooldowns, so the model gets reminded throughout the session
- **Lowered thresholds** — catches waste earlier (4 calls instead of 6)

**State** is stored in `~/.kimi/state/swarm-tracker-v2-<session_id>.json`

### Hook: `discovery-intercept.py` (Aggressive)

A **PreToolUse** hook (not PostToolUse) that intercepts `ReadFile`/`Grep`/`Shell` calls **before they execute** once the model is in a manual work streak of 4+ calls.

Unlike PostToolUse hooks that say "you just wasted a turn," this asks "are you sure you want to do this manually?" **before** the turn is spent. Example output:

```
INTERCEPT: You're about to ReadFile 'src/auth.py' during a 6-call manual work streak.
Could this (and related files) be handled by a parallel explore/coder agent instead?
```

This is the most aggressive nudge in the toolkit. Use it if the model consistently falls back to manual discovery after initial agent usage.

**State** is stored in `~/.kimi/state/discovery-intercept-<session_id>.json`

### Hook: `re-read-guard.py` (Context Saver)

A **PreToolUse** hook that tracks every `ReadFile` call per session and warns when the model is about to re-read a file that hasn't changed.

**Why it matters:** After context compaction, the model forgets file contents. It re-reads files it already saw, burning thousands of tokens on unchanged data. In long sessions, re-reads can account for 15-30% of token waste.

**What it tracks:**
- **File path + mtime** — detects if the file changed since last read
- **line_offset + n_lines** — allows legitimate re-reads of different sections
- **Session-scoped state** — stored in `~/.kimi/state/file-reads-<session_id>.json`

**Example output:**
```
⚠️ CONTEXT GUARD: You already read 'src/auth.py' earlier in this session
(lines full file). The file has not changed since then. Re-reading it wastes
~2,400 tokens of context. Only re-read if you need a *different* section
(use line_offset).
```

Always exits 0 (non-blocking). The model sees the warning and can choose to skip the re-read or proceed if it truly needs the data.

### Hook: `line-offset-enforcer.py` (Context Saver)

A **PreToolUse** hook that detects `ReadFile` calls without `line_offset` on large files and nudges the model toward targeted reads.

**Why it matters:** Reading a 600-line file without `line_offset` burns ~15k tokens. After `Grep` finds a symbol on line 347, the model often reads the entire file instead of the relevant window.

**Mechanism:**
- Runs `wc -l` on the target file with a 1.5s timeout
- If the file is >250 lines and `line_offset` is missing → emit warning
- **Fail-open** on I/O errors or timeouts

**Example output:**
```
⚠️ CONTEXT GUARD: 'src/main.py' is 612 lines (~15,300 tokens). Reading the
entire file without line_offset wastes context. If you only need a section,
use ReadFile(path='src/main.py', line_offset=..., n_lines=...). If you truly
need the full file, proceed.
```

### Hook: `parallel-agent-guard.py` (Speed + Context)

A **PreToolUse** hook that intercepts sequential `Agent` dispatch and nudges toward parallel background execution.

**Why it matters:** Models often dispatch agents one at a time (`run_in_background=false` or missing), then wait for each to finish. This wastes wall-clock time and keeps both agent prompts in parent context longer than necessary.

**Mechanism:**
- Tracks the last tool call type per session
- If the current call is `Agent` and the previous call was also `Agent` without `run_in_background=true` → emit warning
- Allows background agents to pass through silently

**Example output:**
```
⚠️ PARALLEL GUARD: You're about to dispatch an agent sequentially.
If this agent is independent of the previous one, set run_in_background=true
and dispatch them together in the same turn.
```

**State** is stored in `~/.kimi/state/parallel-agent-guard-<session_id>.json`

### Hook: `shell-output-truncator.py` (Context Saver)

A **PreToolUse** hook that detects Shell commands likely to produce **unbounded output**.

**Why it matters:** `shell-check.py` guards against using Shell for the *wrong job* (file reading, discovery). This hook guards against using Shell for the *right job* but with *wrong flags* — commands that dump thousands of lines of unstructured text into context.

**Detects:**
- `git log` without `-n` or `--oneline`
- `journalctl` without `--since` or `-n`
- `docker logs` without `--tail`
- `find` without `-maxdepth`
- `pip list`, `npm ls`, `ps aux`, `dmesg`, `kubectl logs`
- `ls -R` (recursive listing)

**Example output:**
```
⚠️ OUTPUT GUARD: This Shell command may produce unbounded output:
  • git log without -n or --oneline can produce thousands of lines.
    Use git log --oneline -n 20 to limit output.
Unbounded command output silently burns context. Add filters before proceeding.
```

### `apply-patch` (`bin/apply-patch`)

A thin wrapper around GNU `patch` with built-in safety:
1. Reads unified diff from stdin
2. Validates with `--dry-run` first
3. Applies only if dry-run passes
4. Prints `M filename` summary on success
5. Exits non-zero with readable errors on failure

**Usage:**
```bash
# Write a patch file
WriteFile(path="/tmp/fix.patch", content="""
--- a/src/main.py
+++ b/src/main.py
@@ -10,7 +10,7 @@
 def old():
-    pass
+    return 42
""")

# Apply it
Shell(command="apply-patch < /tmp/fix.patch")
```

### `make-patch` (`bin/make-patch`)

Converts a simple `old` → `new` text replacement into a valid unified diff. Use it when you have a string replacement but want the safety of `apply-patch` (dry-run validation, proper context lines).

**Usage:**
```bash
# Generate patch from old/new pair
Shell(command="make-patch src/main.py --old 'def old():' --new 'def new():' > /tmp/fix.patch")

# Apply it
Shell(command="apply-patch < /tmp/fix.patch")
```

The tool validates that `old` exists in the file before generating the patch, so you get the same pre-validation as `strreplace-check.py`.

### `multi-read` (`bin/multi-read`)

Reads multiple files in a single Shell call. This is more efficient than N sequential ReadFile calls when you already know the paths (e.g., after a `Glob` discovery pass) and the files are small.

**Usage:**
```bash
Shell(command="multi-read README.md ARTICLE.md AGENTS.md config.toml.example")
```

**Caveats:**
- Only use for small files (< 100 KB each). For large files, use `Grep` + `ReadFile` with `line_offset`.
- The shell-check hook allows this because the command string doesn't contain `cat`; the script reads files internally.
- Returns formatted output with `--- FILE N: path ---` separators so the model can parse each file's contents.


## Known Bugs & Patches

### Background Subagents Bypass PreToolUse Hooks (Still needed in 1.40)

**Bug:** `BackgroundAgentRunner._run_core()` in Kimi CLI does **not** propagate the parent's `HookEngine` to the subagent soul, while the foreground runner does. This means background subagents (launched with `run_in_background=True`) completely bypass all PreToolUse hooks — including `shell-check.py` and `discovery-intercept.py`.

**Impact:** ~60% of blocked-pattern Shell calls in our quantitative analysis were slipping through via background subagents. This is especially bad for swarm-heavy workflows where most work runs in background agents.

**Patch:** `patches/background-subagent-hook-engine.patch`

Quick apply:
```bash
./scripts/apply-background-patch.sh
```

Or manual:
```bash
# Find your kimi-cli install path
KIMI_CLI=$(python3 -c "import kimi_cli; print(kimi_cli.__path__[0])")
patch -p0 -d / < patches/background-subagent-hook-engine.patch
```

Or apply manually by adding these 3 lines after `prepare_soul()` in `background/agent_runner.py`:
```python
# Propagate hook engine from parent runtime to subagent soul
if self._runtime.hook_engine is not None:
    soul.set_hook_engine(self._runtime.hook_engine)
```

**Upstream:** This should be filed with the Kimi CLI team. The foreground runner already does this at `subagents/runner.py:247`; background runner just missed it.

---

## Why Not Codex's `apply_patch`?

OpenAI Codex has a native `apply_patch` tool with 4-level fuzzy matching. We evaluated porting it but chose standard unified diff + `patch` because:
- Zero code to maintain (system `patch` is battle-tested)
- Model already understands git diff format
- `patch` has built-in fuzz tolerance (`-F` flag)
- Works immediately, no custom format to learn

If Kimi adds native `apply_patch` in the future, this workaround becomes obsolete.

## Project Structure

```
kimi-code-optimizations/
├── AGENTS.md                   # Project-level agent rules (Kimi)
├── README.md                   # This file
├── LICENSE                     # MIT
├── config.toml.example         # Kimi hook config snippet
├── bin/
│   ├── apply-patch             # Safe patch application helper
│   ├── make-patch              # Old/new → unified diff converter
│   └── multi-read              # Read multiple files in one Shell call
├── hooks/                      # Kimi Code CLI hooks
│   ├── shell-check.py          # PreToolUse: coach cat/grep/cd → native tools
│   ├── shell-check-blocking.py # PreToolUse: block cat/grep/cd (aggressive)
│   ├── strreplace-check.py     # PreToolUse: validate old string exists
│   ├── batch-nudge.py          # PostToolUse: detect sequential calls
│   ├── swarm-nudge.py          # PostToolUse: v1 total-count swarm detection
│   ├── swarm-nudge-v2.py       # PostToolUse: v2 streak-aware swarm detection
│   ├── discovery-intercept.py  # PreToolUse: intercept manual discovery streaks
│   ├── re-read-guard.py        # PreToolUse: warn on re-reading unchanged files
│   └── line-offset-enforcer.py # PreToolUse: nudge toward line_offset on large files
└── claude/                          # Claude Code CLI hooks
    ├── README.md                    # Claude-specific installation and diff table
    ├── settings.json.example        # Hook config snippet for ~/.claude/settings.json
    └── hooks/
        ├── edit-check.py            # PreToolUse: validate Edit old_string exists
        ├── re-read-guard.py         # PreToolUse: warn on re-reading unchanged files
        ├── parallel-agent-guard.py  # PreToolUse: plan-time nudge toward parallel Agent batching
        └── cheap-subagent-router.py # PreToolUse: triage subagent model (haiku/sonnet/opus)
```

## Requirements

**Kimi Code CLI:**
- Python 3.10+
- GNU `patch` 2.7+ (usually preinstalled on Linux/macOS)
- Kimi Code CLI 1.39+ (tested through 1.40.0)
- Hooks load at session start — start a **new** `kimi` conversation after installing

**Claude Code CLI:**
- Python 3.10+
- Claude Code CLI 2.x+
- Hooks load at session start — restart `claude` after modifying `settings.json`

## Optimal Config for Swarm-Heavy Workflows

If you're adopting the swarm-first approach, tune these `~/.kimi/config.toml` settings:

```toml
[loop_control]
# Allow long-running agent turns (default was 500, raised to 1000 in 1.40)
max_steps_per_turn = 1000

[background]
# Run more background agents in parallel (default is 10)
max_running_tasks = 15

# Don't kill slow agents prematurely (default is 1h)
agent_task_timeout_s = 7200
```

Higher `max_steps_per_turn` is critical for swarm workflows: a parent agent that dispatches 10 background coders, then polls them, then integrates results, can easily burn 200+ steps in one turn.

## License

MIT
