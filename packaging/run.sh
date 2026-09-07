#!/bin/bash
# ISObe-PS2 launcher (macOS / Linux)

cd "$(dirname "$0")" || exit 1

# 1. Check if a venv folder already exists
if [ ! -d "venv" ]; then
    echo "First time setup: Creating virtual environment..."
    python3 -m venv venv

    # 2. Activate the new venv
    source venv/bin/activate

    # 3. Install packages from your recipe
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    # If venv exists, just activate it
    source venv/bin/activate
fi

# 4. Run the server
echo "Starting ISObe..."
python3 server.py
