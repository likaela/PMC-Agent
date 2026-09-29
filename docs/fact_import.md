# 企业表格导入与受控事实层

## 边界

该事实层独立于现有 Demo 数据源和 PMC 决策链。Excel 原文件只读，导入结果必须先进入
`staging`，经校验和人工确认后才能以单个数据库事务发布。任何错误都会令整个批次保持
`invalid`，不会向 `items`、`bom_headers`、`bom_lines` 或 `price_records` 写入部分事实。

## 数据库

- 生产：设置 `PMC_FACT_DATABASE_URL=postgresql://...`，使用
  `migrations/postgresql/001_controlled_fact_layer.sql`。
- 测试/本地：使用 `sqlite:///...`，使用
  `migrations/sqlite/001_controlled_fact_layer.sql`。

应用启动不会自动把现有 Demo Excel 导入事实库。调用方应显式创建 `FactRepository`、执行
`migrate()`，再调用 `BomImportService`。

## 3588M 核价映射

`import_mappings/3588m_costing_v1.json` 通过元数据标签和列名识别内容，不依赖文件名、
工作表名或固定产品：

- `项目代号`、`版本号` → BOM Header
- `料号`、`名称`、`规格型号`、`数量` → Item / BOM Line
- `含税单价` → Price Record
- `总价` → 仅校验 `数量 × 含税单价`，不发布为价格事实

同一映射同时支持 `.xls` 和 `.xlsx`。源文件名、SHA-256、工作表、Excel 行号和导入批次
会持久化，供发布后追溯。

## 人工确认

单位、币种、生效日期不存在时，批次状态为 `pending_confirmation`。调用
`confirm_pending_fields()` 明确提供这些值后，批次才会进入 `ready_to_publish`。程序不会
默认或推断这些字段。
