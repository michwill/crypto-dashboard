#!/bin/sh
# Install a .desktop shortcut for Crypto Dashboard into the user's application menu.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/applications/crypto-dashboard.desktop"

cat > "$DEST" <<EOF
[Desktop Entry]
Type=Application
Name=Crypto Dashboard
Comment=Real-time cryptocurrency dashboard with candlestick charts
Exec=$SCRIPT_DIR/crypto-dashboard
Icon=$SCRIPT_DIR/icon.svg
Terminal=false
Categories=Finance;Network;
Keywords=crypto;bitcoin;trading;chart;
EOF

echo "Installed $DEST"
