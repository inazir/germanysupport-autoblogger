#!/bin/bash
# scripts/run_news.sh
# Cron wrapper for Germany Daily News Auto Poster
#
# Usage:
#   bash scripts/run_news.sh [--test]
#
# Example crontab:
#   30 7 * * * /bin/bash /home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/scripts/run_news.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

cd "$REPO_DIR" || exit 1

# -------------------------------------------------------------------
# Logs
# -------------------------------------------------------------------
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/news_runner.log"

mkdir -p "$LOG_DIR"

# Append ALL output (stdout + stderr) to log file
exec >> "$LOG_FILE" 2>&1

echo ""
echo "==============================================================================="
echo "NEW EXECUTION START: $(date '+%Y-%m-%d %H:%M:%S')"
echo "==============================================================================="
echo "Repository: $REPO_DIR"

# -------------------------------------------------------------------
# Mode
# -------------------------------------------------------------------
# Use --test flag if passed as argument, otherwise --post
MODE="${1:---post}"

echo "Execution mode: $MODE"

# -------------------------------------------------------------------
# Cache cleanup
# -------------------------------------------------------------------
echo "Starting cache cleanup (files older than 7 days)..."

CACHE_DIRS=(
    "$REPO_DIR/social/cache/generated_images"
    "$REPO_DIR/social/cache/generated_videos"
)

for DIR in "${CACHE_DIRS[@]}"; do
    if [ -d "$DIR" ]; then
        echo "Cleaning directory: $DIR"

        find "$DIR" -mindepth 1 -mtime +7 -exec rm -rf {} +

        echo "Cleanup completed for: $DIR"
    else
        echo "Directory does not exist: $DIR"
    fi
done

echo "Cache cleanup finished."
echo "-------------------------------------------------------------------------------"

# -------------------------------------------------------------------
# Run script
# -------------------------------------------------------------------
python3 -m social.daily_news.share_news "$MODE"

EXIT_CODE=$?

echo "-------------------------------------------------------------------------------"

if [ $EXIT_CODE -eq 0 ]; then
    echo "EXECUTION COMPLETED SUCCESSFULLY"
else
    echo "EXECUTION FAILED"
fi

echo "Finished at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Exit code: $EXIT_CODE"

echo "==============================================================================="
echo "END OF EXECUTION"
echo "==============================================================================="
echo ""

exit $EXIT_CODE