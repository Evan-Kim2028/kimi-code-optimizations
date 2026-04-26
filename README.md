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
2. **`hooks/shell-check.py`** — A PreToolUse hook that rejects `cat`/`grep`/`cd` in Shell calls
3. **`bin/apply-patch`** — A unified-diff helper that replaces fragile string replacement for multi-hunk edits

## Quick Start

### 1. Clone / Copy

```bash
git clone https://github.com/YOUR_USERNAME/kimi-code-optimizations.git
cd kimi-code-optimizations
```

### 2. Install the Hook

```bash
# Copy hook script to ~/.kimi/hooks/
mkdir -p ~/.kimi/hooks
cp hooks/shell-check.py ~/.kimi/hooks/

# Add to your ~/.kimi/config.toml
cat >> ~/.kimi/config.toml << 'EOF'

[[hooks]]
event = "PreToolUse"
matcher = "Shell"
command = "python3 /home/evan/.kimi/hooks/shell-check.py"
timeout = 5
EOF

# Validate TOML
python3 -c "import tomllib; tomllib.load(open('/home/evan/.kimi/config.toml', 'rb')); print('Valid')"
```

> **Note:** The hook loads at session start. Start a **new** `kimi` conversation for it to take effect.

### 3. Install apply-patch Helper

```bash
mkdir -p ~/bin
cp bin/apply-patch ~/bin/
chmod +x ~/bin/apply-patch

# Verify it's in PATH
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

### Hook (`hooks/shell-check.py`)

A PreToolUse hook that intercepts every `Shell` tool call:
- **Blocks** `cat`, `head`, `tail`, `find`, `grep`, `rg` (local file reading)
- **Blocks** `ssh host "cat file"` (remote file reading)
- **Warns** on `cd` (suggests `git -C` or absolute paths)

The hook reads JSON from stdin (Kimi CLI passes tool call data) and exits 2 to block.

### apply-patch (`bin/apply-patch`)

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
│   └── apply-patch           # Safe patch application helper
└── hooks/
    └── shell-check.py        # PreToolUse hook script
```

## Requirements

- Python 3.10+
- GNU `patch` 2.7+ (usually preinstalled on Linux/macOS)
- Kimi Code CLI 1.39+

## License

MIT
