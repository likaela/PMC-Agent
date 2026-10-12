# 产品上下文专项交付报告

本报告对应2026-10-11的产品上下文修复。属于授权本地开发记录，不代表公开Git仓库或公网启动授权。

## 根因与修复

1. 原评审解析入口仅从问题提取完整产品编码。“查询演示产品”没有提取到编码，前端继续采用已选KQ-Z112，随后进入其34项范围。现在由权限范围内的统一产品解析器规范化明确编码、唯一别称和已展示目录中的序号；执行问题与原始历史消息分别保存。
2. 原产品切换会清空页面消息，而且按产品保存的指针不能恢复整个跨产品对话。现在每次切换建立服务端确认的独立绑定；浏览器仅保存分段会话指针，消息与证据仍从服务端恢复。
3. 原分析范围回答和适配器无条件附带最大数量。现在通过本轮问题的展示投影决定是否显示；底层Tool Evidence不删除、不重算。
4. 原目标数量接受说明文字，并在缺数量时显示占位卡片。现在只允许数值，异常映射明确失败，缺数量时不显示该卡片。
5. Demo原因追问未进入已有Evidence复用分支，且复用数据位于reused_result时展示适配未兼容。现在按当前产品、数量、版本、场景核对历史证据后复用，不重复调用计算Tool。
6. 产品目录仅查询有权访问的目录，不修改活动产品。具体产品概览调用已绑定BOM Tool，不执行旧产品库存或产能分析。
7. 目录序号传递的是当前对话实际展示的顺序，权限和会话产品仍由后端检查；它不是权限授予。可选请求字段对旧客户端保持兼容。
8. 相对数量只从当前产品的明确生产目标规范化；缺基数先澄清。零数量保留旧API的安全错误语义，并在执行前拒绝，不更新合法上下文。

## 16轮正式构建验收

| 轮次 | 用户问题 | 实际对象与结果 |
|---|---|---|
| 1 | 生产1片KQ-Z112。 | 标准分析34项，满足 |
| 2 | 那生产2片呢？ | 同产品同范围，不能满足 |
| 3 | 查询演示产品。 | 切换DEMO-PMC-01，产品概览 |
| 4 | 看看它的BOM。 | Demo已发布BOM，不显示旧34项 |
| 5 | 生产50台可以吗？ | Demo满足 |
| 6 | 那生产100台呢？ | Demo缺料 |
| 7 | 为什么不行？ | 复用第6轮100台Evidence，无重复计算 |
| 8 | 最多可以生产多少台？ | Demo理论最大75台 |
| 9 | 回到KQ-Z112。 | 新绑定34项标准范围，不带Demo数量 |
| 10 | 生产1件。 | 正式单位片，34项满足 |
| 11 | 查询BHX3588M。 | 切换KQ-BHX3588M，91项概览 |
| 12 | 生产10片呢？ | 91项真实需求核对，无记录仍未知，不批准完整生产 |
| 13 | 有哪些产品？ | 三产品目录，活动产品不改变，无旧产能卡片 |
| 14 | 看看演示产品。 | 切换Demo，清除旧目标 |
| 15 | 生产0台。 | 正常拒绝，未执行Tool、不改合法上下文 |
| 16 | 那生产75台呢？ | Demo实际计算满足 |

每轮浏览器读取真实HTTP响应，检查产品、范围、版本、数量、Tool/Evidence及页面；未使用固定回答。恢复原16轮历史后，活动产品来自最新服务端绑定。窄窗口390像素无整页横向溢出。

另外验证：空白目录刷新、仅企业目录序号、迟到旧响应、跨产品历史选择、继续分析历史产品、相对数量有/无基数、两个账号与纯合成Trial隔离。

## 数据和安全边界

- 标准范围34项最大1片、完整66项、另一产品完整91项均不改；可选数量模拟34项最大2片不改。
- Demo50台满足、75台边界、76/100台不足，4项采购建议及合成总成本1560.00保持不变。
- 企业SQLite、原始Excel、确认文件和两个私有数据版本的校验值验收前后一致。
- 真实服务验收强制禁用模型出站；Python全量测试也阻断真实模型调用。
- 授权工作台和Trial静态包均无源映射，对167项私有标识对照零命中。
- 未修改BOM/MRP/采购/生产核心计算Service、LangGraph、企业事实模型或业务数据。

## 修改文件

### 后端解析、绑定与展示

新增：

- agents/product_resolver.py
- agents/query_presentation.py

修改：

- agents/enterprise_book_queries.py
- agents/orchestrator.py
- agents/planner.py
- agents/reviewer_catalog_queries.py
- agents/slim_review_queries.py
- api/review_app.py
- api/routes/agent.py
- api/schemas/agent.py
- api/trial_app.py
- services/demo_scenario_agent_service.py
- services/persistent_agent_service.py
- services/reviewer_agent_service.py

### 前端

以下路径位于pmc-agent-frontend-main/frontend/：

- review/ReviewApp.vue
- review/useReviewAgent.ts
- src/components/QueryComposer.vue
- src/components/ResultPanel.vue
- src/components/SummaryCards.vue
- src/composables/useAgent.ts
- src/data/model.ts
- src/services/apiClient.ts
- src/services/responseAdapter.ts
- src/views/WorkspaceView.vue
- trial/TrialApp.vue
- trial/useTrialAgent.ts

### 测试与本机验收入口

新增：

- tests/test_product_context_regression.py
- pmc-agent-frontend-main/frontend/tests/product-context.spec.ts
- pmc-agent-frontend-main/frontend/review-tests/product-context.spec.ts

修改：

- deploy/review/verify.ps1
- scripts/verify_reviewer_workstation_local.py
- pmc-agent-frontend-main/frontend/review-tests/review.spec.ts
- pmc-agent-frontend-main/frontend/tests/agent-contract.spec.ts
- pmc-agent-frontend-main/frontend/tests/book-observation.spec.ts
- pmc-agent-frontend-main/frontend/tests/product-presentation.spec.ts
- pmc-agent-frontend-main/frontend/tests/quantity-review.spec.ts
- pmc-agent-frontend-main/frontend/tests/slim-review.spec.ts
- pmc-agent-frontend-main/frontend/trial-tests/trial.spec.ts
- pmc-agent-frontend-main/frontend/workstation-tests/default.spec.ts

旧测试没有删除或跳过。相关展示断言按本轮按意图展示要求更新，原始Tool数据仍校验；新增测试固定覆盖数量类型、产品绑定、Evidence复用和真实跨产品请求。

### 文档

- README.md
- docs/reviewer_remote_guide.md
- 本报告

## 运行与Git

正式构建验收地址为http://127.0.0.1:8090，受认证保护，后端8020；独立Trial验收8010/8080已停止。本地开发链另用临时8012/5173验证并正常停止，不宣称原8000进程已加载最新代码。

HEAD保留95a526ba3894c8f9effa09ea12b4646ab1a93cb7，分支feat/new-frontend-integration。暂存区为空；未commit、push、重写历史或开启公网。开始时已有的docs/git_checkpoint_plan_20261010.md与docs/review_git_checkpoint_plan.md未修改。

## 最终验证结果

- Python全量：1020 passed、1 skipped，另有45项subtest通过；跳过项为未配置PostgreSQL环境的条件集成测试。3项依赖测试警告不是失败。
- 产品上下文Python专项：22项通过。
- 前端全量：117项通过，使用本机Edge；Typecheck及本地Production Build通过。
- 授权工作台：14组正式构建真实HTTP/浏览器验收通过，含上述16轮、390像素布局、目录序号和迟到响应测试。
- 独立Trial：5组通过；临时本地开发链：2组通过；可选34项数量模拟仍为2片满足、3片不足。
- Review Build、Trial Build通过；167项私有标识扫描均0匹配，Source Map均0。
- git diff --check通过。36个tracked修改、8个untracked（其中2个为开始时已有文档），暂存0。
- 未发现本轮范围内尚未解决的P0/P1。若继续使用原开发8000/5173，需要另行重启至最新代码；本轮验收并未声称旧进程已更新。公网仍须用户明确授权启动。
