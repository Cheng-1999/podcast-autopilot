#!/usr/bin/env bash
# Double-click in Finder to open the dashboard (macOS twin of start-dashboard.bat).
cd "$(dirname "$0")" && ./dashboard.sh
status=$?
echo; echo "Dashboard stopped (exit $status). You can close this window."
