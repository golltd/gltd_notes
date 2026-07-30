#!/usr/bin/env bash
# Install menu entries, icons next to bin/, and optional API autostart on login
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
BIN_DIR="$ROOT/bin"
BIN_LINK="${HOME}/.local/bin"

mkdir -p "$APP_DIR" "$BIN_LINK" "$AUTOSTART_DIR" "$BIN_DIR"

ln -sfn "$ROOT/bin/gltd-notes" "$BIN_LINK/gltd-notes"
ln -sfn "$ROOT/bin/gltd-notes-api" "$BIN_LINK/gltd-notes-api"
ln -sfn "$ROOT/bin/gltd-notes-web" "$BIN_LINK/gltd-notes-web"

# Always regenerate icons (cheap) so launchers stay in sync
python3 "$ROOT/scripts/generate_icons.py"

# Copy/symlink icons next to executables in bin/
install_bin_icon() {
  local name="$1"   # file stem without size, e.g. gltd-notes-api
  local dest="$2"   # bin icon basename, e.g. gltd-notes-api.png
  local src128="$ROOT/icons/${name}-128.png"
  local src="$ROOT/icons/${name}.png"
  if [[ -f "$src128" ]]; then
    cp -f "$src128" "$BIN_DIR/$dest"
  elif [[ -f "$src" ]]; then
    cp -f "$src" "$BIN_DIR/$dest"
  fi
}

# GUI main binary icon
install_bin_icon "gltd-notes-gui" "gltd-notes.png"
# also keep classic name
install_bin_icon "gltd-notes" "gltd-notes-app.png"
install_bin_icon "gltd-notes-api" "gltd-notes-api.png"
install_bin_icon "gltd-notes-web" "gltd-notes-web.png"

# Install hicolor icons for menus
if [[ -d "$ROOT/icons/hicolor" ]]; then
  for szdir in "$ROOT/icons/hicolor"/*; do
    [[ -d "$szdir" ]] || continue
    sz=$(basename "$szdir")
    dest="$ICON_HOME/$sz/apps"
    mkdir -p "$dest"
    for f in "$szdir/apps"/*.png; do
      [[ -f "$f" ]] || continue
      cp -f "$f" "$dest/$(basename "$f")"
    done
  done
  gtk-update-icon-cache -f -t "$ICON_HOME" 2>/dev/null || true
fi

# Prefer theme names; fall back to absolute paths (reliable on Mint)
icon_gui="gltd-notes-gui"
icon_api="gltd-notes-api"
icon_web="gltd-notes-web"
if [[ -f "$BIN_DIR/gltd-notes.png" ]]; then
  icon_gui="$BIN_DIR/gltd-notes.png"
fi
if [[ -f "$BIN_DIR/gltd-notes-api.png" ]]; then
  icon_api="$BIN_DIR/gltd-notes-api.png"
fi
if [[ -f "$BIN_DIR/gltd-notes-web.png" ]]; then
  icon_web="$BIN_DIR/gltd-notes-web.png"
fi

# ── Menu: GUI ──
cat > "$APP_DIR/gltd-notes.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GLTD Notes
GenericName=Notes
Comment=Notas privadas (alternativa ao GNote)
Exec=$ROOT/bin/gltd-notes gui
Icon=$icon_gui
Terminal=false
Categories=Office;Utility;
StartupNotify=true
Keywords=notes;gnote;tomboy;gltd;
StartupWMClass=gltd-notes
EOF

# ── Menu: Web UI ──
cat > "$APP_DIR/gltd-notes-web.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GLTD Notes Web
GenericName=Notes Web UI
Comment=Interface web do GLTD Notes (localhost)
Exec=$ROOT/bin/gltd-notes-web
Icon=$icon_web
Terminal=false
Categories=Office;Network;Utility;
StartupNotify=true
Keywords=notes;web;gltd;browser;
EOF

# ── Menu: API (manual start in terminal so logs are visible) ──
cat > "$APP_DIR/gltd-notes-api.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GLTD Notes API
GenericName=Notes API
Comment=Iniciar API REST local do GLTD Notes (127.0.0.1)
Exec=x-terminal-emulator -e bash -lc '$ROOT/bin/gltd-notes-api; echo; echo "API encerrada. Enter para fechar."; read'
Icon=$icon_api
Terminal=false
Categories=Network;Development;Utility;
StartupNotify=false
Keywords=notes;api;rest;gltd;
EOF

# Silent API launcher (no terminal) — used by autostart
cat > "$APP_DIR/gltd-notes-api-bg.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GLTD Notes API (background)
Comment=API REST em segundo plano
Exec=$ROOT/bin/gltd-notes-api
Icon=$icon_api
Terminal=false
NoDisplay=true
Categories=Network;Utility;
EOF

# ── Autostart API on user login (Linux Mint / Cinnamon / GNOME) ──
cat > "$AUTOSTART_DIR/gltd-notes-api.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GLTD Notes API
Comment=Inicia a API REST do GLTD Notes no login
Exec=$ROOT/bin/gltd-notes-api
Icon=$icon_api
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
Hidden=false
NoDisplay=false
EOF

chmod +x "$ROOT/bin/gltd-notes" "$ROOT/bin/gltd-notes-api" "$ROOT/bin/gltd-notes-web"
update-desktop-database "$APP_DIR" 2>/dev/null || true

# Optional systemd --user unit (installed but NOT enabled by default —
# Mint login uses ~/.config/autostart to avoid double-start).
SYSTEMD_USER="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
if command -v systemctl >/dev/null 2>&1; then
  mkdir -p "$SYSTEMD_USER"
  cat > "$SYSTEMD_USER/gltd-notes-api.service" <<EOF
[Unit]
Description=GLTD Notes local REST API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$ROOT/bin/gltd-notes-api
Restart=on-failure
RestartSec=5
Environment=PYTHONPATH=$ROOT

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload 2>/dev/null || true
  # Disable systemd unit if it was previously enabled, so only autostart runs
  if systemctl --user is-enabled gltd-notes-api.service >/dev/null 2>&1; then
    systemctl --user disable gltd-notes-api.service 2>/dev/null || true
  fi
fi

echo "OK — menu e autostart instalados"
echo "  Desktop:  $APP_DIR/gltd-notes.desktop"
echo "            $APP_DIR/gltd-notes-web.desktop"
echo "            $APP_DIR/gltd-notes-api.desktop"
echo "  Autostart API no login: $AUTOSTART_DIR/gltd-notes-api.desktop"
echo "  Ícones em bin/: $BIN_DIR/*.png"
echo "  CLI: $BIN_LINK"
echo ""
echo "API sobe automaticamente no login do usuário (autostart)."
echo "Para desativar a API no login:"
echo "  rm -f $AUTOSTART_DIR/gltd-notes-api.desktop"
echo "  # ou: Configurações do sistema → Inicialização → desmarque GLTD Notes API"
echo ""
echo "Alternativa systemd (em vez do autostart):"
echo "  rm -f $AUTOSTART_DIR/gltd-notes-api.desktop"
echo "  systemctl --user enable --now gltd-notes-api.service"
