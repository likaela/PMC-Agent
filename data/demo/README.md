# 脱敏演示数据

`kq_z112_demo.json` 是比赛演示专用的纯合成数据：

- 不来源于企业 BOM、库存或供应商 Excel。
- 使用 `DEMO-Mxxx` 与 `DEMO-SUP-xxx` 虚构编码。
- 保留 66 条 BOM、44 条纳入 MRP、22 条排除和 8 条确定缺料的演示结构。
- 仅用于验证既有 PMC 工作流与界面，不代表任何企业实际库存或采购关系。

数据源由 `PMC_DATA_SOURCE` 选择：`auto`、`raw` 或 `demo`。公开发布时不得将
`data/raw/` 或任何真实企业原始文件复制到本目录。
