#!/usr/bin/env bash
# Auto-discover Python path if missing
command -v python3 >/dev/null || export PATH="$(ls -d /opt/alt/python3*/bin 2>/dev/null | sort -V | tail -n 1):$PATH"
# scripts/run_viral_posts.sh
# ---------------------------------------------------------------------------
# Wrapper for social/share_viral_posts.py
# Drop-in companion to run_random_tips.sh
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$REPO_ROOT/.env" ]; then
    set -o allexport
    source "$REPO_ROOT/.env"
    set +o allexport
fi

PYTHON="${PYTHON:-python3}"
LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs}"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/social_viral_posts.log"
touch "$LOG_FILE"
tail -n 400 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
exec >> "$LOG_FILE" 2>&1

echo "=================================================================="
echo "[run_viral_posts] Starting at $(date '+%Y-%m-%d %H:%M:%S')"
echo "[run_viral_posts] Args: $*"
echo "[run_viral_posts] Provider: ${VIRAL_LLM_PROVIDER:-anthropic}"
VIRAL_LANGUAGE="${VIRAL_LLM_LANGUAGE:-bn}"
echo "[run_viral_posts] Language: $VIRAL_LANGUAGE"
echo "=================================================================="

"$PYTHON" -m social.share_viral_posts --language "$VIRAL_LANGUAGE" "$@"

echo "[run_viral_posts] Finished at $(date '+%Y-%m-%d %H:%M:%S')"
echo "" 