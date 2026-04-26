# Defaults

## File Discovery
- Use `Grep` to find symbols. Use `ReadFile` with `line_offset` to read code.
- Never use `ls`, `find`, `cat`, `head`, `tail`, `grep`, or `rg` via `Shell`.
- Batch `ReadFile` calls in parallel.

## Shell
- Shell is for git, tests, builds, and package managers only.
- Never `cd`. Use absolute or relative paths directly.
- For git in other directories: `git -C /path/to/repo <command>` instead of `cd /path/to/repo && git <command>`.

## Batching Native Tools
- Batch `Grep` calls in parallel when searching for multiple patterns or in multiple directories.
- Batch `ReadFile` calls in parallel when you need multiple files or multiple sections.
- Example: call `Grep` for symbols, `Grep` for imports, and `ReadFile` for the main file — all in one response.

## Agent Swarm
ALWAYS maximize use of agent swarms and parallel subagents. Sequential single-threaded execution is the exception, not the default.

- For any task involving >1 file, >1 concern, or estimated >5 minutes of work: use parallel subagents.
- Default pattern: 1 `explore` agent to inventory + N `coder` agents dispatched in parallel with `run_in_background=true`.
- Never do sequential Shell exploration when parallel agents can do it faster.
- The model should reach for `Agent` automatically — the user should never have to ask for parallelization.

## Subagent Scope
- `coder`: one file or one function per task.
- `explore`: one directory or one concern per task.

## Swarm Pattern (multi-file tasks)
1. `explore` to inventory what needs changing.
2. `SetTodoList` into single-file tasks.
3. **If `SetTodoList` has >3 items: dispatch parallel `coder` agents with `run_in_background=true`.**
   - Fewer than 3 items: you may handle sequentially if faster.
   - 3+ items: always parallelize. Sequential execution is wasteful.
4. Poll with `TaskList` / `TaskOutput`.
5. Final integration test only after all return.

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
