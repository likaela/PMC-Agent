import {
  QueryError,
  type BackendResponse,
  type FrontendViewModel,
  type JsonObject,
  type Material,
  type Source,
  type PurchaseView,
  type ResultStatus,
} from "../data/model";
import { isAllowedScenario } from "./scenarioPolicy";

const intents = new Set([
  "pmc_analysis",
  "fact_query",
  "production_capacity",
  "clarification",
  "inventory",
  "inventory_batches",
  "bom",
  "inbound",
  "purchase_planning",
]);
function fail(): never {
  throw new QueryError("mapping", "响应字段暂无法完整展示，请检查接口契约。");
}
function isObject(v: unknown): v is JsonObject {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
function object(v: unknown): JsonObject {
  if (v == null) return {};
  if (!isObject(v)) return fail();
  return v;
}
function text(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v !== "string") return fail();
  return v;
}
function decimal(v: unknown): string | null {
  if (v == null) return null;
  if (
    typeof v !== "string" ||
    !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(v)
  )
    return fail();
  return v; // Keep exact Decimal text, including trailing precision.
}
function count(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === "string") return decimal(v);
  if (typeof v !== "number" || !Number.isSafeInteger(v)) return fail();
  return String(v);
}
function bool(v: unknown): boolean | null {
  if (v == null) return null;
  if (typeof v !== "boolean") return fail();
  return v;
}
function list(v: unknown): JsonObject[] {
  if (v == null) return [];
  if (!Array.isArray(v) || !v.every(isObject)) return fail();
  return v;
}
function strings(v: unknown): string[] {
  if (v == null) return [];
  if (!Array.isArray(v) || !v.every((s) => typeof s === "string"))
    return fail();
  return v;
}
export function validateBackendResponse(payload: unknown): BackendResponse {
  const p = object(payload);
  if (
    !intents.has(p.intent as string) ||
    typeof p.status !== "string" ||
    typeof p.answer !== "string" ||
    !(p.structured_data === null || isObject(p.structured_data)) ||
    !(
      p.provenance === null ||
      isObject(p.provenance) ||
      (Array.isArray(p.provenance) && p.provenance.every(isObject))
    ) ||
    !Array.isArray(p.warnings) ||
    !p.warnings.every((w) => typeof w === "string")
  )
    fail();
  for (const key of ["session_id", "conversation_id", "turn_id"]) text(p[key]);
  if (p.scenario_id != null && !isAllowedScenario(p.scenario_id))
    fail();
  return payload as BackendResponse;
}

// Flatten provenance only, never arbitrary business data or answer prose.
function sourcesFrom(value: unknown, synthetic: boolean): Source[] {
  const result: Source[] = [];
  const seen = new Set<string>();
  function walk(
    v: unknown,
    scope: string,
    code: string | null,
    inherited: JsonObject,
    depth = 0,
  ) {
    if (depth > 30) return;
    if (Array.isArray(v)) {
      v.forEach((child) => walk(child, scope, code, inherited, depth + 1));
      return;
    }
    if (!isObject(v)) return;
    const materialCode =
      typeof v.material_code === "string" ? v.material_code : code;
    const context = { ...inherited };
    for (const key of [
      "bom_version",
      "revision",
      "snapshot_at",
      "observed_at",
      "effective_from",
    ])
      if (v[key] != null) context[key] = v[key];
    if (
      v.source_file != null ||
      v.source_file_id != null ||
      v.import_batch_id != null
    ) {
      const file = text(v.source_file);
      const syntheticSource = synthetic || v.synthetic === true || v.source_kind === "synthetic_review";
      const source: Source = {
        id: "",
        title: file ? file.split(/[\\/]/).pop()! : "已发布来源记录",
        kind: syntheticSource ? "合成演示事实" : v.source_kind === "excel_observation" ? "Excel账面记录" : v.source_kind === "human_business_confirmation" ? "人工业务确认" : "已发布事实",
        scope,
        reference: file ? file.split(/[\\/]/).pop()! : "来源文件名称未提供",
        version: text(context.bom_version ?? context.revision),
        publishedAt: text(v.published_at),
        snapshotAt: text(context.snapshot_at),
        observedAt: text(context.observed_at),
        effectiveFrom: text(context.effective_from),
        importBatch: text(v.import_batch_id),
        sheet: text(v.sheet_name ?? v.source_sheet),
        row: count(v.row_number ?? v.source_row_number),
        sha256: text(v.content_sha256),
        materialCode,
        conditions: syntheticSource
          ? "演示产品数据，仅用于体验，不用于业务放行。"
          : "仅适用于返回的版本、数据时点与查询条件。",
      };
      const key = JSON.stringify(source);
      if (!seen.has(key)) {
        seen.add(key);
        source.id = `source-${result.length + 1}`;
        result.push(source);
      }
    }
    for (const [key, child] of Object.entries(v)) {
      if (!isObject(child) && !Array.isArray(child)) continue;
      if (key === "materials" && isObject(child)) {
        for (const [material, detail] of Object.entries(child))
          walk(detail, "物料分析来源", material, context, depth + 1);
      } else {
        const labels: Record<string, string> = {
          bom: "BOM 来源",
          inventory: "库存来源",
          inbound: "在途来源",
          price: "价格来源",
          parameters: "采购参数来源",
          unit_conversions: "单位换算来源",
          risk_policy: "库存策略来源",
        };
        walk(child, labels[key] ?? scope, materialCode, context, depth + 1);
      }
    }
  }
  walk(value, "本次查询来源", null, {});
  return result;
}
const riskLabels: Record<string, string> = {
  high: "高风险",
  general: "一般风险",
  none: "无缺料风险",
  buffer_only: "安全库存补充",
};

export function adaptBackendResponse(
  payload: unknown,
  userMessage?: string,
): FrontendViewModel {
  const backend = validateBackendResponse(payload);
  const structured = object(backend.structured_data);
  const data = object(structured.data);
  const query = object(structured.query);
  const kind = text(structured.query_type) ?? backend.intent;
  const presentationPrice = object(structured.presentation).price_relevant;
  const priceRelevant =
    typeof presentationPrice === "boolean"
      ? presentationPrice
      : userMessage !== undefined
        ? /成本|多少钱|金额|单价|报价|价格|核价/.test(userMessage)
        : kind === "purchase_planning";
  const conversation =
    backend.intent === "clarification" &&
    backend.status === "ok" &&
    structured.operation === "conversation";
  const completeness = object(structured.completeness);
  const sources = sourcesFrom(
    backend.provenance,
    backend.scenario_id === "demo_scenario_50_vs_100" ||
      (isObject(backend.provenance) && backend.provenance.synthetic === true),
  );
  const item = object(data.canonical_item ?? data.parent_item);
  const product = text(
    data.product ??
      item.material_code ??
      query.resolved_material_code ??
      query.resolved_parent_material_code ??
      query.material_code ??
      query.parent_material_code ??
      query.product,
  );
  const vm: FrontendViewModel = {
    conversation,
    id: backend.turn_id ?? "current-result",
    status: "result",
    queryType: kind,
    product,
    quantity: count(
      data.requested_quantity ??
        data.quantity ??
        query.requested_quantity ??
        query.quantity,
    ),
    quantityUnit: text(data.product_unit) ?? "",
    title: "查询结果",
    // Old history keeps original Evidence/prose, but obsolete generic price
    // notices need not be rendered for a structural question. No numbers parsed.
    answer: priceRelevant
      ? backend.answer
      : backend.answer.replaceAll(
          "部分物料价格尚未确认，暂不能进行完整成本计算。",
          "",
        ),
    conclusion: "仅展示已发布事实",
    nextAction: "核对数据完整性与来源后使用。",
    materials: [],
    sources,
    warnings: backend.warnings.filter(
      (warning) => priceRelevant || !warning.startsWith("price_missing"),
    ),
    completeness,
    backend,
    metrics: [],
  };
  function sourceIds(code: string | null) {
    return sources
      .filter((s) => !s.materialCode || s.materialCode === code)
      .map((s) => s.id);
  }
  function material(row: JsonObject, child: JsonObject = row): Material {
    const code = text(child.material_code ?? row.material);
    return {
      id:
        text(row.bom_line_id) ??
        `material-${vm.materials.length + 1}-${code ?? "unknown"}`,
      code: code ?? undefined,
      name: text(child.name) ?? code ?? "名称未提供",
      spec: text(child.specification) ?? "",
      required: decimal(row.required_qty),
      available: decimal(row.available_qty),
      onHand: decimal(row.on_hand_qty),
      reserved: decimal(row.reserved_qty),
      shortage: decimal(
        row.shortage_qty !== undefined ? row.shortage_qty : row.shortage,
      ),
      purchaseQty: decimal(
        row.suggested_purchase_qty !== undefined
          ? row.suggested_purchase_qty
          : row.purchase_qty,
      ),
      completeness: object(row.completeness),
      unit: text(row.unit ?? child.unit) ?? "",
      state: "unknown",
      sourceIds: sourceIds(code),
    };
  }
  const metric = (label: string, value: string | null) =>
    vm.metrics!.push({ label, value });
  const completenessLabels: Record<string, string> = {
    on_hand_qty: "在库数量",
    available_qty: "可用数量",
    reserved_qty: "预留数量",
    bom: "BOM",
    inventory: "库存",
    units: "单位",
    snapshot_coherent: "库存时点一致性",
    quantity: "数量",
    parameters: "采购参数",
    cost: "成本",
    price: "价格",
    single_currency: "统一币种",
    duplicate_free: "明细去重状态",
    received_at: "收货日期",
    expiry_date: "有效期",
    quality_status: "质量状态",
    in_transit_qty: "在途数量",
  };
  const incomplete = Object.entries(completeness)
    .filter(
      ([field, value]) =>
        value === false &&
        completenessLabels[field] &&
        (priceRelevant ||
          !["price", "cost", "single_currency"].includes(field)),
    )
    .map(([field]) => completenessLabels[field]);
    if (incomplete.length && data.quantity_review !== true && data.stock_read_failed !== true) metric("待核实事实", incomplete.join("、"));
  if (structured.operation === "quantity_validation") {
    vm.validationError = true;
    vm.status = "clarification";
    vm.title = "请调整生产数量";
    vm.conclusion = "本次输入未执行业务分析";
    vm.nextAction = "请提供大于0的整数数量。";
    vm.metrics = [];
    return vm;
  }
  if (data.calculation_scope === "excel_book_observation" && ["ok", "query_failed"].includes(backend.status)) {
    vm.bookObservation = true;
    vm.quantityReview = data.quantity_review === true;
    vm.status = kind === "purchase_planning" ? "purchase" : "inventory";
    vm.title = "企业账面记录与BOM需求核对";
    vm.conclusion = "部分数据分析，不是生产许可或正式采购计划";
    vm.nextAction = "查看BOM需求、主库存记录和来源；有重复疑点的记录合计保持待核验。";
      if (vm.quantityReview) {
        vm.status = data.quantity_check_status === "sufficient" ? "ready" : data.quantity_check_status === "insufficient" ? "blocked" : "partial";
        vm.title = object(data.source_summary).review_scenario ? "数量模拟核对（演示库存）" : "当前实际库存与生产需求核对";
        vm.conclusion = "数量核对结果，不代表正式排程或工单下达";
        vm.nextAction = "查看已计算的需求与缺口；无记录及未核验重复记录保持未知。";
      }
      if (data.stock_read_failed === true) {
        vm.status = "partial";
        vm.title = "BOM需求已计算，库存本次读取失败";
        vm.nextAction = "可查看需求明细；稍后重试库存读取。";
      }
    vm.materials = list(data.materials).map((row) => {
      const m = material(row);
      m.qtyPer = decimal(row.qty_per);
      m.recordedStock = decimal(row.recorded_stock_qty);
      m.bookDifference = decimal(row.book_difference);
      m.shortage = decimal(row.book_shortage_qty);
      m.recordCount = count(row.record_count);
      m.recordFound = bool(row.record_found);
      m.inventoryUnit = text(row.inventory_unit);
      m.comparisonStatus = text(row.comparison_status);
      // Only display status supplied by Python. Never subtract or infer readiness.
        m.state = vm.quantityReview && row.quantity_status === "shortage" ? "shortage" : vm.quantityReview && row.quantity_status === "sufficient" ? "sufficient" : m.comparisonStatus === "comparable" ? "published" : "unknown";
      return m;
    });
    metric("BOM版本", text(data.revision));
    metric("物料数量", count(data.total_material_count));
      metric(object(data.source_summary).review_scenario ? "推演库存覆盖项" : "主库存匹配项", count(data.matched_material_count));
    metric("库存数量口径", text(object(object(data.source_summary).unit_confirmation).unit));
    metric("主库存总记录数", count(object(data.source_summary).record_count));
    metric("记录数量去重待核验", count(object(data.source_summary).duplicate_observation_count));
      if (!vm.quantityReview && data.stock_read_failed !== true) metric("库存时点", null);
      metric("生产数量", count(data.requested_quantity));
      metric("可比较物料", count(data.comparable_material_count));
    vm.detailTable = {
      columns: ["物料编码", "库位", "批次", "账面数量", "单位", "源行号", "重复观察待核验"],
      rows: list(data.materials).flatMap((row) => list(row.details).map((detail) => [
        text(detail.material_code), text(detail.location), text(detail.batch_no),
        decimal(detail.recorded_stock_qty), text(detail.inventory_unit), count(object(detail.provenance).row_number),
        bool(detail.duplicate_observation) === true ? "是" : "否",
      ])),
    };
    if (data.slim_review === true) {
      vm.slimReview = true;
      const range = data.synthetic === true ? "数量模拟范围" : "标准分析范围";
      vm.title = `${vm.product ?? '当前产品'} · ${range}`;
      vm.conclusion = "仅适用于当前分析范围，不代表完整产品生产放行";
      vm.nextAction = "可询问最多生产多少、生产最大数量、再多生产1片，以及查看限制物料和来源。";
      vm.metrics = [
        { label: "产品", value: text(data.product) },
        { label: "物料数量", value: count(data.total_material_count) },
        { label: "BOM版本", value: text(data.revision) },
        { label: "数据集版本", value: text(data.dataset_version) ?? "历史版本未标注" },
        { label: "生产目标数量", value: data.requested_quantity == null ? "本轮查询分析范围／最大数量" : count(data.requested_quantity) },
        { label: "最大满足数量", value: data.theoretical_max_quantity == null ? null : count(data.theoretical_max_quantity) + "片" },
        { label: "库存依据", value: data.synthetic === true ? "主库存记录与演示库存补充" : "已核验主库存记录" },
      ];
      // Re-render old and new replies from structured facts, never extract numbers
      // from answer prose. Keep the original response/Evidence untouched.
      vm.answer = `${structured.reused_from_turn_id ? '依据本会话已有结果：' : ''}已完成 ${vm.product ?? '当前产品'} 本次生产需求核对。当前分析范围：${count(data.total_material_count) ?? '未知'}项物料。`;
      const maximum = count(data.theoretical_max_quantity);
      if (maximum !== null) vm.answer += `当前范围最大满足数量为${maximum}片。`;
      if (data.requested_quantity != null) {
        const sufficient = bool(data.inventory_sufficient_for_requested);
        vm.answer += sufficient === null ? "本次数量是否满足尚无法确认。" : `当前分析范围${sufficient ? '满足' : '不能满足'}生产${count(data.requested_quantity)}片对应的物料需求。`;
      }
      const shortages = list(data.book_shortages);
      if (shortages.length) vm.answer += "不足物料：" + shortages.slice(0,5).map(r => `${text(r.material_code)}缺${decimal(r.shortage_qty)}片`).join("；") + "。";
      const limiting = list(data.limiting_materials);
      if (limiting.length) vm.answer += "限制数量的物料：" + limiting.slice(0,5).map(r => text(r.material_code)).join("、") + "。";
      if (userMessage && /来源|哪里/.test(userMessage)) vm.answer += "BOM单耗来自已发布记录，库存数量来自已核验主库存记录；可在来源区查看本次依据。";
      if (data.synthetic === true) vm.answer += "本次包含演示库存，仅用于数量模拟。";
      if (vm.materials.length === 1 && userMessage?.includes(vm.materials[0].code ?? '\u0000')) {
        const m = vm.materials[0];
        vm.answer = `${m.code}：BOM单耗${m.qtyPer ?? '未知'}片，当前分析范围库存${m.recordedStock ?? '未知'}片。` + (data.synthetic === true ? "本次包含演示库存，仅用于数量模拟。" : "来源为已核验主库存记录。");
      }
      vm.warnings = vm.warnings.filter(w => !w.startsWith("经过筛选及标识脱敏") && !w.startsWith("仅为精简物料集合"));
      vm.materials.forEach(m => { m.name = m.name.replace(/^评审物料/, "物料"); });
      vm.detailTable = undefined;
    }
    return vm;
  }
  if (kind === "inventory") {
    vm.status = "inventory";
    vm.title = "物料库存事实";
    const row = material(data, item);
    row.onHand = decimal(data.on_hand_qty);
    row.reserved = decimal(data.reserved_qty);
    row.state = row.available === null ? "unknown" : "published";
    if (backend.status === "ok" && Object.keys(item).length)
      vm.materials.push(row);
    metric("在库数量", row.onHand);
    metric("可用数量", row.available);
    metric("预留数量", row.reserved);
    metric("批次数", count(data.batch_count));
    metric("库位数", count(data.location_count));
    metric("库存时点", text(data.query_snapshot_at));
  } else if (kind === "production_capacity") {
    const sufficient = bool(data.inventory_sufficient_for_requested);
    vm.status =
      sufficient === true
        ? "ready"
        : sufficient === false
          ? "blocked"
          : "uncalculable";
    vm.title =
      sufficient === true
        ? "本次需求库存齐套"
        : sufficient === false
          ? "本次需求存在物料缺口"
          : "生产能力查询";
    vm.conclusion = "库存齐套分析，不是开工许可或交付承诺";
    metric("理论最大生产数量", count(data.theoretical_max_quantity));
    metric("物料种类齐套比例（0–1）", decimal(data.material_type_ready_rate));
    metric("数量满足比例（0–1）", decimal(data.quantity_fulfillment_rate));
    vm.materials = list(data.materials).map((row) => {
      const m = material(row);
      const ready = bool(row.is_ready);
      m.state =
        ready === true
          ? "sufficient"
          : ready === false
            ? "shortage"
            : "unknown";
      return m;
    });
    const limiting = list(data.limiting_materials)
      .map((row) => text(row.material_code))
      .filter(Boolean);
    if (limiting.length) metric("限制产量的物料", limiting.join("、"));
  } else if (kind === "bom") {
    vm.status = "bom";
    vm.title = "已发布 BOM 明细";
    metric("BOM 版本", text(data.revision));
    metric("生效日期", text(data.effective_from));
    metric("明细数量", count(data.line_count));
    vm.materials = list(data.lines).map((row) => {
      const m = material(row, object(row.child_item));
      m.qtyPer = decimal(row.qty_per);
      m.state = "published";
      const lineSources = sourcesFrom(
        row.provenance,
        backend.scenario_id != null,
      );
      if (lineSources.length) {
        m.sourceIds = lineSources.map((source) => {
          source.id = `source-${sources.length + 1}`;
          sources.push(source);
          return source.id;
        });
      }
      return m;
    });
  } else if (kind === "purchase_planning") {
    vm.status = "purchase";
    vm.title = "已发布事实采购建议";
    vm.conclusion = "建议不代表已下单或已到货";
    vm.purchases = list(data.recommendations).map((row): PurchaseView => ({
      material: text(row.material) ?? "物料未提供",
      unit: text(row.unit) ?? "",
      shortage: decimal(
        row.shortage_qty !== undefined ? row.shortage_qty : row.shortage,
      ),
      suggested: decimal(
        row.suggested_purchase_qty !== undefined
          ? row.suggested_purchase_qty
          : row.purchase_qty,
      ),
      cost: decimal(row.purchase_cost),
      currency: text(row.currency),
      supplier: text(row.supplier),
      leadTime: count(row.lead_time_days),
      risk:
        row.risk_level == null
          ? null
          : (riskLabels[text(row.risk_level)!] ?? "未提供"),
      reasons: strings(row.reason),
      missingFields: strings(row.missing_fields),
    }));
    vm.materials = list(data.recommendations).map((row) => {
      const m = material(row);
      // Display the returned shortage only; never subtract stock from demand,
      // substitute on-hand for available, or use a purchase quantity as stock.
      if (m.available !== null) {
        const coefficient = m.shortage?.split(/[eE]/)[0];
        m.state =
          coefficient == null
            ? "published"
            : !/[1-9]/.test(coefficient)
              ? "sufficient"
              : !coefficient.startsWith("-")
                ? "shortage"
                : "published";
      }
      return m;
    });
    metric("总采购成本", decimal(data.total_purchase_cost));
    metric("成本币种", text(data.total_cost_currency));
  } else if (kind === "inventory_batches") {
    vm.status = "batches";
    vm.title = "库存批次明细";
    metric("库存时点", text(data.query_snapshot_at));
    vm.detailTable = {
      columns: ["批次", "库位", "在库数量", "收货时间", "有效期", "质量状态"],
      rows: list(data.batches).map((row) => [
        text(row.batch_no),
        text(row.location),
        decimal(row.on_hand_qty),
        text(row.received_at),
        text(row.expiry_date),
        text(row.quality_status),
      ]),
    };
  } else if (kind === "inbound") {
    vm.status = "inbound";
    vm.title = "已发布在途事实";
    metric("订购数量", decimal(data.ordered_qty));
    metric("已收数量", decimal(data.received_qty));
    metric("在途数量", decimal(data.in_transit_qty));
    vm.detailTable = {
      columns: ["订单", "供应商", "在途数量", "预计到货", "承诺日期"],
      rows: list(data.lines).map((row) => [
        text(row.order_no),
        text(row.supplier_code),
        decimal(row.in_transit_qty),
        text(row.expected_arrival_date),
        text(row.committed_date),
      ]),
    };
  } else if (["fact_query", "product_search"].includes(kind) && Array.isArray(data.products)) {
    const mixed = list(data.products).some(p => p.synthetic === true || p.published_bom_status === "synthetic");
    vm.title = mixed ? "可查询产品目录" : "已发布产品目录";
    vm.conclusion = "已发布BOM不代表可以开工；不同产品与分析范围分别核对。";
    vm.answer = "当前可查询产品：" + list(data.products).map(p => `${text(p.product_code)}${p.synthetic === true || p.published_bom_status === 'synthetic' ? '（演示产品）' : ''}`).join("、") + "。请选择产品并描述分析需求。";
    vm.nextAction = "选择产品编码并补充生产数量后，再核验齐套情况。";
    vm.detailTable = {
      columns: ["产品编码", "产品名称", "BOM状态", "已发布版本"],
      rows: list(data.products).map((row) => [
        text(row.product_code),
        text(row.product_name),
        row.synthetic === true || row.published_bom_status === "synthetic" ? "演示产品" : row.published_bom_status === "published" ? "已发布" : "未知",
        list(row.revisions)
          .map((version) => text(version.revision))
          .filter(Boolean)
          .join("、") || null,
      ]),
    };
  } else if (kind === "pmc_analysis") {
    // Legacy responses are not the published-fact contract. Keep prose only until a dedicated mapping exists.
    vm.title = "生产分析回答";
    vm.quantity = null;
  }
  const states: Record<string, [ResultStatus, string]> = {
    item_not_found: ["no-facts", "未找到该物料"],
    data_unavailable: ["no-facts", "已发布事实不足"],
    invalid_query: ["clarification", "请确认查询条件"],
    needs_input: ["clarification", "需要补充查询信息"],
    item_alias_ambiguous: ["conflict", "物料别名需要确认"],
    query_failed: ["uncalculable", "查询暂未完成"],
    unavailable: ["uncalculable", "分析服务暂不可用"],
  };
  if (states[backend.status]) [vm.status, vm.title] = states[backend.status];
  else if (backend.status !== "ok") {
    vm.status = "uncalculable";
    vm.title = "结果状态暂无法确认";
  }
  if (
    backend.intent === "clarification" &&
    backend.status === "ok" &&
    structured.operation === "conversation"
  ) {
    vm.title = "企业助手能力介绍";
    vm.conclusion = "可先查看已发布产品，再描述生产需求。";
    vm.nextAction = "试着问“有哪些产品”，或输入产品编码和生产数量。";
  } else if (
    backend.intent === "clarification" ||
    backend.status === "needs_input"
  ) {
    vm.status = "clarification";
    vm.title = "需要补充查询信息";
    const fields = strings(structured.missing_fields);
    metric("待补充信息", fields.length ? fields.join("、") : null);
  }
  return vm;
}
