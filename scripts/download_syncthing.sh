#!/usr/bin/env bash
# Download Syncthing binary for GLTD Notes embedded sync
# Usage: ./scripts/download_syncthing.sh [version] [install_dir]
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    VERSION=$(cat "$(dirname "${BASH_SOURCE[0]}")/../gltd_notes/syncthing_version.txt" | head -1)
fi

INSTALL_DIR="${2:-/var/PROGRAMAS/gltd_notes/bin}"
mkdir -p "$INSTALL_DIR"

URL="https://github.com/syncthing/syncthing/releases/download/${VERSION}/syncthing-${ST_ARCH}-${VERSION}.tar.gz"
SHA256_URL="${URL}.sha256"

echo "Baixando Syncthing ${VERSION} para ${ST_ARCH}..."
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

curl -fsSL "$URL" -o "$TMP_DIR/syncthing.tar.gz"
curl -fsSL "$SHA256_URL" -o "$TMP_DIR/syncthing.tar.gz.sha256"

echo "Verificando checksum..."
cd "$TMP_DIR"
EXPECTED=$(awk '{print $1}' syncthing.tar.gz.sha256)
ACTUAL=$(sha256sum syncthing.tar.gz | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
    echo "ERRO: checksum invalido!"
    echo "  esperado: $EXPECTED"
    echo "  obtido:   $ACTUAL"
    exit 1
fi

echo "Extraindo..."
tar xzf syncthing.tar.gz
cp syncthing-${ST_ARCH}-${VERSION}/syncthing "$INSTALL_DIR/syncthing"
chmod +x "$INSTALL_DIR/syncthing"

echo "Syncthing ${VERSION} instalado em $INSTALL_DIR/syncthing"
