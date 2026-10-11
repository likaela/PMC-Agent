import { test, expect } from "@playwright/test";
import { createAgentClient } from "../src/services/apiClient";
import { session } from "./agentFixtures";

test("同源根地址发送真实API请求，不进入未配置或mock", async () => {
  const calls: string[] = [];
  const client = createAgentClient({
    baseUrl: "/",
    fetch: async (url) => {
      calls.push(String(url));
      return new Response(JSON.stringify(session), { status: 200 });
    },
  });
  await client.createSession();
  expect(calls).toEqual(["/api/v1/agent/sessions"]);
});

test("同源API 500不产生演示成功响应", async () => {
  const client = createAgentClient({
    baseUrl: "/",
    fetch: async () => new Response("internal", { status: 500 }),
  });
  await expect(client.createSession()).rejects.toMatchObject({
    code: "server",
  });
});
