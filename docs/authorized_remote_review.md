# 授权远程评审：部署、权限与HTTPS准备

## 模式与权限

Review提供两个获授权企业产品和一个合成Demo。KQ-Z112默认使用已批准的34项真实精简子集，可显式切换完整66项；第二企业产品保留完整91项。Trial是独立的仅合成备用。两套前端编译入口、端口、代理密钥和会话库分开。不得把开发8000或完整本地dist直接公网开放。

Review访问边界：个人HTTP Basic账号由Caddy验证；Caddy覆盖客户端身份头，后端核验私有代理密钥和明确产品grant。每次历史读取/续写都检查所有权及当前产品权限。无权限使用404，参数伪造422/409，跨站写请求403；每账号60请求/分钟、最多8个并行业务查询。不是企业SSO或通用用户权限平台。

企业SQLite以mode=ro/query_only打开，不迁移或写入；只读取私有配置明确绑定的主库存Excel、两份确认及已批准的版本化真实精简数据。评审会话与所有权写在 `.runtime/authorized-review/sessions.sqlite3`，合成事实/会话在其demo子目录。会话同时绑定产品、分析范围和数据版本；旧完整范围会话仍是完整范围，不能悄悄解释成精简历史。存储身份或版本不匹配明确拒绝，不能把企业库当运行会话库。

Review进程不加载.env，清除模型密钥并禁用模型；网络审计禁止非loopback连接。来源披露过滤统一用于当前响应和历史：隐藏原文件名、文件位置、SHA、内部确认人/证据URI及数据库ID，保留真实数量、单位、BOM关系与业务状态。过滤不是匿名化：认证评委能看获准的真实物料和数量，不得将数据继续公开。

## 工具与私有设置

Python3.12、Node>=22.12，项目依赖按README安装。现有便携Caddy2.11.7在 `.runtime/tools/caddy-2.11.7/caddy.exe`。`.runtime`不随clone交付；新机器从[Caddy官方](https://caddyserver.com/download)准备并校验版本/文件来源，不从企业数据包获取未知程序。

本机已采用随机密码与Windows DPAPI加密保存方式，两个三产品账号和一个仅演示产品账号分别授权。没有在报告、日志或命令行打印密码。下列初始化命令仅用于尚未配置的新环境，遇到已有私有配置会拒绝覆盖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/setup.ps1 -GenerateRandomPasswords -ApprovedDatasetVersion 20261011T030952Z-b4f34740
```

生成的 `credentials.local.xml` 与 `data.local.json` 均被Git忽略并限制当前Windows用户访问。DPAPI凭据不可直接换用户或换机器使用；新环境需重新设置账号和代理密钥。更换密钥会影响既有会话所有权，必须先规划历史迁移，不能删除历史绕过。需要自定义来源和授权范围时可参考示例文件，管理员私下核对：

1. 随机代理密钥至少32字符，不能使用REPLACE占位符。稳定保存以恢复原账号会话；换密钥会令旧所有权不匹配，先规划迁移，不删除历史绕过。
2. 独立账号名、独立强密码及哈希；密码不给前端、不提交，哈希/密钥也不可提交。Caddy账号名须与JSON users键精确对应；停用账号要同时撤销代理账号与后端grant。
3. 私有JSON显式绑定facts_path/inventory_path/units_path/quantity_path及 **slim_dataset_path**（已经审批的版本化真实精简文件，不是合成补充）。库存文件与确认中的source_uri、文件名、SHA、工作表须一致。缺少精简绑定时启动失败，不默默使用完整BOM。用户仅能访问users给出的产品。
4. WEB_ROOT须是本次Review专用构建。默认脚本固定使用 `.runtime/remote-review-web`；绝不能指向data、完整dist或另一个模式的构建。

交互式生成Caddy密码哈希（避免命令行明文密码进入终端历史）：

```powershell
& .\.runtime\tools\caddy-2.11.7\caddy.exe hash-password
```

三个账号是两名三产品用户加一名Demo-only用户。密码只在本机受控窗口查看：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/show-credentials.ps1
```

默认遮罩，主动勾选后仅在本机显示。请通过单独的安全渠道逐人发放，不截图公开、不把密码放进网址。临时验收脚本的一次性凭据不是正式账号。

## 本机启动、验收与停止

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/health.ps1
```

脚本在隐藏窗口启动Caddy与FastAPI，记录进程标识及启动时间。仅停止自己记录且身份核验一致的进程，不影响8000/5173或Trial。检查正式账号与生产页面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/verify.ps1
# 停止本机评审服务；不会停止开发服务或Trial
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/stop.ps1
```

认证页面127.0.0.1:8090、后端8020；均只监听loopback。普通前端API通过同源 `/api`，不把后端端口写成浏览器公网地址。

无人占用8020/8090时，可运行临时自动验收：

```powershell
.\venv\Scripts\python.exe scripts/verify_authorized_review_local.py --use-current-confirmations
# 其他已批准的私有来源配置：
.\venv\Scripts\python.exe scripts/verify_authorized_review_local.py --settings deploy/review/data.local.json
```

脚本生成忽略的一次性配置、凭据和本机进程，测试真实HTTP/生产浏览器、账号隔离及进程重启历史恢复，最后停止自己的进程，检查企业DB、Excel和确认不变。不要与正在运行的评审服务抢端口。测试结果/浏览器截图/日志同样私有，不提交。

使用上述stop脚本停止正式服务；手动启动的终端用Ctrl+C。Caddy admin off，因此不要用caddy stop。备份运行会话须先停止服务或用SQLite一致性备份，不在运行中只复制可能有WAL的主文件。日志与浏览器证据在忽略的 `.runtime/authorized-review`，同样不得公开。

## Cloudflare工具准备（不启动）

本机已准备官方cloudflared **2026.10.0**，路径 `.runtime/tools/cloudflared-2026.10.0/cloudflared.exe`，已核对GitHub发布asset SHA-256并运行version；未执行tunnel。新环境使用[官方Windows下载说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)，核对相应版本的官方release digest。

```powershell
& .\.runtime\tools\cloudflared-2026.10.0\cloudflared.exe --version
```

## 仅在用户明确授权启动后：HTTPS步骤

以下命令会创建公网入口，**不是本轮已经执行的步骤**：

```powershell
& .\.runtime\tools\cloudflared-2026.10.0\cloudflared.exe tunnel --url http://127.0.0.1:8090
```

只给指定评委分享输出的HTTPS链接，账号另渠道分发。不要分享原件、数据库、密钥或本地来源。Cloudflare会作为传输代理处理请求，此授权不等于第三方模型使用授权。Quick Tunnel是临时试用而非稳定SLA/固定网址，重启链接可能改变；其限制与配置要求见[官方Quick Tunnel说明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。正式长期部署应另行规划命名隧道/域名/Access及会话保留策略，不擅自创建。

上线后外部手机/电脑必须测试：未登录401；登录三产品选择；企业1/50/100片真实计算及未知；Demo50/75/76/100和采购；账号交叉历史404；来源不含私有文件定位；刷新恢复；非法0及网络错误不回退Mock；真实HTTPS Origin/Host不被误拒绝。尚未开启隧道，不能宣称这些公网环节已通过。

紧急关闭先Ctrl+C停止cloudflared，再停止Caddy和后端；撤销grant/密码后再验收。不要只隐藏菜单而继续暴露API，不删除原企业事实或历史。

## 剩余上线准备

- 正式账号已在本机生成并加密保存；仍需确认实际使用者、访问期限，并私下逐人发放凭据。
- 用户明确的HTTPS启动指令，然后外部设备验收。
- 审核访问期限、历史保存/清理和反馈管理；当前只读企业API不提供资料下载/修改。
- 主机维持在线及来源文件稳定；修改经核验来源需要重新验证确认，不以猜测默认值恢复。
- 仓库可见性未能通过当前连接确认，不能假定私有。历史含企业元数据，本次部署不授权公开仓库或push。
