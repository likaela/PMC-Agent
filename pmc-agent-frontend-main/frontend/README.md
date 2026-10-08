# PMC-Agent v1.14.1 — 新前端 Agent 客户端

保留 Vue 3 + TypeScript + Vite 的首页、对话工作台、结果卡片、物料表格和来源详情。在线模式通过现有后端 API 查询 published facts；前端不计算 BOM、库存、缺口、产能或采购量，也不调用 LLM。

## 安装与 Windows 启动

在本目录执行（Node.js 22.12+）：

```powershell
npm install
npm run dev
```

这是主项目当前比赛展示入口；根目录 `frontend/` 为 legacy，不是本目录的依赖。
默认在线 API 地址为 `http://127.0.0.1:8000`，无需 `.env.local` 也可启动。
若需要自定义配置，先执行 `Copy-Item .env.example .env.local`，再修改：

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000
```

后端须按主项目已有启动说明另行启动并准备好事实库；本前端不执行后端迁移或导入。前端地址为 http://127.0.0.1:5173，严格使用该端口。预览默认 4173，或部署到其他域名时，应由后端管理员配置对应 CORS origin。VITE_* 是浏览器公开配置，禁止放入 API Key。

## 在线企业事实与独立 Demo

- 企业事实：页头选择“在线 Agent / 企业事实”，自然语言查询库存、批次、BOM、在途、生产能力和采购建议。缺版本、生效日、开工日等条件时继续按回答补充，不默认猜测。
- 独立 Demo：主动选择“在线 Agent / 合成 Demo”，或展开首页“体验隔离 Demo”后选择场景。使用后端 `demo_scenario_50_vs_100`，产品 `DEMO-PMC-01 / V01`；不是 KQ-Z112 的真实企业数据。环境变量及 URL 场景参数不再自动切入 Demo。
- 依次发送“生产50台DEMO-PMC-01”“生产100台DEMO-PMC-01”“采购建议”，结果全部来自后端。采购建议不等于物料到货，库存齐套不等于开工许可。
- “新建分析”清除当前浏览器会话指针和展示，进入空白企业模式：scenario_id / session_id / result 均为 null。首次发送创建企业会话，HTTP 请求保持原契约，不传空场景字段，不删除后端历史。

## 持久会话

客户端先创建 session，再调用统一 query，确保等待超时或刷新时仍可用已有 session 恢复服务端记录。浏览器只使用 sessionStorage，不读取 localStorage；仅保存会话指针和原数据空间，不缓存企业事实或问答正文。旧的 mock 模式偏好会被清理，不能改变 HTTP 调用链。

普通首次导航进入空白企业模式，不自动恢复旧会话或沿用旧 Demo 偏好。刷新企业会话恢复企业历史；即使上次主动选择过 Demo，刷新也先回到企业空间，Demo 历史仅在用户再次显式选择“合成 Demo”后尝试恢复。每次恢复核验接口外层及逐条回答的 session_id / scenario_id，错配时停止恢复并清理当前指针，绝不将 Demo 结果显示为企业事实。也可在对应空间点击“恢复会话”。本地指针按 API 地址及 scenario 隔离。

关闭标签页可能丢失浏览器指针，但不会删除后端记录。当前不提供跨设备会话列表、登录或鉴权。点击历史回答仅切换展示，不改写当前后端上下文。

## 禁止本地业务响应

应用已移除离线模式入口与本地响应调用分支。历史 fixtures.ts / mockService.ts 文件保留，但没有应用入口引用，不参与开发或生产构建。旧 VITE_DATA_MODE / VITE_SCENARIO_ID 不再决定运行模式。企业与显式选择的合成 Demo 都必须经过后端 HTTP API；API 超时、异常 JSON、网络或服务错误只显示错误，不回退到 mock。

## 接口与适配

- POST `/api/v1/agent/query`
- POST `/api/v1/agent/sessions`
- GET `/api/v1/agent/sessions/{session_id}`（分页恢复）

请求只发送 message、session_id、scenario_id、persist_session；不混入旧 workflow_id / fact_session_id。响应通过运行时验证，再按查询类型映射展示。Decimal 字符串不转换 Number，null 不补 0；没有结构化依据的卡片不从 answer 填充。详见 [API 映射](docs/api-mapping.md)。

## 测试与构建

```powershell
npm run typecheck
npm run build
# 已安装 Google Chrome 的 Windows 环境
$env:PLAYWRIGHT_CHANNEL='chrome'
npm test
```

没有 Chrome 时可使用已安装的 Edge（PLAYWRIGHT_CHANNEL=msedge），或自行准备 Playwright Chromium。测试服务使用 5173，需先停止手动启动的 Vite。测试网络全部用测试专用 HTTP 响应夹具拦截，不连接企业数据库或 DeepSeek；应用中没有这类拦截器。原离线 UI 回归改为 HTTP 驱动，覆盖来源、会话恢复、旧 mock 偏好清理、错误不回退、数据隔离及 unknown/zero 区分。npm run test:e2e 与 npm test 等价。

## 当前限制

- 前端回归采用符合后端契约的 mock HTTP 响应；独立 Demo 已完成本机真实 HTTP 联调（50/100 台、采购、刷新恢复），不等同于公开部署验收。
- API 是一次性 JSON 响应，没有 SSE 阶段流；页面只展示等待状态，不伪造执行过程。
- 停止等待不会取消服务端计算。超时/取消后优先恢复历史，避免盲目重复发送；当前没有服务器级幂等取消协议。
- 企业事实持久路径与旧 pmc_analysis 响应不同；旧路径仅保留回答文本，不将未知 report 字段猜测映射为卡片。
- 采购缺价格、单位或约束时保持未知，不能把部分金额当完整成本。
