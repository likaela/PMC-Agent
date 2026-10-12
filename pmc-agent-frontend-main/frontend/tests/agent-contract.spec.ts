import { test, expect } from "@playwright/test";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import {
  createAgentClient,
  createLiveService,
} from "../src/services/apiClient";
import {
  sessionKey,
  saveSession,
  readSession,
  clearSession,
  readPreference,
  savePreference,
  readInitialScenario,
} from "../src/services/sessionStorage";
import {
  inventory,
  production,
  purchase,
  envelope,
  source,
  session,
  scenarioId,
} from "./agentFixtures";

test("普通问候展示能力介绍，不伪装缺参数或业务结果", () => {
  const vm = adaptBackendResponse(envelope("clarification", null, {
    answer: "您好，我是PMC助手。", structured_data: { operation: "conversation", completed_steps: [] },
  }));
  expect(vm.title).toBe("企业助手能力介绍");
  expect(vm.status).toBe("result");
  expect(vm.materials).toEqual([]);
});

test("已发布产品目录只映射结构化数据，不将产品发现当成可生产", () => {
  const vm = adaptBackendResponse(envelope("fact_query", {
    products: [{ product_code: "KQ-Z112", product_name: null,
      published_bom_status: "published", revisions: [{ revision: "V01" }] }],
  }, { answer: "文本包含不存在的产品FAKE-999", provenance: { bom_sources: [source] } }));
  expect(vm.title).toBe("已发布产品目录");
  expect(vm.detailTable?.rows).toEqual([["KQ-Z112", "已发布", "V01"]]);
  expect(vm.detailTable?.columns).not.toContain("产品名称");
  expect(vm.status).not.toBe("ready");
  expect(vm.sources[0]?.reference).toBe("inventory_facts.json");
  expect(vm.materials).toEqual([]);
});

test("库存响应映射：Decimal 字符串精度与 null 原样保留", () => {
  const result = adaptBackendResponse(
    inventory({ answer: "库存999999，不应从此句生成表格。" }),
  );
  expect(result.materials[0].onHand).toBe("100.000");
  expect(result.materials[0].available).toBeNull();
  expect(result.materials[0].reserved).toBeNull();
  expect(result.metrics?.find((m) => m.label === "批次数")?.value).toBe("2");
});
test("50 台 Demo 映射齐套，不生成开工许可", () => {
  const result = adaptBackendResponse(production(50));
  expect(result.status).toBe("ready");
  expect(result.quantity).toBe("50");
  expect(result.materials.map((m) => m.shortage)).toEqual(["0", "0", "0", "0"]);
  expect(result.conclusion).toContain("不是开工许可");
});
test("100 台成功查询仍显示缺料，不将 ok 变为 ready", () => {
  const result = adaptBackendResponse(production(100));
  expect(result.status).toBe("blocked");
  expect(result.materials.map((m) => m.shortage)).toEqual([
    "25",
    "100",
    "50",
    "200",
  ]);
  expect(
    result.metrics?.find((m) => m.label === "理论最大生产数量")?.value,
  ).toBeUndefined();
  expect((production(100).structured_data!.data as any).theoretical_max_quantity).toBe(75);
});
test("无库存事实不生成零库存行", () => {
  const result = adaptBackendResponse(
    envelope("inventory", null, { status: "data_unavailable" }),
  );
  expect(result.status).toBe("no-facts");
  expect(result.materials).toEqual([]);
  expect(result.metrics?.find((m) => m.label === "在库数量")).toBeUndefined();
  expect(result.backend?.structured_data?.data).toBeNull();
});
test("来源保留文件、批次、快照、工作表、行号和完整 hash", () => {
  const result = adaptBackendResponse(inventory());
  expect(result.sources[0]).toMatchObject({
    reference: "inventory_facts.json",
    importBatch: source.import_batch_id,
    snapshotAt: source.snapshot_at,
    sheet: "inventory",
    row: "7",
    sha256: source.content_sha256,
  });
  expect(result.sources[0].publishedAt).toBeNull();
});
test("provenance 数组可映射，不能当成对象异常", () => {
  expect(
    adaptBackendResponse(inventory({ provenance: [source] })).sources,
  ).toHaveLength(1);
});
test("生产库存来源按物料关联，不串用其他物料来源", () => {
  const result = adaptBackendResponse(production(100));
  const ids = result.materials[0].sourceIds;
  expect(
    result.sources
      .filter((s) => ids.includes(s.id) && s.materialCode)
      .map((s) => s.materialCode),
  ).toEqual(["DEMO-BOARD-01"]);
});
test("BOM 单位用量不伪造为生产需求，支持行级来源", () => {
  const result = adaptBackendResponse(
    envelope("bom", {
      parent_item: { material_code: "KQ-Z112" },
      revision: "V01",
      lines: [
        {
          child_item: { material_code: "MAT-001", name: "主板" },
          qty_per: "2.5",
          unit: "pcs",
          provenance: source,
        },
      ],
    }),
  );
  expect(result.materials[0].qtyPer).toBe("2.5");
  expect(result.materials[0].required).toBeNull();
  expect(result.materials[0].sourceIds).toHaveLength(1);
});
test("采购建议、成本与风险直接来自已发布计算结果", () => {
  const result = adaptBackendResponse(purchase());
  expect(result.purchases?.[0]).toMatchObject({
    suggested: "30",
    cost: "600.00",
    risk: "高风险",
  });
  expect(result.metrics?.find((m) => m.label === "总采购成本")?.value).toBe(
    "1560.00",
  );
});
test("缺失采购价格与采购量保持未知，不触发前端计算", () => {
  const response = purchase();
  const data = response.structured_data!.data as Record<string, unknown>;
  data.total_purchase_cost = null;
  (data.recommendations as Record<string, unknown>[])[0].purchase_cost = null;
  (
    data.recommendations as Record<string, unknown>[]
  )[0].suggested_purchase_qty = null;
  const result = adaptBackendResponse(response);
  expect(result.purchases?.[0].suggested).toBeNull();
  expect(result.purchases?.[0].cost).toBeNull();
});
test("澄清展示缺失字段，不从 answer 生成任务数量", () => {
  const result = adaptBackendResponse(
    envelope("clarification", null, {
      status: "needs_input",
      structured_data: {
        missing_fields: ["生产数量"],
        query: { material_code: "MAT-001" },
      },
    }),
  );
  expect(result.status).toBe("clarification");
  expect(result.quantity).toBeNull();
  expect(result.materials).toHaveLength(0);
});
test("批次与在途明细未知字段保持 null", () => {
  const batch = adaptBackendResponse(
    envelope("inventory_batches", {
      batches: [{ on_hand_qty: "0", batch_no: "B1" }],
    }),
  );
  expect(batch.detailTable?.rows[0]).toEqual(["B1", "0"]);
  expect(batch.detailTable?.columns).toEqual(["批次", "在库数量"]);
  expect((batch.backend?.structured_data?.data as Record<string,unknown>).batches).toEqual([{on_hand_qty:"0",batch_no:"B1"}]);
  const inbound = adaptBackendResponse(
    envelope("inbound", {
      ordered_qty: "10",
      received_qty: null,
      in_transit_qty: null,
    }),
  );
  expect(
    inbound.metrics?.find((m) => m.label === "在途数量"),
  ).toBeUndefined();
  expect((inbound.backend?.structured_data?.data as Record<string,unknown>).in_transit_qty).toBeNull();
});
test("异常结构或数值类型拒绝，不把 number 误当 Decimal", () => {
  expect(() => adaptBackendResponse({ intent: "inventory" })).toThrow();
  expect(() =>
    adaptBackendResponse(envelope("inventory", { on_hand_qty: 100 })),
  ).toThrow();
});
test("queryAgent 仅发送约定字段，不泄漏旧 workflow 上下文", async () => {
  const calls: { url: string; body: unknown; method?: string }[] = [];
  const fetcher: typeof fetch = async (url, options) => {
    calls.push({
      url: String(url),
      body: JSON.parse(String(options?.body)),
      method: options?.method,
    });
    return Response.json(inventory());
  };
  await createAgentClient({
    baseUrl: "http://localhost:8000/",
    fetch: fetcher,
  }).queryAgent({
    message: "查询MAT-001库存",
    session_id: session.session_id,
    persist_session: true,
    ...({ workflow_id: "must-not-send" } as object),
  });
  expect(calls[0]).toEqual({
    url: "http://localhost:8000/api/v1/agent/query",
    method: "POST",
    body: {
      message: "查询MAT-001库存",
      session_id: session.session_id,
      persist_session: true,
    },
  });
});
test("目录序号随真实API发送，仍保留原始问题", async () => {
  let body: any;
  const client = createAgentClient({
    baseUrl: "http://localhost:8000",
    fetch: async (_url, options) => {
      body = JSON.parse(String(options?.body));
      return Response.json(inventory());
    },
  });
  await client.queryAgent({ message: "切换到第一个产品", catalog_order: ["EXAMPLE-A"] });
  expect(body).toEqual({ message: "切换到第一个产品", catalog_order: ["EXAMPLE-A"] });
});

test("创建与恢复 Demo 会话始终传递 scenario_id", async () => {
  const urls: string[] = [];
  const bodies: unknown[] = [];
  const fetcher: typeof fetch = async (url, options) => {
    urls.push(String(url));
    bodies.push(options?.body ? JSON.parse(String(options.body)) : null);
    return Response.json({ ...session, scenario_id: scenarioId, turns: [] });
  };
  const client = createAgentClient({
    baseUrl: "http://localhost:8000",
    fetch: fetcher,
  });
  expect((await client.createSession(scenarioId)).session_id).toBe(
    session.session_id,
  );
  await client.getSession(session.session_id, scenarioId);
  expect(bodies[0]).toEqual({ scenario_id: scenarioId });
  expect(urls[1]).toContain("scenario_id=demo_scenario_50_vs_100");
});
test("session_id 可保存恢复，按地址与场景隔离，不缓存业务结果", () => {
  const map = new Map<string, string>();
  const storage = {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, value);
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
  };
  const key = sessionKey("http://localhost:8000", scenarioId);
  saveSession(storage, key, {
    session_id: session.session_id,
    scenario_id: scenarioId,
  });
  expect(readSession(storage, key, scenarioId)?.session_id).toBe(
    session.session_id,
  );
  expect(readSession(storage, sessionKey("http://localhost:8000"))).toBeNull();
  expect(
    readSession(
      storage,
      sessionKey("http://localhost:8001", scenarioId),
      scenarioId,
    ),
  ).toBeNull();
  expect(map.get(key)).not.toContain("inventory");
  savePreference(storage, "http://localhost:8000", {
    mode: "live",
    scenario_id: scenarioId,
  });
  expect(readPreference(storage, "http://localhost:8000")?.mode).toBe("live");
  clearSession(storage, key);
  expect(readSession(storage, key, scenarioId)).toBeNull();
});
for (const sample of [
  {
    name: "旧 Demo 偏好不是主动选择",
    reload: true,
    marker: undefined,
    mode: "live",
    pointer: scenarioId,
    expected: null,
  },
  {
    name: "首次导航不自动恢复 Demo",
    reload: false,
    marker: true,
    mode: "live",
    pointer: scenarioId,
    expected: null,
  },
  {
    name: "即使主动选择过 Demo 刷新也先回企业空间",
    reload: true,
    marker: true,
    mode: "live",
    pointer: scenarioId,
    expected: null,
  },
  {
    name: "未创建会话不从偏好注入 Demo",
    reload: true,
    marker: true,
    mode: "live",
    pointer: undefined,
    expected: null,
  },
  {
    name: "指针场景错配拒绝恢复",
    reload: true,
    marker: true,
    mode: "live",
    pointer: null,
    expected: null,
  },
  {
    name: "未主动选择标记拒绝恢复",
    reload: true,
    marker: false,
    mode: "live",
    pointer: scenarioId,
    expected: null,
  },
  {
    name: "离线偏好不能自动恢复在线 Demo",
    reload: true,
    marker: true,
    mode: "mock",
    pointer: scenarioId,
    expected: null,
  },
] as const) {
  test(`初始化隔离：${sample.name}`, () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => {
        values.set(key, value);
      },
      removeItem: (key: string) => {
        values.delete(key);
      },
    };
    savePreference(storage, "http://localhost:8000", {
      mode: sample.mode,
      scenario_id: scenarioId,
      demo_selected: sample.marker,
    });
    if (sample.pointer !== undefined)
      saveSession(storage, sessionKey("http://localhost:8000", scenarioId), {
        session_id: "saved-demo",
        scenario_id: sample.pointer,
      });
    expect(
      readInitialScenario(storage, "http://localhost:8000", sample.reload),
    ).toBe(sample.expected);
    expect(
      readInitialScenario(storage, "http://localhost:8001", sample.reload),
    ).toBeNull();
  });
}

test("企业指针的 null 与省略场景等价，但不能恢复 Demo 指针", () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    },
  };
  const key = sessionKey("http://localhost:8000", null);
  saveSession(storage, key, { session_id: "enterprise", scenario_id: null });
  expect(readSession(storage, key)?.session_id).toBe("enterprise");
  saveSession(storage, key, { session_id: "enterprise" });
  expect(readSession(storage, key, null)?.session_id).toBe("enterprise");
  saveSession(storage, key, {
    session_id: "wrong-space",
    scenario_id: scenarioId,
  });
  expect(readSession(storage, key, null)).toBeNull();
  expect(storage.getItem(key)).toBeNull();
});

test("HTTP 内部异常脱敏且 live 失败不能回退 mock", async () => {
  const service = createLiveService({
    baseUrl: "http://localhost:8000",
    fetch: async () =>
      Response.json(
        { traceback: "secret-key", user_message: "exception: secret-key" },
        { status: 500 },
      ),
  });
  await expect(
    service.query({ text: "查询主板库存" }, new AbortController().signal),
  ).rejects.toMatchObject({
    code: "server",
    message: "分析服务暂时异常，请稍后重试。",
  });
});
test("timeout 和主动 abort 分别可识别", async () => {
  const fetcher: typeof fetch = (_url, options) =>
    new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError")),
      );
    });
  const client = createAgentClient({
    baseUrl: "http://localhost:8000",
    fetch: fetcher,
    timeoutMs: 10,
  });
  await expect(client.queryAgent({ message: "库存" })).rejects.toMatchObject({
    code: "timeout",
  });
  const controller = new AbortController();
  const request = client.queryAgent({ message: "库存" }, controller.signal);
  controller.abort();
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
});
test("网络异常、非法 JSON 和未配置分别拒绝", async () => {
  await expect(
    createAgentClient({
      baseUrl: "http://localhost:8000",
      fetch: async () => {
        throw Error("private path");
      },
    }).queryAgent({ message: "库存" }),
  ).rejects.toMatchObject({ code: "network" });
  await expect(
    createAgentClient({
      baseUrl: "http://localhost:8000",
      fetch: async () => new Response("bad-json"),
    }).queryAgent({ message: "库存" }),
  ).rejects.toMatchObject({ code: "mapping" });
  await expect(
    createAgentClient({ baseUrl: "" }).queryAgent({ message: "库存" }),
  ).rejects.toMatchObject({ code: "unconfigured" });
});
