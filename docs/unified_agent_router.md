# 统一 Agent 自然语言入口

新增 `POST /api/v1/agent/query`，不替换现有 `/api/v1/chat`、PMC API 或前端调用。当前前端 Demo 行为保持原样；第三方调用方可使用新入口。

请求：

```json
{
  "message": "查询 MAT-001 库存",
  "workflow_id": null
}
```

`workflow_id` 只用于现有 PMC 多轮追问和方案推演。事实查询始终访问独立的已发布事实层，不借用 Demo 库存或生产工作流状态。

统一响应字段：

```json
{
  "intent": "fact_query",
  "status": "ok",
  "answer": "由受控 Tool 结果生成的中文说明",
  "structured_data": {
    "query_type": "inventory",
    "query": {},
    "data": {},
    "completeness": {},
    "tool_name": "published_inventory_query",
    "parser_source": "rule_fallback"
  },
  "provenance": {},
  "warnings": []
}
```

## 分流边界

| 意图 | 交付路径 | 数值来源 |
| --- | --- | --- |
| 生产分析、原因追问、减量方案 | 原 `api.routes.chat.chat` → 既有 PMC Workflow / Scenario / Explanation | 既有确定性服务 |
| 库存、批次、BOM、在途事实 | `agents.fact_query_agent.run_fact_query_agent` → 独立 `FACT_QUERY_TOOL_REGISTRY` | published facts 查询 Tool |
| 混合或无法判定 | `clarification`、`needs_input`，不调用任一业务链 | 无 |

Router 的 LLM 只输出 `pmc_analysis` 或 `fact_query`，由 Pydantic 严格校验；字段抽取仍分别由现有 PMC Task Parser 和 Fact Query Agent 完成。明确信号与 LLM 分类冲突时，以本地规则为准；模型失败时回退规则。Router 不读数据库、不执行 PMC 算法、不生成事实。

事实响应保留 Tool 原始的 `query/data/completeness/provenance/warnings`；来源中的 source file、import batch、snapshot、BOM revision 均按 Tool 实际返回传递，缺失时为 `null`，不补造。`item_not_found`、`data_unavailable`、`invalid_query` 保持其受控状态与无事实拒答。PMC 响应的 `structured_data` 是现有 Chat **公开响应**，不是内部 LangGraph State；其 `provenance` 不伪造为事实层来源。

本阶段不改变旧 Demo Tool 列表，不给 LLM 直接数据库访问，也不把事实查询自动当作生产可行性分析。客户端如需继续 PMC 对话，应从上一次 `structured_data.conversation_workflow_id` 取值并作为下一次请求的 `workflow_id`。
