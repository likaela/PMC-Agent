# v1.14.1 后端契约适配

## 边界

仅修改新前端。本 API client 不连接模型 API，不访问数据库，不读取 Excel。所有业务数值来自 structured_data，answer 只作文本展示。

## 请求

queryAgent → POST `/api/v1/agent/query`：

```json
{
  "message": "生产50台DEMO-PMC-01",
  "session_id": "服务端会话标识",
  "scenario_id": "demo_scenario_50_vs_100",
  "persist_session": true
}
```

企业查询省略 scenario_id；不混用旧 workflow_id / fact_session_id / active_context。客户端先用 createSession 调用 POST `/api/v1/agent/sessions` 保存指针，再 query。首次 API 调用亦支持仅传 persist_session，由后端自动建会话。

getSession → GET `/api/v1/agent/sessions/{session_id}?after=0&limit=200`；Demo 查询和历史恢复均显式带 scenario_id。只恢复保存的 responses，不重新调用 Tool 计算历史。

## 模型与映射

BackendResponse 保留 intent、status、answer、structured_data、provenance、warnings 与会话标识。FrontendViewModel 是独立展示对象，附带原 BackendResponse，供恢复与可追溯核对。

| 查询类型                          | 后端已验证路径                                                                                                                                     | 展示                                                |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| inventory                         | structured_data.data.canonical_item / on_hand_qty / available_qty / reserved_qty / batch_count / location_count / query_snapshot_at                | 查询对象、独立库存字段、批次与时点                  |
| inventory_batches                 | structured_data.data.batches                                                                                                                       | 批次、库位、在库数量、收货时间、有效期、质量状态    |
| bom                               | structured_data.data.parent_item / revision / effective_from / lines                                                                               | 子件、qty_per、单位、行级来源；单位用量不当作总需求 |
| production_capacity               | structured_data.data.product / requested_quantity / theoretical_max_quantity / inventory_sufficient_for_requested / materials / limiting_materials | 齐套结果、缺口、理论最大数量、限制物料              |
| purchase_planning                 | structured_data.data.recommendations / total_purchase_cost / total_cost_currency                                                                   | 多项建议量、成本、供应商、交期、风险、缺失提示      |
| clarification / needs_input       | structured_data.query / missing_fields                                                                                                             | 保留已识别对象并提示补充；无依据不显示结果数值      |
| data_unavailable / item_not_found | status，及可能存在的部分 structured_data                                                                                                           | 无事实或数据不足提示，未知保持 null                 |
| 旧 pmc_analysis                   | 旧 ChatResponse 结构                                                                                                                               | 回答文本；不猜测为 published-fact 卡片              |

completeness 保留字段级结构，已知缺失字段以中文提示；未知枚举不推断业务含义。status=ok 只是查询成功，不是可生产。生产卡片只显示后端明确的库存齐套 bool；不据此承诺排程或开工。

Decimal 值须为合法数值字符串，保留精度和尾随小数，不转 Number。计数及生产数量等后端整数字段经验证后仅转成显示字符串。null/缺字段始终保持未知，不补零。比例展示后端的 0–1 原值，不重新计算齐套率。

## 来源

provenance 支持对象、数组及嵌套 BOM/库存/参数/价格来源。保留来源文件、hash、import batch、快照、观察时间、BOM 版本、工作表、行号；物料来源按对应 material_code 关联。没有行级定位时明确标注，而不是伪造定位。文件显示名去掉本机目录，数据库标识不直接渲染；批次/hash 提供短参考，完整值仍保存在原响应中。

## 错误、取消与隔离

HTTP 400/422 显示输入提示，404/409 显示会话提示，5xx 显示服务异常，网络/超时分别处理。原始错误 body、exception 和 traceback 不进入界面。HTTP 200 的业务数据不足不归类为网络故障。

停止等待只取消浏览器接收，不保证停止服务端业务。重试不确定请求前先恢复会话，已保存的回答不重复发送。sessionStorage 只缓存会话指针与模式，按 base URL + scenario 隔离。

离线固定 fixtures 不删除，但只能由 offline 模式调用；live 不自动回退 mock。首页在线 Demo 只保存问题和 scenario 标识，结果由隔离后端事实空间产生。
