# 受控远程试用（只使用合成数据）

链路：Vue production build → Caddy → FastAPI trial_app → 独立 DEMO-PMC-01 数据库。
确认后才允许启动 Cloudflare Tunnel。本文命令不会自动创建隧道。

## 安全边界

- 本地企业入口 `api.app:app` 和既有 8000/5173 服务不变。
- 专用后端只监听 `127.0.0.1:8010`，Caddy 只监听 `127.0.0.1:8080`。
- Caddy Basic Auth 为每人分配不同账号；不要多人共享一个账号。后端只接受私有代理密钥与 Caddy 覆写的用户名。
- 会话所有权存于隔离 Demo 库中的 `trial_session_owners`；查看历史和发送消息均校验。未知与越权统一404。
- 专用进程不加载 `.env`，不提供旧 Chat/Workflow/企业接口，拒绝 enterprise FactStore，模型完全禁用。
- 启动器的进程级审计钩子也拒绝打开企业 raw/facts/normalized/.env 及非loopback网络连接；只允许Windows事件循环需要的本机socket通信。不等同于操作系统级沙箱，本机管理员仍是可信边界。
- 用户输入也可能包含敏感信息，故即使合成 Demo 也不默认启用 DeepSeek。使用既有 Python fallback，不影响业务查询。
- 同源 API、CSRF Origin 检查、每账号每分钟60请求、全进程最多8并行查询、Caddy请求体上限64KB。
- 保留会话持久化与乐观并发409；仅小规模试用，单 Uvicorn worker。
- 数据/凭证/日志均在 ignored `.runtime` 或 `*.local.ps1`，不得提交。试用后由管理员决定历史保留期限。
- 本机管理员仍是可信边界；本方案不是多租户企业权限系统。不要向本地企业8000端口建立隧道。

## Windows 准备（PowerShell，项目根目录）

先按[环境交接说明](review_environment_handoff.md)准备 Python 3.12 venv 和新前端依赖。`.runtime/tools/caddy-2.11.7/caddy.exe` 是本机已校验的便携工具，不随Git clone分发；新电脑必须单独从官方发行准备该Windows版本并核对官方SHA，或先经测试调整工具路径，不要假设仓库附带二进制。无需安装系统服务。cloudflared 尚未安装；开放前请按 [官方 Windows 下载说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) 安装并确认 `cloudflared --version`，本轮不安装/启动隧道。

```powershell
if (Test-Path deploy/trial/settings.local.ps1) { throw '已有私有配置，请勿覆盖' }
Copy-Item deploy/trial/settings.example.ps1 deploy/trial/settings.local.ps1
```

不要覆盖已有 local 配置。用编辑器填写本地文件：
1. 私有代理密钥：用 `[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')` 生成后存入 local 文件，不要分享。
2. 每位体验者的独立用户名、独立密码哈希；运行 `& ./.runtime/tools/caddy-2.11.7/caddy.exe hash-password` 交互输入密码，复制生成的哈希到 local 文件。配置中禁止放明文密码。
3. 将用户名/密码通过私下渠道分别发给体验者，不要把代理密钥或配置文件发给他们。
4. 如需更多人，在 Caddyfile basic_auth 块逐条增加账号及哈希；后端按用户名自动隔离。

```powershell
powershell -ExecutionPolicy Bypass -File deploy/trial/build.ps1
```

构建采用独立 `frontend/trial/index.html` 入口和独立会话状态，不导入企业 App、路由、私有场景表或离线样例。共享 API 客户端、响应适配器和结果组件仍复用，但试用白名单模块在编译期替换为仅含一个合成场景的模块，而非运行时隐藏。

产物仅在 `.runtime/remote-trial-web`，不覆盖普通 frontend/dist，不改变开发环境变量。旧构建先移动到 ignored `.runtime/build-backups/` 供私有审计，避免旧资源残留在服务目录。关闭 publicDir 和 Source Map，编译依赖白名单拒绝其他应用模块；随后 `scripts/audit_trial_bundle.py` 检查全部产物及 `module-closure.json`。任何检查失败均不得启动代理或发布该目录。

## 启动（三个独立终端）

终端一（专用后端）：
```powershell
. ./deploy/trial/settings.local.ps1
.\venv\Scripts\python.exe scripts/run_remote_trial.py
```

终端二（本地代理）：
```powershell
. ./deploy/trial/settings.local.ps1
& ./.runtime/tools/caddy-2.11.7/caddy.exe validate --config deploy/trial/Caddyfile --adapter caddyfile
& ./.runtime/tools/caddy-2.11.7/caddy.exe run --config deploy/trial/Caddyfile --adapter caddyfile
```

打开 `http://127.0.0.1:8080`，输入个人试用账号，先验收50台、100台、采购建议及刷新恢复。此时仍未公网开放。

**只有经项目负责人确认后**，终端三：
```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

控制台输出 `https://....trycloudflare.com` 链接，分享链接及个人账号。前端通过同源 `/api/v1/agent/...` 调用，密钥不进入前端。
Quick Tunnel 是临时链接，重启地址可能变化，不能当作稳定部署/SLA。机器需在线；如已有 cloudflared config 导致 Quick Tunnel 失败，应检查工具配置，不指向企业端口绕过。

## 停止

依次在终端三、二、一按 `Ctrl+C`。Caddy admin 关闭，不能用 `caddy stop`；不要停止原本的8000/5173进程。
禁止直接复制企业 DB 到 `.runtime/remote-trial`；Demo 身份校验会拒绝混库。不要删除目录来修复身份冲突，应先审计。

## 开放前验收

专用构建已从依赖入口隔离企业模块；仍须对每次将要发布的产物运行隐私扫描，不能拿历史构建的检查结果作证明。静态产物通过不代表开发仓库历史可公开；源码公开使用另行审查的全新合成仓库，不继承企业开发提交历史。本轮不开放公网。

- 两个独立账号，互相 GET/POST 对方 session 均404；同一账号重启服务可恢复。
- 50台齐套；100台四项缺口25/100/50/200；四项采购建议、合成总成本1560.00 CNY；建议不代表到货。
- 浏览器首页和工作台均标注“合成演示数据”，新建分析也保持合成空间。
- 无企业URL/raw访问；模型禁用；API错误不切mock、不暴露堆栈。
- 公网确认后还需验证实际 HTTPS 登录、隧道 Host/Origin、刷新、断网、限流体验。未开隧道时不可宣称这部分验收完成。

参考：[Caddy Basic Auth](https://caddyserver.com/docs/caddyfile/directives/basic_auth)、[Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/)。

本地验收副作用记录：首次便携Caddy测试在Windows用户默认Caddy目录生成了一次性测试autosave配置（不含企业事实）。之后配置增加 `persist_config off` 并把XDG配置/数据目录隔离到 `.runtime`，不再自动写该文件。本轮未擅自删除或恢复用户目录文件；此记录不是要求使用 `--resume`，启动必须始终显式指定本项目Caddyfile。
