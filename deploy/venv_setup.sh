#!/bin/bash
# Installs Python 3.10.0 from source, creates venv, installs requirements.txt
set -e

# Optional: load config for project path
if [ -f variables.env ]; then
    source variables.env
fi

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
VENV_NAME="${VENV_NAME:-venv}"

cd "$PROJECT_ROOT"

PYTHON_VERSION="3.10.0"
PYTHON_BIN="python3.10"

# 1. Install build dependencies
echo "[INFO] Installing build dependencies for Python $PYTHON_VERSION ..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev \
    libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev wget libbz2-dev

# 2. Download, build, and altinstall Python 3.10.0 (idempotent: will not overwrite if already present)
if ! command -v python3.10 &>/dev/null || [[ "$($PYTHON_BIN --version 2>&1)" != "Python 3.10.0" ]]; then
    echo "[INFO] Downloading and building Python $PYTHON_VERSION ..."
    cd /tmp
    wget -q https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tgz
    tar -xf Python-$PYTHON_VERSION.tgz
    cd Python-$PYTHON_VERSION
    ./configure --enable-optimizations
    make -j$(nproc)
    sudo make altinstall
    cd "$PROJECT_ROOT"
else
    echo "[INFO] python3.10 already installed."
fi

python3.10 --version

# 3. Create venv if missing
if [ ! -d "$VENV_NAME" ]; then
    echo "[INFO] Creating venv at $PROJECT_ROOT/$VENV_NAME ..."
    python3.10 -m venv "$VENV_NAME"
else
    echo "[INFO] venv already exists at $PROJECT_ROOT/$VENV_NAME"
fi

# 4. Activate venv and install requirements.txt
source "$VENV_NAME/bin/activate"

if [ -f requirements.txt ]; then
    echo "[INFO] Installing requirements from requirements.txt..."
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "[SUCCESS] requirements.txt installed."
else
    echo "[WARNING] No requirements.txt found in $PROJECT_ROOT."
fi

deactivate
echo "[ALL DONE] Python 3.10.0 venv setup complete."
