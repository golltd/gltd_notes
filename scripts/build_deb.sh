#!/usr/bin/env bash
# =============================================================================
# GLTD Notes — Debian Package Builder
# Gera um pacote .deb instalavel em /var/PROGRAMAS/gltd_notes
# Uso: ./scripts/build_deb.sh
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=$(grep -oP '[0-9]+\.[0-9]+\.[0-9]+' "$ROOT/gltd_notes/_version.py" | head -1)
ARCH="all"
PACKAGE="gltd-notes"
DEB_NAME="${PACKAGE}_${VERSION}_${ARCH}.deb"
BUILD_DIR="$ROOT/build/deb"
DEBIAN_DIR="$BUILD_DIR/DEBIAN"
INSTALL_PREFIX="/var/PROGRAMAS/gltd_notes"
OUTPUT_DIR="${1:-/var/PROGRAMAS}"

echo "============================================"
echo "  GLTD Notes — Gerador de Pacote .deb"
echo "============================================"
echo "  Versao:  $VERSION"
echo "  Pacote:  $DEB_NAME"
echo "  Destino: $OUTPUT_DIR"
echo "============================================"
echo ""

# ── Limpar build anterior ──────────────────────────────────────
rm -rf "$BUILD_DIR"
mkdir -p "$DEBIAN_DIR"
mkdir -p "$BUILD_DIR$INSTALL_PREFIX"

# ── Copiar arquivos da aplicacao ───────────────────────────────
echo "[1/5] Copiando arquivos..."
cp -r "$ROOT/bin"      "$BUILD_DIR$INSTALL_PREFIX/"
cp -r "$ROOT/gltd_notes" "$BUILD_DIR$INSTALL_PREFIX/"
cp -r "$ROOT/icons"    "$BUILD_DIR$INSTALL_PREFIX/"
cp -r "$ROOT/docs"     "$BUILD_DIR$INSTALL_PREFIX/"
cp    "$ROOT/LICENSE"  "$BUILD_DIR$INSTALL_PREFIX/"
cp    "$ROOT/README.md" "$BUILD_DIR$INSTALL_PREFIX/"
cp    "$ROOT/requirements.txt" "$BUILD_DIR$INSTALL_PREFIX/"
cp    "$ROOT/pyproject.toml"   "$BUILD_DIR$INSTALL_PREFIX/"
cp -r "$ROOT/scripts"  "$BUILD_DIR$INSTALL_PREFIX/"
# Remove build-related scripts from installed package
rm -f "$BUILD_DIR$INSTALL_PREFIX/scripts/build_deb.sh"
rm -f "$BUILD_DIR$INSTALL_PREFIX/scripts/bump_version.sh"
# Make scripts executable
chmod +x "$BUILD_DIR$INSTALL_PREFIX/bin/"*
chmod +x "$BUILD_DIR$INSTALL_PREFIX/scripts/"*.sh 2>/dev/null || true
# Remove __pycache__
find "$BUILD_DIR$INSTALL_PREFIX" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR$INSTALL_PREFIX" -type f -name '*.pyc' -delete 2>/dev/null || true
echo "  OK"

# ── Criar links em /usr/local/bin ─────────────────────────────
echo "[2/5] Criando estrutura de links..."
mkdir -p "$BUILD_DIR/usr/local/bin"
ln -sf "$INSTALL_PREFIX/bin/gltd-notes"     "$BUILD_DIR/usr/local/bin/gltd-notes"
ln -sf "$INSTALL_PREFIX/bin/gltd-notes-api"  "$BUILD_DIR/usr/local/bin/gltd-notes-api"
ln -sf "$INSTALL_PREFIX/bin/gltd-notes-web"  "$BUILD_DIR/usr/local/bin/gltd-notes-web"
echo "  OK"

# ── DEBIAN/control ──────────────────────────────────────────────
echo "[3/5] Criando metadados do pacote..."
cat > "$DEBIAN_DIR/control" << CTRL
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo,
 gir1.2-gtk-3.0, gir1.2-notify-0.7,
 gir1.2-webkit2-4.0 | gir1.2-webkit2-4.1,
 gir1.2-ayatanaappindicator3-0.1 | gir1.2-appindicator3-0.1,
 libnotify-bin, qrencode
Recommends: syncthing
Maintainer: GLTD <suporte@golltd.com>
Installed-Size: $(du -sk "$BUILD_DIR$INSTALL_PREFIX" | cut -f1)
Homepage: https://github.com/golltd/gltd_notes
Description: Bloco de notas pessoal com sincronizacao multi-maquina
 GLTD Notes e um aplicativo de notas privado e open-source para Linux,
 com interface GTK3, servidor web local e API REST.
 .
 Recursos:
  - Notas com formatacao rica (HTML)
  - Anexo de arquivos (imagens, PDFs, etc.)
  - Historico completo de alteracoes
  - Listas de tarefas e eventos/lembretes
  - Agentes de IA integrados (DeepSeek, Grok, Gemini)
  - Sincronizacao entre maquinas via Syncthing
  - Compartilhamento de notas entre usuarios
  - Bloqueio de sessao com senha
  - API REST local e interface web
CTRL
echo "  OK"

# ── DEBIAN/postinst ─────────────────────────────────────────────
cat > "$DEBIAN_DIR/postinst" << 'POSTINST'
#!/usr/bin/env bash
set -e

INSTALL_DIR="/var/PROGRAMAS/gltd_notes"

echo ""
echo "============================================"
echo "  GLTD Notes — Pos-instalacao"
echo "============================================"

# Criar atalhos desktop para cada usuario (opcional)
for USER_HOME in /home/*; do
    USER_NAME=$(basename "$USER_HOME")
    if id "$USER_NAME" &>/dev/null; then
        # Criar links no PATH do usuario
        mkdir -p "$USER_HOME/.local/bin"
        ln -sf "$INSTALL_DIR/bin/gltd-notes"      "$USER_HOME/.local/bin/gltd-notes"      2>/dev/null || true
        ln -sf "$INSTALL_DIR/bin/gltd-notes-api"   "$USER_HOME/.local/bin/gltd-notes-api"   2>/dev/null || true
        ln -sf "$INSTALL_DIR/bin/gltd-notes-web"   "$USER_HOME/.local/bin/gltd-notes-web"   2>/dev/null || true
        chown -R "$USER_NAME:$USER_NAME" "$USER_HOME/.local/bin" 2>/dev/null || true

        # Criar atalhos desktop para o usuario
        if [ -x "$INSTALL_DIR/scripts/install_desktop.sh" ]; then
            sudo -u "$USER_NAME" bash "$INSTALL_DIR/scripts/install_desktop.sh" 2>/dev/null || true
        fi
    fi
done

echo ""
echo "GLTD Notes instalado com sucesso!"
echo ""
echo "Para configurar seu usuario execute:"
echo "  gltd-notes init --data-root ~/gltd_notes_data --username SEU_USUARIO"
echo ""
echo "Ou use o assistente grafico:"
echo "  gltd-notes setup"
echo ""
echo "Para iniciar a interface grafica:"
echo "  gltd-notes"
echo ""
POSTINST
chmod 755 "$DEBIAN_DIR/postinst"
echo "  OK"

# ── Construir .deb ─────────────────────────────────────────────
echo "[4/5] Construindo pacote .deb..."
mkdir -p "$OUTPUT_DIR"
dpkg-deb --build "$BUILD_DIR" "$OUTPUT_DIR/$DEB_NAME"
echo "  OK"

# ── Resumo ──────────────────────────────────────────────────────
echo ""
echo "[5/5] Pacote gerado com sucesso!"
echo ""
echo "  Arquivo: $OUTPUT_DIR/$DEB_NAME"
echo "  Tamanho: $(du -h "$OUTPUT_DIR/$DEB_NAME" | cut -f1)"
echo ""
echo "Para instalar:"
echo "  sudo dpkg -i $OUTPUT_DIR/$DEB_NAME"
echo ""
echo "Para desinstalar:"
echo "  sudo dpkg -r gltd-notes"
echo ""

# Limpeza opcional
rm -rf "$BUILD_DIR"
