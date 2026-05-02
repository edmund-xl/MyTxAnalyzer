#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="${RCA_LAUNCH_AGENT_LABEL:-com.lei.rca-workbench.ensure}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
WRAPPER_DIR="$HOME/Library/Scripts/rca-workbench"
WRAPPER_PATH="$WRAPPER_DIR/ensure_rca_services.sh"
LOG_DIR="$HOME/Library/Logs/rca-workbench"
OUT_LOG="$LOG_DIR/rca-ensure.out.log"
ERR_LOG="$LOG_DIR/rca-ensure.err.log"

mkdir -p "$PLIST_DIR" "$WRAPPER_DIR" "$LOG_DIR"
cp "$ROOT_DIR/scripts/ensure_rca_services.sh" "$WRAPPER_PATH"
chmod +x "$WRAPPER_PATH"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$WRAPPER_PATH</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$HOME</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RCA_ROOT_DIR</key>
    <string>$ROOT_DIR</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>StandardOutPath</key>
  <string>$OUT_LOG</string>
  <key>StandardErrorPath</key>
  <string>$ERR_LOG</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

printf '[rca-launch-agent] installed %s\n' "$PLIST_PATH"
printf '[rca-launch-agent] label %s\n' "$LABEL"
printf '[rca-launch-agent] wrapper %s\n' "$WRAPPER_PATH"
printf '[rca-launch-agent] logs %s %s\n' "$OUT_LOG" "$ERR_LOG"
