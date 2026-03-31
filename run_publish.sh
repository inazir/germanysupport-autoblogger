#!/bin/bash

REPO_DIR="/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"
ENV_FILE="$REPO_DIR/.env"
LOG_DIR="$REPO_DIR/logs"
CACHE_DIR="$REPO_DIR/cache"
LOG_FILE="$LOG_DIR/cron.log"
PYTHON_BIN="/usr/bin/python3"
SCRIPT_FILE="$REPO_DIR/publish_article.py"
GIT_SYNC_SCRIPT="$REPO_DIR/run_git_sync.sh"

# Ensure required runtime directories exist
mkdir -p "$LOG_DIR"
mkdir -p "$CACHE_DIR"

# .env is mandatory for this project
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env file not found: $ENV_FILE" >> "$LOG_FILE"
  exit 1
fi

# Export variables from .env for the Python process and sync script
set -a
source "$ENV_FILE"
set +a

# If sourced, only load env and stop here
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

cd "$REPO_DIR" || {
  echo "ERROR: Failed to cd into $REPO_DIR" >> "$LOG_FILE"
  exit 1
}

echo "=== $(date '+%Y-%m-%d %H:%M:%S') === publish_article $* ===" >> "$LOG_FILE"

# Pre-sync: required.
# Reason: always publish from the latest repo state (fresh code + latest manual_topics.csv).
if [ ! -f "$GIT_SYNC_SCRIPT" ]; then
  echo "ERROR: Git sync script not found: $GIT_SYNC_SCRIPT" >> "$LOG_FILE"
  exit 1
fi

echo "[pre-sync] Starting git sync..." >> "$LOG_FILE"
bash "$GIT_SYNC_SCRIPT" >> "$LOG_FILE" 2>&1
PRE_SYNC_EXIT=$?

if [ "$PRE_SYNC_EXIT" -ne 0 ]; then
  echo "ERROR: Pre-sync failed with exit code $PRE_SYNC_EXIT. Publish aborted." >> "$LOG_FILE"
  exit $PRE_SYNC_EXIT
fi

echo "[pre-sync] Git sync completed successfully." >> "$LOG_FILE"

# Run the publish script and capture the real exit code immediately
"$PYTHON_BIN" "$SCRIPT_FILE" "$@" >> "$LOG_FILE" 2>&1
PUBLISH_EXIT=$?

echo "Publish exit: $PUBLISH_EXIT" >> "$LOG_FILE"

# Post-sync: run after publish to push local tracked changes
# such as manual_topics.csv status updates written by publish_article.py.
echo "[post-sync] Starting git sync..." >> "$LOG_FILE"
bash "$GIT_SYNC_SCRIPT" >> "$LOG_FILE" 2>&1
POST_SYNC_EXIT=$?

if [ "$POST_SYNC_EXIT" -ne 0 ]; then
  echo "ERROR: Post-sync failed with exit code $POST_SYNC_EXIT." >> "$LOG_FILE"
fi

# Final status:
# - If publish failed, return publish failure.
# - If publish succeeded but post-sync failed, return post-sync failure so cron shows a problem.
# - Otherwise return success.
if [ "$PUBLISH_EXIT" -ne 0 ]; then
  echo "Exit: $PUBLISH_EXIT" >> "$LOG_FILE"
  exit $PUBLISH_EXIT
fi

if [ "$POST_SYNC_EXIT" -ne 0 ]; then
  echo "Exit: $POST_SYNC_EXIT" >> "$LOG_FILE"
  exit $POST_SYNC_EXIT
fi

echo "Exit: 0" >> "$LOG_FILE"
exit 0