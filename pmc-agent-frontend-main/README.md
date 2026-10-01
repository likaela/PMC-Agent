# PMC-Agent 制造业智能计划助手

Vue 3 + TypeScript + Vite 前端，包含首页、智能分析工作台、物料明细、来源展示及桌面/手机适配。

默认使用明确标注的固定演示数据。真实后端契约尚未交接；live 模式显示“接口尚未配置”，不会自动返回演示结果。

## 安装与启动

需要 Node.js 22.12+。

```bash
git clone https://github.com/Aaron-zhu-tech/pmc-agent-frontend.git
cd pmc-agent-frontend/frontend
npm ci
npm run dev
```

打开终端打印的地址，默认是 http://127.0.0.1:5173/。如果已经启动同一工程，先在其终端按 Ctrl+C，或使用 `npm run dev -- --port 5174` 启动另一个实例。

```bash
npm run build
npm run preview
```

## 仓库内容

- `frontend/`：维护和运行的完整前端工程；服务接入框架、固定 fixtures、设计与验证文档。
- `outputs/`：交付 ZIP、截图、文件清单、哈希与历史交付副本。
- 根目录的项目需求 MD/DOCX 与协作说明：随工程保留的原始项目资料。

依赖目录、构建缓存、测试运行临时文件、Office 锁文件和本地环境配置由 `.gitignore` 排除。`.env.example` 保留用于接入配置。

## 已验证范围

类型检查与生产构建通过。已通过内置浏览器检查 10 个演示场景、来源、历史切换、取消/重试与 1440、1280、1024、390、320 像素布局。

CLI 自动浏览器测试在当前环境的浏览器启动阶段受限，16 项测试没有执行到页面断言；真实后端与实际手机测试尚未完成。详细范围见 [验证记录](frontend/docs/verification.md)。

## 文档

- [页面与组件设计](frontend/docs/design.md)
- [完整运行说明与演示场景](frontend/README.md)
- [真实接口接入与待确认字段](frontend/docs/api-mapping.md)
- [桌面迁移与端口处理](frontend/docs/desktop-migration.md)

## 预览截图

![桌面分析工作台](outputs/screenshots/desktop-analysis.png)

![手机分析结果](outputs/screenshots/mobile-analysis.png)
