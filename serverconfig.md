# ✅ Full Deployment Guide for LLM Backend on EC2/Ubuntu with GitHub Actions
---
## 1️⃣ Launch an EC2 Instance RHEL

### Step-by-step:
1. Go to AWS EC2 Console → Launch Instance
2. Choose Ubuntu Server 22.04 LTS
3. Choose instance type: t3.medium or higher for LLMs
4. Create a new Key Pair (or use existing)
5. Allow inbound security group rules:
    - ✅ SSH (port 22)
    - ✅ HTTP (port 80)
    - ✅ HTTPS (port 443)
6. Click Launch
---
## 2️⃣ SSH into EC2

- From your terminal:
```bash
ssh -i ~/your-key.pem ubuntu@<EC2-Public-IP>
```
---
## 3️⃣ Install Required Packages
```bash
sudo yum update -y
sudo yum install -y python3 python3-pip python3-venv nginx git firewalld
```
---
## ✅ Enable & Start Firewalld
```bash
sudo systemctl enable firewalld
sudo systemctl start firewalld
```

## 🔥 Open Ports in Firewalld (like ufw)
```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---
## 4️⃣ Clone Your Repo & Setup Project

### 🔐 1️⃣ Generate SSH Key
```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"  
```
---

### 📂 2️⃣ View the Public Key
```bash
   cat ~/.ssh/id_ed25519.pub
```
- Copy the entire output (starts with ssh-ed25519 ...)
- Add it to your Git hosting service under SSH keys:
  - GitHub: GitHub SSH Key Settings (https://github.com/settings/keys)
---
```bash
git clone git@github.com:SPM-Global-Technologies/DealdoxAgent_DEVQA.git
cd DealdoxAgent_DEVQA
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
---
## 5️⃣ Create run.sh for Manual Running (optional)
```bash
vi run.sh
```
Paste:

```bash
#!/bin/bash
source venv/bin/activate
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 --workers 2 --timeout 120 --log-level info
```
```bash
chmod +x run.sh
```

---
## 6️⃣ Create a systemd Service
```bash
sudo vi /etc/systemd/system/llm-app.service
```
Paste:
```bash
[Unit]
Description=LLM Backend App
After=network.target

[Service]
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/DealdoxAgent_DEVQA

# FIXED: Use bash to launch gunicorn inside the venv
ExecStart=/bin/bash -c 'source /home/ec2-user/DealdoxAgent_DEVQA/venv/bin/activate && exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 --workers 2 --timeout 120'

Restart=always
Environment="PATH=/home/ec2-user/DealdoxAgent_DEVQA/venv/bin"

[Install]
WantedBy=multi-user.target
```
Enable and start:
```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable llm-app
sudo systemctl start llm-app
```

---
## 7️⃣ Setup NGINX + SSL (llm.dealdox.io)
```bash
sudo apt install certbot python3-certbot-nginx -y
```
Create NGINX config:
```bash
sudo vi /etc/nginx/conf.d/llm.dealdox.io.conf
```
Paste:
```bash
server {
    listen 443 ssl;
    server_name llm.dealdox.io;

    ssl_certificate /etc/letsencrypt/live/llm.dealdox.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llm.dealdox.io/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 20M;

    # Handle CORS preflight requests
    location / {
        if ($request_method = OPTIONS) {
            return 204;
        }

        proxy_pass http://127.0.0.1:8000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # CORS headers
        add_header 'Access-Control-Allow-Origin' 'https://devqa.dealdox.io' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type' always;
        add_header 'Access-Control-Allow-Credentials' 'true' always;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name llm.dealdox.io;
    return 301 https://$host$request_uri;
}
```
Then:
```bash
sudo certbot --nginx -d llm.dealdox.io
sudo nginx -t
sudo systemctl reload nginx
```

---

## 8️⃣ CI/CD with GitHub Actions

### ✅ On EC2: Generate SSH Key
```bash
ssh-keygen -t rsa -b 4096 -f ~/.ssh/github-deploy
cat ~/.ssh/github-deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github-deploy   # copy this private key
```
---

### ✅ On GitHub: Add Repository Secrets
- Go to Settings → Secrets → Actions, then add:

1. SSH_KEY: (Paste private key content)
2. EC2_HOST: Public IP of EC2
3. EC2_USER: ec2-user
4. DEPLOY_PATH: /home/ec2-user/DealdoxAgent_DEVQA

---

### ✅ On EC2: Create deploy.sh
```bash
vi /home/ec2-user/DealdoxAgent_DEVQA/deploy.sh
```
Paste:
```bash
#!/bin/bash
set -e

cd /home/ec2-user/DealdoxAgent_DEVQA || {
  echo "❌ Could not change to /home/ec2-user/DealdoxAgent_DEVQA"
  exit 1
}

echo "🛑 Stopping LLM Backend service..."
sudo systemctl stop llm-app

echo "🔄 Pulling latest code from Production..."
git reset --hard
git pull origin Production

echo "🐍 Activating virtual environment..."
source venv/bin/activate

echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🔐 Writing .env file..."
cat > .env <<EOL
OPENAI_API_KEY=${OPENAI_API_KEY}
MONGODB_URI=${MONGODB_URI}
MONGODB_DB=${MONGODB_DB}
MONGODB_COLLECTION=${MONGODB_COLLECTION}
EOL

echo "🚀 Starting LLM Backend service..."
sudo systemctl daemon-reexec
sudo systemctl start llm-app

echo "✅ Deployment complete."

```

Make Sure it's Executable:
```bash
chmod +x deploy.sh
```

---

### ✅ In GitHub: Create CI/CD Workflow
- Create file: .github/workflows/deploy.yml

```bash
name: Deploy to EC2 Instance

on:
  push:
    branches:
      - Production

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Code
        uses: actions/checkout@v3

      - name: Setup SSH
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.SSH_KEY }}" > ~/.ssh/id_rsa
          chmod 600 ~/.ssh/id_rsa
          ssh-keyscan -H ${{ secrets.EC2_HOST }} >> ~/.ssh/known_hosts

      - name: Deploy to EC2
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          MONGODB_URI: ${{ secrets.MONGODB_URI }}
          MONGODB_DB: ${{ secrets.MONGODB_DB }}
          MONGODB_COLLECTION: ${{ secrets.MONGODB_COLLECTION }}
        run: |
          ssh ${{ secrets.EC2_USER }}@${{ secrets.EC2_HOST }} \
          "OPENAI_API_KEY='$OPENAI_API_KEY' \
           MONGODB_URI='$MONGODB_URI' \
           MONGODB_DB='$MONGODB_DB' \
           MONGODB_COLLECTION='$MONGODB_COLLECTION' \
           bash /home/ec2-user/DealdoxAgent_DEVQA/deploy.sh"
```

Commit and push:
```bash
git add .
git commit -m "Add CI/CD"
git push origin Production
```

---

### ✅ Validate Deployment

1. Push to Production → check GitHub Actions > Deploy to EC2
2. SSH into EC2:

```bash
sudo systemctl status llm-app
curl -I https://llm.dealdox.io
```
✅ You should see 200 OK or similar.
