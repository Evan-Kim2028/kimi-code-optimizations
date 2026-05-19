# Agent Harness Optimizations

A productivity toolkit for the [Kimi Code CLI](https://github.com/moonshot-ai/kimi-cli) — enforcing efficient tool usage, parallel dispatch, and cost-aware subagent routing through harness-level hooks. The patterns generalize to any harness with a PreToolUse/PostToolUse hook system (Codex, Cursor, Gemini CLI, OpenHands).

> Previously `kimi-code-optimizations`. Focused on Kimi Code CLI; patterns may generalize.

## What's This?

AI coding agents are powerful, but they burn turns on inefficient patterns: cat'ing files instead of using a structured Read tool, dispatching subagents serially instead of in parallel, defaulting to the most expensive model for cheap discovery work. The patterns differ by harness, but the fix is the same: **hooks as in-conversation training signals** that redirect behavior in real time.

This repo provides:

- **[`hooks/`](#kimi-code-cli-hooks) + [`bin/`](#helper-scripts)** — Kimi Code CLI suite (Shell coaching, StrReplaceFile validation, swarm nudges, context guards)

---

## Kimi Code CLI Hooks

Kimi's inefficient patterns:
- `ls -R` + `cat` instead of native `Grep`/`ReadFile`
- `cd` loops because subagents don't inherit working directory
- SSH sessions used as slow REPLs for remote file reading
- Fragile `StrReplaceFile` exact-match edits that fail on any context drift

This repo gives you:
1. **`AGENTS.md`** — Project-level rules that guide the model toward efficient patterns
2. **`hooks/kimi/shell-check.py`** — PreToolUse hook that coaches the model away from `cat`/`grep`/`cd` in Shell calls (tips, non-blocking)
2b. **`hooks/kimi/shell-check-blocking.py`** — Aggressive variant that **blocks** `cat`/`grep`/`cd` entirely (exit 2)
3. **`hooks/kimi/strreplace-check.py`** — PreToolUse hook that validates `StrReplaceFile` `old` strings exist before the tool fires (blocks guaranteed-fail turns)
4. **`hooks/kimi/batch-nudge.py`** — PostToolUse hook that detects sequential similar calls and emits real-time batching tips
5. **`hooks/kimi/swarm-nudge.py`** — PostToolUse hook that detects complex manual work and nudges toward subagent swarm decomposition
6. **`hooks/kimi/swarm-nudge-v2.py`** — Improved swarm nudge that tracks manual work *since last agent* (catches the "agent bait-and-switch" pattern where models dispatch agents early then grind manually)
7. **`hooks/kimi/discovery-intercept.py`** — PreToolUse hook that intercepts ReadFile/Grep/Shell calls during long manual streaks and asks "should this be an agent?" *before* the call fires
8. **`hooks/kimi/re-read-guard.py`** — PreToolUse hook that warns when the model re-reads an unchanged file this session
9. **`hooks/kimi/line-offset-enforcer.py`** — PreToolUse hook that nudges toward `line_offset` on large file reads
10. **`hooks/kimi/parallel-agent-guard-v2.py`** — Enhanced PreToolUse hook with timestamp-based same-turn detection and escalating warnings for sequential agent dispatch
11. **`hooks/kimi/background-agent-nudge.py`** — PreToolUse hook that suggests `run_in_background=true` for discovery/explore tasks
12. **`hooks/kimi/todo-persistence-check.py`** — PostToolUse hook that detects todo list resets and encourages incremental updates
13. **`hooks/kimi/taskoutput-guard.py`** — PreToolUse hook that ensures `TaskList` is called before `TaskOutput` polling
14. **`hooks/kimi/re-read-turn-guard.py`** — PostToolUse hook that guards against excessive same-turn file re-reads
15. **`bin/apply-patch`** — Safe unified-diff application with built-in dry-run
11. **`bin/make-patch`** — Converts `old`/`new` text pairs into valid unified diffs (no manual line-number math)
12. **`bin/multi-read`** — Reads multiple files in one Shell call (bypasses N sequential ReadFile calls for small files)

---

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

An independent [analysis of exfiltrated system prompts](https://www.dbreunig.com/2026/02/10/system-prompts-define-the-agent-as-much-as-the-model.html) across multiple CLI coding agents found that **all of them need explicit system-prompt instructions to parallelize**. Kimi's own system prompt states, "you are HIGHLY RECOMMENDED to make [tool calls] in parallel."

> This likely reflects the fact that most post-training reasoning and agentic examples are **serial** in nature… system prompts need to override this training.

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
git clone https://github.com/YOUR_USERNAME/agent-harness-optimizations.git
cd agent-harness-optimizations
```

### 2. Install Hooks

```bash
# Copy hook scripts to ~/.kimi/hooks/
mkdir -p ~/.kimi/hooks ~/.kimi/state
cp hooks/kimi/shell-check.py hooks/kimi/strreplace-check.py hooks/kimi/batch-nudge.py \
   hooks/kimi/swarm-nudge-v2.py hooks/kimi/discovery-intercept.py \
   hooks/kimi/re-read-guard.py hooks/kimi/line-offset-enforcer.py \
   hooks/kimi/parallel-agent-guard.py hooks/kimi/shell-output-truncator.py ~/.kimi/hooks/

# Add to your ~/.kimi/config.toml
cat >> ~/.kimi/config.toml << 'EOF'

[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "python3 /home/evan/.kimi/hooks/kimi/shell-check.py"
timeout = 5

[[hooks]]
event = "PreToolUse"
matcher = "StrReplaceFile"
command = "python3 /home/evan/.kimi/hooks/kimi/strreplace-check.py"
timeout = 3

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile|Grep|Shell"
command = "python3 /home/evan/.kimi/hooks/kimi/discovery-intercept.py"
timeout = 2

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/kimi/re-read-guard.py"
timeout = 3

[[hooks]]
event = "PreToolUse"
matcher = "ReadFile"
command = "python3 /home/evan/.kimi/hooks/kimi/line-offset-enforcer.py"
timeout = 2

[[hooks]]
event = "PreToolUse"
matcher = "Agent"
command = "python3 /home/evan/.kimi/hooks/kimi/parallel-agent-guard.py"
timeout = 2

[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "python3 /home/evan/.kimi/hooks/kimi/shell-output-truncator.py"
timeout = 2

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /home/evan/.kimi/hooks/kimi/batch-nudge.py"
timeout = 2

[[hooks]]
event = "PostToolUse"
matcher = ".*"
command = "python3 /home/evan/.kimi/hooks/kimi/swarm-nudge-v2.py"
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

### Hook: `parallel-agent-guard-v2.py` (Speed + Context)

An enhanced **PreToolUse** hook that intercepts sequential `Agent` dispatch and nudges toward parallel background execution.

**Why it matters:** Models often dispatch agents one at a time (`run_in_background=false` or missing), then wait for each to finish. This wastes wall-clock time and keeps both agent prompts in parent context longer than necessary.

**v2 improvements:**
- **Timestamp-based same-turn detection**: If two `Agent` calls arrive within 3 seconds, they're assumed to be in the same turn (legitimate parallel dispatch) and no warning is emitted. This avoids false positives.
- **Escalating warnings**: First sequential dispatch gets a gentle tip; third consecutive sequential dispatch gets an urgent warning.
- **Explicit batching example**: The warning now shows the exact pattern for dispatching multiple agents in one turn.

**Example output:**
```
⚠️ PARALLEL GUARD: You're about to dispatch an agent sequentially.
If this agent is independent of the previous one, set run_in_background=true
and dispatch them together in the same turn.
Sequential agent dispatch wastes wall-clock time and keeps both agent prompts
in parent context longer than necessary.
```

**State** is stored in `~/.kimi/state/parallel-agent-guard-v2-<session_id>.json`

### Hook: `background-agent-nudge.py` (Speed + Context)

A **PreToolUse** hook that suggests `run_in_background=true` for agents that appear to be doing independent discovery or analysis work.

**Why it matters:** Data from session logs shows **71.5% of agents run in foreground** even when they're clearly independent tasks (exploration, audits, analysis). Foreground agents block the parent for no reason.

**Mechanism:**
- Scores agent prompts for independence using keyword heuristics
- Discovery keywords (`explore`, `audit`, `analyze`, `investigate`) increase the score
- Dependent keywords (`fix`, `then`, `after that`, `before proceeding`) decrease the score
- If score ≥ 2 and `run_in_background` is false/missing → emit nudge
- Capped at 5 tips per session to avoid spam

**Example output:**
```
💡 BACKGROUND NUDGE: This agent looks like independent discovery keywords:
explore, investigate. Consider run_in_background=true so the parent can
continue working or dispatch other agents while it runs. Exploration, audits,
and analysis are almost always safe to background.
```

**State** is stored in `~/.kimi/state/background-agent-nudge-<session_id>.json`

### Hook: `todo-persistence-check.py` (Plan Stability)

A **PostToolUse** hook that detects when `SetTodoList` completely replaces a list that had completed items, destroying completion history.

**Why it matters:** Session log analysis shows models frequently rebuild todo lists from scratch mid-session (e.g., 7 items done → suddenly 5 new items with 0 done). This creates plan instability and loses progress tracking.

**Detects:**
- **Todo reset**: Previous list had ≥2 done items; new list has 0 done but >0 pending/in_progress
- **Todo shrink**: List got smaller by 2+ items without any new completions (silent task dropping)

**Example output:**
```
⚠️ TODO RESET: You just replaced a list with 4 completed tasks with a fresh
list of 5 new items. This destroys completion history. Prefer updating
individual item statuses or adding new items to the existing list.
```

**State** is stored in `~/.kimi/state/todo-persistence-<session_id>.json`

### Hook: `taskoutput-guard.py` (Efficient Polling)

A **PreToolUse** hook that ensures `TaskList` is called before `TaskOutput` when polling background tasks.

**Why it matters:** 29% of sessions that poll background tasks call `TaskOutput` without first checking `TaskList`. This wastes turns polling task IDs that may have crashed, completed, or never started.

**Mechanism:**
- Tracks the last 15 tool calls in a sliding window
- If `TaskOutput` is called with no `TaskList` in the recent window → emit warning
- Capped at 5 tips per session

**Example output:**
```
⚠️ TASK POLL GUARD: You're about to call TaskOutput without checking which
tasks are active first. Call TaskList to verify running tasks, then TaskOutput
only for active ones. This prevents polling stale/crashed tasks.
```

**State** is stored in `~/.kimi/state/taskoutput-guard-<session_id>.json`

### Hook: `re-read-turn-guard.py` (Context Saver)

A **PostToolUse** hook that guards against reading the same file multiple times within a short sliding window of recent calls.

**Why it matters:** Session logs show up to **124 same-turn file re-reads** in a single session. The session-level `re-read-guard.py` catches across-session re-reads; this catches intra-turn storms where the model repeatedly reads the same file before the context even changes.

**Mechanism:**
- Maintains a sliding window of the last 20 `ReadFile` calls
- Warns when the same file is read ≥3 times in the window
- Only warns once per threshold crossing (not on every subsequent read)

**Example output:**
```
⚠️ TURN REREAD GUARD: You've read 'src/auth.py' 3 times in recent calls.
Are you re-reading because you forgot the content? Store key findings in your
reasoning or use line_offset for targeted sections. Repeated full-file reads
waste context.
```

**State** is stored in `~/.kimi/state/turn-reads-<session_id>.json`

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
agent-harness-optimizations/
├── AGENTS.md                   # Project-level agent rules (Kimi)
├── README.md                   # This file
├── LICENSE                     # MIT
├── config.toml.example         # Kimi hook config snippet
├── bin/
│   ├── apply-patch             # Safe patch application helper
│   ├── make-patch              # Old/new → unified diff converter
│   └── multi-read              # Read multiple files in one Shell call
├── hooks/
│   ├── kimi/                       # Kimi Code CLI hooks
│   │   ├── shell-check.py          # PreToolUse: coach cat/grep/cd → native tools
│   │   ├── shell-check-blocking.py # PreToolUse: block cat/grep/cd (aggressive)
│   │   ├── strreplace-check.py     # PreToolUse: validate old string exists
│   │   ├── batch-nudge.py          # PostToolUse: detect sequential calls
│   │   ├── swarm-nudge.py          # PostToolUse: v1 total-count swarm detection
│   │   ├── swarm-nudge-v2.py       # PostToolUse: v2 streak-aware swarm detection
│   │   ├── discovery-intercept.py  # PreToolUse: intercept manual discovery streaks
│   │   ├── re-read-guard.py        # PreToolUse: warn on re-reading unchanged files
│   │   ├── line-offset-enforcer.py # PreToolUse: nudge toward line_offset on large files
│   │   ├── parallel-agent-guard-v2.py  # PreToolUse: v2 sequential agent guard with same-turn detection
│   │   ├── background-agent-nudge.py   # PreToolUse: nudge toward background for discovery agents
│   │   ├── todo-persistence-check.py   # PostToolUse: detect todo list resets
│   │   ├── taskoutput-guard.py         # PreToolUse: ensure TaskList before TaskOutput
│   │   └── re-read-turn-guard.py       # PostToolUse: guard same-turn re-read storms

```

## Requirements

**Kimi Code CLI:**
- Python 3.10+
- GNU `patch` 2.7+ (usually preinstalled on Linux/macOS)
- Kimi Code CLI 1.39+ (tested through 1.40.0)
- Hooks load at session start — start a **new** `kimi` conversation after installing

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
