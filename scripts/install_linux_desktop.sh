#!/usr/bin/env bash
# Creates a native Linux desktop menu entry (~/.local/share/applications/wattwise.desktop)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

mkdir -p "${APP_DIR}" "${ICON_DIR}"

cat > "${ICON_DIR}/wattwise.svg" << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#059669"/>
      <stop offset="55%" stop-color="#0EA5E9"/>
      <stop offset="100%" stop-color="#6366F1"/>
    </linearGradient>
  </defs>
  <rect x="8" y="8" width="112" height="112" rx="28" fill="url(#bg)"/>
  <polygon points="72,22 36,69 61,69 54,106 92,58 67,58" fill="#FFFFFF"/>
</svg>
EOF

cat > "${APP_DIR}/wattwise.desktop" << EOF
[Desktop Entry]
Type=Application
Name=WattWise
Comment=Track device power consumption, electricity cost, and carbon footprint
Exec=env PYTHONPATH=${ROOT_DIR}/src python3 -m wattwise
Icon=${ICON_DIR}/wattwise.svg
Terminal=false
Categories=Utility;System;Monitor;
StartupNotify=true
EOF

chmod +x "${APP_DIR}/wattwise.desktop"
echo "Installed Linux desktop launcher at ${APP_DIR}/wattwise.desktop"
