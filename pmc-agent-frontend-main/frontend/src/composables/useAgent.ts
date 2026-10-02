import { computed, ref, shallowRef } from "vue";
import {
  QueryError,
  type AgentResult,
  type DataMode,
  type ScenarioId,
  type BackendTurn,
} from "../data/model";
import { createMockService } from "../services/mockService";
import { createAgentClient, configuredBaseUrl } from "../services/apiClient";
import { adaptBackendResponse } from "../services/responseAdapter";
import {
  sessionKey,
  saveSession,
  readSession,
  clearSession,
  readPreference,
  savePreference,
} from "../services/sessionStorage";

interface Message {
  id: number;
  question: string;
  requestedAt: string;
  state: "pending" | "done" | "error" | "cancelled";
  result?: AgentResult;
  error?: QueryError;
  sequenceNo?: number;
  attemptAfter?: number;
  uncertain?: boolean;
}
const initialStorage = storage();
const preference = initialStorage
  ? readPreference(initialStorage, configuredBaseUrl())
  : null;
const mode = ref<DataMode>(
  preference?.mode ??
    (import.meta.env.VITE_DATA_MODE === "mock" ? "mock" : "live"),
);
const scenario = ref<ScenarioId | undefined>(
  preference
    ? preference.scenario_id
    : import.meta.env.VITE_SCENARIO_ID === "demo_scenario_50_vs_100"
      ? "demo_scenario_50_vs_100"
      : undefined,
);
const sessionId = ref<string>();
const messages = ref<Message[]>([]);
const selectedId = ref<number | null>(null);
const pending = ref(false);
const notice = ref("");
const draft = ref("");
const controller = shallowRef<AbortController>();
let sequence = 0;
let messageId = 0;
let initialized = false;
const mockService = createMockService();
const client = createAgentClient();
const selected = computed(() =>
  messages.value.find((m) => m.id === selectedId.value),
);
const result = computed(() => selected.value?.result);
function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}
function key() {
  return sessionKey(configuredBaseUrl(), scenario.value);
}
function remember() {
  const s = storage();
  if (s && sessionId.value)
    saveSession(s, key(), {
      session_id: sessionId.value,
      scenario_id: scenario.value,
    });
}
function rememberPreference() {
  const s = storage();
  if (s)
    savePreference(s, configuredBaseUrl(), {
      mode: mode.value,
      scenario_id: scenario.value,
    });
}
function forget() {
  const s = storage();
  if (s) clearSession(s, key());
  sessionId.value = undefined;
}
function cancel() {
  if (!pending.value) return;
  controller.value?.abort();
  sequence++;
  const active = messages.value.find((m) => m.state === "pending");
  if (active) {
    active.state = "cancelled";
    active.uncertain = mode.value === "live";
  }
  pending.value = false;
  notice.value =
    mode.value === "live"
      ? "已停止等待；服务端可能仍在分析，请先恢复会话确认结果。"
      : "已取消本次离线请求，可以修改问题或重试。";
}
function reset() {
  cancel();
  forget();
  messages.value = [];
  selectedId.value = null;
  draft.value = "";
  notice.value = "";
}
function setMode(value: DataMode) {
  if (mode.value === value) return;
  reset();
  mode.value = value;
  rememberPreference();
  notice.value = "查询模式已切换，当前展示已清除。";
  if (value === "live") void restoreSession();
}
function setScenario(value: ScenarioId | undefined) {
  if (scenario.value === value) return;
  reset();
  scenario.value = value;
  rememberPreference();
  notice.value = value
    ? "已切换到独立合成 Demo，不会修改企业事实。"
    : "已切换到企业事实查询。";
  if (mode.value === "live") void restoreSession();
}
async function restoreSession(): Promise<BackendTurn[] | null> {
  if (mode.value !== "live" || pending.value) return null;
  if (!sessionId.value) {
    const s = storage();
    const pointer = s ? readSession(s, key(), scenario.value) : null;
    sessionId.value = pointer?.session_id;
  }
  if (!sessionId.value) return null;
  const token = ++sequence;
  const abort = new AbortController();
  controller.value = abort;
  pending.value = true;
  try {
    const turns: BackendTurn[] = [];
    let after = 0;
    // Paginate saved responses; never rerun historical tools or calculations.
    for (;;) {
      const page = await client.getSession(
        sessionId.value,
        scenario.value,
        after,
        abort.signal,
      );
      if (
        page.session_id !== sessionId.value ||
        (page.scenario_id ?? undefined) !== scenario.value
      )
        throw new QueryError("mapping", "会话来源不一致，请重新开始分析。");
      if (!page.turns.length) break;
      for (const turn of page.turns) {
        if (turn.sequence_no <= after)
          throw new QueryError("mapping", "会话顺序暂无法确认。");
        after = turn.sequence_no;
        turns.push(turn);
      }
      if (page.turns.length < 200) break;
    }
    const restored: Message[] = turns.map((turn) => ({
      id: ++messageId,
      question: turn.user_query,
      requestedAt: turn.created_at,
      sequenceNo: turn.sequence_no,
      state: "done",
      result: adaptBackendResponse(turn.response),
    }));
    if (token !== sequence || abort.signal.aborted) return null;
    messages.value = restored;
    selectedId.value = restored.at(-1)?.id ?? null;
    notice.value = "已恢复当前会话及已保存的分析结果。";
    return turns;
  } catch (error) {
    if (token !== sequence || abort.signal.aborted) return null;
    if (error instanceof QueryError && error.code === "session") {
      forget();
      messages.value = [];
      selectedId.value = null;
      notice.value = "当前会话已失效，请新建分析。";
    } else {
      notice.value =
        "暂时无法恢复会话，请检查连接后再次恢复；未切换到离线数据。";
    }
    return null;
  } finally {
    if (token === sequence) pending.value = false;
  }
}
async function send(candidate: unknown = draft.value) {
  const text = typeof candidate === "string" ? candidate.trim() : "";
  if (!text || pending.value) return;
  const token = ++sequence;
  const abort = new AbortController();
  controller.value = abort;
  const message: Message = {
    id: ++messageId,
    question: text,
    state: "pending",
    requestedAt: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    attemptAfter: Math.max(0, ...messages.value.map((m) => m.sequenceNo ?? 0)),
  };
  messages.value.push(message);
  selectedId.value = message.id;
  pending.value = true;
  notice.value = "";
  draft.value = "";
  try {
    let data: AgentResult;
    if (mode.value === "mock") {
      data = await mockService.query({ text }, abort.signal);
    } else {
      // Create and save the pointer before querying so timeout/refresh can recover the server turn.
      if (!sessionId.value) {
        const session = await client.createSession(
          scenario.value,
          abort.signal,
        );
        if (token !== sequence || abort.signal.aborted) return;
        sessionId.value = session.session_id;
        remember();
      }
      const response = await client.queryAgent(
        {
          message: text,
          session_id: sessionId.value,
          scenario_id: scenario.value,
          persist_session: true,
        },
        abort.signal,
      );
      if (token !== sequence || abort.signal.aborted) return;
      if (
        response.session_id !== sessionId.value ||
        (response.scenario_id ?? undefined) !== scenario.value
      )
        throw new QueryError("mapping", "会话来源不一致，请恢复会话后重试。");
      data = adaptBackendResponse(response);
      message.sequenceNo = (message.attemptAfter ?? 0) + 1;
      remember();
    }
    if (token !== sequence || abort.signal.aborted) return;
    const current = messages.value.find((m) => m.id === message.id)!;
    current.result = data;
    current.state = "done";
  } catch (error) {
    if (token !== sequence || abort.signal.aborted) return;
    const current = messages.value.find((m) => m.id === message.id)!;
    current.error =
      error instanceof QueryError
        ? error
        : new QueryError("network", "请求失败，请检查连接后重试。");
    current.state = "error";
    current.uncertain = mode.value === "live";
    draft.value = text;
  } finally {
    if (token === sequence) pending.value = false;
  }
}
function select(id: number) {
  if (!pending.value) {
    selectedId.value = id;
    notice.value = "";
  }
}
async function retry() {
  const previous = selected.value;
  if (!previous || pending.value) return;
  if (mode.value === "live" && previous.uncertain && sessionId.value) {
    const turns = await restoreSession();
    if (turns === null) return;
    if (
      turns.some(
        (t) =>
          t.sequence_no > (previous.attemptAfter ?? 0) &&
          t.user_query === previous.question,
      )
    ) {
      notice.value = "已恢复服务端保存的回答，无需重复发送。";
      return;
    }
  }
  return send(previous.question);
}
export function useAgent() {
  if (!initialized) {
    initialized = true;
    void restoreSession();
  }
  return {
    mode,
    scenario,
    sessionId,
    messages,
    selected,
    selectedId,
    result,
    pending,
    notice,
    draft,
    send,
    retry,
    cancel,
    reset,
    setMode,
    setScenario,
    restoreSession,
    select,
  };
}
