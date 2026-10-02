# PMC-Agent 当前前端启动入口

## 目录与职责

| 目录 | 定位 | 默认启动 |
| --- | --- | --- |
| `pmc-agent-frontend-main/frontend/` | 当前比赛展示入口、真实统一 Agent API 客户端 | 是 |
| `frontend/` | legacy：原 Dashboard / Chat，保留兼容回归 | 否 |
| `pmc-agent-frontend-main/outputs/` | 历史交付资料与副本 | 否 |

新前端不依赖旧前端代码，不复制两份工程。只维护实际运行目录。

## Windows CMD

在项目根目录打开两个终端。后端方式不变：

```bat
call venv\Scripts\activate.bat
python -m uvicorn api.app:app --reload
```

前端：

```bat
cd /d "pmc-agent-frontend-main\frontend"
npm install
npm run dev
```

也可分别双击根目录 `start-backend.bat`、`start-frontend.bat`。
脚本用 `%~dp0` 定位根目录，支持路径含空格；只检查依赖，不自动安装。
这两个脚本在当前 `.gitignore` 中属于本地文件；文档中的手动命令不依赖脚本是否随仓库分发。

## PowerShell / Bash

在项目根目录运行：

```text
cd pmc-agent-frontend-main/frontend
npm install
npm run dev
```

后端继续使用原环境中的 `python -m uvicorn api.app:app --reload`。
没有新增或更改后端启动脚本，也没有新增 sh 部署体系。

## 地址与环境配置

- Node.js：22.12 或更高版本。
- 前端：`http://127.0.0.1:5173`；Vite 使用 strictPort，端口占用时明确失败。
- 后端：`http://127.0.0.1:8000`；Swagger `/docs`。
- 默认 `VITE_API_BASE_URL=http://127.0.0.1:8000`；新前端无需旧前端 `.env`。
- 自定义地址：在新前端目录复制 `.env.example` 为 `.env.local`，修改后重启 Vite。
- `VITE_DATA_MODE=live` 为在线模式；显式 `mock` 保留原离线逻辑，不作为网络失败 fallback。
- `VITE_SCENARIO_ID=demo_scenario_50_vs_100` 可预选独立合成 Demo；也可在页面选择“合成 Demo”。
- 已保存的浏览器模式/数据空间选择优先于初始环境配置；需要时在页头重新选择“在线 Agent / 合成 Demo”。
- 后端根目录 `.env` 与前端 `.env.local` 各自独立。`VITE_*` 公开可见，不能包含密钥。
- 当前后端 CORS 示例允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`；使用其他 origin 需按已有后端配置说明确认，不自动放行。

## 首次切换与验证

1. 若旧前端正运行，在其终端按 Ctrl+C 正常停止；不要仅打开另一个 5173 页面。
2. 初次进入新目录执行 `npm install`。已有完整依赖时无需重复安装。
3. 启动后端和新前端，打开 `http://127.0.0.1:5173`，应看到首页和“分析工作台”，而非旧 Chat/Dashboard。
4. 选择“在线 Agent / 合成 Demo”，依次发送“生产50台DEMO-PMC-01”“生产100台DEMO-PMC-01”“采购建议”。
5. 预期：50 台齐套，100 台 4 项缺料，有采购建议；刷新恢复同一会话。齐套不等于开工许可，建议不等于已到货。
6. 如需 legacy 回归，先停止新前端，再手动进入根目录 `frontend/` 启动。根目录脚本不再启动 legacy。

本次仅切换启动入口与公开配置，未改变业务接口、事实层、Demo 数据或 mock 计算/匹配逻辑。
