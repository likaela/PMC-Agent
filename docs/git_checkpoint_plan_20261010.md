# Git 检查点建议（只读分类；不代表公开授权）

> 历史计划（22/16起点），已由 [当前评审冻结提交计划](review_git_checkpoint_plan.md) 的32/40完整清单取代。不要按本页旧清单直接暂存。

检查起点：22 tracked修改、16 untracked文件；暂存区为空。保留既有三个提交，不 amend/rebase/reset。
本文件仅列提交设计，不执行 add/commit/push。公开前仍需检查历史企业元数据。

## 1. 011 企业业务确认、单位、日期

新增整文件候选：
- migrations/sqlite/011_published_bom_confirmations.sql
- migrations/postgresql/011_published_bom_confirmations.sql
- repositories/published_bom_confirmation_repository.py
- services/published_bom_confirmation_service.py
- scripts/confirm_published_bom_business_facts.py
- tests/test_published_bom_business_confirmation.py
- tests/test_parent_unit_confirmation_acceptance.py

修改整文件候选：
- repositories/fact_repository.py
- repositories/fact_query_repository.py
- services/fact_query_service.py
- agents/context_resolver.py
- repositories/agent_context_repository.py
- services/task_parser_service.py
- tests/test_enterprise_bom_catalog.py
- tests/test_fact_layer_hardening.py
- tests/test_published_inventory_analysis.py
- tests/test_published_purchase_planning.py

共享文件仅选择011相关hunks：
- agents/business_language.py：normalize_business_dates、production_unit
- agents/planner.py：单位/生效日期追问读取当前BOM元数据
- agents/orchestrator.py：evidence_is_current、过期历史证据重核验
- agents/business_answer.py：parent_unit_missing、单位分离、人工确认日期表达；排除价格提示相关改动
- services/persistent_agent_service.py：中文日期与“片”参数解析；排除presentation/warnings过滤
- tests/test_business_answer_quality.py：仅对应单位/日期契约的断言

说明：核对共享文件依赖后用 git add -p；mixed hunk用s，不能拆时用e。不能为凑提交把整个共享文件暂存。
建议message：feat(facts): add audited BOM business confirmations and explicit unit/date context

## 2. 自然语言与产品上下文

- tests/test_natural_conversation_polish.py：整文件
- agents/business_language.py：拼音/大小写问候、目录/概览、显式物料查询、price_requested
- agents/planner.py：目录优先、显式切换、保护制造业编码；排除011元数据hunk
- agents/orchestrator.py：查询失败保留原上下文、参数不足时有证据的成本拒答；排除011水印
- agents/business_answer.py：visible_warnings、普通BOM取消价格提示、生产原因过滤无关价格
- agents/business_formatter.py：成本不足明确表达
- services/persistent_agent_service.py：公开warnings按问题相关性过滤、presentation标记
- tests/test_business_answer_quality.py：普通BOM不提示缺价，但保留completeness及防篡改断言

旧遗留依赖：conversation operation及白名单、普通问候分支、友好补参文案已经在工作区但未在HEAD。这些是本轮NIHAO修复的必要支架，不能留在工作区导致提交后无法运行。
可先单独提交该支架和 tests/test_enterprise_interaction_enhancement.py，或明确作为本组依赖纳入；不要混进011。
建议message：fix(agent): polish conversation routing and query-relevant business warnings

## 3. 前端回答/面板与价格展示

整文件候选（仅这次前端hunks，不混合后续远程试用修改）：
- pmc-agent-frontend-main/frontend/src/components/MessageList.vue
- pmc-agent-frontend-main/frontend/src/components/ResultPanel.vue
- pmc-agent-frontend-main/frontend/src/composables/useAgent.ts
- pmc-agent-frontend-main/frontend/src/data/model.ts
- pmc-agent-frontend-main/frontend/src/services/responseAdapter.ts
- pmc-agent-frontend-main/frontend/tests/conversation-polish.spec.ts

依赖第2组的conversation/presentation结构；旧响应兼容路径保留。
建议message：fix(ui): bind selected replies and hide irrelevant price notices

## 4. 旧遗留及需决定公开的文档

- tests/test_enterprise_interaction_enhancement.py：旧普通交流、产品发现、友好补参验收，可随第2组必要支架提交。
- docs/enterprise_interaction_enhancement.md：旧交互说明，先审查脱敏。
- docs/business_answer_contract.md：早期业务回答合同，不是011或本轮主要代码，单独文档提交。
- docs/enterprise_bom_structural_import.md：此前结构发布文档，含真实产品及日期示例，不能直接认定公开安全。
- docs/kq_z112_enterprise_import.md：含真实产品/源文件及内部统计，暂不提交。
- scripts/verify_bom_business_confirmation_http.py：011验收工具，但硬编码真实产品/统计；先改成授权私有配置或合成参数再决定公开，暂不纳入代码commit。

## 5. 私有及绝不提交

- docs/kq_z112_business_confirmation_checklist.md：完整真实料号、源文件、来源SHA和库存覆盖信息，不提交。
- data/raw/**、data/facts/**、data/normalized/**、.env、.runtime/**。
- 所有企业库/备份、人工确认原始Evidence、HTTP企业验收报告、日志、cache、dist、node_modules。
- local试用账号配置/密码哈希/代理密钥。

不要使用 git add .、-A、目录暂存或add -f。当前清单不等于源码历史已脱敏。

## 本轮远程试用另建第4代码检查点

api/trial_app.py、scripts/run_remote_trial.py、scripts/verify_remote_trial_local.py、deploy/trial/Caddyfile、deploy/trial/build.ps1、deploy/trial/settings.example.ps1、config.py试用开关、fact_store.py试用拒绝企业工厂、.gitignore私有运行目录。
前端App/useAgent/API client/Vite中的trialMode、同源和独立产物hunks，加trialMode.ts、same-origin.spec.ts、playwright.trial.config.ts、trial-tests/trial.spec.ts；tests/test_remote_trial.py、docs/remote_trial.md。
再次与第3组共享的useAgent只用patch暂存。所有新部署文件不含真实企业标识或凭证。

## 建议顺序与检查

011 → 旧必要会话支架（若独立）→ 自然语言 → 前端 → 受控远程试用 → 脱敏文档。
每组先检查 cached diff/name-only/check，再运行对应测试；最后全量pytest、npm test、typecheck、build。
工作区测试通过不等于各提交独立通过。提交前用独立工作树逐个验证父提交依赖，不能仅运行带未暂存改动的工作区冒充单提交验收。
未获用户确认，不执行暂存、提交、push，更不覆盖原三个核心提交。
