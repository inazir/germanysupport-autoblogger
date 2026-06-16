#!/bin/bash
# Auto-discover Python path if missing
command -v python3 >/dev/null || export PATH="$(ls -d /opt/alt/python3*/bin 2>/dev/null | sort -V | tail -n 1):$PATH"

# ============================================================
# GermanySupport.de — Run Multi Link Replacement Script
# ============================================================

set -e

# Load environment variables
set -a
source "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger/.env"
set +a

# Go to repo directory
cd "/home/u989113309/domains/germanysupport.de/repos/germanysupport-autoblogger"

echo "=========================================="
echo " Running update_links.py"
echo " Date: $(date)"
echo "=========================================="

CMD=(python update_links.py)
HAS_REPLACE=0

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --replace)
      if [[ -z "$2" ]]; then
        echo "❌ ERROR: --replace needs a value"
        exit 1
      fi
      CMD+=(--replace "$2")
      HAS_REPLACE=1
      shift 2
      ;;
    --replace-file)
      if [[ -z "$2" ]]; then
        echo "❌ ERROR: --replace-file needs a value"
        exit 1
      fi
      CMD+=(--replace-file "$2")
      HAS_REPLACE=1
      shift 2
      ;;
    --post-id|--days)
      if [[ -z "$2" ]]; then
        echo "❌ ERROR: $1 needs a value"
        exit 1
      fi
      CMD+=("$1" "$2")
      shift 2
      ;;
    --dry-run)
      CMD+=(--dry-run)
      shift
      ;;
    *)
      echo "Unknown parameter: $1"
      echo "Example:"
      echo 'bash run_update_links.sh --replace "steuergo:wiso:SteuerGo:WISO Steuer" --dry-run'
      exit 1
      ;;
  esac
done

if [[ "$HAS_REPLACE" -ne 1 ]]; then
  echo "❌ ERROR: Provide at least one --replace or --replace-file"
  echo "Examples:"
  echo 'bash run_update_links.sh --replace "steuergo:wiso" --dry-run'
  echo 'bash run_update_links.sh --replace "steuergo:wiso:SteuerGo:WISO Steuer" --replace "advanzia:credit-cards:Advanzia Mastercard:Credit Card Comparison"'
  echo 'bash run_update_links.sh --replace-file replacements.txt --dry-run'
  exit 1
fi

echo "Command:"
printf ' %q' "${CMD[@]}"
echo
echo "------------------------------------------"

"${CMD[@]}"

echo "=========================================="
echo " DONE"
echo "=========================================="
