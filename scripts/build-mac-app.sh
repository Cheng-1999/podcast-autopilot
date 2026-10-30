#!/usr/bin/env bash
# Builds "Podcast Autopilot.app" (default: ~/Applications) that opens a
# Terminal window running start-dashboard.command -> dashboard.sh — the macOS twin of start-dashboard.bat.
# Usage: scripts/build-mac-app.sh [dest-dir]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/Podcast Autopilot.app"
mkdir -p "$DEST"
rm -rf "$APP"

# `open -a Terminal <.command>` needs no Automation (Apple Events) permission,
# unlike `tell application "Terminal"`, so first launch has no TCC prompt.
osacompile -o "$APP" <<EOF
on run
  do shell script "open -a Terminal " & quoted form of "$REPO_ROOT/start-dashboard.command"
end run
EOF

# Icon: macOS microphone-ish system icon if available, else default applet.
ICON_SRC="/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/SidebarMusicFolder.icns"
[[ -f "$ICON_SRC" ]] && cp "$ICON_SRC" "$APP/Contents/Resources/applet.icns" && touch "$APP"

echo "Built: $APP"
