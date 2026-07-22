#!/usr/bin/env zsh
# Dynamically generate launchd plists for Vigil using current working directory ($PWD)

set -e

PROJECT_DIR="${1:-$PWD}"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_AGENTS_DIR"

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.vigil.server.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vigil.server</string>
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
  <string>${PROJECT_DIR}/data/vigil-server.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/vigil-server.log</string>
</dict>
</plist>
EOF

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.vigil.tracker.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vigil.tracker</string>
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
  <string>${PROJECT_DIR}/data/vigil-tracker.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/vigil-tracker.log</string>
</dict>
</plist>
EOF

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.vigil.menubar.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vigil.menubar</string>
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
  <string>${PROJECT_DIR}/data/vigil-menubar.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/vigil-menubar.log</string>
</dict>
</plist>
EOF

cat <<EOF > "$LAUNCH_AGENTS_DIR/com.vigil.dashboard.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vigil.dashboard</string>
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
  <string>${PROJECT_DIR}/data/vigil-dashboard.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/data/vigil-dashboard.log</string>
</dict>
</plist>
EOF

echo "Launchd plists generated and installed to $LAUNCH_AGENTS_DIR for project $PROJECT_DIR"
