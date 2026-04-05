#!/usr/bin/env bash
#
# Provision a VPS for Claude Code agent execution.
# Usage: ssh root@<vps-ip> 'bash -s' < agents/install_vps.sh
#
set -euo pipefail

echo "=== Phoenix Claw VPS Provisioning ==="
echo "Host: $(hostname)"
echo "Date: $(date -u)"
echo ""

# --- System updates ---
echo "[1/6] Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

# --- Python ---
echo "[2/6] Installing Python 3.11+ and pip..."
apt-get install -y -qq python3 python3-pip python3-venv git curl jq

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "       Python $PYTHON_VERSION installed."

# --- Node.js (for Claude Code) ---
echo "[3/6] Installing Node.js 20.x..."
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
fi
NODE_VERSION=$(node --version 2>&1)
echo "       Node $NODE_VERSION installed."

# --- Claude Code CLI ---
echo "[4/6] Installing Claude Code CLI..."
if ! command -v claude &>/dev/null; then
    npm install -g @anthropic-ai/claude-code
fi
CLAUDE_VERSION=$(claude --version 2>&1 || echo "unknown")
echo "       Claude Code $CLAUDE_VERSION installed."

# --- Agent directory structure ---
echo "[5/6] Creating agent directories..."
mkdir -p ~/agents/backtesting
mkdir -p ~/agents/live
echo "       ~/agents/ ready."

# --- Python dependencies for agents ---
echo "[6/6] Installing Python ML dependencies..."
python3 -m pip install --quiet \
    numpy pandas scikit-learn xgboost lightgbm catboost \
    torch --index-url https://download.pytorch.org/whl/cpu \
    joblib pyarrow yfinance httpx discord.py-self pyotp \
    robin_stocks sentence-transformers shap

echo ""
echo "=== Provisioning Complete ==="
echo "  Python: $PYTHON_VERSION"
echo "  Node:   $NODE_VERSION"
echo "  Claude: $CLAUDE_VERSION"
echo "  Agents: ~/agents/"
echo ""
echo "Next: Ship backtesting agent with SCP and configure .env"
