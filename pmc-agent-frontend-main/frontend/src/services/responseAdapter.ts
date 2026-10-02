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
  if (p.scenario_id != null && p.scenario_id !== "demo_scenario_50_vs_100")
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
      const source: Source = {
        id: "",
        title: file ? file.split(/[\\/]/).pop()! : "已发布来源记录",
        kind: synthetic ? "合成演示事实" : "已发布事实",
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
        conditions: synthetic
          ? "独立合成演示事实，不代表企业真实库存。"
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

export function adaptBackendResponse(payload: unknown): FrontendViewModel {
  const backend = validateBackendResponse(payload);
  const structured = object(backend.structured_data);
  const data = object(structured.data);
  const query = object(structured.query);
  const kind = text(structured.query_type) ?? backend.intent;
  const completeness = object(structured.completeness);
  const sources = sourcesFrom(
    backend.provenance,
    backend.scenario_id != null ||
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
    answer: backend.answer,
    conclusion: "仅展示已发布事实",
    nextAction: "核对数据完整性与来源后使用。",
    materials: [],
    sources,
    warnings: [...backend.warnings],
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
    .filter(([field, value]) => value === false && completenessLabels[field])
    .map(([field]) => completenessLabels[field]);
  if (incomplete.length) metric("待核实事实", incomplete.join("、"));
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
  if (backend.intent === "clarification" || backend.status === "needs_input") {
    vm.status = "clarification";
    vm.title = "需要补充查询信息";
    const fields = strings(structured.missing_fields);
    metric("待补充信息", fields.length ? fields.join("、") : null);
  }
  return vm;
}
