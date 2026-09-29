# Published Facts 受控查询 Tool

本阶段提供只读、确定性的结构化事实查询接口。Tool 不读取 `data/raw` 或 Excel，
不调用 LLM，也不执行 MRP、采购建议或生产决策。

## Tool 列表

| Tool | 输入 | 用途 |
| --- | --- | --- |
| `published_inventory_query` | `material_code`, 可选 `as_of` | 查询最近或指定时点的库存汇总 |
| `published_inventory_batch_query` | `material_code`, 可选 `as_of` | 查询库存批次、库位及来源已提供的属性 |
| `published_bom_query` | `parent_material_code`, `revision` | 查询已发布 BOM、价格和来源 |
| `published_inbound_supply_query` | `material_code`, 可选 `as_of` | 查询已发布权威在途事实 |

四个 Tool 通过独立的 `FACT_QUERY_TOOLS` 暴露，当前不加入旧 Demo Agent 的工具列表，
因此不会改变已有 Demo 或 Workflow 行为。

## 统一输出

所有 Tool 都返回：

```json
{
  "status": "ok",
  "query": {},
  "data": {},
  "completeness": {},
  "provenance": {},
  "warnings": []
}
```

受控状态包括：

- `ok`：存在可返回的已发布事实；
- `item_not_found`：canonical item 和 alias 均无精确匹配；
- `item_alias_ambiguous`：同一 alias 对应多个 item，必须先治理；
- `data_unavailable`：item 存在，但指定时点或事实类型没有 published facts；
- `invalid_query`：输入为空或 `as_of` 不是带时区 ISO 8601 时间；
- `query_failed`：事实存储不可访问；不返回数据库异常文本或推断值。

## Item / Alias 解析

查询顺序固定为：

1. `items.material_code` 精确匹配；
2. `item_aliases.alias_code` 精确匹配；
3. 无匹配时返回 `item_not_found`。

不做大小写折叠、相似度匹配或 LLM 猜测。BOM 父件同样必须先存在于标准
`items/item_aliases`；仅存在 BOM Header、但没有受控 item 身份时返回 `item_not_found`。

## 库存时间语义

- 未传 `as_of`：选择该 item 最新的已发布库存快照；
- 传入 `as_of`：只选择 `snapshot_at <= as_of` 的最近快照；
- 过去时点之前没有快照：返回 `data_unavailable`，绝不使用未来快照；
- `available_qty` 或 `reserved_qty` 只要任一行未知，汇总值就是 `null`；
- 批次查询只返回事实字段，不生成 FIFO、临期或呆滞建议。

## Provenance

- 库存：snapshot、snapshot_at、import batch、source file、SHA-256、sheet；
- BOM：版本、import batch、source file、SHA-256、sheet，以及每行 row number；
- 在途：observation、import batch、source file、SHA-256、source name，行级 sheet/row。

金额与数量对外以十进制定点字符串返回，避免 JSON 浮点精度损失。
