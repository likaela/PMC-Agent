#!/usr/bin/env bash
# PMC-Agent 腾讯云轻量应用服务器（Ubuntu）一键部署脚本
# 用法：
#   1. 已通过 git clone 拉取项目，进入项目根目录
#   2. 复制 .env.production.example 为 .env 并填好密钥
#   3. bash deploy/lighthouse/deploy.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="${PROJECT_ROOT}/pmc-agent-frontend-main/frontend"
APP_USER="${APP_USER:-ubuntu}"
SERVICE_NAME="pmc-agent"
BACKEND_PORT=8000

log()  { echo -e "\033[1;32m[部署]\033[0m $*"; }
warn() { echo -e "\033[1;33m[警告]\033[0m $*"; }
err()  { echo -e "\033[1;31m[错误]\033[0m $*"; exit 1; }

cd "${PROJECT_ROOT}"

# 0. 环境变量检查
if [ ! -f ".env" ]; then
  err "未找到 .env 文件。请先执行：cp deploy/lighthouse/.env.production.example .env 并填写密钥"
fi

# 1. 安装系统依赖
log "安装系统依赖 (python3-venv / pip / git / nginx / nodejs)..."
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git nginx curl

# 2. Node.js 22（前端需要 >= 22.12）
if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node' 2>/dev/null | cut -d. -f1)" -lt 22 ]; then
  log "安装 Node.js 22..."
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
log "Node 版本: $(node -v) / npm $(npm -v)"

# 3. Python 虚拟环境 + 依赖
log "创建 Python 虚拟环境并安装依赖..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. 构建前端
log "构建前端..."
cd "${FRONTEND_DIR}"
npm install
# 生产构建：同源反代，API 走根路径
VITE_API_BASE_URL=/ npm run build
cd "${PROJECT_ROOT}"

# 5. 安装 systemd 服务
log "安装 systemd 服务 ${SERVICE_NAME}..."
SERVICE_SRC="${PROJECT_ROOT}/deploy/lighthouse/pmc-agent.service"
sudo tee /etc/systemd/system/${SERVICE_NAME}.service >/dev/null <<EOF
[Unit]
Description=PMC-Agent FastAPI Backend
After=network.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${PROJECT_ROOT}
EnvironmentFile=${PROJECT_ROOT}/.env
ExecStart=${PROJECT_ROOT}/venv/bin/uvicorn api.app:app --host 127.0.0.1 --port ${BACKEND_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_NAME}
log "后端服务已启动，状态如下："
sudo systemctl status ${SERVICE_NAME} --no-pager || true

# 6. 安装 nginx 站点
log "配置 nginx 反向代理..."
sudo tee /etc/nginx/sites-available/${SERVICE_NAME} >/dev/null <<EOF
server {
    listen 80 default_server;
    server_name _;

    root ${FRONTEND_DIR}/dist;
    index index.html;

    # Vue 前端 history 路由回退
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # 后端 API 反代
    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # 健康检查直通
    location /health {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/${SERVICE_NAME} /etc/nginx/sites-enabled/${SERVICE_NAME}
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

log "部署完成！"
log "后端健康检查: curl http://127.0.0.1:${BACKEND_PORT}/health"
log "请在腾讯云控制台防火墙放行 80 端口后，通过 http://<公网IP> 访问。"
