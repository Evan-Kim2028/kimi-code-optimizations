# We Spent 3,034 Tool Calls in 24 Hours. Then We Fixed Kimi Code CLI.

**What happens when you instrument an AI coding agent and actually look at the telemetry.**

We run a small engineering team building [SilphCo Analytics](https://silphcoanalytics.xyz) — a Pokemon TCG intelligence platform. We've been using Kimi Code CLI (the `kimi` command-line agent) for a few months. It's powerful. But power without telemetry is just burning API tokens in the dark.

So we instrumented it.

---

## What We Observed

In 24 hours across our team, Kimi Code CLI made **3,034 tool calls** across 87 conversation turns. Here's the breakdown:

| Metric | Value |
|--------|-------|
| Total tool calls | 3,034 |
| Shell commands | **63.5%** (1,929 calls) |
| ReadFile | 14% |
| Grep | **1.3%** |
| Navigation Shell (ls, find, cd) | 1,214 |
| SSH commands | 899 |
| SSH file-reading (cat, grep, ls) | **511 (57%)** |

### The Problems

**1. The `cd` Tax**

Every Shell tool call starts in a fresh process with no working directory inheritance. Subagents don't know where they are. So they burn turns on `cd` — sometimes looping back to the same directory 10+ times in one session.

```bash
cd backend/src && ls
cd .. && ls
cd frontend/src && ls
cd ../../backend/src && cat file.py  # We were just here
```

**2. `cat` and `grep` via Shell**

Kimi Code CLI has native `ReadFile` and `Grep` tools. They're faster, more precise, and don't spawn subprocesses. But the model defaults to Shell because it "feels" more natural — like a human in a terminal.

The result: `cat file.py | grep "foo"` instead of just calling `Grep`.

**3. SSH as a Slow REPL**

We deploy on a VPS. The agent would SSH in, run `cat`, disconnect, SSH in again, run `grep`, disconnect. 899 SSH connections in 24 hours. Over half were just reading files one by one.

**4. Subagent Timeouts Are False Negatives**

We launched 87 subagents. 18 were killed, 4 "failed." But when we forensically examined the sessions, **the work was correct** — the subagent just hit a 30-minute wall because it burned 200+ turns on navigation instead of using native tools.

**5. No `apply_patch`**

Kimi's primary edit primitive is `StrReplaceFile` — exact string replacement. For multi-hunk changes (editing a function signature *and* its caller), this means N fragile string matches instead of one unified diff. One character of drift and the whole edit fails.

Compare to OpenAI Codex: `apply_patch` is their most-used tool (282K invocations vs 2.7K for `write_file`).

---

## What We Built

### 1. AGENTS.md — Rules at the Prompt Level

We wrote a project-level instruction file that lives in our repo root. Kimi Code CLI reads it automatically at session start. It codifies efficient patterns:

- **File Discovery**: `Grep` first, `ReadFile` with `line_offset`. Never `cat`/`grep` via Shell.
- **Shell**: git/tests/builds only. Never `cd`. Use `git -C <path>` for cross-directory operations.
- **Batching**: Make parallel `Grep`/`ReadFile` calls in a single turn.
- **Subagent Scope**: `coder` = one file/function. `explore` = one directory.
- **SSH**: One script that dumps JSON, then parse locally. No remote `cat`.

### 2. PreToolUse Hook — Enforcement at Runtime

AGENTS.md is a suggestion. We wanted a guardrail.

Kimi Code CLI supports `PreToolUse` hooks in `~/.kimi/config.toml`. We wrote a Python script that intercepts every `Shell` call, reads the command from stdin JSON, and rejects the bad patterns:

```python
# Reject local file-reading
cmd = data.get("tool_input", {}).get("command", "")
if re.search(r"\b(cat|head|tail|find|grep|rg)\b", cmd):
    sys.exit(2)  # Block
```

Exit code 2 = block. The model gets an error message and learns to use `ReadFile`/`Grep` instead.

**One critical gotcha we hit:** The Kimi CLI passes tool data as **JSON on stdin**, not via environment variables. Our first attempt used `$KIMI_TOOL_ARGUMENTS_COMMAND` (which doesn't exist) and silently failed open. We rewrote it to parse stdin JSON.

### 3. apply-patch Helper — A Workaround for Missing Native Diff

Since Kimi doesn't have `apply_patch`, we built a thin Python wrapper around GNU `patch`:

```bash
apply-patch < fix.patch
```

It dry-runs first, then applies. It lives at `~/bin/apply-patch` and is documented in AGENTS.md as the tool for multi-hunk edits.

Why not port Codex's custom format? Codex uses a `*** Begin Patch` format with 4-level fuzzy matching. It's elegant but:
- Not published as a standalone crate
- Would require ~300 lines of Python to port
- Standard unified diff is already in every model's training data

Our workaround is 56 lines. It handles 80% of the value with 5% of the effort.

---

## Results

We haven't run a full 24-hour A/B yet, but the initial test on a real PR review (PR 342, 106 files changed) showed immediate improvements:

| Pattern | Before | After |
|---------|--------|-------|
| File discovery | `ls -R` + `cat` | `Grep` + `ReadFile` |
| Git across directories | `cd` + `git` | `git -C` |
| Multi-hunk edits | N× `StrReplaceFile` | `apply-patch` |
| Tool calls per review | ~200 (estimated) | ~50 (estimated) |

More importantly, the hook caught us in real time. During the review, we instinctively reached for `sed` to read a file section. The hook blocked it. We switched to `ReadFile` with `line_offset`.

That's the point: **the constraint forces the optimization.**

---

## The Broader Pattern

What we built isn't Kimi-specific. Every LLM coding agent has the same failure modes:

1. **Terminal emulation bias** — Models default to Shell because their training data is full of bash one-liners. Native tools are always faster.
2. **No working memory** — Fresh process per tool call means no cwd, no env, no venv. Claude Code solves this with shell snapshots. Codex solves it by passing `workdir` to `exec_command`. Kimi doesn't have this yet.
3. **Edit primitive mismatch** — String replacement is fine for 3-line fixes. For 50-line refactors, you need structured diffs.

If you're running an AI coding agent, instrument it. Look at your tool call distribution. If Shell is >50% of calls, you're probably leaving latency and accuracy on the table.

---

## Open Source

Everything is public:

**https://github.com/Evan-Kim2028/kimi-code-optimizations**

- `AGENTS.md` — Copy into your project root
- `hooks/shell-check.py` — Add to `~/.kimi/config.toml`
- `bin/apply-patch` — Put in `~/bin/`

MIT licensed. PRs welcome.

---

*Evan Kim runs engineering at SilphCo Analytics. He instruments things and then writes about the instrumentation.*
