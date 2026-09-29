# 库存与在途受控事实导入

## 范围

本阶段只建立库存时点事实和采购在途事实的导入基础，不提供 Agent 查询工具，
也不改变现有 BOM、MRP、采购、生产决策或 Demo 数据链路。

## 库存导入口径

真实工作簿仅以 `库存表` 作为一期库存事实来源，字段映射如下：

| 原始字段 | 标准字段 | 规则 |
| --- | --- | --- |
| 物料代码 | `raw_material_code` / `item_id` | 先匹配 `items.material_code`，再匹配受控 `item_aliases`；未匹配不创建 item |
| 库存 | `on_hand_qty` | 使用 `Decimal`，必须为非负数 |
| 归属地 | `site` | 原样保留，不猜测为 warehouse |
| 库位 | `location` | 原样保留，允许来源空值 |
| 批次号 | `batch_no` | 原样保留，不在导入阶段汇总 |

来源没有明确提供的 `warehouse`、`available_qty`、`reserved_qty`、
`quality_status`、`received_at`、`expiry_date` 均保存为 `NULL/unknown`。
系统不会从工作簿后续扩展列推断预留量、可用量或在途量。

以下来源继续独立并被明确排除：

- 电阻电容现库位
- 历史可处理库存（工作表 `2023年至2025年形成的存货-可以处理`）
- 成品库存表
- 料号查询表
- 阻容库存表-2019

## 时间点与历史

- `observed_at` 是系统读取来源的观测时间，自动记录。
- `snapshot_at` 是业务库存时点，必须由来源或业务人员明确提供；缺失时批次停在
  `pending_confirmation`，不能发布。
- 发布后的查询按 `snapshot_at <= as_of` 选择最近快照，并返回该快照的行级库位/批次事实。
- 同一来源 SHA-256、工作表和 `snapshot_at` 的重复发布采用 **reject** 策略；
  原 staging 批次和错误/状态仍保留以供审计，禁止静默覆盖历史。
- 来源内精确重复明细不会被删除或合并，只标记 `is_duplicate` 并计入质量报告。

## Item 关联

库存和在途共用已有 `items` 与 `item_aliases`，不建立第二套 material master。
未匹配记录保留原始料号、来源行和 `unmatched` 状态，不能发布，也不能被解释成库存 0。
主数据或别名经人工治理后，可显式刷新 staging 关联再发布。

## 在途导入口径

当前私有库存工作簿和 supplier master 不构成可靠采购订单事实源，因此真实在途可用状态为
`false`，发布事实数为 0。现阶段只提供标准化导入合同和测试夹具：

- `ordered_qty` 必须明确且大于 0；
- `received_qty` 仅在来源明确提供时保存；
- `in_transit_qty = ordered_qty - received_qty` 仅在两个字段都明确且合法时计算；
- `received_qty` 缺失时 `in_transit_qty` 保持 `NULL/unknown`；
- supplier、order_no、到货日期和状态均不得从 supplier master 或库存扩展列推断。

## Staging 与发布

库存和在途沿用统一链路：

`source_files → staging → validation → confirmation/item matching → publish`

发布在单个写事务中重新检查批次状态、校验错误、item 匹配和重复来源键。
任一校验错误会使整个批次保持 `invalid`，不会写入 published facts。

## 数据质量报告

每个导入批次在 `import_quality_reports` 保存结构化 JSON，库存报告至少包含：

- 原始行数、有效事实数、唯一料号数；
- 批次数、库位数；
- item 匹配/未匹配料号数；
- 精确重复行数、非法行数；
- 排除数据源和无法获得字段；
- 在途事实是否真实可用及当前假设。

本机私有文件可用以下命令执行只读验收；缺失时明确跳过：

```powershell
.\venv\Scripts\python.exe scripts\validate_real_inventory_fact_import.py
```

脚本使用临时 SQLite，不发布数据、不修改原始 Excel，也不输出企业料号或库存明细。
