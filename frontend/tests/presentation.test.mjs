import assert from 'node:assert/strict'
import {
  getMaterialPresentation,
  getPresentedActions,
  getPresentedMaterials,
  getVisibleFollowUpQuestions,
  hasLoadedDemoPurchaseParameters,
} from '../src/utils/presentation.js'

const materials = Array.from({ length: 7 }, (_, index) => ({
  material: `DEMO-M00${index + 1}`,
  priority: index + 1,
  shortage: 10 - index,
}))

const demoResponse = {
  blocking_materials: materials,
  missing_purchase_parameters: [],
  follow_up_questions: ['请为物料 DEMO-M001 补充 supplier_code。'],
  report: { purchase_recommendations: [{ material: 'DEMO-M001', suggested_purchase_qty: 10 }] },
}

assert.equal(hasLoadedDemoPurchaseParameters(demoResponse), true)
assert.deepEqual(getVisibleFollowUpQuestions(demoResponse), [])
assert.equal(getPresentedMaterials(materials).length, 5)
assert.deepEqual(getPresentedMaterials(materials).map((item) => item.priority), [1, 2, 3, 4, 5])
assert.deepEqual(getMaterialPresentation({ material: '11296476B0101' }, 1), {
  label: '关键物料 2',
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
assert.deepEqual(getVisibleFollowUpQuestions(rawResponse), ['请补充采购参数。'])

console.log('presentation tests passed')
