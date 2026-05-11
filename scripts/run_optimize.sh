#!/bin/bash
set -e

REPO_DIR="/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"
ENV_FILE="$REPO_DIR/.env"
LOG_FILE="$REPO_DIR/logs/cron.log"
PYTHON_BIN="/usr/bin/python3"
SCRIPT_FILE="$REPO_DIR/optimize_articles.py"

set -a
source "$ENV_FILE"
set +a

# If sourced, only load env and stop here
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

cd "$REPO_DIR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') === optimize_articles $* ===" >> "$LOG_FILE"

OPT_EXIT=0
$PYTHON_BIN "$SCRIPT_FILE" "$@" >> "$LOG_FILE" 2>&1 || OPT_EXIT=$?

echo "optimize_articles exit: $OPT_EXIT" >> "$LOG_FILE"
exit $OPT_EXIT
