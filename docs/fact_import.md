# 企业表格导入与受控事实层

## 边界

该事实层独立于现有 Demo 数据源和 PMC 决策链。Excel 原文件只读，导入结果必须先进入
`staging`，经校验和人工确认后才能以单个数据库事务发布。任何错误都会令整个批次保持
`invalid`，不会向 `items`、`bom_headers`、`bom_lines` 或 `price_records` 写入部分事实。

## 数据库

- 生产：设置 `PMC_FACT_DATABASE_URL=postgresql://...`，使用
  `migrations/postgresql/001_controlled_fact_layer.sql` 和
  `002_source_audit_and_item_history.sql`。
- 测试/本地：使用 `sqlite:///...`，使用
  `migrations/sqlite/001_controlled_fact_layer.sql` 和
  `002_source_audit_and_item_history.sql`。

事实层每个 Repository 操作都会建立独立连接，因此明确拒绝 SQLite `:memory:`。测试应使用
临时文件数据库，避免迁移表和事务状态随连接关闭而丢失。

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

适配器使用以下读取边界：

- `.xlsx` 使用 `read_only=True`，逐行迭代。
- `.xls` 使用 `on_demand=True`，逐工作表迭代并及时卸载。
- 每个工作表只扫描映射配置指定的前 100 行来识别候选表头。
- 未命中表头的工作表不会继续读取；命中后只保留匹配 BOM 明细，遇到“合计/总计”停止。

## Source File 审计

`source_files` 记录 `source_kind`、`storage_key`、`source_uri`、SHA-256 和文件大小：

- `upload`：复制到未纳入 Git 的 `data/facts/source_files` 私有目录，按 SHA-256 内容寻址。
  已存在的对象只校验、不覆盖。
- `local`：不复制原文件，保存 `project://...` 或受控 `file://...` 引用及 SHA-256。
- `erp`：调用方必须显式提供 `source_uri`，程序不推断 ERP 位置。

发布查询同时返回 source file id、SHA-256、工作表、行号和 import batch。物料身份表不再被
后续导入覆盖；每次发布会在 `item_revisions` 中保存不可变主数据和来源快照。

## 人工确认

单位、币种、生效日期不存在时，批次状态为 `pending_confirmation`。调用
`confirm_pending_fields()` 明确提供这些值后，批次才会进入 `ready_to_publish`。程序不会
默认或推断这些字段。

## 发布与重复版本策略

`publish()` 会在同一事务内重新锁定并检查 import batch 状态、错误数、待确认字段、staging
行数和每行有效性。SQLite 使用 `BEGIN IMMEDIATE`，PostgreSQL 对父件和版本使用事务级
advisory lock。

重复 `parent_material_code + version` 的策略为 **reject**。系统不会覆盖或自动 supersede
已发布 BOM；失败批次仍保留在 staging，可审计其 source file 和 batch。

## 验收

本机存在私有文件时运行：

```powershell
venv\Scripts\python.exe scripts\validate_3588m_fact_import.py
```

文件不存在时脚本输出 `skipped` 并以成功退出码结束，公开测试不依赖 `data/raw`。

真实 PostgreSQL 集成测试只在设置 `PMC_TEST_POSTGRESQL_URL` 时运行。测试会创建随机 schema，
实际执行两版 migration、事务回滚与 BOM 发布，结束后删除该 schema；未设置时明确 skip。
