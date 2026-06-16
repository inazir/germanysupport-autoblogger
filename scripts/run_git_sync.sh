#!/bin/bash
# Auto-discover Python path if missing
command -v python3 >/dev/null || export PATH="$(ls -d /opt/alt/python3*/bin 2>/dev/null | sort -V | tail -n 1):$PATH"

REPO_DIR="/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"
ENV_FILE="$REPO_DIR/.env"
LOG_DIR="$REPO_DIR/logs"
CACHE_DIR="$REPO_DIR/cache"
LOG_FILE="$LOG_DIR/git_sync.log"
SYNC_FILE="manual_topics.csv"

# Ensure runtime directories exist
mkdir -p "$LOG_DIR"
mkdir -p "$CACHE_DIR"

# .env is mandatory in your setup
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env file not found: $ENV_FILE" >> "$LOG_FILE"
  exit 1
fi

# Export env vars if needed later
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

echo "=== $(date '+%Y-%m-%d %H:%M:%S') === git sync start ($SYNC_FILE only) ===" >> "$LOG_FILE"

# Make sure this is a git repo
if [ ! -d ".git" ]; then
  echo "ERROR: Not a git repository: $REPO_DIR" >> "$LOG_FILE"
  exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -z "$CURRENT_BRANCH" ]; then
  echo "ERROR: Could not determine current git branch" >> "$LOG_FILE"
  exit 1
fi

# If manual_topics.csv has local changes, commit it first
if ! git diff --quiet -- "$SYNC_FILE" || ! git diff --cached --quiet -- "$SYNC_FILE"; then
  echo "[git] local changes detected in $SYNC_FILE, creating commit" >> "$LOG_FILE"
  git add "$SYNC_FILE" >> "$LOG_FILE" 2>&1
  git commit -m "Auto-sync $SYNC_FILE from server $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE" 2>&1
  COMMIT_EXIT=$?
  if [ "$COMMIT_EXIT" -ne 0 ]; then
    echo "ERROR: git commit failed with exit code $COMMIT_EXIT" >> "$LOG_FILE"
    exit $COMMIT_EXIT
  fi
else
  echo "[git] no local changes in $SYNC_FILE to commit" >> "$LOG_FILE"
fi

# Pull latest remote changes
echo "[git] pull --rebase origin $CURRENT_BRANCH" >> "$LOG_FILE"
git pull --rebase origin "$CURRENT_BRANCH" >> "$LOG_FILE" 2>&1
PULL_EXIT=$?
if [ "$PULL_EXIT" -ne 0 ]; then
  echo "ERROR: git pull --rebase failed with exit code $PULL_EXIT" >> "$LOG_FILE"
  echo "ACTION NEEDED: Resolve rebase conflict manually." >> "$LOG_FILE"
  exit $PULL_EXIT
fi

# Push only if there is a local commit to send
echo "[git] push origin $CURRENT_BRANCH" >> "$LOG_FILE"
git push origin "$CURRENT_BRANCH" >> "$LOG_FILE" 2>&1
PUSH_EXIT=$?
if [ "$PUSH_EXIT" -ne 0 ]; then
  echo "ERROR: git push failed with exit code $PUSH_EXIT" >> "$LOG_FILE"
  exit $PUSH_EXIT
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') === git sync complete ===" >> "$LOG_FILE"
exit 0