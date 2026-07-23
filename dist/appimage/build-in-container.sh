#!/usr/bin/env bash
# Build the crypto-dashboard AppImage by running build-appimage.sh inside a
# manylinux container (keeps the dev host's glibc/CPU tuning out of the bundle).
# Needs podman or docker.
#
#   ./dist/appimage/build-in-container.sh                        # glibc 2.34 floor
#   IMAGE=quay.io/pypa/manylinux_2_39_x86_64 ./...               # newer floor
#
# PyQt6 6.11's Linux wheel is manylinux_2_34, so 2_34 is the lowest usable image
# (an older image makes pip fall back to building PyQt6 from source, which needs
# qmake and fails). Floor: Ubuntu 22.04+, Debian 12+, Fedora 35+, RHEL 9+.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${IMAGE:-quay.io/pypa/manylinux_2_34_x86_64}"
OUT="$REPO/dist/appimage/out"
mkdir -p "$OUT"

ENGINE="$(command -v podman || command -v docker || true)"
[ -n "$ENGINE" ] || { echo "need podman or docker"; exit 1; }

"$ENGINE" run --rm \
  -v "$REPO":/src:ro \
  -v "$OUT":/out \
  -e PYVER="${PYVER:-cp312-cp312}" \
  "$IMAGE" bash /src/dist/appimage/build-appimage.sh

echo ">> built:"
ls -la "$OUT"/*.AppImage
