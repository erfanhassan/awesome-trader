#!/bin/bash
set -e

echo "Unzipping code..."
unzip -o deploy.zip -d awesome-trader
cd awesome-trader

echo "Setting up Python venv..."
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
pip install uvicorn  # Ensure uvicorn is installed

echo "Installing Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "Building frontend..."
cd frontend
npm install
npm run build
cd ..

echo "Starting server..."
# Kill any existing screen session named trader
screen -X -S trader quit || true
# Start the backend in a detached screen session
cd backend
screen -dmS trader ../venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000

echo "Setup complete!"
