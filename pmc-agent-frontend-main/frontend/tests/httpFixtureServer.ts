// Test harness only. The application never imports this HTTP interception code.
import type { Page } from "@playwright/test";
import type {
  BackendResponse,
  BackendTurn,
  ScenarioId,
} from "../src/data/model";
import { session } from "./agentFixtures";

export async function httpFixtureServer(
  page: Page,
  respond: (message: string) => BackendResponse | "network" | "500" | "invalid",
  delayMs = 0,
) {
  const requests: {
    url: string;
    method: string;
    body: Record<string, unknown>;
  }[] = [];
  const sessions = new Map<
    string,
    { scenario: ScenarioId | null; turns: BackendTurn[] }
  >();
  await page.route("http://127.0.0.1:8000/api/v1/agent/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.method() === "POST" ? request.postDataJSON() : {};
    requests.push({ url: request.url(), method: request.method(), body });
    if (path.endsWith("/sessions") && request.method() === "POST") {
      const id = `http-session-${sessions.size + 1}`;
      const scenario = body.scenario_id ?? null;
      sessions.set(id, { scenario, turns: [] });
      await route.fulfill({
        json: { ...session, session_id: id, scenario_id: scenario },
      });
      return;
    }
    if (request.method() === "GET") {
      const id = path.split("/").at(-1)!;
      const state = sessions.get(id);
      if (!state) {
        await route.fulfill({ status: 404, json: {} });
        return;
      }
      const after = Number(
        new URL(request.url()).searchParams.get("after") ?? 0,
      );
      await route.fulfill({
        json: {
          ...session,
          session_id: id,
          scenario_id: state.scenario,
          turns: state.turns.filter((turn) => turn.sequence_no > after),
        },
      });
      return;
    }
    const response = respond(body.message);
    if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (response === "network") {
      await route.abort();
      return;
    }
    if (response === "500") {
      await route.fulfill({
        status: 500,
        json: { traceback: "PRIVATE_EXCEPTION" },
      });
      return;
    }
    if (response === "invalid") {
      await route.fulfill({
        json: { answer: "Invalid payload must not become local facts" },
      });
      return;
    }
    const state = sessions.get(body.session_id)!;
    const turnId = `turn-${state.turns.length + 1}`;
    const checked = {
      ...response,
      session_id: body.session_id,
      scenario_id: state.scenario,
      turn_id: turnId,
    };
    state.turns.push({
      turn_id: turnId,
      sequence_no: state.turns.length + 1,
      user_query: body.message,
      response: checked,
      created_at: session.created_at,
    });
    await route.fulfill({ json: checked });
  });
  return requests;
}
