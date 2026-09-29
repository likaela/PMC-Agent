# 受控事实查询 Agent（独立入口）

本能力只查询 **published facts**，不进入既有 PMC 生产工作流，也不加入 Demo Agent 的 `ALL_AGENT_TOOLS`。
入口为 `agents.fact_query_agent.run_fact_query_agent(message)`；当前未接入 FastAPI/前端聊天页面。

## Tool Registry

`tools.fact_query_registry.FACT_QUERY_TOOL_REGISTRY` 将四种受控意图固定映射到既有 `FACT_QUERY_TOOLS`：

| 查询意图 | Tool | 必要参数 |
| --- | --- | --- |
| `inventory` | `published_inventory_query` | `material_code`，可选 `as_of` |
| `inventory_batches` | `published_inventory_batch_query` | `material_code`，可选 `as_of` |
| `bom` | `published_bom_query` | `parent_material_code`、`revision` |
| `inbound` | `published_inbound_supply_query` | `material_code`，可选 `as_of` |

调用示例：

```python
from agents.fact_query_agent import run_fact_query_agent

result = run_fact_query_agent("查询 MAT-001 库存")
print(result["answer"])
print(result["provenance"])
```

## 调用顺序与安全边界

1. 若 LLM 已配置，仅让模型返回结构化的查询类型、原文中出现的物料编码、版本和时点；输出通过 Pydantic 校验，标识符还必须能在用户原文中逐字找到。模型失败、格式错误或凭空添加标识时回退到本地规则。
2. Python 使用固定 Registry 调用**一个**已发布事实查询 Tool。Tool 返回原有 `status/query/data/completeness/provenance/warnings`，Agent 原样保留这些字段。
3. Python 只把已返回的事实转成中文说明；LLM 不撰写事实回答，不读取数据库，不计算库存、到货或生产结论。
4. `item_not_found`、`data_unavailable`、`invalid_query` 均明确回答“当前事实库没有对应信息”。`null` 显示为“未知”，不变成 0；Tool 调用异常和畸形返回均按 `query_failed` 封闭处理。

Agent 返回在 Tool 六字段之外增加：`query_type`、`tool_name`、`parser_source` 和 `answer`。数量仍使用 Tool 给出的十进制定点字符串；完整结构化结果供调用方追溯。`as_of` 的时点合法性和 snapshot 选择仍由既有 FactQueryService 判定。

## 当前限制

- 不提供公开 HTTP 接口或 Chat UI；后续接入须先决定授权、会话与用户可见 provenance 口径。
- 没有已发布权威在途事实时，只会得到 `data_unavailable`，不会从供应商主数据或库存扩展列推测。
- 不执行模糊料号匹配、FIFO、MRP、采购建议或生产可行性判断。
