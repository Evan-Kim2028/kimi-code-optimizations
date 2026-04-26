# Defaults

## Parallel Execution First

**Before doing any work, decide the execution strategy.**

The default is NOT to respond directly. The default is to parallelize.

### Decision Gate (run this before every non-trivial request)

| Question | If YES → | If NO → |
|----------|----------|---------|
| Does this involve more than 1 file? | Use parallel subagents | Continue below |
| Does this need exploration before I know what to change? | Use an `explore` agent first | Continue below |
| Will this take more than 2 sequential tool calls? | Use parallel subagents | Direct response is OK |
| Is this a simple Q&A with no file changes? | Direct response is OK | — |

**Rule of thumb: If you need more than 2 tool calls to complete the task, default to parallel subagents.**

Sequential single-threaded execution is the **exception**, not the default. The model should reach for `Agent` automatically — the user should never have to ask for parallelization.

### Default Swarm Pattern

For any task involving >1 file, >1 concern, or estimated >5 minutes of work:

1. **Dispatch parallel `explore` agents** for discovery. Do NOT Grep/ReadFile solo across multiple concerns — delegate each research thread to a separate agent.
2. **`SetTodoList`** into single-file tasks based on findings.
3. **If `SetTodoList` has >3 items: dispatch parallel `coder` agents with `run_in_background=true`.**
   - Fewer than 3 items: you may handle sequentially if faster.
   - 3+ items: always parallelize. Sequential execution is wasteful.
4. **Poll** with `TaskList` / `TaskOutput`.
5. **Final integration test** only after all return.

**Research is work too.** If the user asks you to investigate multiple things (e.g., "how does auth work AND how does billing work"), do not do two sequential Grep/ReadFile passes. Dispatch two `explore` agents in parallel.

### Subagent Scope

- `coder`: one file or one function per task.
- `explore`: one directory or one concern per task.

## File Discovery

- **For single-concern lookups**: Use `Grep` to find symbols. Use `ReadFile` with `line_offset` to read code.
- **For multi-concern research**: Dispatch parallel `explore` agents instead of doing sequential Grep/ReadFile yourself.
- Never use `ls`, `find`, `cat`, `head`, `tail`, `grep`, or `rg` via `Shell`.
- Batch `ReadFile` calls in parallel.

## Shell

- Shell is for git, tests, builds, and package managers only.
- Never `cd`. Use absolute or relative paths directly.
- For git in other directories: `git -C /path/to/repo <command>` instead of `cd /path/to/repo && git <command>`.

## Batching Native Tools

Batching is for when you are doing direct work on a **single concern**. If you have multiple independent concerns, use parallel agents instead.

- Batch `Grep` calls in parallel when searching for multiple patterns in the **same logical concern**.
- Batch `ReadFile` calls in parallel when you need multiple files for the **same task**.
- For multiple small files (e.g., configs after a `Glob` pass), use `multi-read file1 file2 file3` in one `Shell` call instead of N `ReadFile` calls.
- Example (single concern): call `Grep` for symbols, `Grep` for imports, and `ReadFile` for the main file — all in one response.
- Example (multiple concerns): dispatch 2 `explore` agents — one for auth, one for billing — in parallel.

## SSH / Remote Servers

- Never use SSH for file reading (`cat`, `grep`, `head`, `tail`, `ls`, `find`, `sed`).
- For remote discovery: run ONE script over SSH that dumps JSON/CSV, then parse locally.
- For remote editing: sync files with `rsync`, edit locally, sync back.
- For service management: write a single deploy script on the server, invoke it once.
- Batch SSH commands into a single multi-line script instead of many individual calls.

## File Editing

Choose the right tool for the edit size and shape:

| Situation | Tool | Why |
|-----------|------|-----|
| Single small change (≤5 lines) | `StrReplaceFile` | Fast, exact, no temp files |
| Full file rewrite | `WriteFile` | Cleanest when replacing entire contents |
| Multi-hunk change (>1 location in a file) | `apply-patch` | One tool call instead of N `StrReplaceFile` calls; dry-run built-in |
| Delete a file | `Shell` (`rm path`) | Simplest |

### StrReplaceFile Pre-Validation

A `PreToolUse` hook validates that the `old` string actually exists in the target file **before** the tool call is sent. If the text has drifted (whitespace, line endings, or the file changed), the call is blocked with a clear error so you can re-read the file instead of wasting a turn on a guaranteed failure.

### `make-patch` Helper

If you have an `old`/`new` pair but the replacement spans multiple hunks, use `make-patch` to convert it to a unified diff:

```bash
make-patch path/to/file --old "original text" --new "replacement text" > /tmp/fix.patch
apply-patch < /tmp/fix.patch
```

This avoids manual diff formatting. The hook validates that `old` exists in the file before generating the patch.

### Using `patch` for Multi-Hunk Edits

When a file needs changes in multiple places, generate a standard unified diff and apply it via the `apply-patch` helper:

1. **Write the patch** to a temp file with `WriteFile`:
   ```diff
   --- a/src/module.py
   +++ b/src/module.py
   @@ -10,7 +10,7 @@
    def old_func():
   -    pass
   +    return 42

    def another():
        x = 1
   @@ -25,3 +25,6 @@
    def third():
        pass
   +
   +def new_func():
   +    return 123
   ```

2. **Apply with the helper** (dry-run is built-in):
   ```bash
   apply-patch < /tmp/fix.patch
   ```

Rules for generating patches:
- Use `--- a/path` and `+++ b/path` headers (run from project root)
- Preserve context lines exactly — do not modify them
- Use at least 3 lines of context around each hunk
- For new files: `--- /dev/null` / `+++ b/path`
- For deletions: use `rm path` instead of a patch

The helper lives at `~/bin/apply-patch`. It validates with `--dry-run` first, then applies. It exits non-zero on failure with clear error messages.

## Shared Environment Awareness

- You are not the only agent or user in this repo or on this server.
- Do not assume exclusive access to files, branches, ports, or processes.
- Check before overwriting: `git status`, process lists, port usage.
- Do not spam servers with rapid sequential SSH connections — batch and rate-limit.
- Stash or backup before destructive operations. Prefer atomic changes.
