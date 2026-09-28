# PMC-Agent v1.5-beta Demo Release

面向制造业 PMC 场景的智能生产决策 Agent。它将自然语言生产任务转换为受控参数，
再由确定性工作流完成 BOM 展开、MRP 齐套分析、采购参数检查、生产决策与结构化报告。

> 适合人工智能应用创新大赛现场演示：**能听懂任务、能展示执行过程、能追问缺失信息，且不让模型编造业务结论。**

## 核心亮点

- 自然语言入口：例如“我要生产 100 台 KQ-Z112，帮我看看能不能开工”。
- 可追踪 Agent：展示输入校验、BOM、MRP、采购、生产决策和报告工具的调用状态；不暴露思维链。
- 主动追问：采购参数缺失时，明确列出需要业务人员补充的物料和字段。
- 确定性业务：BOM、库存、缺料、采购量、风险和生产结论全部由 Python Service 计算。
- 双入口演示：保留表单式 PMC Dashboard，并提供自然语言 Chat Agent。
- Demo 体验：内置 KQ-Z112 / V01 快捷案例、当前进程内体验统计和可选文字反馈。

## 系统架构

```text
Vue Dashboard / Chat
        ↓ HTTP
FastAPI API
        ↓
Task Parser（仅提取 product / bom_version / quantity）
        ↓
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
$env:PMC_ALLOWED_ORIGINS = "http://localhost:5173"
.\venv\Scripts\python.exe -m uvicorn api.app:app --reload
```

另开 PowerShell：

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

访问 `http://localhost:5173`，在“自然语言 Agent”页面选择 Demo 案例或直接输入任务。
API 文档位于 `http://localhost:8000/docs`。

## Demo 使用方法

首次打开“自然语言 Agent”会显示项目简介、支持能力与推荐演示顺序。默认案例为
`KQ-Z112 / V01`，按下列顺序点击即可，无需手动组织复杂参数：

1. **我要生产100台KQ-Z112**：启动确定性 PMC 分析。
2. **为什么不能生产？**：复用当前 workflow，说明阻塞物料与待补采购参数，不重跑 BOM/MRP。
3. **哪些物料最影响生产？**：展示既有 Production Decision 的阻塞优先级，不新增评分规则。
4. **如果减少到50台呢？**：由 Scenario Service 调用既有 PMC 工作流推演备选数量，原 workflow 保持不变。

分析完成后可提交简短体验反馈。体验记录仅存在服务当前进程，包含会话时间、workflow 标识、
用户输入、分析完成状态及用户反馈；不会保存 Excel、原始 BOM、库存或其他企业源数据。

## 比赛演示流程

1. 打开“自然语言 Agent”，点击“单台开工分析”。
2. Agent 展示解析结果、执行工具轨迹和生产决策。
3. 观察阻塞物料、建议行动和采购参数待补充清单。
4. 切换回 PMC Dashboard，补充明确的采购参数并恢复同一工作流。
5. 强调：生成采购建议不等于物料已到货，系统不会直接改判为可开工。

## 示例

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
Set-Location frontend
npm run build
```

## 当前限制

- 工作流 checkpoint 仅存在当前进程内，未接入数据库持久化。
- Demo 反馈与统计同样只在当前进程可见，服务重启后会清空；它们不适合作为正式运营数据。
- 不包含用户、权限、ERP、MES、WMS 或复杂 APS 排产。
- 真实原始企业数据保持在 `data/raw/` 本地忽略目录，不应提交到版本库。
- Python 3.14 下 LangChain 会给出 Pydantic v1 兼容性警告；建议部署时选用团队验证过的版本组合。
