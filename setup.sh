#!/usr/bin/env bash
# One-shot Ubuntu setup for bybit-smm-as
# Run as: bash setup.sh
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/5] Updating system packages..."
apt-get update -y && apt-get upgrade -y

echo "[2/5] Installing Python 3.11 + pip + venv..."
apt-get install -y python3.11 python3.11-venv python3-pip git

echo "[3/5] Creating virtual environment..."
python3.11 -m venv "$REPO_DIR/venv"
source "$REPO_DIR/venv/bin/activate"

echo "[4/5] Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$REPO_DIR/requirements.txt"

echo "[5/5] Setting up config files..."
if [ ! -f "$REPO_DIR/parameters.yaml" ]; then
    cp "$REPO_DIR/parameters.yaml.example" "$REPO_DIR/parameters.yaml"
    echo "  -> Copied parameters.yaml.example to parameters.yaml"
    echo "  -> EDIT $REPO_DIR/parameters.yaml with your settings!"
fi

if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "  -> Copied .env.example to .env"
    echo "  -> EDIT $REPO_DIR/.env with your API keys!"
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Edit $REPO_DIR/parameters.yaml"
echo "  2. Edit $REPO_DIR/.env  (API_KEY and API_SECRET)"
echo "  3. Install systemd service:"
echo "     sudo cp $REPO_DIR/smm-as.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now smm-as"
echo "  4. Check logs: sudo journalctl -u smm-as -f"
