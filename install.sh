#!/bin/bash

echo -e "\033[1;36m========================================\033[0m"
echo -e "\033[1;36m      Installing Aurora Agent...        \033[0m"
echo -e "\033[1;36m========================================\033[0m"

# Check for git
if ! command -v git &> /dev/null; then
    echo -e "\033[1;31mGit is not installed. Please install git and try again.\033[0m"
    exit 1
fi

# Check for python3
if ! command -v python3 &> /dev/null; then
    echo -e "\033[1;31mPython3 is not installed. Please install Python3 and try again.\033[0m"
    exit 1
fi

echo "[1/4] Cloning the Aurora repository..."
git clone https://github.com/Muminul-Hoque/Aurora.git
cd Aurora || exit

echo "[2/4] Setting up a Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[3/4] Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[4/4] Launching the Setup Wizard..."
python setup.py

echo -e "\033[1;32m========================================\033[0m"
echo -e "\033[1;32m      Aurora Installation Complete!     \033[0m"
echo -e "\033[1;32m========================================\033[0m"
echo ""
echo "To start your agent at any time, run:"
echo "cd Aurora"
echo "source venv/bin/activate"
echo "python telegram_bot.py"
echo ""
