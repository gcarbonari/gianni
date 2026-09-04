#!/usr/bin/env bash
# Crea cartelle, .venv e installa le librerie (idempotente).
# Uso: dalla root del progetto,  ./scripts/setup_env.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Directory progetto"
mkdir -p plc_monitor tests scripts .vscode

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 non trovato."
  echo "  macOS:  brew install python@3.12"
  echo "  oppure: https://www.python.org/downloads/"
  exit 1
fi

echo "==> $(python3 --version)  ($(command -v python3))"

if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "==> Installo python3-venv / pip / tk (matplotlib)"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip python3-tk
  else
    echo "Manca il modulo venv. Reinstalla Python 3.10+ con pip e venv abilitati."
    exit 1
  fi
fi

echo "==> Ambiente virtuale .venv"
python3 -m venv .venv

echo "==> Librerie da requirements.txt"
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt

echo
echo "Ambiente pronto."
echo "  Interprete: $ROOT/.venv/bin/python"
echo "  Attiva:     source .venv/bin/activate"
echo "  Demo:       python -m plc_monitor demo"
echo
echo "In Cursor: Command Palette → Python: Select Interpreter → .venv/bin/python"
