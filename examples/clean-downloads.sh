#!/usr/bin/env bash
# Run pixsort on your Downloads folder without thinking about it.
#
# 1. Install:      pip install pixsort
# 2. Make it run:  crontab -e       (Linux/macOS)
#    Add one line to run it every evening at 21:00:
#        0 21 * * * /path/to/clean-downloads.sh >> ~/pixsort.log 2>&1
#
# On macOS you may need to allow "Full Disk Access" for /usr/sbin/cron in
# System Settings → Privacy & Security.

set -euo pipefail

# Where to clean (default: your Downloads folder)
SOURCE="${1:-$HOME/Downloads}"

# Where the dated folders go. Comment the line to keep them next to the source.
TARGET="${PIXSORT_ROOT:-}"

ARGS=(--yes --quiet --min-gain 5)

if [[ -n "$TARGET" ]]; then
  ARGS+=(--root "$TARGET")
fi

echo "── $(date '+%Y-%m-%d %H:%M') · pixsort on $SOURCE ──"
pixsort "$SOURCE" "${ARGS[@]}"
echo
