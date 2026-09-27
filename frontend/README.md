# PMC-Agent Vue Dashboard

该界面只展示 FastAPI 的确定性 PMC 工作流结果，不在浏览器中计算 BOM、缺料、齐套率、风险、采购量或生产决策。

## 配置与启动

1. 在项目根目录启动后端，并明确允许 Vite 开发来源：

   ```powershell
   $env:PMC_ALLOWED_ORIGINS="http://localhost:5173"
   .\venv\Scripts\uvicorn.exe api.app:app --reload
   ```

2. 复制环境变量示例并按需修改 API 地址：

   ```powershell
   Copy-Item .env.example .env.local
   ```

3. 在 `frontend/` 目录安装并启动：

   ```bash
   npm install
   npm run dev
   ```

默认访问地址为 `http://localhost:5173`。

## 演示流程

输入 `KQ-Z112`、`V01`、`1` 并开始分析。页面将显示后端返回的 `blocked`、8 项阻塞物料和待补采购参数。补充一个或多个物料的明确参数后提交，后端从暂停的 LangGraph 工作流恢复；页面显示最新 API 响应。
