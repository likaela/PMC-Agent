import assert from 'node:assert/strict'
import {
  formatAgentMessage,
  formatHistoryMessage,
  formatScenarioImprovement,
  getMaterialPresentation,
  getPresentedActions,
  getPresentedMaterials,
  getVisibleFollowUpQuestions,
  hasLoadedDemoPurchaseParameters,
} from '../src/utils/presentation.js'

const materials = Array.from({ length: 7 }, (_, index) => ({
  material: `11296476B01${String(index + 1).padStart(2, '0')}`,
  priority: index + 1,
  shortage: 10 - index,
  purchase_status: '采购建议已生成',
  risk_level: index < 2 ? '高风险' : '一般风险',
}))

const demoResponse = {
  blocking_materials: materials.map((item, index) => ({ ...item, material: `DEMO-M00${index + 1}` })),
  missing_purchase_parameters: [],
  follow_up_questions: ['请为物料 DEMO-M001 补充 supplier_code。'],
  report: { purchase_recommendations: [{ material: 'DEMO-M001', suggested_purchase_qty: 10 }] },
}

assert.equal(hasLoadedDemoPurchaseParameters(demoResponse), true)
assert.deepEqual(getVisibleFollowUpQuestions(demoResponse), [])
assert.equal(getPresentedMaterials(materials).length, 5)
assert.deepEqual(getPresentedMaterials(materials).map((item) => item.priority), [1, 2, 3, 4, 5])
assert.deepEqual(getMaterialPresentation({ material: '11296476B0101' }, 1), {
  label: '重点物料 2',
  code: '1129…0101',
})

const actions = materials.map((item) => ({ material: item.material, action: '发起采购' }))
assert.equal(getPresentedActions(actions, materials).length, 5)

const rawResponse = {
  blocking_materials: [{ material: '11296476B0101' }],
  missing_purchase_parameters: [{ material: '11296476B0101' }],
  follow_up_questions: ['请补充采购参数。'],
  report: { purchase_recommendations: [] },
}
assert.equal(hasLoadedDemoPurchaseParameters(rawResponse), false)
assert.deepEqual(getVisibleFollowUpQuestions(rawResponse), ['部分采购信息需要业务人员确认。'])

const formattedPurchaseQuestion = getVisibleFollowUpQuestions({
  follow_up_questions: ['请为物料 11296476B0101 补充：supplier_code、safety_stock、lead_time_days。'],
})[0]
assert.equal(formattedPurchaseQuestion, '关键物料 1 的采购信息待确认：供应商编码、安全库存、采购周期。')
assert.doesNotMatch(formattedPurchaseQuestion, /11296476B0101|supplier_code|safety_stock|lead_time_days/)

const explanationResponse = {
  response_type: 'analysis',
  turn_type: 'explanation',
  decision_status: 'blocked',
  blocking_materials: materials,
  missing_purchase_parameters: [],
  report: {
    purchase_recommendations: materials.map((item) => ({ material: item.material })),
  },
  agent_message: `P1 ${materials[0].material} workflow blocked`,
  explanation: { answer: `P1 ${materials[0].material} workflow blocked` },
}

const whyMessage = formatAgentMessage(explanationResponse)
assert.match(whyMessage, /当前无法立即开工/)
assert.equal((whyMessage.match(/缺口数量：/g) || []).length, 5)
assert.doesNotMatch(whyMessage, /P1|P2|P3/)
assert.doesNotMatch(whyMessage, new RegExp(materials[0].material))
assert.doesNotMatch(whyMessage, /workflow|blocked/i)

const impactMessage = formatAgentMessage({ ...explanationResponse, turn_type: 'impact' })
assert.match(impactMessage, /影响最大的关键物料/)
assert.match(impactMessage, /依据现有生产影响顺序排列/)
assert.equal((impactMessage.match(/\n   缺口：/g) || []).length, 5)
assert.doesNotMatch(impactMessage, /P1|P2|P3/)
assert.doesNotMatch(impactMessage, new RegExp(materials[5].material))

const scenarioMessage = formatAgentMessage({
  ...explanationResponse,
  turn_type: 'scenario',
  decision_status: 'procurement_pending',
  parsed_task: { product: 'KQ-Z112', quantity: 50 },
  agent_message: 'workflow 返回 blocked，scenario service 已完成',
})
assert.match(scenarioMessage, /已复用当前会话，将生产数量调整为50台/)
assert.match(scenarioMessage, /PMC 分析已完成/)
assert.doesNotMatch(scenarioMessage, /workflow|scenario service|ready|blocked/i)
assert.equal(
  formatScenarioImprovement({ workflow_result: { decision_status: 'blocked' } }),
  '调整数量后仍存在关键物料缺口，建议继续处理缺料与采购风险。',
)
assert.doesNotMatch(
  formatScenarioImprovement({ workflow_result: { decision_status: 'ready' } }),
  /ready|workflow/i,
)

const restoredMessage = formatHistoryMessage(
  {
    role: 'agent',
    turn_type: 'impact',
    content: `P1 ${materials[0].material} workflow blocked`,
  },
  explanationResponse,
)
assert.match(restoredMessage, /影响最大的关键物料/)
assert.equal((restoredMessage.match(/\n   缺口：/g) || []).length, 5)
assert.doesNotMatch(restoredMessage, /P1|workflow|blocked/i)
assert.doesNotMatch(restoredMessage, new RegExp(materials[0].material))

console.log('presentation tests passed')
