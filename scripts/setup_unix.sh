#!/usr/bin/env bash
set -euo pipefail
echo "Setting up virtualenv and installing dependencies (Unix)"
python3 -m venv .venv
echo "Activating .venv"
source .venv/bin/activate
echo "Upgrading pip, setuptools, wheel"
python -m pip install --upgrade pip setuptools wheel
echo "Uninstalling old torch packages (if any)"
pip uninstall -y torch torchvision torchaudio || true
echo "Installing PyTorch CPU build (2.2.1)"
pip install --upgrade "torch==2.2.1+cpu" --index-url https://download.pytorch.org/whl/cpu
pip install --upgrade "torchvision==0.17.1+cpu" --index-url https://download.pytorch.org/whl/cpu
echo "Installing remaining requirements"
pip install -r requirements.txt --upgrade
echo "Setup complete. Activate the venv with: source .venv/bin/activate"