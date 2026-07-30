#!/usr/bin/env bash
# =============================================================================
# GLTD Notes — CLI Install & Setup
# Usage: sudo ./scripts/install.sh [--data-root PATH] [--username NAME]
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/var/PROGRAMAS/gltd_notes"
DATA_ROOT="/home/$SUDO_USER/gltd_notes_data"
USERNAME="${SUDO_USER:-$USER}"
DISPLAY_NAME="$USERNAME"
LOCK_PASSWORD=""

# ── Argument parsing ───────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-root) DATA_ROOT="$2"; shift 2 ;;
        --username)  USERNAME="$2"; shift 2 ;;
        --display)   DISPLAY_NAME="$2"; shift 2 ;;
        --password)  LOCK_PASSWORD="$2"; shift 2 ;;
        --help|-h)
            cat << EOF
GLTD Notes — Instalador CLI

Uso: sudo ./install.sh [OPCOES]

Opcoes:
  --data-root PATH   Pasta de dados (padrao: /home/\$USER/gltd_notes_data)
  --username  NAME   Nome do usuario (padrao: usuario atual)
  --display   NAME   Nome de exibicao (padrao: igual ao username)
  --password  PASS   Senha de bloqueio de sessao (padrao: sem senha)

Exemplo:
  sudo ./scripts/install.sh --username seu_usuario --data-root /home/seu_usuario/gltd_notes_data
EOF
            exit 0 ;;
        *) echo "Opcao desconhecida: $1"; exit 1 ;;
    esac
done

# ── Requer root ─────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERRO: execute como root (sudo ./scripts/install.sh)"
    exit 1
fi
REAL_USER="$SUDO_USER"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

echo "============================================"
echo "  GLTD Notes — Instalacao CLI"
echo "============================================"
echo "  Usuario:      $USERNAME"
echo "  Nome:         $DISPLAY_NAME"
echo "  Dados:        $DATA_ROOT"
echo "  Instalacao:   $INSTALL_DIR"
echo "  Home usuario: $REAL_HOME"
echo "============================================"
echo ""

# ── Dependencias do sistema ────────────────────────────────────
echo "[1/6] Instalando dependencias..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 gir1.2-notify-0.7 \
    gir1.2-ayatanaappindicator3-0.1 libnotify-bin \
    python3-gi-cairo gir1.2-webkit2-4.0 \
    qrencode 2>/dev/null || true
echo "  OK"

# ── Copiar arquivos ────────────────────────────────────────────
echo "[2/6] Instalando arquivos em $INSTALL_DIR..."
if [[ -d "$INSTALL_DIR" ]]; then
    echo "  Diretorio ja existe, atualizando..."
    cp -r "$ROOT"/{bin,gltd_notes,icons,scripts,docs,LICENSE,README.md,requirements.txt,pyproject.toml} "$INSTALL_DIR/" 2>/dev/null || true
else
    mkdir -p "$INSTALL_DIR"
    cp -r "$ROOT"/{bin,gltd_notes,icons,scripts,docs,LICENSE,README.md,requirements.txt,pyproject.toml} "$INSTALL_DIR/"
fi
chown -R "$REAL_USER:$REAL_USER" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/bin/"*
echo "  OK"

# ── Criar atalhos ──────────────────────────────────────────────
echo "[3/6] Criando atalhos no sistema..."
mkdir -p "$REAL_HOME/.local/bin"
ln -sf "$INSTALL_DIR/bin/gltd-notes" "$REAL_HOME/.local/bin/gltd-notes"
ln -sf "$INSTALL_DIR/bin/gltd-notes-api" "$REAL_HOME/.local/bin/gltd-notes-api"
ln -sf "$INSTALL_DIR/bin/gltd-notes-web" "$REAL_HOME/.local/bin/gltd-notes-web"
chown -R "$REAL_USER:$REAL_USER" "$REAL_HOME/.local/bin"
echo "  OK"

# ── Configurar dados ───────────────────────────────────────────
echo "[4/6] Configurando dados do usuario..."
mkdir -p "$DATA_ROOT"
chown -R "$REAL_USER:$REAL_USER" "$DATA_ROOT"

CONFIG_DIR="$REAL_HOME/.config/gltd_notes"
mkdir -p "$CONFIG_DIR"
chown -R "$REAL_USER:$REAL_USER" "$CONFIG_DIR"

# Inicializar como o usuario real
INIT_ARGS=(
    --data-root "$DATA_ROOT"
    --username  "$USERNAME"
    --display-name "$DISPLAY_NAME"
)
if [[ -n "$LOCK_PASSWORD" ]]; then
    INIT_ARGS+=(--lock-password "$LOCK_PASSWORD")
fi

su - "$REAL_USER" -c "cd '$INSTALL_DIR' && PYTHONPATH='$INSTALL_DIR' python3 -m gltd_notes init ${INIT_ARGS[*]}" || {
    echo "  AVISO: init falhou — execute manualmente:"
    echo "  $INSTALL_DIR/bin/gltd-notes init --data-root $DATA_ROOT --username $USERNAME"
}
echo "  OK"

# ── Atalhos desktop ─────────────────────────────────────────────
echo "[5/6] Criando atalhos desktop..."
sudo -u "$REAL_USER" "$INSTALL_DIR/scripts/install_desktop.sh" 2>/dev/null || {
    echo "  AVISO: atalhos desktop nao foram criados"
}
echo "  OK"

# ── Verificar ───────────────────────────────────────────────────
echo "[6/6] Verificando instalacao..."
su - "$REAL_USER" -c "cd '$INSTALL_DIR' && PYTHONPATH='$INSTALL_DIR' python3 -m gltd_notes status" 2>/dev/null || {
    echo "  AVISO: verificacao falhou — pode ser normal se nenhum dado existe ainda"
}

echo ""
echo "============================================"
echo "  Instalacao concluida!"
echo "============================================"
echo ""
echo "  Comandos disponiveis:"
echo "    gltd-notes          — interface grafica"
echo "    gltd-notes api      — servidor API REST (porta 8765)"
echo "    gltd-notes web      — interface web (http://127.0.0.1:8766)"
echo ""
echo "  Dados salvos em: $DATA_ROOT"
echo "  Config em:       $CONFIG_DIR/config.json"
echo ""
