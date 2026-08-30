#!/usr/bin/env bash
# Register the curator with launchd: every night at 02:30 when the Mac is
# awake. Run once. Remove with:
#     launchctl unload ~/Library/LaunchAgents/com.linguallm.curator.plist
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="$ROOT/.venv/bin/python"
command -v conda >/dev/null 2>&1 && PY="$(conda info --base)/envs/reader/bin/python"
[ -x "$PY" ] || { echo "No reader environment found; run setup-mac.command first."; exit 1; }

PLIST="$HOME/Library/LaunchAgents/com.linguallm.curator.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.linguallm.curator</string>
  <key>ProgramArguments</key>
  <array><string>${PY}</string><string>-m</string><string>curator.run</string></array>
  <key>WorkingDirectory</key><string>${ROOT}</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key>
  <string>${HOME}/Library/Application Support/ReadingDesk/curator/night.log</string>
  <key>StandardErrorPath</key>
  <string>${HOME}/Library/Application Support/ReadingDesk/curator/night.log</string>
</dict></plist>
XML
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Scheduled nightly at 02:30. Log: ~/Library/Application Support/ReadingDesk/curator/night.log"
