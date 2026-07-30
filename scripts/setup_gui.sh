#!/usr/bin/env bash
# =============================================================================
# GLTD Notes — GUI Setup Wizard
# Abre o assistente grafico de configuracao inicial.
# Uso: ./scripts/setup_gui.sh
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "GLTD Notes — Assistente de Configuracao"
echo ""

# Verifica dependencias graficas
if ! python3 -c "import gi; gi.require_version('Gtk','3.0')" 2>/dev/null; then
    echo "ERRO: GTK 3 nao encontrado. Instale com:"
    echo "  sudo apt install python3-gi gir1.2-gtk-3.0"
    exit 1
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m gltd_notes setup "$@"
