# 受控评审数量核对

## 范围与确认

本地企业模式支持源文件绑定的人工库存口径确认。该口径只用于基础数量核对，不改写 Published Inventory、不把账面数量填入 available_qty、不生成正式排程许可。

私有文件 `data/facts/confirmations/inventory_quantity_use.json` 沿用单位确认的校验与指纹机制，记录文件相对定位、原文件标识、SHA-256、工作表、数量列、单位、确认人、原始确认语句、理由、带时区审计时间及产品/版本白名单。文件被 Git 忽略。源路径、内容、工作表或产品版本不匹配时，确认不生效；不能自动应用到新数据源。

迁移到新电脑时，由获授权人员重验文件路径和 SHA-256 后准备私有确认，不能把公开空模板当作确认。单位文件 `inventory_units.json` 继续独立校验。公开示例在 `deploy/examples/`，不包含企业资料。

## 数量与计算

- 数量须为大于0的整数。0、零、负数、小数、分数、科学计数输入在查询库存前拒绝；不覆盖上一轮合法数量/产品/Evidence。
- 已发布成品单位明确为片时，口语“个/件”表示成品计数，显示仍为片。这不是物理单位转换。
- 先读取 Published BOM，按 Decimal 计算需求，再读取库存。库存 I/O 失败时保留全部需求、库存和缺口保持 null，并记录服务端诊断。
- 同料不同批次/库位的有效记录可汇总；疑似重复的观察保留分项，未经核验不汇总。
- 需求量 = 单耗 × 生产数量。已确认可比记录的缺口 = max(需求量 − 实际库存量, 0)。没有记录或疑点合计保持未知。
- 已知物料不足则返回确定不足；没有已知不足但仍有未知项则不能证明全齐套。仅所有物料可比且满足才返回“满足物料需求”。正式工单放行字段保持 false。
- 不重新写正式 MRP/产能/采购规则。原 Published Facts 严格分析与完整合成 Demo 不变。

## 隔离评审推演

主动选择“评审推演（合成补充库存）”后，携带 `scenario_id=review_real_bom_simulation` 创建独立会话。默认企业入口不自动恢复该场景。

私有 `data/facts/confirmations/review_scenario.json` 指定产品、版本和目标数量。复用真实 Published BOM 的原始单耗，以同一个 BookInventoryService 做比较。在内存情景层对可核实原库存补充至目标需求；原记录未知/重复时，仅采用明确标记的假设余额，并在来源内保留原观察及“未纳入真实合计”说明。绝不把未知真实库存说成0。

推演会话单独存放 `.runtime/review_real_bom_simulation/sessions.db`；不复制/发布 BOM 或库存到此库，不更新企业事实库，不修改 Excel。该场景只适用配置的产品/版本。前端和回答明确标记合成库存。切回企业空间后不携带场景标识。

远程合成试用禁止使用此私有场景；既有 `demo_scenario_50_vs_100` 继续完全隔离。

## 回归要求

### 版本化精简评审模型

`scripts/prepare_slim_review_dataset.py --product <授权产品> --revision <版本> --inventory <主库存Excel>`先备份原BOM/库存文件和既有处理/确认文件，再在被忽略的`data/normalized/review_slim/<version>/`生成`verified.json`、`synthetic.json`、`excluded.json`、`synthetic_supplements.json`与备份清单。产品、路径和来源由参数/现有私有确认限定；不更新企业事实表。私有入口配置为`data/facts/confirmations/review_slim.json`。

可核验模型先按料号合并真实BOM单耗，核验库存记录身份与单位，再只保留 `floor(stock / qty_per) >= 1` 的物料。零库存、正库存但不足一片、无记录及未解决重复均在私有审计中逐项记录排除原因。完整企业空间仍保留这些物料，不能将筛选结果冒充完整产品的生产能力。未知不补0，无有效物料拒算。合成模型仅在独立情景中补充保留集合，不回写原文件/企业库存。

`SlimReviewService`复用`BookInventoryService`的需求/差额计算，对保留集合用Decimal整数商计算`min(floor(stock / qty_per))`。独立Agent适配器调用现有StructuredTool；最大数量、限制物料及结果均入Evidence，前端不重新计算。每个场景和数据版本采用独立会话库；新企业分析不继承过滤，公开远程试用禁止访问私有精简模型。

固定覆盖100→50→0→1，缺数量后补数量，库存读取失败后恢复、产品切换、历史结果选择、刷新恢复，以及正向/反向推演。前端只映射后端数量和状态，不计算差额，不从回答提取数字，不以旧结果冒充当前失败输入。
