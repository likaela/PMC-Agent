# PMC-Agent

面向制造业 PMC（生产与物料控制）的展示型 MVP。项目将真实 Excel 主数据接入为确定性 BOM、库存、MRP、采购风险和生产决策流程，并提供 LangGraph 工作流、FastAPI API 与 Vue Dashboard。

> 核心数值和生产结论由 Python Service 计算；LLM 只保留为旧 Agent 模式的自然语言交互能力，不参与确定性计算。

## 核心能力

- 多层 BOM 展开、循环 BOM 检测与物料需求汇总。
- 库存可用量、缺料、MRP 齐套率及数据完整性识别。
- 采购参数逐项补充、采购建议与规则型风险等级。
- 生产决策：`ready`、`blocked`、`procurement_pending`、`data_incomplete`。
- LangGraph 内存工作流：采购参数缺失时暂停，补充后仅从采购分析继续。
- FastAPI 公开接口及 Vue 3 Dashboard 演示界面。

## 系统架构

```text
Excel Data → Repository → Service → Tool → LangGraph → FastAPI → Vue Dashboard
```

详细分层与职责见 [docs/architecture.md](docs/architecture.md)。

## 技术栈

- Python、LangChain、LangGraph、FastAPI、Pydantic
- OpenPyXL、xlrd
- Vue 3、Vite
- DeepSeek-compatible API（仅旧 Agent 自然语言入口可选使用）

## 目录结构

```text
api/           FastAPI 路由和公开 Schema
data/          示例数据、模板与本机数据目录
repositories/  Excel 适配与标准化
services/      确定性业务规则
tools/         Agent / Workflow 工具适配
workflows/     LangGraph 编排
frontend/      Vue 3 + Vite Dashboard
tests/         Python、API、工作流回归测试
docs/          交接、映射、架构与演示文档
```

## 安装

在 Windows PowerShell 的项目根目录执行：

```powershell
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

真实企业原始文件仅应保留在本机 `data/raw/`；该目录已被 Git 忽略，不能提交。

## 启动后端

Vue 开发环境默认使用 `http://localhost:5173`，因此启动后端前设置明确 CORS 来源：

```powershell
$env:PMC_ALLOWED_ORIGINS="http://localhost:5173"
.\venv\Scripts\uvicorn.exe api.app:app --reload
```

后端文档：`http://localhost:8000/docs`

## 启动前端

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

默认前端地址：`http://localhost:5173`。如后端地址变化，在 `frontend/.env.local` 设置：

```ini
VITE_API_BASE_URL=http://localhost:8000
```

## API 概览

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 服务存活检查 |
| `POST` | `/api/v1/pmc/analyze` | 启动 PMC 工作流 |
| `GET` | `/api/v1/pmc/{workflow_id}` | 查询当前工作流状态 |
| `POST` | `/api/v1/pmc/{workflow_id}/purchase-parameters` | 补充采购参数并从暂停点恢复 |

分析请求：

```json
{
  "product": "KQ-Z112",
  "bom_version": "V01",
  "quantity": 1
}
```

## KQ-Z112 演示流程

1. 在 Dashboard 输入 `KQ-Z112`、`V01`、`1`。
2. FastAPI 调用 LangGraph：BOM → MRP → Purchase → Production Decision → Report。
3. 当前本地演示数据返回 `blocked`，并展示 8 项阻塞物料和 8 项待补采购参数。
4. 在表格中填写明确的供应商编码、安全库存、提前期并提交。
5. 工作流从采购分析节点恢复；BOM 和 MRP 不会重复执行。

## 测试与构建

```powershell
# Python / API / 工作流回归
.\venv\Scripts\python.exe -m unittest discover -s tests -v

# Vue 生产构建
Set-Location frontend
npm run build
```

## 当前限制

- LangGraph checkpoint 和采购参数会话仅保存在当前 Python 进程；服务重启后失效。
- 不包含数据库、登录鉴权、ERP/MES/WMS 集成或复杂 APS 排产。
- 真实原始数据不随代码发布；没有本地 `data/raw/` 时无法运行真实 KQ-Z112 验证。
- 当前 Vue 项目为本地演示界面，不包含生产部署、用户管理或权限控制。
- Python 3.14 下 LangChain 会产生 Pydantic v1 兼容性警告；当前测试可通过，正式部署建议采用经团队验证的 Python 版本。

## 后续路线

1. 增加持久化 checkpoint 与采购参数主数据管理。
2. 增加认证、审计日志和环境化部署配置。
3. 接入企业数据同步机制，并完善库存来源确认流程。
4. 在保持确定性规则的前提下，扩展计划模拟与可视化分析。
