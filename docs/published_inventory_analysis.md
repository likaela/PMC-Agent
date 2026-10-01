# v1.11 批次库存与计划供给

本能力读取 published facts，通过独立 Repository → Service → Tool 调用，不改变既有 Agent Router、Fact Query Agent、Demo、Chat 或 v1.10 产能计算。没有 LLM 调用，也不新增采购建议。

## 模型与迁移

`inventory_facts` 已是一条源行对应一条批次/库位事实，本阶段以 `inventory_lot` 表达该行身份，不创建第二套库存表或物料主数据。不在导入或查询阶段把不同批次覆盖为单行。

SQLite / PostgreSQL 新增 `005_inventory_analysis`：

- `inventory_facts.last_movement_at`：可空、无默认值，仅记录权威来源的最后移动时间。
- `inventory_risk_policies`：按 item 保存 `safety_stock_qty`、单位、`expiry_warning_days`、`stagnant_days`、生效期和 source file / SHA-256 / sheet / row / import batch。
- 已存在事实与导入行为保持不变；旧库存行的新事件字段为 null，不填补历史事实。

使用现有 `FactRepository.migrate()` 执行迁移，查询 Tool 不自动迁移数据库。需先备份生产数据库，再应用迁移；本次测试只迁移临时数据库，未更新本地企业事实库。

风险策略仅使用已发布且在分析日生效的唯一记录。缺失、重叠、单位冲突或非法阈值都返回不完整，不自动选择最新。结束日期为空表示开放区间，日期两端包含。没有内置安全库存、临期或呆滞阈值。

当前企业 Excel 适配器仍只读取已确认列，不因新增字段而扫描、猜测额外列。真实风险策略、最后移动时间及批次日期需通过后续明确的企业适配与审核提供；本阶段不新增这类文件导入流程。

## 调用

独立工具清单为 `tools.inventory_analysis_tools.INVENTORY_ANALYSIS_TOOLS`：

| Tool | 参数 | 结果 |
| --- | --- | --- |
| `published_inventory_risk_analysis` | material_code、可选 as_of、availability_basis、预警天数 | 批次明细、数量完整性、安全库存、临期及库龄预警 |
| `published_inventory_fifo_plan` | material_code、十进制字符串 required_qty、可选 as_of / availability_basis | 模拟使用批次、逐步扣减、剩余需求、来源 |
| `published_supply_by_start_query` | material_code、start_date、可选 as_of / availability_basis | 开工日前确定在途、待确认行、计划供给及来源 |

共用顶层契约：`status / query / data / completeness / provenance / warnings`。

物料只走精确 Item / Alias 解析。as_of 使用带时区 ISO 8601；不传时采用当前 UTC 时点。库存/在途只选择不晚于查询时点的最新 published 观察。同一时点有多个来源时拒绝任意选择。SQLite 按真实日期时间比较，支持带时区的来源数据。

```python
from tools.inventory_analysis_tools import published_inventory_fifo_plan

result = published_inventory_fifo_plan.invoke({
    "material_code": "MAT-001",
    "required_qty": "7.25",
    "as_of": "2026-10-01T00:00:00+00:00",
})
```

## 数量与 FIFO

所有数量采用 Decimal；公开结果以十进制字符串保存精度。

默认 `availability_basis="source_only"`，只使用 published `available_qty`。未知预留与可用量始终为 null。

只有业务明确指定 `on_hand_minus_reserved` 且两项权威数量都存在、有效时，才计算 `available = on_hand - reserved`。该口径声明没有其他扣减项；若企业有质检冻结等扣减，必须提供权威可用量，不应启用该简化口径。来源可用量已经存在时直接采用，不再次扣减预留。可用量不能大于在手量或已知扣除预留后的数量。

标记重复、非法或矛盾数量保留源行，但不生成合计或 FIFO 结果。

FIFO 必须具备批次标识、有效的入库日期与权威可用量；缺任何项返回 `data_unavailable`。按入库时间升序，同时间按仓库、库位、批次、来源 sheet/row 稳定排序。每步输出：可用量、分配量、剩余可用量、剩余需求与来源。

已明确过期的批次排除；有效期为日期时按当天结束有效处理。有效期未知时只给出 FIFO 顺序并提示缺少有效期核验，不能据此宣称质量放行或可生产。FIFO 是只读模拟，不修改库存事实或实际预留。

## 预警

- 临期：`days_remaining = expiry_date - analysis_date`；负数为过期，`0 <= days_remaining <= expiry_warning_days` 为临期。没有日期不判断，没有阈值不判断临期；明确已过期不需要临期阈值。
- 呆滞：有最后移动时间时优先使用，否则使用明确入库时间；达到 `stagnant_days` 阈值预警。入库时间口径表示库龄预警，不证明之后完全没有移动。事件时间矛盾或晚于快照时拒绝判断。
- 安全库存：权威可用量小于已发布安全库存时预警，输出差额。差额不是采购建议；未知阈值不默认为零。

预警按批次提供 assessment 状态与完整性信息。总体查询 `ok` 只表示在手事实可读取，不保证所有预警都可计算；调用方须检查 `completeness`。

## 在途与开工日

仅从 published inbound facts 读取。在途量采用明确剩余量，或在 ordered / received 两项都明确时计算差值。缺失或矛盾数量不补零。

标准开放状态为 `open / confirmed / in_transit / partially_received`。`cancelled / canceled / closed / received` 不计入。来源状态缺失或企业自定义状态未完成明确映射时待确认，不猜测其业务含义。

承诺日期明确时使用 committed_date，否则使用 expected_arrival_date。只有 `arrival_date < start_date` 才纳入；日期粒度不能保证开工同日提前到货，同日到货暂不计入。到货日已早于分析日但仍标记在途的行需重新确认，不视为已收到。

`known_eligible_inbound_qty` 是当前已知可纳入行的合计；只要有待确认行，完整 `eligible_inbound_qty` 为 null，不把局部合计冒充完整在途。

只有库存快照和在途观察处于同一时点，才尝试相加，避免老采购观察中的剩余量与后来库存重复。开工前过期批次排除；批次未来有效性未知时保留当前权威可用量，但完整 `planned_supply_qty` 为 null。计划供给不证明已经到货，也不替代 Production Decision。

## 当前业务待确认

1. 企业安全库存及预警阈值、单位和生效区间。
2. 权威批次 received_at / last_movement_at / expiry_date；非保质物料需明确业务规则，不能把缺少有效期自动解释为永久有效。
3. 可用量定义，尤其预留、质检冻结与其他限制是否已扣除。
4. 采购状态标准映射、承诺日期权威性、采购订单行标识与重复行审计口径。
5. 库存与采购事实的统一观察时点，以及同日到货的实际时间精度。

当前真实来源缺少这些字段时，服务应输出数据不完整。合成测试只用于证明规则，不会写入 Demo 或企业数据。
