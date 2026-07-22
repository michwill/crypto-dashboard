#!/bin/sh
# Dev convenience: install a user-level .desktop entry + icon for running
# Crypto Dashboard straight from this source checkout via the uv launcher.
#
# Distribution packages do NOT use this script — they install data/*.desktop
# and data/icons/... into system paths (see "Packaging for distributions" in
# the README). This is only for running from a git clone.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"

mkdir -p "$APPS_DIR" "$ICON_DIR"

# Themed icon so QIcon.fromTheme("crypto-dashboard") resolves.
cp "$SCRIPT_DIR/data/icons/hicolor/scalable/apps/crypto-dashboard.svg" \
   "$ICON_DIR/crypto-dashboard.svg"

# Desktop entry pointing at the repo launcher (Exec differs from the packaged
# entry, which uses the installed `crypto-dashboard` command on PATH).
sed "s|^Exec=.*|Exec=$SCRIPT_DIR/crypto-dashboard|" \
    "$SCRIPT_DIR/data/crypto-dashboard.desktop" \
    > "$APPS_DIR/crypto-dashboard.desktop"

echo "Installed $APPS_DIR/crypto-dashboard.desktop"
echo "Installed $ICON_DIR/crypto-dashboard.svg"