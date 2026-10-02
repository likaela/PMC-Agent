# 企业 Agent 体验层修复

本轮只修改 Agent 编排、语言适配和持久会话接入；不修改 Fact Layer、数据库模型、
published facts、计算 Service、前端、旧 LangGraph 路径或 Demo 数据。
`test_enterprise_user_acceptance.py` 保留 75 个用例；经确认，原因/限制追问的验收
契约更新为证据复用，工具白名单补充真实风险/FIFO分析工具。没有删除或 skip 用例。

## 1. 实际调用链

```text
持久会话 → Planner（原文参数 + 企业语义规则 + DeepSeek 校验/fallback）
         ├ 原因追问 / 邮件草稿 → 已保存 Evidence → 有界自然语言生成
         ├ 普通查询 → Context Resolver → 原查询 Tools
         └ 库存诊断 / FIFO → 明确参数与事实时点 → 原分析 Service 的绑定 Tool
                                       ↓
                          证据与问答通过原存储模型保存
```

企业语义增强只在 enterprise 模式启用；Demo 使用原查询模式、原 formatter、原数据
空间。新增库存分析工具在 Demo Registry 中不可调用。

## 2. 多轮证据复用

“为什么”“原因”“限制”“哪些物料影响”“怎么回事”等解释型追问，优先读取
同一会话最近 50 轮持久化证据，不再次运行计算 Tool。

- 校验当前 active domain、物料/产品、原 Tool 类型、数量、版本和业务日期，不能
  仅因为历史里有一个成功结果就重用。
- 显式新物料不借用旧任务；库存总量不能作为生产需求或缺料原因的证据。
- “重新计算”“按最新库存”“再查一次”进入真实重查；“不要重新计算”不触发重查。
- 解释回答明确标记基于历史证据，不声称是最新库存结果。
- `completed_steps=[]`，不伪造本轮 Tool 执行；原结果放在 `reused_result`，
  保留 `reused_from_turn_id` 与原始 Tool Evidence/provenance。
- 这是解释/草稿响应，不把历史结果伪装成新执行的查询卡片。
- 没有匹配采购证据时，要求先完成采购分析，不凭空生成邮件事实。

## 3. Planner 语义与实体保护

到货/运输语义优先于宽泛采购词：“什么时候到”“到货”“在途”“运输”“已采购”
“预计交付”“采购订单”进入既有 inbound 路径。

“采购”“买”“下单”“补货”“MOQ”“成本”“供应商”等进入采购规划。
采购邮件是证据驱动草稿操作，不进入在途，也不执行采购或发送。

未加引号的 MOQ/LT/BOM/FIFO/MRP/PMC 等制造术语不作为物料；V01 等保留为版本。
只过滤实体解析，不删除原文中的 BOM/FIFO 意图关键词。

`MOQ 100` / `LT 7` 记录为 `constraints=[{type,value}]`。它们是用户请求，不是
published facts；不会覆盖 Service 使用的已发布 MOQ/交期。查询时返回待确认提示。
LLM 不得改换原文物料、生产数量或分析参数。

## 4. 回答表达与邮件

企业 formatter 只展示既有 Tool 字段，不计算：

- 采购：物料、缺口、建议量、供应商、单项与总成本、风险及缺失字段中文提示。
- 库存：保持在库/可用/预留的区别，未知仍是 null/“未知”。
- 批次：补充已有有效期和入库日期；原始列表不是 FIFO 建议。
- 风险：分别展示临期、呆滞、安全库存；生产缺料风险仍要求 BOM 和明确需求证据。
- 邮件：提供可审核草稿，物料/量/供应商/风险来自已有采购证据，交付时间待人工
  确认，不把模拟交期当承诺。不发送邮件，不执行下单。

DeepSeek 继续采用有界 statement 引用输出。Python 从证据渲染事实和草稿；模型
可以组织给定文字，但不能任意增添供应商、数字或交付承诺。非法输出自动 fallback。

## 5. 既有库存能力接入

Registry 新增 enterprise 专用别名：

| 别名 | 真实工具名 | 复用能力 |
| --- | --- | --- |
| inventory_risk_analysis（规范名称） | published_inventory_risk_analysis | PublishedInventoryAnalysisService.analyze |
| inventory_risk | published_inventory_risk_analysis | PublishedInventoryAnalysisService.analyze |
| inventory_fifo | published_inventory_fifo_plan | PublishedInventoryAnalysisService.fifo |

绑定到当前会话 Repository 的 Store，不从全局环境跳到别的企业库或 Demo 库。
未给分析时点时采用已发布快照时点，不任意使用今天。
FIFO 缺领用量时追问，不把生产台数或全批次库存猜成领用量。
FIFO 仍按入库时间，不改成 FEFO，且只是模拟分配，不写库存。
临期/呆滞阈值不存在时保持“数据不足”；用户显式提供阈值只作为此次分析参数。
所有排序、日龄、数量、风险和分配仍由原 Service 计算。

外部供应/政策风险：明确说明缺少权威外部数据源，暂不判断；没有增加 provider。

## 6. 验收契约对齐

前一轮保留的六个失败来自以下契约冲突，本轮按用户确认对齐：

1. **P13/P14**：原验收要求限制/影响物料追问调用 `_tool` 并返回新的执行步骤。
   现在验证原轮次、原结果、原 query/provenance 及持久引用完全一致；限制物料集合
   与回答仍必须正确。通过拦截所有 BaseTool.invoke 验证不重算，不能伪造完成步骤。
2. **W01/W04/W19/W20**：原验收 `ACTUAL_TOOLS` 只允许六个查询工具，未包含本轮
   要求接入的已有 `published_inventory_risk_analysis`。真实调用和来源被白名单
   拒绝。现在补充明确工具白名单，并要求风险响应的规范 operation、真实工具名、
   data/provenance 与持久 Evidence 一致；不伪装为普通库存查询。

新增体验测试独立验证这些行为：不调用任何 Tool 的原因复用、显式刷新真实执行、
真实风险/FIFO工具名与 Evidence、FIFO/FEFO区分、缺参不猜、邮件防伪、会话/数据空间
隔离。规范别名兼容原 inventory_risk，不改变既有普通库存查询的默认工具。

## 7. 运行与边界

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_enterprise_user_acceptance.py -q -p no:cacheprovider
.\venv\Scripts\python.exe -m pytest tests/test_enterprise_agent_experience.py -q -p no:cacheprovider
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
git diff --check
```

新增体验测试使用真实临时 SQLite published facts / API / Agent / Tools，DeepSeek
全部 mock。未执行真实企业数据或线上 DeepSeek 验收，未开展前端联调。

### 体验修复首次验证（2026-10-02，历史记录）

- 原企业验收：69 passed / 6 failed（原基线 55 passed / 20 failed）。
- 新增体验测试：44 passed。
- 全量：571 passed / 6 failed / 1 skipped，另有 45 个 subtest 通过。
- 六个失败均为第 6 节列出的验收契约冲突；全量尚未全绿，不宣称验收完成。
- PostgreSQL 条件集成测试因未提供 `PMC_TEST_POSTGRESQL_URL` 保持原有 skip，
  本轮没有新增 skip 或 xfail。
- `git diff --check` 通过；新文件也单独检查，未发现空白错误。
- 未提交 Git。

### 验收契约对齐后的验证（2026-10-02）

- 原企业验收：75 passed / 0 failed，六个剩余失败全部消除。
- 体验测试：48 passed；本轮新增 4 项，验证新旧风险别名共用原工具、参数校验、
  意图白名单及 Demo 拒绝调用。
- 全量：581 passed / 0 failed / 1 skipped，另有 45 个 subtest 通过。
- 唯一跳过项仍是未提供 `PMC_TEST_POSTGRESQL_URL` 的原 PostgreSQL 条件集成测试。
- 保留已有 Starlette/anyio 弃用警告；`git diff --check` 通过。
- Fact Layer、数据库结构、计算 Service、Demo、前端及 LangGraph 未修改，未提交 Git。
