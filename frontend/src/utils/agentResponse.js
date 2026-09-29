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

  const sourceFields = [
    ['来源文件', provenance.source_file],
    ['导入批次', provenance.import_batch_id],
    ['库存快照时间', provenance.snapshot_at],
    ['库存快照', provenance.snapshot_id],
    ['BOM 版本', provenance.bom_version],
    ['工作表', provenance.sheet_name],
    ['在途观测时间', provenance.observed_at],
  ]
  const sources = sourceFields
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([label, value]) => ({ label, value: String(value) }))
  const warnings = (Array.isArray(envelope.warnings) ? envelope.warnings : [])
    .filter((item) => typeof item === 'string')
    .map((item) => item.replace(/\bunknown\b/gi, '未知'))

  const unavailableAnswers = {
    item_not_found: '当前事实库没有对应信息：未找到精确匹配的物料，请核对编码。',
    data_unavailable: '当前事实库没有对应信息：该查询条件下暂无已发布的权威数据。',
    invalid_query: '当前事实库没有对应信息：请补充物料编码、BOM 版本或有效的查询时点。',
    item_alias_ambiguous: '当前物料别名对应多个标准料号，请先确认物料身份。',
    query_failed: '事实查询暂不可用，请稍后重试。',
  }
  return {
    kindLabel: FACT_KIND_LABELS[queryType] || '事实查询',
    statusLabel: FACT_STATUS_LABELS[envelope.status] || '查询状态待确认',
    queryObject: String(queryObject),
    answer: unavailableAnswers[envelope.status]
      || (typeof envelope.answer === 'string' && envelope.answer.trim() ? envelope.answer : '查询完成，请查看下方事实结果。'),
    metrics,
    rows,
    sources,
    warnings,
  }
}
