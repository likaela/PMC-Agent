import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { envelope } from "./agentFixtures";
test("数量只接受数值；普通生产和BOM不展示最大产量", () => {
  const response = envelope("production_capacity", {
    product: "EXAMPLE",
    requested_quantity: 1,
    theoretical_max_quantity: 75,
    inventory_sufficient_for_requested: true,
    materials: [],
  });
  expect(
    adaptBackendResponse(response, "生产1台").metrics?.some((m) =>
      m.label.includes("最大"),
    ),
  ).toBe(false);
  expect(
    adaptBackendResponse(response, "最多能生产多少台").metrics?.find((m) =>
      m.label.includes("最大"),
    )?.value,
  ).toBe("75");
  (response.structured_data!.data as any).requested_quantity =
    "本轮查询分析范围／最大数量";
  expect(() => adaptBackendResponse(response)).toThrow();
});
test("产品概览不制造数量和库存，目录不使用旧产品", () => {
  const r = envelope("fact_query", {
    product: "EXAMPLE",
    revision: "V01",
    line_count: 3,
    analysis_scope: "产品分析",
  });
  r.structured_data!.query_type = "product_overview";
  const vm = adaptBackendResponse(r);
  expect(vm.quantity).toBeNull();
  expect(vm.materials).toEqual([]);
  expect(vm.metrics?.map((m) => m.label)).not.toContain("理论最大生产数量");
  r.structured_data!.query_type = "product_search";
  r.structured_data!.data = { products: [] };
  expect(adaptBackendResponse(r).product).toBeNull();
});
