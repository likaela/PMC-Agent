# PMC-Agent 制造业智能计划助手

独立运行的 Vue 3 + TypeScript + Vite 前端。首页与分析工作台采用蓝白 Dashboard 风格；默认使用明确标注的固定演示数据。当前没有后端契约，不声称已完成真实 API 联调。

## 安装、启动与构建

需要 Node.js 22.12+（本机验证 Node 24.21.0 / npm 11.19.0）。

```bash
cd frontend
npm ci
npm run dev
```

默认地址：<http://127.0.0.1:5173/>。开发服务绑定本机回环地址；端口占用会明确报错，不偷偷切换。要在同一局域网真机访问时，自行启动 `npm run dev -- --host 0.0.0.0` 并使用电脑局域网 IP。本轮只完成浏览器窄屏验证，不声称完成真实手机/局域网验证。

```bash
npm run typecheck
npm run build
npm run preview
```

构建输出 `dist/`，生产预览默认 <http://127.0.0.1:4173/>。使用 Hash 路由，静态服务无需额外页面回退规则。部署到域名子路径时，按实际路径设置 Vite `base` 后重新构建。

工程采用 [Vue 官方推荐的 Vite 项目方式](https://vuejs.org/guide/quick-start.html)；命令行为依据 [Vite 官方文档](https://vite.dev/guide/)。实际版本以 package-lock.json 为准。

## 体验路径

1. 首页点击生产场景，完整示例问题会填入工作台；点击发送。
2. 查看 ABC-1000 / 1,000 台结论：主板需求 1,000 件、库存 800 件、缺口 200 件；电机和螺丝库存、缺口仍为“未提供”。
3. 展开结论或物料的来源，核对本次分析级引用、发布时间缺失与适用条件。
4. 选择“主板库存查询”，查看 800 件固定库存；点击历史助手消息切换对应结果。
5. 选择其他状态，体验错误、取消/重试，以及 mock/live 隔离。

## 10 个固定演示场景

| 场景 | 完整示例问题 | 数据性质 |
|---|---|---|
| 生产物料分析 / 部分数据 | 生产 1,000 台 ABC-1000，物料够吗？ | 项目资料示例 |
| 库存查询 | 查询主板库存 | 项目资料示例 |
| 独立采购建议 | 查看独立采购建议样例 | 项目资料独立样例；不等同于 ABC-1000 结论 |
| 所列物料齐套 | 查看所列物料齐套演示 | 人工构造 |
| 库存明确为 0 | 查看零库存演示 | 人工构造 |
| 无事实 | 查看无已发布事实演示 | 人工构造 |
| 条件冲突 | 查看条件冲突演示 | 人工构造 |
| 无法计算 | 查看无法计算演示 | 人工构造 |
| 请求错误 | 模拟请求失败与重试 | 人工构造；每次重试均失败，可切换其他场景恢复 |
| 映射错误 | 模拟响应映射失败 | 人工构造；不生成数字或结论 |

文本匹配只忽略空格、数字分隔逗号与句末问号/句号。型号、数量或其他文本不同即拒绝，不作为业务计算器，不继承追问条件。请求延迟 750ms 仅用于演示加载/取消，不代表后端性能。

## 模式与接入

复制 `.env.example` 为 `.env.local`，设置 `VITE_DATA_MODE=mock|live` 和未来的 `VITE_API_BASE_URL`。默认 mock。页头模式切换只影响当前页面，清空旧对话/结果并中止在途请求。

接入点：`src/services/apiClient.ts`、`src/services/responseAdapter.ts`、`src/composables/useAgent.ts`。目前 live 明确返回“接口尚未配置”；不会猜测请求体、调用模型服务或回退 mock。详见 [api-mapping.md](docs/api-mapping.md)。

## 文件清单

- `src/App.vue`、`src/styles.css`：应用壳、导航、帮助、数据模式、视觉 tokens 与响应式样式。
- `src/views/HomeView.vue`、`WorkspaceView.vue`：首页与分析工作台。
- `src/components/`：Icon、StatusBadge、SummaryCards、MessageList、QueryComposer、ResultPanel、MaterialTable、SourceDetails。
- `src/data/model.ts`、`fixtures.ts`：前端展示模型与集中固定场景。
- `src/services/`：演示服务、真实请求接入框架、待实现的真实响应适配器。
- `src/composables/useAgent.ts`：会话状态、请求序号、AbortController、历史结果绑定和模式隔离。
- `src/main.ts`、`public/favicon.svg`、`index.html`：入口、路由和图标。
- `package.json`、`package-lock.json`、`tsconfig.json`、`vite.config.ts`、`.env.example`、`.gitignore`：可复现的工程配置。
- `playwright.config.ts`、`tests/workflows.spec.ts`：16 项浏览器自动回归定义。
- `docs/design.md`、`docs/api-mapping.md`、`docs/verification.md`：设计、接入与实际验证范围。

本轮从空目录新建；无已有源码、用户修改或 Git 历史可保留。全部工程改动在 frontend/；未创建提交、推送、部署或修改后端。交付 ZIP 和关键截图另存于项目 outputs/。

## 自动回归

```bash
npx playwright install chromium
npm run test:e2e
```

已安装 Chrome 的环境可用 `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`。本轮此命令在浏览器启动阶段被当前 macOS 沙箱限制（SIGABRT / EPERM），16 项用例没有运行到页面断言；不能算通过。已使用 Codex 内置浏览器完成场景实测及五种宽度检查，详见验证记录。输入法组合事件的自动用例尚未执行；真实中文 IME 待实机核验。

对话只保存在内存，刷新清空。不存储用户问题，不上传演示数据，不使用外部字体或图片网络服务。
