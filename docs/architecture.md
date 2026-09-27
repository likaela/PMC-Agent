# PMC-Agent 架构说明

## 分层链路

```text
Data
  ↓
Repository
  ↓
Service
  ↓
Tool
  ↓
LangGraph
  ↓
FastAPI
  ↓
Vue Dashboard
```

## 各层职责

| 层 | 目录 | 职责 | 不负责 |
|---|---|---|---|
| Data | `data/` | 示例数据、模板及本机真实数据入口 | 业务计算 |
| Repository | `repositories/` | 读取 Excel、字段适配、标准化输出 | BOM/MRP/采购规则 |
| Service | `services/` | BOM、库存、MRP、采购、生产决策和报告规则 | Excel 读取、HTTP、页面展示 |
| Tool | `tools/` | 对 Agent 和工作流做参数适配，调用 Service | 字符串解析或业务重算 |
| LangGraph | `workflows/` | 节点顺序、错误路由、暂停与内存恢复 | 生产可行性或采购数量计算 |
| FastAPI | `api/` | 稳定 HTTP Schema、状态查询、错误映射、CORS | 暴露内部 LangGraph State 或重算业务结果 |
| Vue | `frontend/` | 用户输入、API 调用和结构化结果展示 | BOM、缺料、齐套率、风险或生产决策计算 |

## 确定性原则

- Python Service 是唯一的业务规则与数值计算来源。
- LLM 不计算 BOM、可用库存、缺料、齐套率、采购量、风险等级或生产决策。
- LangGraph 只直接采用 `production_service` 已生成的状态进行路由。
- Vue 只显示 FastAPI 返回的字段，不推导或覆盖业务结论。

## 真实分析流程

```text
产品 + BOM版本 + 生产数量
  ↓
真实 BOM Tool
  ↓
真实 MRP Tool
  ↓
采购参数完整性 Tool
  ↓
Production Decision Tool
  ↓
确定性 Report Tool
```

当采购参数缺失时，LangGraph 将报告与当前生产决策写入内存 checkpoint，并暂停等待业务人员提供：

- `supplier_code`
- `safety_stock`
- `lead_time_days`

恢复后仅重新执行采购分析、生产决策和报告节点；BOM 与 MRP 结果保留。

## 数据与安全边界

- `data/raw/` 是私有企业原始数据目录，必须仅保留在本机，已由 `.gitignore` 排除。
- `.env`、`venv/`、前端 `node_modules/`、`dist/` 和 `.env.local` 不应进入版本库。
- FastAPI 使用明确的 `PMC_ALLOWED_ORIGINS`，不默认允许 `*`。
- API 仅返回公开响应模型，不返回 API Key、环境变量、内部 checkpoint 或堆栈。
