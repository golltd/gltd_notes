#!/usr/bin/env bash
# Bump patch version in _version.py and pyproject.toml
# Usage: ./scripts/bump_version.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="$ROOT/gltd_notes/_version.py"
PYPROJECT="$ROOT/pyproject.toml"

current=$(grep -oP '[0-9]+\.[0-9]+\.[0-9]+' "$VERSION_FILE" | head -1)
if [ -z "$current" ]; then
    echo "ERRO: versao nao encontrada em $VERSION_FILE"
    exit 1
fi

IFS='.' read -r major minor patch <<< "$current"
new_patch=$((patch + 1))
new_version="${major}.${minor}.${new_patch}"

echo "Atualizando versao: $current -> $new_version"

sed -i "s/__version__ = \"$current\"/__version__ = \"$new_version\"/" "$VERSION_FILE"
sed -i "s/version = \"$current\"/version = \"$new_version\"/" "$PYPROJECT"

echo "Versao $new_version atualizada em:"
echo "  $VERSION_FILE"
echo "  $PYPROJECT"
echo ""
echo "Lembre-se de commitar as alteracoes junto com o codigo."
