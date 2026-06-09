#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "==> PLC Monitor setup"

# 1) Ensure Python deps are installed via uv/venv
if [ ! -d ".venv" ]; then
  echo "Creating .venv..."
  uv venv .venv
fi

echo "Installing Python deps..."
uv pip install -r requirements.txt --python .venv/bin/python

# 2) Install system packages (Ubuntu/Debian)
echo "Installing system packages (requires sudo)..."
sudo apt-get update
sudo apt-get install -y \
  build-essential \
  libsnap7-dev \
  python3-dev

# 3) Initialize config if missing
if [ ! -f "config.json" ]; then
  echo "Creating config.json from example..."
  cp config.example.json config.json
  echo "Edit config.json with your PLC IP and DB addresses."
fi

echo "Setup complete."
echo "Run with:"
echo "  source .venv/bin/activate"
echo "  python monitor.py"
