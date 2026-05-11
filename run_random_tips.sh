#!/usr/bin/env bash
# run_random_tips.sh
# ---------------------------------------------------------------------------
# Wrapper for social/share_random_tips.py
# ---------------------------------------------------------------------------

set -euo pipefail

# Resolve repo root (directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if available (safe for cron usage)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -o allexport
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +o allexport
fi

# Default Python
PYTHON="${PYTHON:-python3}"

# Ensure log directory exists
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"

# Log file
LOG_FILE="$LOG_DIR/social_run_random_tips.log"
touch "$LOG_FILE"

# Simple + portable logging (NO /dev/fd dependency)
exec >> "$LOG_FILE" 2>&1

echo "=================================================================="
echo "[run_random_tips] Starting at $(date '+%Y-%m-%d %H:%M:%S')"
echo "[run_random_tips] Script: $0"
echo "[run_random_tips] Args: $*"
echo "[run_random_tips] Provider: ${TIPS_LLM_PROVIDER:-anthropic}"
echo "[run_random_tips] Language: ${TIPS_LLM_LANGUAGE:-en}"
echo "=================================================================="

# Run Python module
"$PYTHON" -m social.share_random_tips "$@"

echo "[run_random_tips] Finished at $(date '+%Y-%m-%d %H:%M:%S')"
echo ""