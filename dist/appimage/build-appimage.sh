#!/usr/bin/env bash
# Assemble the crypto-dashboard AppImage *inside a manylinux container* (old,
# generic glibc; SSE2 baseline). Nothing from the developer's host enters the
# bundle: the interpreter and every wheel come from the container. Run via
# build-in-container.sh — NOT on the host directly.
#
# An AppImage is self-contained by design (no runtime), so — unlike the Flatpak,
# which gets Qt from org.kde.Platform — it MUST bundle Python + PyQt6 (whose
# wheel ships its own Qt6) + the deps. glibc floor = the container's; PyQt6 6.11
# ships manylinux_2_34 wheels, so build-in-container.sh uses manylinux_2_34
# (floor glibc 2.34: Ubuntu 22.04+, Debian 12+, Fedora 35+, RHEL 9+). GL comes
# from the HOST (never bundled).
#
# Env knobs: SRC (/src), OUT (/out), WORK (/tmp/cd-appimage), PYVER (cp312-cp312)
set -euo pipefail

SRC="${SRC:-/src}"
OUT="${OUT:-/out}"
WORK="${WORK:-/tmp/cd-appimage}"
PYVER="${PYVER:-cp312-cp312}"
ARCH="x86_64"
APPDIR="$WORK/AppDir"

rm -rf "$WORK"; mkdir -p "$APPDIR/usr/lib" "$OUT"

# 1. System libs the Qt xcb platform plugin dlopens/DT_NEEDs but the PyQt6-Qt6
#    wheel does NOT bundle. Pulled from the container (old glibc, generic).
#    mesa-libGL is installed only so ldd resolves at build time — libGL itself
#    is NOT bundled (step 4 excludes it; GL comes from the host GPU driver).
dnf install -y -q \
    libxcb libxkbcommon libxkbcommon-x11 xcb-util-cursor xcb-util-image \
    xcb-util-keysyms xcb-util-renderutil xcb-util-wm libX11 libX11-xcb libXext \
    libXrender libXrandr libXi libXfixes libXcursor libSM libICE \
    fontconfig freetype dbus-libs mesa-libGL \
    >/dev/null 2>&1 || echo "WARN: some packages unavailable — refine for the target"

# 2. A relocatable CPython from the container ($ORIGIN-relative RPATH).
mkdir -p "$APPDIR/usr/python"
cp -a "$(readlink -f "/opt/python/${PYVER}")/." "$APPDIR/usr/python/"
M="${PYVER#cp3}"; M="${M%%-*}"                 # cp312-cp312 -> 12
ln -sf "python3.${M}" "$APPDIR/usr/python/bin/python3"
PY="$APPDIR/usr/python/bin/python3"
export PYTHONHOME="$APPDIR/usr/python"

# 3. crypto-dashboard + PyQt6 + the rest, fresh from PyPI manylinux wheels.
#    Source copied to a WRITABLE dir first (pip's build writes into the tree;
#    /src is read-only). The [pyqt] extra pulls PyQt6 (= PyQt6-Qt6, all the Qt
#    .so + plugins, and PyQt6-sip); the base deps come along.
BUILD_SRC="$WORK/src"
mkdir -p "$BUILD_SRC"
tar -C "$SRC" \
    --exclude=.git --exclude=.venv --exclude=build --exclude=dist \
    --exclude='__pycache__' --exclude='.env' --exclude='.claude' \
    -cf - . | tar -C "$BUILD_SRC" -xf -
"$PY" -m pip install --no-cache-dir --upgrade pip wheel >/dev/null
"$PY" -m pip install --no-cache-dir --prefix="$APPDIR/usr/python" \
    "${BUILD_SRC}[pyqt]"
if ! ls -d "$APPDIR"/usr/python/lib/python*/site-packages/PyQt6/Qt6 >/dev/null 2>&1; then
    echo "FATAL: PyQt6/Qt6 not in the AppDir after install. site-packages holds:"
    ls "$APPDIR"/usr/python/lib/python*/site-packages/ 2>&1 | head -40
    exit 1
fi
SP="$(echo "$APPDIR"/usr/python/lib/python*/site-packages)"
# The app's icon fallback is <module dir>/data/icons/.../crypto-dashboard.svg.
cp -a "$BUILD_SRC/data" "$SP/data"
echo "DIAG: AppDir after install = $(du -sh "$APPDIR" | cut -f1)"

# 3b. Trim big Qt modules crypto-dashboard never uses (keep Core/Gui/Widgets,
#     OpenGL+OpenGLWidgets for useOpenGL=True, Svg+SvgWidgets for the icon,
#     DBus, Network, PrintSupport). Also drop pyqtgraph examples/tests + numpy
#     tests (never imported).
QT6="$SP/PyQt6/Qt6"
rm -rf "$QT6/qml" "$QT6/translations" "$QT6/resources" "$QT6/libexec" 2>/dev/null || true
for mod in WebEngineCore WebEngineWidgets WebEngineQuick WebChannel WebSockets \
           Quick Quick3D QuickWidgets QuickControls2 QuickControls2Impl \
           QuickTemplates2 QuickShapes QuickParticles QuickTest QuickLayouts \
           QuickDialogs2 QuickDialogs2QuickImpl QuickDialogs2Utils QuickEffects \
           QuickTimeline QuickVectorImage \
           Qml QmlModels QmlWorkerScript QmlMeta QmlLocalStorage QmlCore \
           QmlXmlListModel 3DCore 3DRender 3DInput 3DLogic 3DAnimation 3DExtras \
           3DQuick 3DQuickRender 3DQuickScene2D \
           Charts ChartsQml DataVisualization DataVisualizationQml Graphs \
           GraphsWidgets Multimedia MultimediaWidgets MultimediaQuick SpatialAudio \
           Pdf PdfWidgets PdfQuick Designer DesignerComponents Help UiTools \
           Sql Test Bluetooth Nfc Positioning PositioningQuick Location Sensors \
           SensorsQuick SerialPort SerialBus RemoteObjects RemoteObjectsQml \
           Scxml ScxmlQml TextToSpeech StateMachine; do
    rm -f "$QT6/lib/libQt6${mod}".so* "$SP/PyQt6/Qt${mod}.abi3.so" \
          "$SP/PyQt6/Qt${mod}.pyi" 2>/dev/null || true
done
rm -rf "$QT6"/plugins/{qmltooling,webview,sqldrivers,designer,position,sensors,texttospeech,multimedia,scenegraph} 2>/dev/null || true
rm -rf "$SP"/pyqtgraph/examples "$SP"/pyqtgraph/tests 2>/dev/null || true
find "$SP/numpy" -depth -type d -name tests -exec rm -rf {} + 2>/dev/null || true
echo "DIAG: AppDir after trim = $(du -sh "$APPDIR" | cut -f1)"

# 4. Bundle the external (non-wheel) shared-lib deps of Qt's libs + plugins.
#    EXCLUDE the GL/DRI stack — it must come from the host GPU driver, or the
#    app crashes on a machine with a different GPU.
{ find "$QT6/lib" -name 'libQt6*.so*' 2>/dev/null
  find "$QT6/plugins/platforms" -name '*.so' 2>/dev/null
  find "$QT6/plugins/xcbglintegrations" -name '*.so' 2>/dev/null; } | while read -r so; do
    ldd "$so" 2>/dev/null || true
done | awk '/=> \// {print $3}' \
  | grep -vE 'PyQt6/|/libQt6|/libpython|/ld-linux|/libc\.so|/libm\.so|/libdl|/libpthread|/librt|/libstdc\+\+|/libgcc_s|/libGL|/libEGL|/libGLX|/libGLdispatch|/libOpenGL|/libglapi|/libdrm|/libgbm' \
  | sort -u | xargs -r -I{} cp -Lu {} "$APPDIR/usr/lib/" 2>/dev/null || true

# 4b. Strip ONLY the libs we copied from the container (usr/lib). The wheel-
#     provided libs (PyQt6/Qt6/*, numpy.libs/* OpenBLAS, …) are already
#     release-stripped; re-stripping them with the container's binutils
#     misaligns their PT_LOAD segments so a NEWER-glibc host rejects the dlopen
#     ("ELF load command address/offset not page-aligned" — numpy's OpenBLAS
#     hits exactly this). Leave them untouched.
find "$APPDIR/usr/lib" -type f -name '*.so*' -exec strip --strip-unneeded {} \; 2>/dev/null || true
echo "DIAG: AppDir after strip = $(du -sh "$APPDIR" | cut -f1)"

# 5. AppImage metadata (AppRun + one top-level .desktop + matching icon), plus
#    the hicolor icon + .desktop under usr/share (AppRun points XDG_DATA_DIRS here).
install -Dm755 "$SRC/dist/appimage/AppRun"                   "$APPDIR/AppRun"
install -Dm644 "$SRC/dist/appimage/crypto-dashboard.desktop" "$APPDIR/crypto-dashboard.desktop"
install -Dm644 "$SRC/data/icons/hicolor/scalable/apps/crypto-dashboard.svg" \
        "$APPDIR/crypto-dashboard.svg"
install -Dm644 "$SRC/dist/appimage/crypto-dashboard.desktop" \
        "$APPDIR/usr/share/applications/crypto-dashboard.desktop"
install -Dm644 "$SRC/data/icons/hicolor/scalable/apps/crypto-dashboard.svg" \
        "$APPDIR/usr/share/icons/hicolor/scalable/apps/crypto-dashboard.svg"

# 6. Pack. --appimage-extract-and-run avoids needing FUSE inside the container.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$BUILD_SRC/crypto_dashboard.py")"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 -o "$WORK/appimagetool" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
chmod +x "$WORK/appimagetool"
ARCH="$ARCH" "$WORK/appimagetool" --appimage-extract-and-run \
  "$APPDIR" "$OUT/crypto-dashboard-${VERSION}-${ARCH}.AppImage"
echo "OK -> $OUT/crypto-dashboard-${VERSION}-${ARCH}.AppImage  (needs host libGL, generic x86-64)"
