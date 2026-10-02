# v1.13 受控自然语言问答与持久会话

## 边界与兼容方式

企业持久问答只能读取 published facts。理解层不接触数据库；Python 通过 Tool 白名单执行库存、批次、BOM、在途、生产能力及采购建议查询。回答采用确定性格式，不把 Tool 返回的 null 改成 0，不调用 LLM 生成企业事实。

为保持已有 Demo、Scenario、Explanation 和内存 Workflow 行为，持久能力显式启用：

- `POST /api/v1/agent/sessions` 创建企业会话，后续 `/api/v1/agent/query` 携带 `session_id`。
- 或首次 query 使用 `persist_session: true`，响应返回可保存的 `session_id`。
- 未带这两个参数的旧请求保持原行为；`fact_session_id`/`workflow_id` 仍是旧内存上下文，不会隐式转为持久会话。
- 企业会话禁止混入 `workflow_id`、`fact_session_id`、`active_context`。生产问题在企业模式调用 published production capacity Tool，不调用 Demo PMC Workflow。这是理论库存能力分析，不替代原开工决策。
- 本阶段不改前端；调用方需保存返回的 session_id。服务重启后使用同一数据库和 session_id 即可恢复。

## 数据库与迁移

新增双方言 migration `007_agent_conversations.sql`，兼容 SQLite 文件库和 PostgreSQL。使用现有 `PMC_FACT_DATABASE_URL`，不另建物料主数据。不支持不安全的 SQLite `:memory:`。

部署前备份数据库，停止并发迁移进程，在已配置的环境执行一次：

```powershell
.\venv\Scripts\python.exe -c "from repositories.fact_store import create_fact_store; print(create_fact_store().migrate())"
```

本次开发只迁移临时测试数据库，不自动迁移本机企业库；API 请求不执行 migration。缺少迁移时返回统一服务器错误，日志供管理员诊断。

新增模型：

| 表 | 职责 |
| --- | --- |
| agent_sessions | 会话时间、独立 fact/production 上下文、context_version |
| agent_conversations | 对话归属；目前一会话一对话，不做分支管理 |
| agent_turns | 有序问答、完整公开响应、时间；会话内序号唯一 |
| agent_fact_references | Tool 标识、实际调用参数、结构化结果快照、完整 provenance |

每轮上下文、user query、agent response、fact reference 在同一事务内提交。版本条件更新实现乐观并发控制，旧上下文提交返回 409，不丢失或静默覆盖另一轮。Tool 查询为只读；提交冲突时其结果不会成为已保存回答。

## API

首次查询：

```json
{
  "message": "查询 KQ-Z112 V01 库存 截至2026-10-01T00:00:00+08:00",
  "persist_session": true
}
```

后续查询：

```json
{
  "session_id": "第一次响应中的session_id",
  "message": "还能生产多少？生效日期2026-10-01"
}
```

响应保留 `intent/status/answer/structured_data/provenance/warnings`，新增 `session_id/conversation_id/turn_id`。intent 在企业模式为 inventory、inventory_batches、bom、inbound、production_capacity、purchase_planning、clarification。

恢复与审计：`GET /api/v1/agent/sessions/{session_id}?after=0&limit=50`。

- 返回保存的上下文、按序问答及来源，不重新读取当前事实来替换历史回答。
- after 为已读序号，limit 范围 1–200；按返回的 sequence_no 继续分页。
- 不存在会话返回 404 中文公开错误；并发冲突 409；混合上下文/非法请求 422。
- 业务事实不足仍 HTTP 200，status 为 data_unavailable；需要补充版本或日期为 needs_input。

## 理解、上下文与拒答

1. 规则优先识别编码、意图、中文/数字数量、V版本、带时区时点。
2. 无明确规则时 LLM 可辅助提取；Pydantic 禁止额外字段，编码/日期/版本必须逐字来自用户输入，数量必须与本地解析一致。LLM 异常或编造参数回退规则/澄清。
3. 同对象继承版本、生效日、查询时点、生产数量和开工日；显式新对象清除旧对象的版本/时间/数量。无事实的新对象也成为当前对象，下一问不能退回旧物料。
4. fact 和 production 上下文分别保存。库存对象转生产能力只继承当前事实查询对象，不借用不相关的旧生产方案。
5. “当前/现在/最新”清除继承的查询时点，重新查询最新可用快照；历史指定时点不会读取未来快照。
6. 版本或生效日未明确时必须澄清，不自动选 V01 或最新版本。`生效日期YYYY-MM-DD` 与 `开工日期YYYY-MM-DD` 用于区分日期语义。
7. BOM、库存、单位、在途、采购参数、价格的完整性由原有 v1.10–v1.12 Tool/Service 判定；不新增计算规则。产能不计假设在途，采购建议不等于下单或到货。

采购示例：

```text
PRODUCT V1 生产100台 采购建议 生效日期2026-10-01 开工日期2026-10-20 截至2026-10-01T00:00:00+00:00
```

采购来源不足、供应参数冲突、单位不明确时保留 unknown 并拒绝完整结论。本阶段不增单物料价格查询 Tool、供应商选择模型或采购执行。

## 来源与历史

保存 Tool 原样公开 provenance，包括 source file 标识/SHA-256、import batch、snapshot/observed_at、BOM revision、sheet/row 及多层路径。缺少事实的调用也记录 status 和空来源；不伪造引用。历史结果独立于之后的新快照或事实变化，数值与引用保持原回答时的快照。

本阶段提供应用级追加审计，不宣称数据库管理员不可篡改。问答包含用户原文和查询结果，属于企业敏感记录，应存放私有数据库、不提交 Git。

## 运维限制与验证

- 只持久企业问答，不持久 LangGraph MemorySaver 或旧 Demo 会话。
- 未新增账号/权限系统。session_id 是随机 UUID，但不是身份认证；未做企业鉴权前不得将私有数据 API 直接暴露公网。
- 保留期、备份/删除策略、团队权限及部署侧加密需要企业另行确认，不在本阶段自动实现。
- migration 需在部署阶段单进程执行；数据库暂不可用时不能保证保存当次问答，不返回“已保存”的成功结论。
- SQLite 使用临时文件库测试；真实 PostgreSQL 集成仅有 `PMC_TEST_POSTGRESQL_URL` 时执行，否则明确 skip。
- 测试包含跨 Python 子进程恢复，而不只是重建一个内存对象；所有 LLM 测试 mock，不依赖外部 API 或私有 raw Excel。
