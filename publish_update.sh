#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo 'Local changes exist; commit or review them before updating.' >&2
  exit 1
fi
git pull --ff-only
python3 update_calendar.py
git add schedule.json public/silk-way-star.ics
if ! git diff --cached --quiet; then
  git commit -m 'Update SWHL schedule from Mac'
  git push
fi
