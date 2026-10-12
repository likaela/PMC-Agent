# 评审候选版本：Git 检查点与公开边界

本轮起点：`feat/new-frontend-integration` / `185a642`，38项tracked修改、52项untracked文件，暂存区为空。下面精确盘点这90个文件。37275fc、9982a05、185a642保持不变。本轮只更新说明和私有验收记录，不暂存、不提交、不推送、不重写历史。

**工作区可以验收，不代表HEAD或任意中间提交可以复现。** 本计划是依赖拆分方案，不是已经建立的七个提交。公开仓库需另行处理源码及历史中的企业标识；ignore不等于已脱敏。

## 提交顺序和依赖

| 批次 | 建议message | 依赖 |
| --- | --- | --- |
| A 企业业务确认 | feat(facts): audit published BOM business confirmations | 现有三个核心提交 |
| B 自然语言和数量上下文回归 | fix(agent): stabilize catalog dialogue and task context | A（确认读取、测试fixture） |
| C 真实Excel库存与数量核对 | feat(review): compare source-confirmed inventory with BOM demand | A、B；不得遗漏私有出站禁用绑定 |
| D 前端展示适配 | fix(frontend): synchronize selected responses and inventory semantics | A、B、C；只适配API，不计算 |
| E 隔离评审推演 | feat(review): isolate versioned filtered review scenarios | C、D；API枚举、路由与UI需同批 |
| F 受控远程合成试用 | feat(trial): isolate authenticated synthetic-only trial | A至E；共用最终API schema，但拒绝私有场景 |
| G 公开交付文档与依赖 | docs(release): document reproducible reviewer delivery | 上述代码检查点通过后，文档完成公开审查 |

先纳入.gitignore的私有保护hunk，再进行A（可单独形成chore保护提交，也可随A）。各批提交前从暂存快照构造隔离源码运行测试；不使用脏工作区的全量通过证明中间提交可用。

## 全部tracked修改：38项

T代表tracked。下列路径从仓库根目录计算。所有路径完整列出；暂存不能整目录。

| 文件 | 批次、准确变更范围 |
| --- | --- |
| .gitignore | A前置：私有评委/确认/精简文档忽略；F：.runtime、trial local设置。只提交规则，不提交被忽略数据 |
| README.md | G：安装、迁移提示、冻结范围、历史恢复、测试命令；旧企业示例须脱敏或取得公开授权 |
| agents/business_answer.py | A：父项/子料单位区分、BOM/业务日期呈现；B：visible_warnings、结构查询去无关价格提示 |
| agents/business_formatter.py | B：缺少可靠价格的成本拒答；不改事实 |
| agents/business_language.py | A：normalize_business_dates、production_unit、confirmed_context_requested；B：conversational、product_discovery同义句、intent_override、price_requested |
| agents/context_resolver.py | A：确认读取、显式情境绑定、用户日期优先、日期作用域、单位核验、remember；无全局日期默认 |
| agents/orchestrator.py | A：resolve接context、确认Evidence、父单位warning、remember/evidence_is_current；B：普通交流、数量引导、目录/缺参、成本拒答、失败对象与重试保护；详见共享hunk表 |
| agents/planner.py | A：显式确认情境、确认日期/单位追问；B：conversation schema白名单、目录发现、显式对象切换、新生产任务数量重置；re仅引入一次 |
| api/routes/agent.py | E：_persistent_service的完整评审推演和两个精简场景分支 |
| api/schemas/agent.py | E：ScenarioId新增三个私有场景，与路由和前端类型同批 |
| config.py | F：试用不加载.env、get_llm/status禁止出站；不改本地企业配置 |
| pmc-agent-frontend-main/frontend/src/App.vue | D：冻结能力说明；E：三个私有场景选项/标签；F：trialMode import、固定合成空间、远程横幅和选项隐藏 |
| pmc-agent-frontend-main/frontend/src/components/MaterialTable.vue | D：账面/实际数量、未知/零、缺口、记录和状态语义；E：slimReview单耗列/精简记录列 |
| pmc-agent-frontend-main/frontend/src/components/MessageList.vue | D：普通交流“回复”而非“结果” |
| pmc-agent-frontend-main/frontend/src/components/ResultPanel.vue | D：当前/历史选中同步、普通交流空状态，不把旧结果冒充本次 |
| pmc-agent-frontend-main/frontend/src/components/SourceDetails.vue | E：精简模型来源标签和真实/合成范围提示 |
| pmc-agent-frontend-main/frontend/src/components/SummaryCards.vue | E：真实子集/合成精简/原Demo区分 |
| pmc-agent-frontend-main/frontend/src/composables/useAgent.ts | D：交流结果隔离、新消息和恢复携带user_query给adapter；E：私有场景切换提示；F：trial初始化/reset/setScenario强制固定合成 |
| pmc-agent-frontend-main/frontend/src/data/model.ts | D：conversation/bookObservation/quantityReview/validationError及账面记录字段、来源类型；E：ScenarioId新增、slimReview |
| pmc-agent-frontend-main/frontend/src/services/apiClient.ts | F：同源“/”base URL配置；错误不返回mock |
| pmc-agent-frontend-main/frontend/src/services/responseAdapter.ts | D：无关价格展示筛除、数量校验空结果、账面/实际库存映射及I/O失败保留需求；E：场景白名单、合成来源识别、slim_review指标；详见hunk表 |
| pmc-agent-frontend-main/frontend/src/services/sessionStorage.ts | E：只认可明确场景白名单；刷新不自动进入私有/Demo场景 |
| pmc-agent-frontend-main/frontend/src/styles.css | D：移动端选择框宽度，不改计算 |
| pmc-agent-frontend-main/frontend/src/views/HomeView.vue | D：只宣传当前可用企业查询及合成Demo能力 |
| pmc-agent-frontend-main/frontend/src/views/WorkspaceView.vue | D：企业说明；E：精简和旧评审推演快捷入口 |
| pmc-agent-frontend-main/frontend/vite.config.ts | F：专用生产构建输出位置 |
| repositories/agent_context_repository.py | A：published_business_fields、confirmed_analysis_context、requested_analysis_context、evidence_is_current；已有structure_evidence不是新增重写 |
| repositories/fact_query_repository.py | A：确认审计来源、父项单位读取优先级 |
| repositories/fact_repository.py | A：正式父项单位优先、父/子完整性分离 |
| repositories/fact_store.py | F：trial禁止enterprise Store |
| services/fact_query_service.py | A：父/子单位完整性分离、确认来源附加 |
| services/persistent_agent_service.py | A：中文日期正规化与“片”解析；B：价格展示相关性；C：book_service构造/本地只读源绑定、模型禁用、book_queries和错误不回退其他事实源 |
| services/task_parser_service.py | A：数量解析识别“片”；B/C使用此基础，不重复拆两个相同regex |
| tests/test_business_answer_quality.py | B：结构查询无关价格不展示，Evidence完整性仍保留 |
| tests/test_enterprise_bom_catalog.py | A：011迁移预期 |
| tests/test_fact_layer_hardening.py | A：PostgreSQL迁移预期011 |
| tests/test_published_inventory_analysis.py | A：迁移预期011 |
| tests/test_published_purchase_planning.py | A：迁移预期011 |

## 全部untracked文件：52项

每一行列出实际完整路径（U）。前端不使用上述缩写。

| 文件 | 批次/处理 |
| --- | --- |
| agents/enterprise_book_queries.py | C，完整文件：真实源查询、合法数量、Evidence复用、错误上下文；不得漏出站禁用 |
| agents/slim_review_queries.py | E，完整文件：明确精简场景调用既有Tool、M/M+1及来源追问 |
| api/trial_app.py | F，完整文件：账号所有权、合成专用、CSRF/限流/安全错误 |
| deploy/examples/inventory_quantity_use.example.json | G，空配置示例非业务授权 |
| deploy/examples/inventory_units.example.json | G，空配置示例非真实确认 |
| deploy/examples/review_scenario.example.json | E或G，只有EXAMPLE identifier，不包含真实事实 |
| deploy/trial/Caddyfile | F，认证代理，仅loopback；不放真实hash/密码 |
| deploy/trial/build.ps1 | F，同源合成生产构建 |
| deploy/trial/settings.example.ps1 | F，只占位符；local私有副本禁提交 |
| docs/business_answer_contract.md | G，通用契约；历史表述应复核，与源码一致再提交 |
| docs/enterprise_interaction_enhancement.md | G，通用交互说明，审核后提交 |
| docs/git_checkpoint_plan_20261010.md | 旧遗留计划：不随功能批提交；本文件取代其执行用途，保留本地不删除 |
| docs/judge_demo_guide.md | G，公开仅合成产品指南 |
| docs/remote_trial.md | G，与F配套，公开前复核工具版本/本地副作用说明 |
| docs/review_environment_handoff.md | G，私有包/公共包分发和复现；不带企业数据 |
| docs/review_git_checkpoint_plan.md | G，当前计划；含企业场景标识等元数据，公开授权/脱敏前暂缓 |
| docs/review_quantity_comparison.md | G，通用来源限定和精简处理说明，场景标识需公开审查 |
| migrations/postgresql/011_published_bom_confirmations.sql | A，完整迁移 |
| migrations/sqlite/011_published_bom_confirmations.sql | A，完整迁移 |
| pmc-agent-frontend-main/frontend/playwright.trial.config.ts | F，真实合成生产验收配置 |
| pmc-agent-frontend-main/frontend/src/services/trialMode.ts | F，固定远程合成模式 |
| pmc-agent-frontend-main/frontend/tests/book-observation.spec.ts | D，C响应展示、null/Decimal/单位来源 |
| pmc-agent-frontend-main/frontend/tests/conversation-polish.spec.ts | D，普通交流、价格展示、当前/历史同步 |
| pmc-agent-frontend-main/frontend/tests/quantity-review.spec.ts | D/E分hunk：D为100→50→0→1、I/O失败和旧状态清理；E为旧完整评审推演测试 |
| pmc-agent-frontend-main/frontend/tests/same-origin.spec.ts | F，同源API、trial固定空间 |
| pmc-agent-frontend-main/frontend/tests/slim-review.spec.ts | E，精简适配、明确选择、50/51、恢复与企业隔离 |
| pmc-agent-frontend-main/frontend/trial-tests/trial.spec.ts | F，真实Caddy/后端/两用户 |
| repositories/book_inventory_repository.py | C，只读核验主工作表、去重复、原行审计 |
| repositories/inventory_unit_confirmation_repository.py | C，源hash/路径/表/产品限定，含实际数量授权模型 |
| repositories/published_bom_confirmation_repository.py | A，确认审计与事务 |
| requirements-dev.txt | G或A前置，pytest9/subtests依赖；只依赖清单 |
| scripts/confirm_published_bom_business_facts.py | A，显式确认入口；本轮不执行 |
| scripts/prepare_slim_review_dataset.py | E，参数化生成/先备份，只写私有处理层；本轮不执行 |
| scripts/run_remote_trial.py | F，独立进程/禁私有路径和外部网络 |
| scripts/verify_remote_trial_local.py | F，本地生产构建QA；不创建公网隧道 |
| services/book_inventory_service.py | C，需求先算、记录比对、未知不补0、原算法不重写 |
| services/published_bom_confirmation_service.py | A，确认schema/哈希/事务审计 |
| services/review_scenario_agent_service.py | E，旧完整BOM合成补充隔离；保留兼容，不当作四空间主演示 |
| services/slim_review_service.py | E，版本化筛选结果、复用需求计算、Decimal最大量，仅私有层 |
| services/slim_scenario_agent_service.py | E，场景+数据版本会话隔离 |
| tests/test_enterprise_book_analysis.py | C，真实调用链+合成源fixture |
| tests/test_enterprise_interaction_enhancement.py | B，问候/产品发现/友好缺参/Demo隔离 |
| tests/test_enterprise_regression_context.py | B，目录同义句/日期作用域/失效Evidence/失败重试；依赖A确认fixture |
| tests/test_inventory_unit_confirmation.py | C，单位限定、source hash、重复记录、未知、trial拒读 |
| tests/test_natural_conversation_polish.py | B，拼音/大小写/产品上下文/价格相关性 |
| tests/test_parent_unit_confirmation_acceptance.py | A，父/子单位完整性验收 |
| tests/test_published_bom_business_confirmation.py | A，011、审计、日期与单位 |
| tests/test_remote_trial.py | F，来源隔离/所有权/禁出站/重启/限流 |
| tests/test_review_quantity_regression.py | C，零/负数/整数规则、当前任务、需求保留和恢复 |
| tests/test_review_real_bom_simulation.py | E，旧完整BOM推演与企业隔离 |
| tests/test_slim_review_scenario.py | E，真实零不删、过滤原因、最大量、Evidence和原Demo保护 |
| tools/book_inventory_tools.py | C，既有服务的StructuredTool薄适配 |

## 共享hunk的拆分方法与依赖冲突

所有共享文件仅用`git add -p -- <单个精确路径>`；mixed hunk先`s`，不能拆则`e`。不整目录暂存，不使用`git add .`、`git add -A`或`-f`。

| 共享文件 | 先后边界/注意 |
| --- | --- |
| business_language.py | A只引入三个日期/单位/确认函数；B再引入问候/目录/价格函数。不要让A调用B未存在函数 |
| planner.py | A的confirmed_context_requested和单位/生效日期追问；B的conversation枚举/校验、产品切换、新任务quantity=None。共享re import属于先使用它的批次 |
| orchestrator.py | A：resolve(context)、business_context、parent_unit_missing、remember、_reuse中的evidence_is_current。B：last_query_failure与重试、conversation、价格拒答、缺参文案、_quantity_guidance及其调用。_quantity_guidance依赖A的published_business_fields，不能提前提交 |
| business_answer.py | A：单位/日期和parent_unit_missing；B：visible_warnings及去价格。incomplete_production若同hunk同时引入visible_warnings，A暂存版本先保留原warnings迭代，B再替换；不能让A引用不存在函数 |
| persistent_agent_service.py | A：parse_enterprise_query日期/片；B：visible_warnings/presentation；C：os/import、book_service构造、绑定、run分支和异常策略。C必须包括llm_status=private_local_only，否则可能外传私有Evidence |
| App.vue | D仅文案；E场景选项/标签；F再引入trialMode和v-if隔离。不能在E引用尚未随F提交的trialMode；需手工编辑暂存hunk |
| useAgent.ts | D result/restore/send适配；E场景notice；F trialMode import和初始化/reset强制。新import在F前不得落入D |
| model.ts | D账面/交流/校验字段与来源类型；E ScenarioId/slimReview |
| responseAdapter.ts | D价格过滤、quantity_validation、账面库存主体；E whitelist、slimReview指标、合成来源。source.kind的Excel/确认标签为D，synthetic_review识别为E。大hunk用e，不跨批 |
| MaterialTable.vue | D账面/实际数量和状态；E单耗/slimReview条件。不能将slimReview字段提前使用到D的暂存版本 |
| WorkspaceView.vue | D说明，E私有场景快捷按钮 |
| .gitignore | 私有禁止提交规则先落地；runtime/local相关规则随F或同前置保护提交 |

**两个实际拆分阻塞：**

1. `quantity-review.spec.ts`同时覆盖C数量和E旧完整BOM推演。D先暂存数量/失败UI测试hunk，E再暂存旧推演分支；若文件尚untracked，先建立只含D测试的暂存版本（intent-to-add后add-p），不能D整文件带E。
2. App和responseAdapter是相邻甚至同一个mixed hunk。不能简单按文件归类整文件提交，也不能只按现有行号自动切patch。需检查暂存后的TypeScript/导入依赖。

推荐每批检查：

```powershell
git diff --cached --name-only
git diff --cached
git diff --cached --check
```

然后按依赖组合运行A确认/迁移，B会话，C库存/数量，D前端，E推演，F试用测试；最终完整pytest+前端test/typecheck/build。不要在本轮执行这些暂存/提交动作。

## 禁止提交的私有数据与运行产物

- `data/raw/**`，包括原BOM、主库存、供应商/物料原文件。
- `data/facts/**`：企业SQLite、WAL/SHM、backups、不可变来源副本、私有确认。
- `data/normalized/**`：review_slim版本、原文件备份、新版34项集合、2项补充和旧版审计、真实HTTP响应、当前QA报告及源码测试副本。
- `.env`、`.runtime/**`、`deploy/trial/*.local.*`、真实代理密钥/密码hash、会话、日志、Caddy本机配置。
- `docs/judge_user_guide.md`、`docs/judge_test_cases.md`、`docs/kq_z112_slim_review.md`、企业审计/目录/确认/导入内部文档。
- node_modules、dist、测试报告、cache、pycache、pytest缓存和本地启动bat。
- 私有34项合成补充数据仍保存真实料号和真实BOM来源（评委响应为MAT替代编号），不是可公开的纯合成数据；它与DEMO-PMC-01性质不同。

公开可用的只有经审查的通用代码/schema、纯合成DEMO数据、无秘密的模板和指南。产品编码/文件名/源hash/统计若出现在源码或测试中，也需另行脱敏或取得授权；ignore不保护tracked历史。密钥值不在本报告输出。

## 当前验证与交付结论

### 公开源码与历史审计

本轮检查当前源码及全部62个本地可达提交（含缓存origin引用），没有把raw、企业DB、.env或私有版本数据加入index；未发现符合扫描规则的真实密钥token。该扫描不能替代人工秘密审查，也没有联网刷新origin引用。

- 已有企业标识和真实格式物料号：例如`repositories/data_source.py:20`、`import_mappings/3588m_costing_v1.json:3`、`docs/real_data_mapping.md:5`及多份旧测试/旧前端文件。产品编码、原文件名、内部覆盖统计需授权或脱敏。
- 已跟踪本机私有路径：`docs/项目交接文档2.md:168`。通用的“E:/C:不写死路径”说明不是实际私有路径。
- 54个硬编码SHA候选全部来自`pmc-agent-frontend-main/outputs/manifest.json`的前端归档/文件校验，不是企业来源SHA；不可把所有64位字符串误判为企业数据。当前查询响应/私有版本内的企业SHA仍属于内部数据，不进入Git。
- 历史可达12个Excel对象位于示例/测试/模板路径，不能仅因扩展名判为企业原件。`scripts/create_sample_data.mjs`可证明当前基础样例来源是人工构造；未对每个历史二进制对象做逐单元格鉴定，公开历史前仍须确认。可达历史未发现`data/raw/**`、`data/facts/**`、`.env`对应文件对象。
- 缓存的origin历史已含企业元数据，如`cb14d5b`、`bb76410`、`d7f1d72`。**修改当前文件无法清除这些历史**；本轮不filter/rebase/force-push。
- 专用合成production bundle仍保留私有场景/产品字符串（虽然UI隐藏且API拒绝）。页面不显示不是源码脱敏；公网发布前需另行批准这些标识公开或准备无私有标识的合成构建。不靠隐藏选项宣称不泄露。

结论：授权本地候选可冻结；当前源码/历史不宜直接当作已脱敏的公开仓库。公共文档只介绍DEMO-PMC-01，不能解决代码或历史泄露；公开发布另行授权处理，不借本轮重构。

- 脏工作区：929 passed、1 skipped；前端106 passed，typecheck/build通过。
- 不含raw、企业库、私有确认和.env的源码副本：926 passed、4 skipped；复用当前venv，并非新机器依赖全新安装验证。
- 四空间开发/生产构建分别55次HTTP、53次浏览器查询与4次恢复（合计110／106／8）通过；受控合成正式构建另3项浏览器测试通过。
- 未建立上述提交，clone当前HEAD无法得到38+52项修复；授权私有包也必须单独交付并校验来源。
- 全部真实企业文件和数据集保持本地。公网只允许专用trial入口，不能给8000企业服务加隧道。
