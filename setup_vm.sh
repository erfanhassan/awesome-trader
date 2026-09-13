#!/bin/bash
set -e

# Update and install dependencies
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nginx curl tar

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Extract code
mkdir -p ~/app
tar -xzf ~/awesome-trader.tar.gz -C ~/app
mv ~/.env ~/app/backend/
mv ~/credentials.json ~/app/backend/

# Setup Backend
cd ~/app/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup Frontend
cd ~/app/frontend
npm install
npm run build

# Configure Systemd for Backend
cat << EOF | sudo tee /etc/systemd/system/awesome-trader.service
[Unit]
Description=Awesome Trader Backend
After=network.target

[Service]
User=$USER
WorkingDirectory=/home/$USER/app/backend
Environment="PATH=/home/$USER/app/backend/venv/bin:/usr/bin"
ExecStart=/home/$USER/app/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable awesome-trader
sudo systemctl start awesome-trader

# Configure Nginx
cat << EOF | sudo tee /etc/nginx/sites-available/default
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    root /home/$USER/app/frontend/dist;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

# Fix permissions so nginx can read frontend dist
chmod +x /home/$USER
chmod +x /home/$USER/app
chmod +x /home/$USER/app/frontend
chmod -R 755 /home/$USER/app/frontend/dist

sudo systemctl restart nginx
echo "Deployment successful!"
