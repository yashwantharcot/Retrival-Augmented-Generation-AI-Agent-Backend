#!/usr/bin/env pwsh
Write-Host "Setting up virtualenv and installing dependencies (Windows)"

if (-Not (Test-Path -Path .venv)) {
    python -m venv .venv
}

Write-Host "Activating .venv"
. .\.venv\Scripts\Activate.ps1

Write-Host "Upgrading pip, setuptools, wheel"
python -m pip install --upgrade pip setuptools wheel

Write-Host "Uninstalling old torch packages (if any)"
pip uninstall -y torch torchvision torchaudio 2>$null

Write-Host "Installing PyTorch CPU build (2.2.1)"
pip install --upgrade "torch==2.2.1+cpu" --index-url https://download.pytorch.org/whl/cpu
pip install --upgrade "torchvision==0.17.1+cpu" --index-url https://download.pytorch.org/whl/cpu

Write-Host "Installing remaining requirements"
pip install -r requirements.txt --upgrade

Write-Host "Setup complete. To activate the venv, run:`n. \.venv\Scripts\Activate.ps1`"