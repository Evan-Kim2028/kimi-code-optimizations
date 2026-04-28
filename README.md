# Kimi Code CLI Optimizations

A productivity toolkit for [Kimi Code CLI](https://github.com/moonshot-ai/kimi-cli) — enforcing efficient tool usage, adding a safe `apply_patch` workaround, and eliminating wasted turns on file-navigation busywork.

## What's This?

Kimi Code CLI is a powerful AI coding agent, but like all LLM-based tools, it can burn turns on inefficient patterns:
- `ls -R` + `cat` instead of native `Grep`/`ReadFile`
- `cd` loops because subagents don't inherit working directory
- SSH sessions used as slow REPLs for remote file reading
- Fragile `StrReplaceFile` for multi-hunk edits

This repo gives you:
1. **`AGENTS.md`** — Project-level rules that guide the model toward efficient patterns
2. **`hooks/shell-check.py`** — PreToolUse hook that coaches the model away from `cat`/`grep`/`cd` in Shell calls (tips, non-blocking)
2b. **`hooks/shell-check-blocking.py`** — Aggressive variant that **blocks** `cat`/`grep`/`cd` entirely (exit 2)
3. **`hooks/strreplace-check.py`** — PreToolUse hook that validates `StrReplaceFile` `old` strings exist before the tool fires (blocks guaranteed-fail turns)
4. **`hooks/batch-nudge.py`** — PostToolUse hook that detects sequential similar calls and emits real-time batching tips
5. **`bin/apply-patch`** — Safe unified-diff application with built-in dry-run
6. **`bin/make-patch`** — Converts `old`/`new` text pairs into valid unified diffs (no manual line-number math)
7. **`bin/multi-read`** — Reads multiple files in one Shell call (bypasses N sequential ReadFile calls for small files)

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
cp hooks/shell-check.py hooks/strreplace-check.py hooks/batch-nudge.py ~/.kimi/hooks/

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
event = "PostToolUse"
matcher = ".*"
command = "python3 /home/evan/.kimi/hooks/batch-nudge.py"
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

### Background Subagents Bypass PreToolUse Hooks (Fixed)

**Bug:** `BackgroundAgentRunner._run_core()` in Kimi CLI does **not** propagate the parent's `HookEngine` to the subagent soul, while the foreground runner does. This means background subagents (launched with `run_in_background=True`) completely bypass all PreToolUse hooks — including `shell-check.py`.

**Impact:** ~60% of blocked-pattern Shell calls in our quantitative analysis were slipping through via background subagents.

**Patch:** `patches/background-subagent-hook-engine.patch`

Apply to your Kimi CLI installation:
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
├── AGENTS.md                 # Project-level agent rules
├── README.md                 # This file
├── LICENSE                   # MIT
├── config.toml.example       # Hook config snippet
├── bin/
│   ├── apply-patch           # Safe patch application helper
│   ├── make-patch            # Old/new → unified diff converter
│   └── multi-read            # Read multiple files in one Shell call
└── hooks/
    ├── shell-check.py        # PreToolUse hook: coach cat/grep/cd
    ├── shell-check-blocking.py # PreToolUse hook: block cat/grep/cd (aggressive)
    ├── strreplace-check.py   # PreToolUse hook: validate old string exists
    └── batch-nudge.py        # PostToolUse hook: detect sequential calls
```

## Requirements

- Python 3.10+
- GNU `patch` 2.7+ (usually preinstalled on Linux/macOS)
- Kimi Code CLI 1.39+

> **Note:** The hooks load at session start. Start a **new** `kimi` conversation after installing them.

## License

MIT
