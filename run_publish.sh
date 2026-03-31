#!/bin/bash

REPO_DIR="/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"
ENV_FILE="$REPO_DIR/.env"
LOG_DIR="$REPO_DIR/logs"
CACHE_DIR="$REPO_DIR/cache"
LOG_FILE="$LOG_DIR/cron.log"
PYTHON_BIN="/usr/bin/python3"
SCRIPT_FILE="$REPO_DIR/publish_article.py"

# Ensure required runtime directories exist
mkdir -p "$LOG_DIR"
mkdir -p "$CACHE_DIR"

# .env is mandatory for this project
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env file not found: $ENV_FILE" >> "$LOG_FILE"
  exit 1
fi

# Export variables from .env for the Python process
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

# Run the publish script and capture the real exit code immediately
"$PYTHON_BIN" "$SCRIPT_FILE" "$@" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "Exit: $EXIT_CODE" >> "$LOG_FILE"

exit $EXIT_CODE