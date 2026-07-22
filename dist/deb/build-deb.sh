#!/bin/bash
# Build a crypto-dashboard .deb (x86-independent, Architecture: all).
#
# Unlike qeth — which has to vendor PySide6 + the eth stack because Debian/Ubuntu
# don't ship a compatible PySide6 or the eth libraries — EVERY runtime dependency
# of crypto-dashboard (PyQt6, pyqtgraph, numpy, requests, websocket-client,
# platformdirs) is a stock system package on both Debian 13 (LMDE) and
# Ubuntu 24.04 (Mint). So this build vendors nothing: it just drops the single
# module under /usr/lib/crypto-dashboard, installs a tiny launcher, and Depends
# on the distro's python3-* packages. The identical package therefore installs
# on both the Debian and the Ubuntu/Mint families.
#
# Build prereq (apt): dpkg-dev  (for dpkg-deb).
# Usage: ./dist/deb/build-deb.sh [OUTPUT_DIR]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VERSION="$(sed -nE 's/^__version__ = "(.*)"/\1/p' "$REPO/crypto_dashboard.py")"
OUT="${1:-$REPO/dist/deb}"

echo ">> crypto-dashboard $VERSION  (out: $OUT)"

STAGE="$(mktemp -d)/crypto-dashboard"
install -d "$STAGE/usr/lib/crypto-dashboard" "$STAGE/usr/bin" \
        "$STAGE/usr/share/applications" \
        "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/DEBIAN"

install -Dm0644 "$REPO/crypto_dashboard.py" \
        "$STAGE/usr/lib/crypto-dashboard/crypto_dashboard.py"
install -Dm0755 "$HERE/crypto-dashboard.launcher" "$STAGE/usr/bin/crypto-dashboard"
install -Dm0644 "$REPO/data/crypto-dashboard.desktop" \
        "$STAGE/usr/share/applications/crypto-dashboard.desktop"
install -Dm0644 "$REPO/data/icons/hicolor/scalable/apps/crypto-dashboard.svg" \
        "$STAGE/usr/share/icons/hicolor/scalable/apps/crypto-dashboard.svg"

INSTALLED_KB="$(du -sk "$STAGE/usr" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: crypto-dashboard
Version: $VERSION
Architecture: all
Maintainer: Michael Egorov <michwill@yieldbasis.com>
Depends: python3, python3-pyqt6, python3-pyqtgraph, python3-numpy, python3-requests, python3-websocket, python3-platformdirs
Installed-Size: $INSTALLED_KB
Section: utils
Priority: optional
Homepage: https://github.com/michwill/crypto-dashboard
Description: Real-time cryptocurrency dashboard with candlestick charts
 Crypto Dashboard is a PyQt6 desktop app showing real-time cryptocurrency
 candlestick and volume charts, with live prices streamed from Binance over a
 websocket. It uses the system PyQt6 so it matches your desktop's Qt theme.
EOF

mkdir -p "$OUT"
DEB="$OUT/crypto-dashboard_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
rm -rf "$(dirname "$STAGE")"
echo ">> built $DEB"
dpkg-deb -I "$DEB" | sed -n '1,16p'
