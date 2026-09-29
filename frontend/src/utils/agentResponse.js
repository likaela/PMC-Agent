const FACT_STATUS_LABELS = {
  ok: '已查询到权威事实',
  item_not_found: '未找到该物料',
  data_unavailable: '暂无已发布数据',
  invalid_query: '查询条件需补充',
  item_alias_ambiguous: '物料身份待确认',
  query_failed: '查询暂不可用',
}

const FACT_KIND_LABELS = {
  inventory: '物料库存',
  inventory_batches: '库存批次',
  bom: 'BOM 明细',
  inbound: '采购在途',
}

function record(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function known(value) {
  return value === null || value === undefined || value === '' ? '未知' : String(value)
}

function addMetric(metrics, label, value) {
  metrics.push({ label, value: known(value) })
}

export function extractPmcResponse(envelope) {
  if (envelope?.intent !== 'pmc_analysis') return null
  const data = record(envelope.structured_data)
  return Object.keys(data).length ? data : null
}

export function isPmcResponseUnavailable(envelope) {
  const data = extractPmcResponse(envelope)
  return envelope?.intent === 'pmc_analysis'
    && (envelope.status === 'unavailable' || Boolean(data?.public_error))
}

export function presentFactResult(envelope) {
  if (envelope?.intent !== 'fact_query') return null
  const structured = record(envelope.structured_data)
  const query = record(structured.query)
  const data = record(structured.data)
  const completeness = record(structured.completeness)
  const provenance = record(envelope.provenance)
  const queryType = structured.query_type
  const queryObject = query.resolved_material_code
    || query.resolved_parent_material_code
    || query.material_code
    || query.parent_material_code
    || '待确认物料'
  const metrics = []
  const rows = []

  if (envelope.status === 'ok') {
    if (queryType === 'inventory') {
      addMetric(metrics, '在库数量', data.on_hand_qty)
      addMetric(metrics, '可用数量', data.available_qty)
      addMetric(metrics, '预留数量', data.reserved_qty)
      addMetric(metrics, '批次数', data.batch_count)
      addMetric(metrics, '库位数', data.location_count)
    } else if (queryType === 'inventory_batches') {
      for (const item of Array.isArray(data.batches) ? data.batches : []) {
        const batch = record(item)
        rows.push({
          label: `批次 ${known(batch.batch_no)}`,
          detail: `库位 ${known(batch.location)} · 质量状态 ${known(batch.quality_status)}`,
          value: known(batch.on_hand_qty),
        })
      }
    } else if (queryType === 'bom') {
      addMetric(metrics, 'BOM 版本', data.revision)
      addMetric(metrics, '明细条数', data.line_count)
      for (const item of Array.isArray(data.lines) ? data.lines : []) {
        const line = record(item)
        const child = record(line.child_item)
        rows.push({
          label: known(child.name || child.material_code),
          detail: `物料编码 ${known(child.material_code)}`,
          value: `${known(line.qty_per)} ${line.unit || ''}`.trim(),
        })
      }
    } else if (queryType === 'inbound') {
      addMetric(metrics, '订购数量', data.ordered_qty)
      addMetric(metrics, '已收数量', data.received_qty)
      addMetric(metrics, '在途数量', data.in_transit_qty)
      for (const item of Array.isArray(data.lines) ? data.lines : []) {
        const line = record(item)
        rows.push({
          label: `订单 ${known(line.order_no)}`,
          detail: `供应商 ${known(line.supplier_code)} · 预计到货 ${known(line.expected_arrival_date)}`,
          value: known(line.in_transit_qty),
        })
      }
    }
  }

  const sourceFields = envelope.status === 'ok' ? [
    ['来源文件', known(provenance.source_file)],
    ['导入批次', known(provenance.import_batch_id)],
    ...(queryType === 'inventory' || queryType === 'inventory_batches'
      ? [['库存快照时间', known(provenance.snapshot_at)]] : []),
    ...(queryType === 'bom'
      ? [['BOM 版本', known(provenance.bom_version || data.revision)], ['生效时间', known(data.effective_from)]] : []),
    ...(queryType === 'inbound'
      ? [['在途观测时间', known(provenance.observed_at)]] : []),
    ['工作表', provenance.sheet_name],
  ] : []
  const sources = sourceFields
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([label, value]) => ({ label, value: String(value) }))
  const warnings = (Array.isArray(envelope.warnings) ? envelope.warnings : [])
    .filter((item) => typeof item === 'string')
    .map((item) => item.replace(/\bunknown\b/gi, '未知'))
  const completenessFields = {
    inventory: [['on_hand_qty', '在库数量'], ['available_qty', '可用数量'], ['reserved_qty', '预留数量']],
    inventory_batches: [['batch_no', '批次号'], ['received_at', '收货时间'], ['expiry_date', '有效期']],
    bom: [['bom_lines', 'BOM 明细'], ['qty_per', '单位用量'], ['price', '价格']],
    inbound: [['ordered_qty', '订购数量'], ['in_transit_qty', '在途数量']],
  }
  const completenessItems = envelope.status === 'ok'
    ? (completenessFields[queryType] || [])
      .filter(([key]) => typeof completeness[key] === 'boolean')
      .map(([key, label]) => ({ label, value: completeness[key] ? '已核实' : '暂无完整权威数据' }))
    : []

  const unavailableAnswers = {
    item_not_found: `当前事实库没有对应信息：未找到物料编码 ${queryObject}，请确认编码是否正确。`,
    data_unavailable: {
      inventory: '当前事实库没有对应信息：已找到该物料，但查询时点没有已发布的库存快照。',
      inventory_batches: '当前事实库没有对应信息：已找到该物料，但查询时点没有已发布的库存批次。',
      bom: '当前事实库没有对应信息：当前没有该产品的已发布 BOM 版本。',
      inbound: '当前事实库没有对应信息：当前没有权威在途采购事实。',
    }[queryType] || '当前事实库没有对应信息：该查询条件下暂无已发布的权威数据。',
    invalid_query: '当前事实库没有对应信息：请补充物料编码、BOM 版本或有效的查询时点。',
    item_alias_ambiguous: '当前物料别名对应多个标准料号，请先确认物料身份。',
    query_failed: '系统查询异常，请稍后重试。',
  }
  return {
    kindLabel: FACT_KIND_LABELS[queryType] || '事实查询',
    statusLabel: FACT_STATUS_LABELS[envelope.status] || '查询状态待确认',
    queryObject: String(queryObject),
    answer: unavailableAnswers[envelope.status]
      || (typeof envelope.answer === 'string' && envelope.answer.trim() ? envelope.answer : '查询完成，请查看下方事实结果。'),
    metrics,
    rows,
    completenessItems,
    sources,
    warnings: envelope.status === 'ok' ? warnings : [],
  }
}

export function presentProductionCapacityResult(envelope) {
  if (envelope?.intent !== 'production_capacity') return null
  const structured = record(envelope.structured_data)
  const query = record(structured.query)
  const data = record(structured.data)
  const provenance = record(envelope.provenance)
  const bomSource = record(provenance.bom)
  const inventorySources = Array.isArray(provenance.inventory) ? provenance.inventory.map(record) : []
  const inboundSources = Array.isArray(provenance.inbound) ? provenance.inbound.map(record) : []
  const sources = []
  const addSource = (label, value) => {
    if (value !== null && value !== undefined && value !== '' && !sources.some((item) => item.label === label && item.value === String(value))) {
      sources.push({ label, value: String(value) })
    }
  }
  addSource('BOM 来源文件', bomSource.source_file)
  addSource('BOM 导入批次', bomSource.import_batch_id)
  addSource('BOM 版本', bomSource.bom_version || query.bom_version)
  for (const source of inventorySources) {
    addSource('库存来源文件', source.source_file)
    addSource('库存导入批次', source.import_batch_id)
    addSource('库存快照时间', source.snapshot_at)
  }
  for (const source of inboundSources) {
    addSource('在途来源文件', source.source_file)
    addSource('在途导入批次', source.import_batch_id)
    addSource('在途观测时间', source.observed_at)
  }
  const metrics = []
  if (envelope.status === 'ok') {
    addMetric(metrics, '库存理论最大产量', data.max_producible_quantity)
    if (data.requested_quantity !== null && data.requested_quantity !== undefined) {
      addMetric(metrics, '询问的生产数量', data.requested_quantity)
      addMetric(metrics, '当前可用库存是否满足', data.inventory_sufficient_for_requested === true ? '足够' : '不足')
    }
  }
  const visibleMaterials = envelope.status === 'ok'
    ? data.limiting_materials
    : data.materials
  const rows = (Array.isArray(visibleMaterials) ? visibleMaterials : []).map((item) => {
    const material = record(item)
    return {
      label: known(material.material_code),
      detail: `单位用量 ${known(material.qty_per)} ${known(material.unit)} · 可用 ${known(material.available_qty)} · 缺口 ${known(material.shortage_qty)}`,
      value: envelope.status === 'ok'
        ? `限制产量 ${known(material.material_capacity)}`
        : `需求 ${known(material.required_qty)} ${known(material.unit)}`,
    }
  })
  const fallback = envelope.status === 'invalid_query'
    ? '请提供产品型号和明确的 BOM 版本，或先完成一轮生产分析。'
    : envelope.status === 'data_unavailable'
      ? '当前事实库数据不足，无法确定生产能力；请查看数据完整性提示。'
      : '生产能力查询暂不可用，请稍后重试。'
  return {
    kindLabel: '库存理论产能',
    statusLabel: envelope.status === 'ok' ? '已完成事实核对' : '数据不足，无法确定',
    queryObject: [query.product, query.bom_version].filter(Boolean).join(' / ') || '待确认产品',
    answer: ['ok', 'data_unavailable'].includes(envelope.status)
      && typeof envelope.answer === 'string'
      && !/traceback|exception|workflow state/i.test(envelope.answer)
      ? envelope.answer : fallback,
    metrics,
    rows,
    sources,
    warnings: Array.isArray(envelope.warnings) ? envelope.warnings.filter((item) => typeof item === 'string') : [],
  }
}
