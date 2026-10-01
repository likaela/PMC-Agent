# v1.12 published facts 采购建议

本模块沿用 Fact Layer → Repository → Service → Tool；只读取 published facts，不调用 LLM、不生成订单，不修改 Agent Router、Fact Query Agent、Chat、Demo 或原 PMC 决策链。

## 模型与迁移

SQLite / PostgreSQL 增加 `006_published_purchase_planning`，使用现有 `FactRepository.migrate()` 迁移。查询 Tool 不自动迁移数据库。本阶段仅迁移合成测试库，未修改本地企业事实库。

`purchase_parameter_facts` 的显式字段：

| 字段 | 口径 |
| --- | --- |
| item_id | 标准 item，沿用现有物料主数据 |
| supplier_code | 来源明确的供应商编码；不从 supplier master 推断 |
| purchase_unit | 采购约束的计量单位；必须与本次叶子需求单位一致 |
| minimum_order_quantity | MOQ，零明确表示没有最低数量要求；null 表示未知 |
| order_multiple / packaging_multiple | 正数表示明确约束；两项同时存在须同时满足 |
| order_multiple_applicable / packaging_multiple_applicable | false 且数量为 null 才表示明确无该约束；全为 null 表示未知 |
| lead_time_days | 明确非负整天交期；null 表示未知 |
| price_record_id | 明确绑定既有 published price，不自动选择价格 |
| effective_from / effective_to | 在模拟下单分析日选择有效参数，结束日期为空表示开放区间 |
| import_batch / source_file / sheet / row | 参数来源与审计定位 |

旧 `price_records` 仅增加可空 `unit / supplier_code / effective_to`。不回填旧价格的单位、供应商或截止日期；旧导入逻辑与价格数值保持不变。采购成本必须有明确价格单位和币种。

企业采购参数的实际来源、审核与标准适配仍需确认；本阶段没有新增上传页面或文件导入流程，不把合成测试参数写入企业库或 Demo。

## 独立入口

`tools.published_purchase_tools.PUBLISHED_PURCHASE_TOOLS` 仅包含 `published_purchase_recommendations_query`，不加入旧 Tool 列表。

```python
from tools.published_purchase_tools import published_purchase_recommendations_query

result = published_purchase_recommendations_query.invoke({
    "product": "PRODUCT",
    "revision": "V1",
    "effective_date": "2026-10-01",
    "quantity": 100,
    "start_date": "2026-10-20",
    "as_of": "2026-10-01T00:00:00+00:00",
    # 若多个有效供应商参数并存，须明确选择，不自动推荐：
    "suppliers": {"MAT-001": "SUP-1"},
})
```

共用顶层 `status / query / data / completeness / provenance / warnings`。

服务复用 `PublishedPlanningService` 的多层 BOM 叶子需求与路径，以及 `PublishedInventoryAnalysisService` 的安全库存和开工日前计划供给。不会重新实现递归、库存预留、FIFO 或在途规则。

## 采购量

所有事实数量、成本采用 Decimal；公开结果使用十进制字符串。内部以 96 位精度支持现有 NUMERIC(38,12) 数量与价格的乘积，整数倍数取整使用精确有理数计算。

令 R 为生产需求，A 为开工日可用库存，I 为明确可纳入在途，S 为已发布安全库存：

```text
production_shortage = max(R - A - I, 0)
net_purchase_requirement = max(R + S - A - I, 0)
```

生产缺口与安全库存补足分开表达。没有在途观察不等于在途为零；安全库存没有策略不等于安全库存为零。

沿用 v1.11：仅明确到货日期早于开工日的开放在途纳入；过期库存排除；未来有效性未知或库存/在途时点不一致时，完整计划供给为 null。产品不同叶子的库存快照批次/时点不一致时，不确认完整采购计划合计。

净补足量为零时采购量为零，不因 MOQ 强行采购。净补足量大于零时：

```text
base = max(net_purchase_requirement, MOQ)
suggested_purchase_qty = ceil(base / effective_multiple) * effective_multiple
```

没有倍数约束必须有明确 `not_applicable` 事实，此时采购量为 base。未知约束时采购量为 null。

两项倍数同时存在时采用精确最小公倍数。例如 order=50、packaging=20，公共倍数为100，净需求120得到200；仅 packaging=50 时，120得到150。这是满足约束的最小量，不额外加量。

采购单位与需求单位不一致时拒绝本阶段建议，不隐式改变购买单位。可先由明确的标准适配提供同单位事实；本模块未新增购买单位转换算法。

## 价格与成本

只使用参数显式关联的已发布价格。物料、单位、生效期、币种必须匹配；价格若限定供应商，则必须与参数供应商一致。价格未限定供应商时，参数中的明确价格引用表示选择该通用物料价格；不会通过 supplier master 或名称推断关联。

```text
purchase_cost = suggested_purchase_qty * tax_included_unit_price
unconstrained_cost = net_purchase_requirement * tax_included_unit_price
constraint_extra_qty = suggested_purchase_qty - net_purchase_requirement
constraint_cost_impact = constraint_extra_qty * tax_included_unit_price
```

保留原含税价格口径；不拆税、不假设折扣、不猜币种小数位或会计舍入规则。价格缺失时，数量若已经确定可以保留，成本始终为 null。

只有全部材料成本确定、库存一致且单一币种时输出总采购成本和总约束成本影响。混合币种不合并，不假设汇率。`known_cost_subtotals_by_currency` 只是已知分币种金额，任何价格缺失时都不能冒充完整总成本。

## 风险与排序

存在确定生产缺口时：交期超过7天，或模拟分析日下单后的到货日期不早于开工日，为 high；其他完整交期情形为 general。仅需恢复安全库存时标记 buffer_only；净需求为零标记 none。缺少关键风险事实时为 null，不猜等级。模拟到货日不是已下单或承诺到货。

全局优先级是可复算的字典序：

1. 关键数量/采购参数或风险未知的行优先核验数据；不把未知风险说成高风险。
2. 已知风险等级 high → general → buffer_only → none。
3. 交期降序。
4. 生产缺口比例降序。
5. 只有成本完整且单币种时按采购金额降序。
6. 精确物料编码升序保证稳定。

另提供同币种采购金额排名与 MOQ/倍数额外成本排名，不跨币种比较，不使用缺少来源的“高成本阈值”或 AI 打分。

## 来源与缺失

每项建议保留 BOM 路径、库存快照、在途观察、安全库存策略、采购参数和价格来源，包含文件标识、SHA-256、导入批次、工作表与行号。

缺失列表与数量、参数、价格、成本、风险完整性独立返回。能计算数量并不证明供应商/交期已完整，也不证明成本已知。全局 `data_unavailable` 可以携带已确认的局部计算结果，调用方必须检查完整性。

## 企业待确认

- 各物料 MOQ、订单及包装倍数，哪些约束明确不适用。
- 权威供应商、交期、采购单位及参数有效区间。
- 价格与物料/供应商的显式关联、单位、币种、有效期、税价口径和会计舍入规则。
- 完整在途来源、日期、状态及与库存一致的观察时点。
- 安全库存策略和批次有效期；非保质物料需明确独立口径，不能把缺失有效期当永久有效。
- 多供应商、多币种场景必须显式选择或分组，不做供应商推荐或汇率推断。
