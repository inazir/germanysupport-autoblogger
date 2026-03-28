#!/bin/bash
set -a
source "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/.env"
set +a

# If sourced, only load env and stop here
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

cd "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') === publish_article $* ===" >> "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/logs/cron.log"

/usr/bin/python3 "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/publish_article.py" "$@" >> "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/logs/cron.log" 2>&1

echo "Exit: $?" >> "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/logs/cron.log"
