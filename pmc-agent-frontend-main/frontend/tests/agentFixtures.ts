import type { BackendResponse, BackendSession } from "../src/data/model";

export const scenarioId = "demo_scenario_50_vs_100" as const;
export const source = {
  source_file: "inventory_facts.json",
  content_sha256: "a".repeat(64),
  import_batch_id: "batch-public-demo",
  snapshot_at: "2026-10-02T00:00:00+00:00",
  sheet_name: "inventory",
  row_number: 7,
};
export const session: BackendSession = {
  session_id: "session-test",
  conversation_id: "conversation-test",
  context_version: 0,
  created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z",
  context: {},
};
export function envelope(
  intent: BackendResponse["intent"],
  data: Record<string, unknown> | null,
  overrides: Partial<BackendResponse> = {},
): BackendResponse {
  return {
    intent,
    status: "ok",
    answer: "回答由后端生成，前端不提取数值。",
    warnings: [],
    structured_data: {
      query_type: intent,
      query: { material_code: "MAT-001" },
      data,
      completeness: {},
    },
    provenance: source,
    session_id: session.session_id,
    ...overrides,
  };
}
export function inventory(
  overrides: Partial<BackendResponse> = {},
): BackendResponse {
  return envelope(
    "inventory",
    {
      canonical_item: { material_code: "MAT-001", name: "主板", unit: "pcs" },
      on_hand_qty: "100.000",
      available_qty: null,
      reserved_qty: null,
      batch_count: 2,
      location_count: 2,
      query_snapshot_at: source.snapshot_at,
    },
    overrides,
  );
}
export function production(quantity: 50 | 100): BackendResponse {
  const enough = quantity === 50;
  const codes = [
    "DEMO-BOARD-01",
    "DEMO-CHIP-01",
    "DEMO-MOTOR-01",
    "DEMO-SCREW-01",
  ];
  const requirements = enough
    ? ["50", "200", "100", "400"]
    : ["100", "400", "200", "800"];
  const available = ["75", "300", "150", "600"];
  const shortage = enough ? ["0", "0", "0", "0"] : ["25", "100", "50", "200"];
  return envelope(
    "production_capacity",
    {
      product: "DEMO-PMC-01",
      revision: "V01",
      product_unit: "pcs",
      requested_quantity: quantity,
      theoretical_max_quantity: 75,
      inventory_sufficient_for_requested: enough,
      material_type_ready_rate: enough ? "1" : "0",
      quantity_fulfillment_rate: enough ? "1" : "0.75",
      materials: codes.map((material_code, i) => ({
        material_code,
        unit: "pcs",
        required_qty: requirements[i],
        available_qty: available[i],
        shortage_qty: shortage[i],
        is_ready: enough,
      })),
      limiting_materials: codes.map((material_code) => ({ material_code })),
    },
    {
      scenario_id: scenarioId,
      answer: enough
        ? "50台库存齐套，不代表开工许可。"
        : "100台方案缺料，不能立即满足需求。",
      provenance: {
        synthetic: true,
        scenario_id: scenarioId,
        bom: [{ ...source, source_file: "bom_facts.json", revision: "V01" }],
        inventory: codes.map((material_code) => ({ ...source, material_code })),
      },
    },
  );
}
export function purchase(): BackendResponse {
  return envelope(
    "purchase_planning",
    {
      product: "DEMO-PMC-01",
      quantity: 100,
      total_purchase_cost: "1560.00",
      total_cost_currency: "CNY",
      recommendations: [
        {
          material: "DEMO-BOARD-01",
          unit: "pcs",
          required_qty: "100",
          available_qty: "75",
          shortage_qty: "25",
          suggested_purchase_qty: "30",
          purchase_cost: "600.00",
          supplier: "DEMO-SUP-01",
          lead_time_days: 8,
          risk_level: "high",
          currency: "CNY",
          reason: ["MOQ 与包装倍数约束"],
          missing_fields: [],
        },
      ],
    },
    { scenario_id: scenarioId },
  );
}
