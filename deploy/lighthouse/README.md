# PMC-Agent 腾讯云轻量服务器（Lighthouse）部署指南

> 目标：把带 FastAPI 后端 + Vue 前端的 LangChain/LangGraph PMC Agent 部署到腾讯云轻量应用服务器（Ubuntu），对外通过 80 端口访问。

## 整体架构

```
浏览器 ──> Nginx(80) ──> 静态文件 dist/（前端）
              │
              └──> /api/* ──> uvicorn(FastAPI, 127.0.0.1:8000) ──> LangGraph Agent ──> DeepSeek/MiMo
```

前端构建时 `VITE_API_BASE_URL=/`，走同源反代，无需跨域配置，也无需暴露 8000 端口。

## 前置条件

- 服务器：Ubuntu 22.04/24.04（轻量应用服务器默认镜像即可）
- 已在腾讯云控制台「防火墙」放行 **22（SSH）** 和 **80（HTTP）** 端口
- 项目代码已提交到 GitHub（或已上传到服务器）

## 部署步骤

### 1. 本地提交并推送代码

```bash
cd "E:\I Wanna go to BJUT\Competetion\RGZN+\PMC-Agent"
git add -A
git commit -m "chore: 部署到腾讯云轻量服务器"
git push origin feat/new-frontend-integration
```

### 2. SSH 登录服务器并拉取代码

```bash
ssh ubuntu@62.234.100.141

# 拉取代码
git clone https://github.com/likaela/PMC-Agent.git
cd PMC-Agent
git checkout feat/new-frontend-integration
```

### 3. 配置生产环境变量

```bash
cp deploy/lighthouse/.env.production.example .env
nano .env   # 填入真实的 DEEPSEEK_API_KEY
```

### 4. 一键部署

```bash
bash deploy/lighthouse/deploy.sh
```

脚本会自动完成：装系统依赖 → 装 Node.js 22 → 建 Python venv 装依赖 → 构建前端 → 配置 systemd 服务 → 配置 nginx 反代。

### 5. 验证

```bash
# 后端健康检查
curl http://127.0.0.1:8000/health

# 查看服务状态
sudo systemctl status pmc-agent

# 查看后端日志
sudo journalctl -u pmc-agent -f
```

浏览器访问 `http://62.234.100.141` 即可看到前端页面。

## 常用运维命令

```bash
# 更新代码后重新部署
cd ~/PMC-Agent && git pull && bash deploy/lighthouse/deploy.sh

# 重启后端
sudo systemctl restart pmc-agent

# 查看实时日志
sudo journalctl -u pmc-agent -f
```

## 注意事项

1. **密钥安全**：`.env` 已被 `.gitignore` 排除，永远不会进入 git。服务器上的 `.env` 文件请设置 `chmod 600 .env`。
2. **数据源**：当前使用 `PMC_DATA_SOURCE=demo`（内置演示数据 + SQLite），无需 PostgreSQL。若需企业真实数据，需额外部署 PostgreSQL 并改环境变量，同时上传 `data/normalized` 私有数据（该目录也在 gitignore 中，不会随 clone 传播）。
3. **LLM**：默认走 DeepSeek。若使用 MiMo，改 `LLM_PROVIDER=mimo` 并填 MIMO 相关变量。
4. **端口**：后端仅监听 127.0.0.1，不直接暴露公网，安全性更好。
