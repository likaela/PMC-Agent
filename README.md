# PMC-Agent — v1.14 后端 / v1.14.1 比赛展示前端

默认开发与比赛展示入口为 `pmc-agent-frontend-main/frontend/`，通过统一 Agent API 访问后端。
根目录 `frontend/` 保留为 **legacy**，不是默认启动入口；两套前端不要同时占用 5173。
Windows 启动脚本与配置说明见 [前端启动指南](docs/frontend_startup.md)。

面向制造业 PMC 场景的智能生产决策 Agent。它将自然语言生产任务转换为受控参数，
再由确定性工作流完成 BOM 展开、MRP 齐套分析、采购参数检查、生产决策与结构化报告。

> 适合人工智能应用创新大赛现场演示：**能听懂任务、能展示执行过程、能追问缺失信息，且不让模型编造业务结论。**

## 核心亮点

- 自然语言入口：例如“我要生产 100 台 KQ-Z112，帮我看看能不能开工”。
- 可追踪 Agent：展示输入校验、BOM、MRP、采购、生产决策和报告工具的调用状态；不暴露思维链。
- 主动追问：采购参数缺失时，明确列出需要业务人员补充的物料和字段。
- 确定性业务：BOM、库存、缺料、采购量、风险和生产结论全部由 Python Service 计算。
- 当前入口：自然语言查询工作台、结构化结果、物料明细及来源引用。
- 独立比赛 Demo：`DEMO-PMC-01 / V01` 的 50 台齐套、100 台缺料与采购建议，不修改真实企业数据。
- Legacy 兼容：原表单 Dashboard、KQ-Z112 Chat 与反馈功能仍保留在旧前端及兼容接口中。

## 系统架构

```text
新 Vue Agent 客户端（pmc-agent-frontend-main/frontend）
        ↓ HTTP
FastAPI 统一 Agent API（/api/v1/agent/query）
        ↓
Agent Router（理解与参数校验）
        ↓
Published Fact Query / Production Feasibility / Purchase Planning
        ↓
Fact Layer（SQLite / PostgreSQL，来源审计、持久会话）

兼容生产分析路径（保持不变）：
LangGraph Workflow（只负责编排）
        ↓
LangChain Tools（参数适配）
        ↓
Python Services（BOM / MRP / Purchase / Production / Report）
        ↓
Excel Repository / 主数据
```

LLM 或任务解析层只负责理解用户意图和提取任务参数；不参与库存、缺料、采购量、
风险等级或生产可行性的判断。

## 快速启动（Windows）

```powershell
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\venv\Scripts\python.exe scripts/check_release_readiness.py
.\venv\Scripts\python.exe -m uvicorn api.app:app --reload
```

另开 PowerShell：

```powershell
Set-Location pmc-agent-frontend-main/frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`，进入新前端首页或“分析工作台”。
API 文档位于 `http://localhost:8000/docs`。

双击根目录 `start-backend.bat` 和 `start-frontend.bat` 也可分别启动；脚本不自动安装依赖。
新前端默认使用在线模式及 `http://127.0.0.1:8000` API，无需复制旧前端配置。
需要覆盖地址时，在新前端目录执行 `Copy-Item .env.example .env.local` 并修改配置，再重启 Vite。
`VITE_*` 是公开浏览器配置，禁止放入密钥。若 5173 已被旧前端占用，先在旧终端按 Ctrl+C 停止旧前端。

兼容生产分析路径的数据源默认使用 `PMC_DATA_SOURCE=auto`：本机 `data/raw/` 三个企业文件齐全时读取真实数据，
否则自动使用仓库内 `data/demo/kq_z112_demo.json` 的纯合成演示数据。公开仓库不得提交
真实企业 Excel。`GET /health?details=true` 可检查数据、工作流、LLM 与 CORS 就绪状态，
响应不会返回密钥或本机绝对路径。

新前端的“企业事实”模式读取 published facts；“合成 Demo”显式携带
`scenario_id=demo_scenario_50_vs_100`，两者不由上述 legacy 数据源开关混为一套数据。

## Demo 使用方法

### 当前比赛展示入口

1. 打开新前端，选择“在线 Agent / 合成 Demo”。
2. 发送“生产50台DEMO-PMC-01”：库存齐套，缺口为 0。
3. 发送“生产100台DEMO-PMC-01”：4 项物料缺料。
4. 同一会话发送“采购建议”：展示建议量、成本、风险和来源；建议不表示已到货。
5. 刷新页面：从服务端恢复同一持久会话与历史回答。

亦可通过首页快捷入口进入独立 Demo。该合成案例理论最大生产数量为 75 台，
50 台库存齐套不等于开工许可或交付承诺。

### Legacy KQ-Z112 Demo（非默认入口）

首次打开“自然语言 Agent”会显示项目简介、支持能力与推荐演示顺序。默认案例为
`KQ-Z112 / V01`，按下列顺序点击即可，无需手动组织复杂参数：

1. **我要生产100台KQ-Z112**：启动确定性 PMC 分析。
2. **为什么不能生产？**：复用当前 workflow，说明阻塞物料与待补采购参数，不重跑 BOM/MRP。
3. **哪些物料最影响生产？**：展示既有 Production Decision 的阻塞优先级，不新增评分规则。
4. **如果减少到50台呢？**：由 Scenario Service 调用既有 PMC 工作流推演备选数量，原 workflow 保持不变。

分析完成后可提交简短体验反馈。体验记录仅存在服务当前进程，包含会话时间、workflow 标识、
用户输入、分析完成状态及用户反馈；不会保存 Excel、原始 BOM、库存或其他企业源数据。

## 比赛演示流程

默认使用上面的独立 50/100 台演示。新前端等待一次性 JSON 响应，不伪造逐节点执行过程。
需要展示原 KQ-Z112 工作流轨迹或人工补参时，可单独启动 legacy 前端；后端原功能没有删除。

## 示例

以下为保留的 legacy 生产分析示例，不是独立 50/100 台 Demo 的产品编码。

输入：

```text
我要生产1台KQ-Z112，帮我看看能不能开工
```

系统会解析为：

```json
{"product":"KQ-Z112","bom_version":"V01","quantity":1}
```

并展示来自工作流的生产决策、阻塞物料、采购参数缺失项和结构化报告。

## API

| 接口 | 作用 |
| --- | --- |
| `GET /health` | 健康检查 |
| `POST /api/v1/agent/query` | 新前端统一生产/事实查询入口，支持 session_id / scenario_id |
| `POST /api/v1/agent/sessions` | 创建持久会话 |
| `GET /api/v1/agent/sessions/{session_id}` | 分页恢复持久会话与来源 |
| `POST /api/v1/pmc/analyze` | 表单方式启动 PMC 分析 |
| `GET /api/v1/pmc/{workflow_id}` | 查询当前进程内工作流状态 |
| `POST /api/v1/pmc/{workflow_id}/purchase-parameters` | 补参并从采购节点恢复 |
| `POST /api/v1/chat` | 自然语言任务解析并启动 PMC 工作流 |
| `GET /api/v1/chat/{workflow_id}/history` | 查询当前进程内 Chat 会话历史 |
| `GET /api/v1/demo/cases` | 获取 KQ-Z112 Demo 快捷案例 |
| `POST /api/v1/demo/feedback` | 提交当前进程内体验反馈 |
| `GET /api/v1/demo/statistics` | 获取当前进程体验次数、成功分析与方案推演统计 |

## 验证

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
Set-Location pmc-agent-frontend-main/frontend
npm run build
```

## 当前限制

- 统一 Agent 会话已持久化；兼容 LangGraph 工作流 checkpoint 仍仅存在当前进程内，二者不要混淆。
- Demo 反馈与统计同样只在当前进程可见，服务重启后会清空；它们不适合作为正式运营数据。
- 不包含用户、权限、ERP、MES、WMS 或复杂 APS 排产。
- 真实原始企业数据保持在 `data/raw/` 本地忽略目录，不应提交到版本库。
- Python 3.14 下 LangChain 会给出 Pydantic v1 兼容性警告；建议部署时选用团队验证过的版本组合。
