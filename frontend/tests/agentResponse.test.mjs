import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { extractPmcResponse, isPmcResponseUnavailable, presentFactResult, presentProductionCapacityResult } from '../src/utils/agentResponse.js'

const inventoryEnvelope = {
  intent: 'fact_query',
  status: 'ok',
  answer: 'MAT-001 的已发布在库数量为 7；可用数量为 未知。',
  structured_data: {
    query_type: 'inventory',
    query: { material_code: 'MAT-001', resolved_material_code: 'MAT-001' },
    data: { on_hand_qty: '7', available_qty: null, reserved_qty: null, batch_count: 1, location_count: 1 },
    completeness: { on_hand_qty: true, available_qty: false, reserved_qty: false },
  },
  provenance: {
    source_file: 'synthetic.xlsx',
    import_batch_id: 'batch-1',
    snapshot_id: 'snapshot-1',
    snapshot_at: '2026-09-20T00:00:00+00:00',
  },
  warnings: ['可用数量缺少权威来源，返回 unknown'],
}

const inventory = presentFactResult(inventoryEnvelope)
assert.equal(inventory.kindLabel, '物料库存')
assert.equal(inventory.queryObject, 'MAT-001')
assert.deepEqual(inventory.metrics.slice(0, 3), [
  { label: '在库数量', value: '7' },
  { label: '可用数量', value: '未知' },
  { label: '预留数量', value: '未知' },
])
assert.deepEqual(inventory.sources, [
  { label: '来源文件', value: 'synthetic.xlsx' },
  { label: '导入批次', value: 'batch-1' },
  { label: '库存快照时间', value: '2026-09-20T00:00:00+00:00' },
])
assert.ok(!inventory.sources.some((item) => item.value === 'snapshot-1'))
assert.equal(inventory.warnings[0], '可用数量缺少权威来源，返回 未知')
assert.equal(inventoryEnvelope.structured_data.data.available_qty, null)

const bom = presentFactResult({
  ...inventoryEnvelope,
  structured_data: {
    query_type: 'bom',
    query: { parent_material_code: 'PARENT-1', revision: 'V1' },
    data: { revision: 'V1', line_count: 1, lines: [{ child_item: { material_code: 'MAT-001', name: '测试物料' }, qty_per: '2', unit: null }] },
  },
  provenance: { source_file: 'bom.xlsx', import_batch_id: 'batch-2', bom_version: 'V1', sheet_name: 'BOM明细' },
  warnings: [],
})
assert.equal(bom.kindLabel, 'BOM 明细')
assert.equal(bom.queryObject, 'PARENT-1')
assert.equal(bom.rows[0].label, '测试物料')
assert.equal(bom.rows[0].value, '2')
assert.ok(bom.sources.some((item) => item.label === 'BOM 版本' && item.value === 'V1'))
assert.ok(bom.sources.some((item) => item.label === '生效时间' && item.value === '未知'))

for (const [queryType, expected] of [
  ['inventory', '库存快照'],
  ['bom', 'BOM 版本'],
  ['inbound', '权威在途采购事实'],
]) {
  const unavailable = presentFactResult({
    ...inventoryEnvelope,
    status: 'data_unavailable',
    structured_data: { query_type: queryType, query: { material_code: 'MAT-001' }, data: null },
    provenance: null,
    warnings: [],
  })
  assert.match(unavailable.answer, new RegExp(expected))
  assert.match(unavailable.answer, /当前事实库没有对应信息/)
}

const inbound = presentFactResult({
  ...inventoryEnvelope,
  structured_data: {
    query_type: 'inbound',
    query: { material_code: 'MAT-001' },
    data: { ordered_qty: '10', received_qty: null, in_transit_qty: null },
  },
  provenance: { source_file: 'order.xlsx', import_batch_id: 'batch-3' },
  warnings: [],
})
assert.deepEqual(inbound.metrics, [
  { label: '订购数量', value: '10' },
  { label: '已收数量', value: '未知' },
  { label: '在途数量', value: '未知' },
])

for (const status of ['item_not_found', 'data_unavailable', 'invalid_query', 'query_failed']) {
  const unavailable = presentFactResult({
    ...inventoryEnvelope,
    status,
    answer: 'traceback workflow blocked',
    structured_data: { ...inventoryEnvelope.structured_data, data: null },
    provenance: null,
    warnings: [],
  })
  assert.equal(unavailable.metrics.length, 0)
  assert.doesNotMatch(unavailable.answer, /traceback|workflow|blocked/i)
}

const pmcPayload = {
  workflow_id: 'workflow-1',
  decision_status: 'blocked',
  blocking_materials: [{ material: 'MAT-001', shortage: 5 }],
  report: { production_decision: { recommended_actions: [] } },
  agent_trace: [{ step: '物料分析', status: 'completed' }],
}
assert.equal(extractPmcResponse({ intent: 'pmc_analysis', structured_data: pmcPayload }), pmcPayload)
assert.equal(extractPmcResponse({ intent: 'fact_query', structured_data: pmcPayload }), null)
assert.equal(isPmcResponseUnavailable({ intent: 'pmc_analysis', status: 'ok', structured_data: pmcPayload }), false)
assert.equal(isPmcResponseUnavailable({ intent: 'pmc_analysis', status: 'unavailable', structured_data: pmcPayload }), true)
assert.equal(isPmcResponseUnavailable({ intent: 'pmc_analysis', status: 'ok', structured_data: { ...pmcPayload, public_error: { user_message: '内部错误' } } }), true)

const chatView = readFileSync(new URL('../src/views/Chat.vue', import.meta.url), 'utf8')
assert.match(chatView, /class="panel fact-result-panel"/)
assert.match(chatView, /class="status-grid"/)
assert.match(chatView, /<WorkflowTrace v-if="activeView === 'pmc'"/)
assert.match(chatView, /数据来源/)
assert.match(chatView, /数据完整性提示/)

const capacity = presentProductionCapacityResult({
  intent: 'production_capacity',
  status: 'ok',
  answer: '按已发布事实，理论最多可生产 50 件。',
  structured_data: {
    query: { product: 'PARENT-1', bom_version: 'V1' },
    data: {
      max_producible_quantity: 50,
      requested_quantity: 100,
      inventory_sufficient_for_requested: false,
      limiting_materials: [{ material_code: 'MAT-A', qty_per: '2', unit: '件', available_qty: '100', shortage_qty: '100', material_capacity: 50 }],
    },
  },
  provenance: {
    bom: { source_file: 'bom.xlsx', import_batch_id: 'bom-batch', bom_version: 'V1', source_file_id: 'hidden' },
    inventory: [{ material_code: 'MAT-A', source_file: 'stock.xlsx', import_batch_id: 'stock-batch', snapshot_at: '2026-09-20T00:00:00+00:00', snapshot_id: 'hidden' }],
    inbound: [],
  },
  warnings: ['在途不计入当前可用库存'],
})
assert.equal(capacity.kindLabel, '库存理论产能')
assert.equal(capacity.metrics[0].value, '50')
assert.equal(capacity.metrics[2].value, '不足')
assert.equal(capacity.rows[0].label, 'MAT-A')
assert.ok(capacity.sources.some((item) => item.label === '库存快照时间'))
assert.ok(!capacity.sources.some((item) => item.value === 'hidden'))
assert.match(chatView, /envelope\?\.intent === 'production_capacity'/)

const unavailableCapacity = presentProductionCapacityResult({
  intent: 'production_capacity', status: 'data_unavailable',
  answer: 'traceback: private database path',
  structured_data: { query: { product: 'PARENT-1', bom_version: 'V1' }, data: { max_producible_quantity: null } },
  provenance: null, warnings: [],
})
assert.equal(unavailableCapacity.metrics.length, 0)
assert.doesNotMatch(unavailableCapacity.answer, /traceback|private database path/i)

console.log('agent response presentation tests passed')
