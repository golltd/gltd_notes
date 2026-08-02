#!/usr/bin/env bash
# Download Syncthing binary for GLTD Notes embedded sync
# Usage: ./scripts/download_syncthing.sh [install_dir]
set -euo pipefail

INSTALL_DIR="${1:-/var/PROGRAMAS/gltd_notes/ext_program}"
mkdir -p "$INSTALL_DIR" 2>/dev/null || true
if [ ! -w "$INSTALL_DIR" ]; then
    echo "ERRO: sem permissao de escrita em $INSTALL_DIR"
    echo "Execute: chown -R \$USER:\$USER $INSTALL_DIR"
    exit 1
fi

ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ST_ARCH="linux-amd64" ;;
    aarch64) ST_ARCH="linux-arm64" ;;
    armv7l)  ST_ARCH="linux-arm" ;;
    *) echo "ERRO: arquitetura nao suportada: $ARCH"; exit 1 ;;
esac

echo "============================================"
echo "  GLTD Notes — Instalador Syncthing"
echo "  Arquitetura: $ST_ARCH"
echo "  Destino:     $INSTALL_DIR/syncthing"
echo "============================================"
echo ""

TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

echo "[1/2] Obtendo versao mais recente..."
API_URL="https://api.github.com/repos/syncthing/syncthing/releases/latest"
LATEST_TAG=$(curl -fsSL "$API_URL" | grep -oP '"tag_name":\s*"\K[^"]+')
if [ -z "$LATEST_TAG" ]; then
    echo "ERRO: nao foi possivel obter a versao mais recente do Syncthing"
    exit 1
fi
echo "  Versao: $LATEST_TAG"

FILENAME="syncthing-${ST_ARCH}-${LATEST_TAG}.tar.gz"
URL="https://github.com/syncthing/syncthing/releases/download/${LATEST_TAG}/${FILENAME}"
echo "  URL: $URL"

echo "[2/2] Baixando e extraindo..."
curl -fsSL -o "$TMP_DIR/syncthing.tar.gz" "$URL" || {
    echo "ERRO: falha no download. Verifique a URL: $URL"
    exit 1
}

tar xzf "$TMP_DIR/syncthing.tar.gz" -C "$TMP_DIR"
BIN_DIR=$(find "$TMP_DIR" -maxdepth 1 -type d -name "syncthing-*" | head -1)
if [ -z "$BIN_DIR" ]; then
    echo "ERRO: diretorio syncthing nao encontrado apos extracao"
    exit 1
fi

cp "$BIN_DIR/syncthing" "$INSTALL_DIR/syncthing"
chmod +x "$INSTALL_DIR/syncthing"

VER=$("$INSTALL_DIR/syncthing" --version | head -1)
echo "  Versao: $VER"
echo ""
echo "Syncthing instalado em $INSTALL_DIR/syncthing"
echo "Execute o GLTD Notes para configurar automaticamente."
