#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VERSION="1.0.1-1"
PKG="whisper-gui-bg"
BUILD_DIR="build/${PKG}_${VERSION}_all"

rm -rf "$BUILD_DIR"

mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/whisper-gui"
mkdir -p "$BUILD_DIR/usr/share/applications"

install -m 644 packaging/DEBIAN/control "$BUILD_DIR/DEBIAN/control"
install -m 755 whisper-gui "$BUILD_DIR/usr/bin/whisper-gui"
install -m 755 whisper-gui-setup "$BUILD_DIR/usr/bin/whisper-gui-setup"
install -m 644 app.py "$BUILD_DIR/usr/share/whisper-gui/app.py"
install -m 644 whisper-gui.desktop "$BUILD_DIR/usr/share/applications/whisper-gui.desktop"

mkdir -p dist
dpkg-deb --build --root-owner-group "$BUILD_DIR" "dist/${PKG}_${VERSION}_all.deb"

echo "Готов пакет: dist/${PKG}_${VERSION}_all.deb"
