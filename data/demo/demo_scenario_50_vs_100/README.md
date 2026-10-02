# 独立比赛 Demo：50 台齐套 / 100 台缺料

场景标识：`demo_scenario_50_vs_100`。产品：`DEMO-PMC-01 / V01`。

这里全部是公开合成数据，不来自企业 Excel，不表示 KQ-Z112 的真实库存或供应商关系。旧 KQ-Z112 Demo 保持不变。

## 文件与数据口径

| 文件 | 内容 |
| --- | --- |
| manifest.json | 场景身份、产品、明确版本、生效日、库存时点、计划开工日 |
| items.json | 6 个合成物料的名称、单位 |
| bom_facts.json | 2 个 BOM 头、5 条关系，含控制组件二层展开 |
| inventory_facts.json | 4 种叶子物料、8 条批次/库位事实，明确在库/预留/可用数量 |
| purchase_parameters.json | 4 组显式供应商、MOQ/倍数、交期、安全库存和含税 CNY 单价 |
| inbound_facts.json | 4 条合成已收货采购记录，明确剩余在途为 0 |

在途为 0 来自完整的合成已收货记录，不是把缺少采购事实当作 0。已收货量不再叠加库存；只有剩余在途按原 Service 规则参与计划。安全库存 0 是场景显式配置，不是业务缺省。

数据时间固定在 `2026-10-02T00:00:00+00:00`，BOM 生效分析日为 `2026-10-02`，计划开工日为 `2026-10-20`。初始会话参数来自 manifest，非 LLM 猜测。显式新产品/版本/时点仍按原上下文规则处理，不用场景参数冒充新产品事实。

## 预期结果（由现有 Service 计算）

| 物料 | 每台用量 | 可用库存 | 50 台需求/缺口 | 100 台需求/缺口 |
| --- | ---: | ---: | ---: | ---: |
| 演示主板 | 1 | 75 | 50 / 0 | 100 / 25 |
| 演示芯片 | 4 | 300 | 200 / 0 | 400 / 100 |
| 演示电机 | 2 | 150 | 100 / 0 | 200 / 50 |
| 演示紧固件 | 8 | 600 | 400 / 0 | 800 / 200 |

- 理论最大生产量：75 台。
- 50 台：物料种类齐套率 100%，数量满足率 100%。
- 100 台：4 种物料均缺料，种类齐套率 0%，数量满足率 75%。
- 100 台采购建议：主板 30、芯片 100、电机 50、紧固件 200；主板的 25 件缺口受 10 件倍数约束向上到 30 件。总含税合成成本 1560 CNY。
- 50 台采购建议量及成本为 0；不是缺失字段被补 0。
- 采购建议不改变库存，不代表已下单或到货；100 台不会因建议生成而变为齐套。

这里“可以生产”只表示该演示场景的库存齐套用量条件满足，不是排程、设备能力、质量放行或交付承诺。

## 隔离与来源

独立数据库：本目录 `.runtime/demo_facts.sqlite3`，由场景加载器初始化，Git 忽略该运行目录。加载器不读取或修改 `PMC_FACT_DATABASE_URL`，不将数据发布到企业事实库，不访问 `data/raw/`。

该库复用现有 Fact Layer migration 与 published 表，额外的 `demo_scenario_identity` 是独立运行库的身份保护，不是企业事实模型迁移。每个数据文件有独立 import batch / source file、SHA-256 和 `demo://demo_scenario_50_vs_100/...` 受控来源。JSON 数组的逻辑 sheet 表示记录类别，row_number 是 1 开始的数组记录序号（不是文本行号）。BOM 名称修订冻结来源为 items.json，关系来源为 bom_facts.json。

加载器只做类型/数值/引用校验与持久化，不展开 BOM、不计算库存缺口或采购建议。齐套、产能和采购全部复用原 Service。种子发布时间/观察时间为固定场景时间，保证来源可复现。

幂等加载不重复发布；数据包 SHA 改变时明确拒绝覆盖已有场景历史，需管理员选择新的空运行目录（Python `runtime_root`），不自动删除或覆盖数据库。已有非本场景数据库、企业 raw/facts 目录作为运行路径均被拒绝。

## Agent / API 演示

沿用统一入口，不改变旧调用。首次：

```http
POST /api/v1/agent/query
Content-Type: application/json
```

```json
{
  "scenario_id": "demo_scenario_50_vs_100",
  "message": "生产50台DEMO-PMC-01"
}
```

Agent 解析数量并调用隔离 Tool，Tool 经已有生产能力 Service 查询多层 BOM 和库存，返回“可以生产 50 台”（库存齐套口径）。返回 session_id、scenario_id、结构化结果和真实合成来源，问答持久保存在场景库。

继续使用返回的 session_id：

```json
{
  "scenario_id": "demo_scenario_50_vs_100",
  "session_id": "首次响应的session_id",
  "message": "生产100台DEMO-PMC-01"
}
```

Agent 返回缺料清单、缺口和来源。继续问“采购建议”“减少到50台呢？”“查询DEMO-BOARD-01库存”，均调用已有 Service，不改写任何库存。

也可 `POST /api/v1/agent/sessions`，body 为 `{"scenario_id":"demo_scenario_50_vs_100"}` 先创建会话。

历史恢复：

```http
GET /api/v1/agent/sessions/{session_id}?scenario_id=demo_scenario_50_vs_100
```

scenario_id 必须显式传递；不自动从企业库寻找 Demo 会话或反向寻找企业会话。上下文不可混入旧 workflow_id/fact_session_id。原企业持久会话 API、旧 Chat/Demo 路径、前端均不变；本阶段不自动切换旧界面到新场景。

## 离线验证

在项目根目录运行：

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_demo_scenario_50_100.py -q -p no:cacheprovider
```

公开测试使用临时独立库，不依赖企业 raw、真实数据库或外部 LLM。包括 API 链路、来源、幂等加载、企业库/会话隔离和不扣减库存验证。
