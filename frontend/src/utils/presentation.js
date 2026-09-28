export const PRESENTATION_MATERIAL_LIMIT = 5

const DECISION_LABELS = {
  ready: '具备开工条件',
  blocked: '暂时无法开工',
  procurement_pending: '采购准备中，暂不能立即开工',
  data_incomplete: '关键数据待确认，暂不能判断是否开工',
}

const PURCHASE_FIELD_LABELS = {
  supplier_code: '供应商编码',
  safety_stock: '安全库存',
  lead_time_days: '采购周期',
}

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
    label: materialName?.trim() || `重点物料 ${index + 1}`,
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
  return asArray(response?.follow_up_questions).map((question, index) => {
    const fieldLabels = Object.entries(PURCHASE_FIELD_LABELS)
      .filter(([field]) => typeof question === 'string' && question.includes(field))
      .map(([, label]) => label)
    if (fieldLabels.length) {
      return `关键物料 ${index + 1} 的采购信息待确认：${fieldLabels.join('、')}。`
    }
    return '部分采购信息需要业务人员确认。'
  })
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

function decisionPresentation(response) {
  return DECISION_LABELS[response?.decision_status] || '生产结论待确认'
}

function purchasePresentation(response) {
  const recommendations = asArray(response?.report?.purchase_recommendations)
  const missingParameters = asArray(response?.missing_purchase_parameters)
  if (recommendations.length) return `已生成 ${recommendations.length} 项采购建议。`
  if (missingParameters.length) return `仍有 ${missingParameters.length} 项采购信息需要业务人员确认。`
  return '采购分析已完成，当前没有新增采购建议。'
}

function riskPresentation(materials) {
  const visibleMaterials = getPresentedMaterials(materials)
  if (visibleMaterials.some((item) => item?.risk_level === '高风险')) {
    return '存在高风险缺料，请优先处理下方标记为高风险的关键物料。'
  }
  if (visibleMaterials.some((item) => item?.risk_level)) {
    return '存在采购风险，请结合下方风险信息安排处理顺序。'
  }
  return '请结合采购状态继续跟进关键物料。'
}

function materialState(item) {
  if (item?.purchase_status === '采购建议已生成') return '采购建议已生成，等待采购执行'
  if (item?.purchase_status === '需要补充采购参数') return '采购信息待确认'
  return item?.purchase_status || '待确认'
}

function formatWhyMessage(response) {
  const materials = getPresentedMaterials(response?.blocking_materials)
  if (response?.decision_status === 'ready' && materials.length === 0) {
    return [
      '当前方案具备开工条件。',
      '',
      'PMC 分析已完成，目前未发现确定性阻塞物料。',
      `采购建议：${purchasePresentation(response)}`,
    ].join('\n')
  }

  const totalMaterials = asArray(response?.blocking_materials).length
  const lines = [
    response?.decision_status === 'data_incomplete' ? '当前暂时无法形成完整开工结论。' : '当前无法立即开工。',
    '',
    '主要原因：',
    totalMaterials
      ? `存在 ${totalMaterials} 项关键物料库存缺口。`
      : '关键业务数据仍待确认。',
  ]
  if (materials.length) {
    lines.push('', '关键影响物料：')
    materials.forEach((item, index) => {
      lines.push(
        `${index + 1}. ${getMaterialPresentation(item, index).label}`,
        `   缺口数量：${item?.shortage ?? '待确认'}`,
        `   当前状态：${materialState(item)}`,
        `   风险提示：${presentationRiskLabel(item)}`,
      )
    })
  }
  lines.push('', `采购建议：${purchasePresentation(response)}`)
  return lines.join('\n')
}

function formatImpactMessage(response) {
  const materials = getPresentedMaterials(response?.blocking_materials)
  if (!materials.length) return '当前分析未发现影响开工的确定性关键物料。'

  const lines = [
    '影响最大的关键物料：',
    '以下结果依据现有生产影响顺序排列，优先展示最需要处理的物料。',
    '',
  ]
  materials.forEach((item, index) => {
    lines.push(
      `${index + 1}. ${getMaterialPresentation(item, index).label}`,
      `   缺口：${item?.shortage ?? '待确认'}`,
      `   影响：${presentationRiskLabel(item)}；${materialState(item)}`,
    )
  })
  if (asArray(response?.blocking_materials).length > materials.length) {
    lines.push('', '当前仅展示影响优先级最高的 5 项，其余物料已保留在完整分析结果中。')
  }
  return lines.join('\n')
}

function formatScenarioMessage(response) {
  const quantity = response?.parsed_task?.quantity ?? response?.scenario?.quantity
  const quantityText = Number.isInteger(quantity) ? `${quantity}台` : '新的生产数量'
  return [
    `已复用当前会话，将生产数量调整为${quantityText}。`,
    '',
    `调整后结论：${decisionPresentation(response)}。`,
    'PMC 分析已完成，已按调整后的数量更新物料、库存和生产判断。',
    `采购建议：${purchasePresentation(response)}`,
    `风险提示：${riskPresentation(response?.blocking_materials)}`,
  ].join('\n')
}

function formatAnalysisMessage(response) {
  return [
    'PMC 分析已完成。',
    `生产结论：${decisionPresentation(response)}。`,
    `采购建议：${purchasePresentation(response)}`,
    `风险提示：${riskPresentation(response?.blocking_materials)}`,
  ].join('\n')
}

function sanitizeFallbackMessage(value) {
  if (typeof value !== 'string') return '当前请求已处理，请查看最新分析结果。'
  return value
    .replace(/\bworkflow\b/gi, '分析流程')
    .replace(/\bscenario service\b/gi, '方案分析')
    .replace(/\bwaiting_for_purchase_parameters\b/gi, '采购信息待确认')
    .replace(/\bprocurement_pending\b/gi, '采购准备中')
    .replace(/\bblocked\b/gi, '暂时无法开工')
    .replace(/\bready\b/gi, '具备开工条件')
    .replace(/\bP\d+\s+/g, '')
    .replace(/\b[A-Z0-9]{11,}\b/g, '物料编码')
}

export function formatAgentMessage(response) {
  if (!response || typeof response !== 'object') return '当前请求已处理，请查看最新分析结果。'
  if (response.response_type === 'clarification') return sanitizeFallbackMessage(response.agent_message)
  if (response.turn_type === 'explanation') return formatWhyMessage(response)
  if (response.turn_type === 'impact') return formatImpactMessage(response)
  if (response.turn_type === 'scenario') return formatScenarioMessage(response)
  if (response.turn_type === 'analysis' || response.response_type === 'analysis') return formatAnalysisMessage(response)
  return sanitizeFallbackMessage(response.agent_message)
}

export function formatScenarioImprovement(scenario) {
  const status = scenario?.workflow_result?.decision_status
  if (status === 'ready') return '调整数量后物料条件满足，可作为优先开工候选方案。'
  if (status === 'procurement_pending') return '调整数量后采购建议已形成，物料到位前仍不建议立即开工。'
  if (status === 'data_incomplete') return '调整数量后仍有关键数据待确认，暂不能形成完整开工结论。'
  if (status === 'blocked') return '调整数量后仍存在关键物料缺口，建议继续处理缺料与采购风险。'
  return '调整后的生产方案已完成分析，请结合最新结果继续决策。'
}

export function formatHistoryMessage(item, workflowContext = {}) {
  if (!item || typeof item !== 'object') return ''
  if (item.role === 'user') return typeof item.content === 'string' ? item.content : ''
  return formatAgentMessage({
    ...workflowContext,
    turn_type: item.turn_type,
    agent_message: item.content,
  })
}
