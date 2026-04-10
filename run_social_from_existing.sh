#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/social_from_existing.log"

mkdir -p "$LOG_DIR"

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

"$PYTHON_BIN" social_from_existing.py --only-english "$@" >> "$LOG_FILE" 2>&1
