export const PRESENTATION_MATERIAL_LIMIT = 5

function asArray(value) {
  return Array.isArray(value) ? value : []
}

export function getPresentedMaterials(materials, limit = PRESENTATION_MATERIAL_LIMIT) {
  const safeLimit = Number.isInteger(limit) && limit > 0 ? limit : PRESENTATION_MATERIAL_LIMIT
  return asArray(materials).slice(0, safeLimit)
}

export function getMaterialPresentation(item, index = 0) {
  const materialName = [item?.material_name, item?.name, item?.materialName]
    .find((value) => typeof value === 'string' && value.trim())
  const materialCode = typeof item?.material === 'string' ? item.material.trim() : ''

  return {
    label: materialName?.trim() || `关键物料 ${index + 1}`,
    code: shortenMaterialCode(materialCode),
  }
}

export function shortenMaterialCode(materialCode) {
  if (!materialCode) return ''
  if (materialCode.length <= 10) return materialCode
  return `${materialCode.slice(0, 4)}…${materialCode.slice(-4)}`
}

export function hasLoadedDemoPurchaseParameters(response) {
  const blockingMaterials = asArray(response?.blocking_materials)
  const purchaseRecommendations = asArray(response?.report?.purchase_recommendations)
  const missingParameters = asArray(response?.missing_purchase_parameters)
  const usesDemoMaterials = blockingMaterials.length > 0
    && blockingMaterials.every((item) => typeof item?.material === 'string' && item.material.startsWith('DEMO-'))

  return usesDemoMaterials && missingParameters.length === 0 && purchaseRecommendations.length > 0
}

export function getVisibleFollowUpQuestions(response) {
  if (hasLoadedDemoPurchaseParameters(response)) return []
  return asArray(response?.follow_up_questions)
}

export function getPresentedActions(actions, materials, limit = PRESENTATION_MATERIAL_LIMIT) {
  const visibleMaterials = getPresentedMaterials(materials, limit)
  const visibleCodes = new Set(visibleMaterials.map((item) => item?.material).filter(Boolean))
  const relevantActions = asArray(actions).filter((action) => !action?.material || visibleCodes.has(action.material))
  return relevantActions.slice(0, limit)
}

export function presentationRiskLabel(item) {
  if (item?.risk_level) return item.risk_level
  if (item?.purchase_status === '需要补充采购参数') return '采购信息待确认'
  return item?.purchase_status || '待确认'
}
