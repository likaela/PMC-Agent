# 企业 Agent Context Resolver

## 接入与边界

企业持久会话入口：Planner → Context Resolver → 参数完整性检查 → 既有 Tool。
Resolver 仅读取已发布 BOM 元数据和库存快照时点，不修改事实、不计算 BOM、库存、齐套或采购量。
旧服务调用路径不变；独立 Demo 不启用企业 Resolver，仍使用原场景元数据与隔离工具。

## 版本及日期口径

- 保留用户或会话中明确指定的版本。若版本不存在或在分析日期不生效，拒绝计算，不换成另一个版本。
- BOM 分析日期优先采用明确的 `effective_date`，其次采用用户明确的计划开工日。
  单个未标注的 ISO 日期可作为 BOM 业务分析日期；多个未标注日期、无时区的库存截止日、相对日期需澄清。
- 若没有上述日期，采用明确的库存查询时点，或最新已发布库存快照的 UTC 日期。
  该日期是事实分析时点，不代表今天、实时库存或未来的开工日期。
- 按 `effective_from <= 分析日期 <= effective_to` 校验，空结束日期表示开放区间。
  只有一个有效版本才自动选取；多个有效版本要求用户确认；没有有效版本返回数据不可用。
- 不能仅凭一个 BOM 的起始日期判断它是当前版本。没有明确事实时点时，要求补充日期。
- 自动选定的库存时点来自 published 快照，禁止采用尚未发布的快照或系统默认日期。
- 不推断采购开工日，缺失时继续追问；不根据版本名称排序选择“最新”。

## 审计与多轮对话

自动填入字段通过 `structured_data.context_evidence` 返回，例如：

```json
{
  "source": "published_bom_context",
  "field": "revision",
  "value": "V01",
  "provenance": {
    "source_file": "published-bom.xlsx",
    "import_batch_id": "来源批次",
    "content_sha256": "来源校验值",
    "sheet_name": "来源工作表",
    "evaluated_on": "2026-10-01"
  }
}
```

Resolver 元数据查询以 `published_bom_context` 操作记录保存到既有会话来源表；
它不是新增业务 Tool，也不是伪造 Tool 执行进度。业务 Tool 的原始证据分别保存。
不增加数据库表或 migration，不改变 API 顶层字段及 intent 枚举。

自动补全字段在下一轮重新读取事实核验，避免新增冲突版本后沿用旧结论；
用户明确选择的版本仍保持，显式新产品不会继承旧产品元数据。

## 运行与测试

企业数据库需预先通过既有迁移流程初始化。Resolver 和 API 查询不会执行迁移。
专项测试：

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_agent_context_resolver.py
```

测试使用临时 SQLite、合成 published facts 和禁止外部 LLM 的环境，不修改本地企业数据。
