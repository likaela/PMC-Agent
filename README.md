# 智造 PMC Agent

面向制造企业 PMC、计划员与生产协调人员的智能计划助手。

用户描述产品与生产数量，系统查询已发布BOM、计算物料需求、核对库存记录，并给出可追溯结果与自然语言解释。大语言模型用于理解和表达，事实与业务数字来自受控工具和Python计算。

## 项目背景与核心能力

生产计划涉及BOM、库存与采购等分散资料。PMC-Agent将数据来源、数量核对和连续追问组织在同一个分析工作台，帮助用户定位需求与限制条件。

- 产品目录、BOM与物料组成查询。
- 多层BOM、版本、生效期和显式单位换算。
- 库存匹配、需求计算及已知数量核对。
- 数据完整时的齐套、最大数量、批次/FIFO和库存风险分析。
- 参数与价格完整时的MOQ、包装倍数、采购数量及成本建议。
- 持久会话、证据复用、来源查询及历史恢复。
- 产品与分析范围隔离，未知保持null，连接失败不伪造成功。

能力存在不代表每个来源都满足计算条件。无库存记录不补0，在库量不自动视为可用量。当前主库存数量比较须有来源绑定的人工确认。数量结果不等于工单放行、设备产能或交期承诺。

## 系统架构与Agent工作流

```text
Vue → FastAPI /api/v1/agent/query → Persistent Agent Service
  → Planner → Context Resolver → 白名单Tool Registry
  → Published Facts / 受控库存Repository / 确定性Service
  → Evidence → Response Generator与事实校验 → 响应与持久会话

原有生产路径：FastAPI → LangGraph PMC → Tool → 业务Service（保留）
```

Planner理解问题，Context Resolver补全有来源的业务条件，Python校验工具与参数。Tool返回结构化数据、完整性、来源和警告，Evidence用于回答、原因追问和审计。模型失败使用Python业务模板，事实与许可状态不改变。没有数据时明确拒答，不猜库存、价格或到货日期。

开发环境可以配置DeepSeek。未经批准的企业Evidence不得发送到第三方模型；授权远程版和独立演示版禁用模型出站，使用规则理解与确定性表达。界面不展示思维链或伪造实时执行阶段。

## 前后端结构

Python3.12、FastAPI/Pydantic、LangChain/LangGraph、SQLite/PostgreSQL、openpyxl/xlrd；Vue3、TypeScript、Vite、Playwright。Node要求>=22.12.0。

```text
agents/                         编排、上下文、Evidence、回答
api/                            开发、Review与Trial入口
services/ tools/ repositories/  计算与数据访问
workflows/                      原LangGraph生产路径
migrations/ import_mappings/    迁移与字段映射
data/demo/                      可复现演示产品
data/raw/ facts/ normalized/    私有来源、事实与版本化数据
pmc-agent-frontend-main/frontend/
  src/                          本地工作台
  review/                       认证远程工作台编译入口
  trial/                        独立演示版编译入口
frontend/                       legacy，非默认入口
deploy/ scripts/ tests/ docs/    配置模板、验证与文档
.runtime/                       忽略的构建及隔离会话
```

前端只转换结构化响应，不从回答文本提取数字，不计算库存或生成生产结论。Decimal保持字符串，null保持未知。

## 数据组织方式

企业BOM经原始文件→预检→staging→validation→人工确认→publish进入事实库，保留来源审计。Agent不直接读取raw BOM。当前主库存通过受控Repository读取并验证批准来源，不是实时ERP同步。

完整追溯范围保有已发布BOM；标准分析范围绑定独立版本数据，两者口径不能混用。演示产品使用独立事实与会话空间，不改企业数据。用户、产品、范围和版本分别绑定会话，历史结果不能冒充当前结果。

## 产品目录与推荐体验路径

目录通过认证API按权限提供，不包含在远程静态资源中。

| 产品 | 分析范围 | 推荐体验 |
| --- | --- | --- |
| KQ-Z112 / V01 / 片 | 默认标准分析范围34项；可切换完整追溯范围66项 | 物料→库存→1片→2片→限制与来源 |
| KQ-BHX3588M / V01 / 片 | 完整追溯范围91项 | BOM→10片需求→对应库存 |
| DEMO-PMC-01 / V01 / 台（演示产品） | 独立产品分析 | 50台→最大数量→75/76台→100台采购建议 |

当前KQ-Z112标准分析范围最大满足数量1片，1片满足、2片不足；不代表完整产品生产能力。完整两产品库存匹配分别44/66、58/91，无记录保持未知。可选数量模拟范围采用演示库存，单独标注。

DEMO-PMC-01理论最大75台，50/75台齐套、76/100台不足，100台有4项采购建议。演示产品不用于业务放行。操作详见[使用说明](docs/reviewer_remote_guide.md)。

## 本地安装与启动

Windows PowerShell，在项目根目录执行：

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 仅新环境空库初始化；已有企业库先备份、核对迁移，不重复发布BOM。
.\venv\Scripts\python.exe -c "import config; from repositories.fact_store import create_fact_store; print(create_fact_store().migrate())"
.\venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```

另开终端：

```powershell
Set-Location pmc-agent-frontend-main/frontend
npm ci
npm run dev
```

工作台http://127.0.0.1:5173，后端http://127.0.0.1:8000。前端默认请求该后端，可在前端`.env.local`设置`VITE_API_BASE_URL`，不得放密钥。旧frontend保留，不作为默认入口。开发8000端口不得直接接公网隧道。

`.env.example`仅为模板，私下填写`.env`；未经出站批准时保持`LLM_PROVIDER=`空值。`PMC_FACT_DATABASE_URL`支持SQLite文件或PostgreSQL；不安全的多连接SQLite`:memory:`明确拒绝。实际PostgreSQL测试需测试URL。

企业数据、来源绑定、单位和数量确认、标准范围版本文件须经授权私下交接。换路径后重新验证定位和SHA，不把确认扩展到新来源。缺资料明确不可用，不回退假企业数据。演示产品不依赖企业原件。参见[环境交接](docs/review_environment_handoff.md)。

## 远程试用架构

```text
HTTPS（经明确授权启动） → Cloudflare Tunnel → Caddy认证与静态工作台
  → 同源 /api → 专用FastAPI → 授权只读数据 + 独立会话库
```

Review支持授权产品，Trial仅支持演示产品。独立编译入口与模块边界防止企业标识进入静态包，关闭Source Map及public目录复制；不能用完整本地dist替代。

### 授权远程工作台

按[部署说明](docs/authorized_remote_review.md)准备授权私有来源与标准范围绑定，在本机生成独立随机密码和代理密钥，以Windows DPAPI加密保存；私有配置不能提交。模板不能直接上线。Review当前读取SQLite企业库；通用Store支持PostgreSQL不等于该部署已验证PostgreSQL。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/build.ps1
# 仅新环境首次初始化；现有私有配置会拒绝覆盖
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/setup.ps1 -GenerateRandomPasswords -ApprovedDatasetVersion 20261011T030952Z-b4f34740
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/health.ps1
```

在本机受控窗口查看密码、执行正式账号验收或停止服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/show-credentials.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/review/stop.ps1
```

本机页面127.0.0.1:8090，后端127.0.0.1:8020。浏览器同源`/api`访问，后端检查代理身份、账号授权与会话所有权。启动/停止脚本仅管理自己的已核验进程。加密凭据绑定当前Windows用户与机器，新电脑须重新初始化并妥善迁移历史所有权。

### 独立演示版

按[Trial部署说明](docs/remote_trial.md)准备独立私有配置：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/trial/build.ps1
. .\deploy\trial\settings.local.ps1
.\venv\Scripts\python.exe scripts/run_remote_trial.py
```

另开终端加载相同配置，用`deploy/trial/Caddyfile`启动Caddy。本机页面127.0.0.1:8080，后端127.0.0.1:8010，仅能访问DEMO-PMC-01，不能读取企业及标准范围数据。

公网链接须用户另行批准启动；当前不创建隧道。本机通过后仍需外部设备验证HTTPS、登录、账号隔离与恢复。

## 安全与权限

- 密钥只在后端，前端不调用模型API。
- 原件、数据库、备份、normalized、私有确认/映射、日志不提交或提供下载。
- 授权用户只读查询，不能远程修改BOM与库存。
- 会话绑定账号，禁止跨用户读取或续写历史。
- 展示授权不等于公开GitHub、匿名访问或第三方模型出站授权。
- `.gitignore`不能保护已跟踪内容；仓库历史含企业元数据，不能直接公开。公开演示仓库需独立审查且不继承企业历史。

## 测试与当前版本

已完成v1.9事实层与查询、v1.10多层BOM与齐套、v1.11批次与风险、v1.12采购规划、v1.13持久会话、v1.14隔离演示与新前端；当前收敛产品化交互和交付验证，不新增计算规则。

```powershell
.\venv\Scripts\python.exe -m pytest
git diff --check
Set-Location pmc-agent-frontend-main/frontend
npm test
npm run typecheck
npm run build
```

有Edge的Windows可设置`$env:PLAYWRIGHT_CHANNEL='msedge'`，否则按Playwright要求安装测试浏览器。私有来源验收须禁用模型出站、隔离会话，并核对企业文件前后不变。

本机真实HTTP和浏览器验证：

```powershell
.\venv\Scripts\python.exe scripts/verify_authorized_review_local.py --use-current-confirmations
.\venv\Scripts\python.exe scripts/verify_remote_trial_local.py
```

第一条只适用已授权且唯一绑定的当前库存来源；其他环境用`--settings <私有配置路径>`。脚本停止自己的临时进程，不开公网。自动采购执行、实时ERP同步、外部供应风险预测不在当前交付范围。
