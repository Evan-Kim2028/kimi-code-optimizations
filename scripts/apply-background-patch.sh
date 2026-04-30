#!/usr/bin/env bash
# Auto-apply the background subagent hook engine patch.
# This patch fixes a bug where background subagents bypass PreToolUse hooks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="$SCRIPT_DIR/../patches/background-subagent-hook-engine.patch"

# Find kimi-cli installation
KIMI_PYTHON="${KIMI_PYTHON:-python3}"
KIMI_PATH=$("$KIMI_PYTHON" -c "import kimi_cli; print(kimi_cli.__path__[0])" 2>/dev/null) || true

if [[ -z "$KIMI_PATH" ]]; then
    # Try common uv install paths
    for p in /home/evan/.local/share/uv/tools/kimi-cli/lib/python*/site-packages/kimi_cli; do
        if [[ -d "$p" ]]; then
            KIMI_PATH="$p"
            break
        fi
    done
fi

if [[ -z "$KIMI_PATH" ]]; then
    echo "ERROR: Could not find kimi-cli installation." >&2
    echo "Set KIMI_PYTHON to the Python interpreter that has kimi_cli installed." >&2
    exit 1
fi

echo "Found kimi-cli at: $KIMI_PATH"
echo "Patch file: $PATCH_FILE"

TARGET_FILE="$KIMI_PATH/background/agent_runner.py"

if [[ ! -f "$TARGET_FILE" ]]; then
    echo "ERROR: Expected file not found: $TARGET_FILE" >&2
    exit 1
fi

# Check if already patched
if grep -q "Propagate hook engine from parent runtime to subagent soul" "$TARGET_FILE"; then
    echo "Already patched. Skipping."
    exit 0
fi

# Apply patch
cd "$KIMI_PATH"
if patch -p0 -d / < "$PATCH_FILE"; then
    echo "Patch applied successfully."
else
    echo "ERROR: Patch failed. You may need to apply it manually." >&2
    echo "See: $PATCH_FILE" >&2
    exit 1
fi
