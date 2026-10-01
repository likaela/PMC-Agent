# 真实接口接入说明

当前没有后端仓库、schema 或可调用的真实响应。**已验证的后端字段映射：0 项。** 本轮只验证前端展示模型和固定 fixtures。前端模型不是后端真实 schema，不能据此要求后端改契约。

## 接入位置

| 文件 | 职责 | 本轮状态 |
|---|---|---|
| `src/data/model.ts` | `AgentQueryService`、`AgentResult` 展示模型、显式空值与错误类型 | 已实现 |
| `src/data/fixtures.ts` | 集中固定场景及 provenance | 已实现；不计算业务值 |
| `src/services/mockService.ts` | 完整示例匹配、固定延迟、演示错误 | 已实现 |
| `src/services/apiClient.ts` | `createLiveService(transport, adapter)`、取消、异常处理 | transport 等待真实契约；默认拒绝未配置请求 |
| `src/services/responseAdapter.ts` | 未知真实响应 → 展示模型 | 明确抛出未配置映射错误，等待真实样例 |
| `src/composables/useAgent.ts` | 绑定服务、会话页面状态、请求隔离 | 已实现；需在这里为 liveService 注入核验后的 transport/adapter |

`.env.example` 默认 `VITE_DATA_MODE=mock`，可设置为 `live`。`VITE_API_BASE_URL` 仅为接入配置入口；仅填写 URL 不会启用猜测的端点。配置变更后重启 Vite。页面顶部模式选择器可临时切换并清空对话，不写入持久存储，不改变环境配置。

真实请求失败必须保留真实错误，不自动切回 mock。前端不接触模型 API 或模型密钥。不要把任何密钥放进 `VITE_*`，它们会进入浏览器资源。

## 文档线索与待确认路径

| 文档线索 | 后端真实路径 | 前端展示模型 | 使用组件 / 空值处理 |
|---|---|---|---|
| POST `/api/v1/agent/query` | 待核验；当前未发起该请求 | `QueryInput.text` 是内部参数 | 请求体、HTTP 方法、认证、错误体待确认 |
| `intent` | 待确认枚举和路径 | 决定可显示的结果类型 | ResultPanel；未知枚举不得猜测业务语义 |
| `status` | 待确认枚举和语义 | `AgentResult.status` | 状态标签；HTTP 成功与业务受阻分开 |
| `answer` | 待确认类型和路径 | `answer` | MessageList / ResultPanel；按文本安全插值，不使用 v-html |
| `structured_data` | 所有嵌套字段均待确认 | product / quantity / materials / purchase | SummaryCards / MaterialTable；不可从回答提取数字补表 |
| `provenance` | 标识、引用层级和发布时间待确认 | sources / sourceIds | SourceDetails；缺版本、时间显示“未提供”；只有响应级依据时不伪造字段级引用 |
| `warnings` | 结构和级别待确认 | warnings | 结论旁可见列表，不静默丢弃 |

## 已验证的前端映射（仅演示）

| 固定 fixture | 页面验证结果 |
|---|---|
| ABC-1000 / 1,000 台，主板 1,000 / 800 / 200 件 | 任务卡与需求/库存/缺口列保持原值 |
| 电机 2,000 件、螺丝 8,000 件，available 与 shortage 为 null | 库存和缺口均显示“未提供”，未补 0 |
| `zero` 的 available=0 | 显示 0 件，仍具有明确库存记录状态 |
| `no-facts` 的 available=null、state=no-facts | 显示“暂无已发布数据”，与缺失字段区别 |
| 独立采购 200 / 100 / 300 | 只在 purchase fixture 展示，不嵌入生产分析 |
| 来源 version/publishedAt=null | 显示“未提供”，不以请求时间填充 |

## 组员需提供的最小资料

1. 后端仓库/分支或 OpenAPI、实际启动地址与方法路径。
2. 请求体字段、必填项、认证、CORS、是否支持会话/追问以及会话生命周期。
3. 至少一份脱敏成功响应和一份部分数据响应；另提供零库存、无事实、冲突、无法计算及 HTTP 错误样例。
4. intent/status 枚举；物料标识、需求、可用库存、缺口的精确嵌套路径、单位与空值约定。采购数量应由后端返回。
5. provenance 的引用粒度、记录 ID、版本、适用条件和发布时间；warnings 的实际结构。

拿到资料后：先对照真实响应编写 adapter 的运行时校验和单元测试，再实现 transport，注入 useAgent，开启 live，逐场景做真实联调。不实现前端 BOM 展开、单位换算、齐套、产能、缺口或采购计算。

若后端只有自然语言：只展示 answer、已提供的 warnings 和 sources，隐藏没有结构化依据的数字模块。部分结构无法映射时须保留已验证内容及可诊断提示，不能输出错误业务结论。

## 尚未启用

真实产能、多层 BOM、批次、自动排产、ERP、上传/发布事实、采购下单、会话记忆均未核实。首页只说明接入状态，无可误认为已实现的业务操作。
