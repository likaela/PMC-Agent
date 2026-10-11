# 评审候选版本：环境交接与数据边界

本文只说明已实现能力与初始化步骤，不包含企业料号、源文件标识、真实校验值或密钥。不代表公开企业源码历史的授权。

## 冻结范围

授权企业本地版：产品目录、BOM与物料组成、主库存Excel记录、BOM需求量、数量展示、匹配覆盖、来源及连续追问。用户新确认当前来源的实际库存口径后，支持基础数量比较及已知缺口；不代表正式工单放行，不生成真实正式采购计划。详见 `review_quantity_comparison.md`。

隔离合成版：DEMO-PMC-01 / V01，50台齐套、100台四项缺料、理论最大75台、合成采购建议、历史恢复。齐套不等于设备/质量/交付放行，采购建议不表示到货。

授权私有精简评审包另包含两个明确选择的版本化空间：可核验真实子集与合成补充子集。两者均不能作为完整企业产品的生产能力，不能放进公网包。界面选择后才恢复该空间历史，刷新先回企业空间。早期完整BOM合成补充场景仅保留兼容，不替代本次精简评审流程。

## 两种交接包

| 包 | 内容 | 不包含 |
| --- | --- | --- |
| 源码/合成包 | 经审查的代码、migrations、合成JSON、依赖锁文件、公开说明 | raw、企业库、私有确认、密钥、会话与日志 |
| 授权企业附加包 | 管理员交付的数据库一致性备份、获授权的Excel与源文件私有副本、确认审计材料、本机私有配置 | 不通过公开Git或前端目录分发 |

代码按依赖顺序建立本地检查点，组员须按交接报告中确定的最终 commit 获取源码。源码提交不包括私有数据包，也不构成公开授权。公开 Git 前另行审查历史里的企业标识；.gitignore 不能清除历史。

## 新电脑（Windows PowerShell，项目根目录）

使用经验证的 Python 3.12 系列，Node >=22.12。当前验证环境为 Python 3.12.10、Node 24.21.0。不要复制旧电脑的 venv/node_modules。

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
Push-Location pmc-agent-frontend-main/frontend
try { npm ci } finally { Pop-Location }
```

`requirements-dev.txt` 在应用依赖之外锁定 pytest；原 README 的 unittest 发现方式不能覆盖所有 pytest 函数测试。前端完整测试还需要 Playwright 浏览器；可安装 Chromium，或已安装 Microsoft Edge 时设置 `$env:PLAYWRIGHT_CHANNEL='msedge'`。执行 `npm test` 前释放5173，测试配置默认拒绝复用已有服务；不要因此结束他人的进程。

当前SQLite回归venv没有安装PostgreSQL驱动；`requirements.txt`仍声明psycopg[binary]。离线 `pip --dry-run --no-index` 因缺少该安装包不能完成，不能据此承诺离线安装。新电脑需联网安装或管理员预先准备完整wheel包；没有真实PostgreSQL测试URL时仍只证明SQLite路径。不要为了部署临时更换依赖版本。

普通本地空库只在新环境、明确数据库目标后初始化：

```powershell
.\venv\Scripts\python.exe -c "import config; from repositories.fact_store import create_fact_store; print(create_fact_store().migrate())"
.\venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

另一终端进入 `pmc-agent-frontend-main/frontend`，执行 `npm run dev -- --port 5173 --strictPort`。默认API地址为 `http://127.0.0.1:8000`；覆盖地址仅在该前端 `.env.local` 设置 `VITE_API_BASE_URL`，重启Vite。禁止将任何密钥放入 VITE_*。

迁移只创建schema，不自动导入企业数据。空企业库的目录/查询应明确无事实；不会自动切换到合成答案。用户显式选择“合成Demo”后，既有隔离场景自行初始化独立运行库，无需企业Excel或企业确认。

本地启动bat、venv、便携Caddy、.env和私有确认被忽略，不随clone交付。使用文档命令；无需依赖本机 E:/C: 绝对路径。

## 授权企业迁移：不重发布已有BOM

1. 源电脑停止写入会话/事实的服务，使用 SQLite online backup 生成一致性备份（包含WAL），或完全停止后复制数据库及其所需文件；不要在线只复制主db而遗漏WAL。
2. 私下交付管理员批准的备份、源文件和确认证据。核对文件 SHA-256 与源电脑私有清单，做 `PRAGMA integrity_check`，核对 schema_migrations、已发布版本、行数和确认审计。历史会话也可能敏感，可使用另行批准的无历史交接包；本轮没有删除历史。
3. 默认恢复到 `data/facts/pmc_facts.db`，原来源放回相同项目相对路径。不覆盖已有目标数据库。当前来源是 `project://` 相对引用，换盘符不要求重发布BOM；数据内容校验值应不变。
4. 如需要使用非默认库存位置，管理员私下配置 `PMC_BOOK_INVENTORY_FILE`，并重新核验单位确认的 source_uri、原件 basename、SHA、sheet。不要将路径写进公开源码。自定义数据库不会自动获得私有Excel，需要显式路径绑定。
5. 库存单位确认还须单独迁移 `data/facts/confirmations/inventory_units.json`；BOM数据库确认与Excel库存单位确认不是同一存储。原文件不变、项目内相对路径不变时可沿用合法源绑定；内容/文件名/工作表变化必须重新人工确认，不自动继承。
6. 已有 published BOM 不要重复stage/publish。若没有获得数据库，只能由获授权管理员按既有 import_enterprise_boms 的审计→stage→validate→publish流程重建，不能用直接INSERT或模拟料替代企业事实。
7. 如历史来源是外部 `file://` 或绝对审计路径，保留其历史语义。当前账面入口可显式绑定新的读取位置；不要直接改历史 source_uri/确认ID，破坏证据指纹。无法通过来源验证时应暂停相关操作，另行设计受审计绑定，不假装已完成迁移。

不要复制旧电脑含密钥的.env。授权企业交接仍保持 `LLM_PROVIDER=` 空值；只有另行批准数据出站后才启用模型。当前账面入口绑定时会关闭企业模型调用，但缺失原件/未绑定该入口时不能依赖这一条件保护替代全局禁用配置。

当前数据库若已有011，不再重复应用。旧备份缺011时，先备份并经管理员批准运行上述迁移；API不替管理员自动迁移。业务发布日期、分析情境日期和库存业务日期不互相替代，也不自动成为新会话默认日期。

## 库存单位配置（必须私有）

安全空模板为 `deploy/examples/inventory_units.example.json`，内容仅 `confirmations: []`，不含任何业务确认。**不能以空模板覆盖已有私有文件，也不会自动加载模板。**

人工确认条目所需字段：

| 字段 | 规则 |
| --- | --- |
| source_uri | 当前获授权原件的项目相对路径，外部路径须显式绑定 |
| source_file | 原文件 basename 精确匹配 |
| content_sha256 | 对实际获授权文件重新计算，与来源清单核对；不使用示例hash |
| sheet_name | 当前已核验主库存工作表；不扩展到其他sheet |
| quantity_field | 当前适配契约为“库存” |
| unit | 业务人员明确确认的单位，不默认PCS/个/片 |
| confirmed_by / reason / user_statement | 真实确认人、依据及确认原文，仅私有保存 |
| recorded_at | 该确认记录的真实时间，包含时区；不是库存快照 |
| applies_to_existing_source_only | true，仅适用当前源 |

核对命令（结果也是私有资料，不粘贴到公开仓库）：

```powershell
Get-FileHash -LiteralPath '获授权原件的实际路径' -Algorithm SHA256
git check-ignore -v data/facts/confirmations/inventory_units.json
```

不存在确认文件或源绑定不匹配：原始数量仍可查询，库存单位保持未知，warnings明确单位尚未确认；不会填零或自动恢复旧单位。文件非法、重复确认或明确单位冲突：拒绝使用相应确认/返回安全错误，不吞掉异常制造成功。

单位确认不产生 available、reserved 或正式 snapshot，也不授权正式工单。新私有确认 `data/facts/confirmations/inventory_quantity_use.json` 单独授权当前来源的基础实际数量核对，须同单位文件一起迁移并重新验证来源绑定；缺失该规则时不会暗中启用实际库存比较。

私有推演配置 `data/facts/confirmations/review_scenario.json` 与 `.runtime/review_real_bom_simulation/` 同企业和完整合成Demo隔离。主动选择才启动，不用于公网试用。新环境没有私有配置时不能声称可运行真实BOM推演；公开示例不含真实产品。不要把这些私有文件加入Git。

## 版本化精简评审包恢复

管理员私下交付同一版本的以下文件，不能只复制单个JSON：

- `data/normalized/review_slim/<version>/verified.json`、`synthetic.json`；分别保存真实可核验集合与合成补充集合。
- 同目录的`excluded.json`、`synthetic_supplements.json`、`backup_manifest.json`及获授权备份，用于逐项追溯。即使合成补充文件也包含真实物料标识，不可公开。
- `data/facts/confirmations/review_slim.json`，两个明确场景标识映射到上述项目相对路径；不是前端常量或默认选项。
- 对应的企业事实库一致性备份、来源核验与单位/数量确认。版本JSON保留BOM来源，不能伪装成新Published Enterprise Facts。

恢复到同样相对目录后重验数据集文件SHA及备份清单，确认集合数、排除原因、单耗和补充量。不要更改JSON来追求成功结果，也不要在恢复时重新生成覆盖原版本。新版数据应另建版本，并另行验收。使用`scripts/prepare_slim_review_dataset.py`重建是受控数据准备操作，需管理员授权；本轮冻结不执行它。

会话库在`.runtime/<scenario>/<dataset_version>/sessions.db`。新环境可新建会话；如需原历史，获授权时单独迁移对应一致性会话备份。数据版本/hash不同的会话不能恢复到另一版本，不删除历史来绕过检查。顶栏主动选择场景；刷新默认先回企业，再主动选择原空间恢复。返回企业后完整BOM重新查询，不继承筛选集合。

没有私有配置/版本文件时，精简场景应显示请求错误或不可用，不回退到纯合成Demo或伪造企业计算。公开远程后端从API层拒绝这些场景；公开包不应附带配置、版本JSON及审计报告。

迁移时必须复制管理员批准的同版私有数据包、计算报告与映射，不得沿用历史版本的物料数或产量边界。每个版本独立会话，hash不同的旧会话明确失效后重新分析。另核验私有单位/数量确认缺失时不暗中授权数量比较，数据集缺失时明确拒绝、不切换其他Demo。这是本机路径迁移证明，不是新Windows机器的全新依赖安装证明。具体版本与企业统计仅在私有交接清单中记录。

## 远程合成试用

严格使用 `docs/remote_trial.md` 的专用启动器、试用构建、Caddy和每人独立账号；不将8000企业入口开放公网。生产前端以 `/` 作为API base，实际请求同源 `/api/v1/agent/...`，无需企业 .env。

Caddy便携工具不在Git。新电脑须单独准备已校验的Windows版本到文档指定路径；测试工具目前使用2.11.7路径。不要把下载成功当成SHA验收。cloudflared另行准备，经负责人确认后才创建隧道；本轮只验收本机代理。

专用进程不加载企业.env、禁读raw/facts、禁止模型出站；未知或越权会话均404。账号名和稳定代理密钥决定会话归属，重启须保持，轮换前明确历史失效范围。

## 回归与限制

```powershell
.\venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
Push-Location pmc-agent-frontend-main/frontend
try { npm test; npm run typecheck; npm run build } finally { Pop-Location }
git diff --check
```

企业HTTP验收应对只读备份承接临时会话、禁用外部模型，不能在原库创建测试历史。普通pytest验证使用合成夹具和临时数据库；未设置 `PMC_TEST_POSTGRESQL_URL` 时真实PostgreSQL集成测试明确跳过，不能宣称已在新PostgreSQL部署验证。

当前校验无私有文件的源码副本时复用了原电脑的venv依赖，不是一次全新联网pip/npm安装证明。新电脑仍需实际安装和端到端冒烟验证。单个拟议commit也必须在只含其父提交的隔离工作树验证，不能用全部脏工作区的测试结果冒充每个commit独立通过。

本次冻结重新验证：工作区929 passed、1 skipped、45 subtests；前端106 passed，typecheck/build成功。无raw、企业库、私有确认和.env的源码副本为926 passed、4 skipped、45 subtests：三个skip是原有私有核价BOM、私有库存与私有企业BOM预检，另一个是未配置PostgreSQL。没有增加skip或降低断言。该副本复用现有venv，未完成新机器全新pip/npm安装，不承诺离线依赖已齐备。

私有数据缺失的副本中，专用合成HTTP真实验证0/1/50/51/75/76/100台、采购、重启历史、两账号互读/续写拒绝及所有私有场景拒绝，模型出站尝试0。本机专用生产构建→Caddy→trial FastAPI另3项浏览器验收通过；未创建公网隧道，不能宣称公网HTTPS登录和实际隧道已验收。
