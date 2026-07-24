#!/usr/bin/env zsh
# Dynamically generate launchd plists for Satan using current working directory ($PWD)

set -e

PROJECT_DIR="${1:-$PWD}"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_AGENTS_DIR"

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.satan.server.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.satan.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>${PROJECT_DIR}/backend/server.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>${PROJECT_DIR}/backend</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/satan-server.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/satan-server.log</string>
</dict>
</plist>
EOF

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.satan.tracker.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.satan.tracker</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>${PROJECT_DIR}/trackers/mac_tracker.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/satan-tracker.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/satan-tracker.log</string>
</dict>
</plist>
EOF

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.satan.menubar.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.satan.menubar</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>${PROJECT_DIR}/menu_bar/menubar.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/satan-menubar.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/satan-menubar.log</string>
</dict>
</plist>
EOF

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.satan.dashboard.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.satan.dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/npm</string>
    <string>--prefix</string>
    <string>dashboard</string>
    <string>run</string>
    <string>dev</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/data/satan-dashboard.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/satan-dashboard.log</string>
</dict>
</plist>
EOF

echo "Launchd plists generated and installed to $LAUNCH_AGENTS_DIR for project $PROJECT_DIR"
