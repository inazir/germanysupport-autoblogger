#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/social_from_existing.log"
mkdir -p "$LOG_DIR"

touch "$LOG_FILE"

tmp="$(mktemp)"
tail -n 300 "$LOG_FILE" > "$tmp" && mv "$tmp" "$LOG_FILE"

exec >> "$LOG_FILE" 2>&1

cd "$REPO_DIR"

if [ -f ".env" ]; then
    set -a
    . ./.env
    set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

# Defaults for this script
export SOCIAL_EXISTING_TARGETS="${SOCIAL_EXISTING_TARGETS:-gs_fb_main,gs_ig_main}"
export SOCIAL_EXISTING_ONLY_ENGLISH="${SOCIAL_EXISTING_ONLY_ENGLISH:-true}"
export SOCIAL_DB_PATH="${SOCIAL_DB_PATH:-social/cache/social.db}"

# --- Logging Separator and Timestamp ---
echo "" >> "$LOG_FILE"
echo "===============================================================================" >> "$LOG_FILE"
echo "NEW EXECUTION START: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "===============================================================================" >> "$LOG_FILE"

# 1. Execute the Social Script
"$PYTHON_BIN" social_from_existing.py --only-english "$@" >> "$LOG_FILE" 2>&1

# 2. Cache Cleanup
echo "LOG: Starting cache cleanup (older than 7 days)..." >> "$LOG_FILE"

CACHE_DIRS=(
    "$REPO_DIR/social/cache/generated_images"
    "$REPO_DIR/social/cache/generated_videos"
)

for DIR in "${CACHE_DIRS[@]}"; do
    if [ -d "$DIR" ]; then
        find "$DIR" -mindepth 1 -mtime +7 -exec rm -rf {} + >> "$LOG_FILE" 2>&1
    fi
done

echo "LOG: Cleanup finished." >> "$LOG_FILE"