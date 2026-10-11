import { computed, ref, shallowRef } from "vue";
import {
  QueryError,
  type AgentResult,
  type DataMode,
  type ScenarioId,
  type BackendTurn,
} from "../data/model";
import { createAgentClient, configuredBaseUrl } from "../services/apiClient";
import { adaptBackendResponse } from "../services/responseAdapter";
import { trialMode, trialScenario } from "../services/trialMode";
import {
  sessionKey,
  saveSession,
  readSession,
  clearSession,
  readPreference,
  savePreference,
  readInitialScenario,
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
// Legacy offline preferences must never choose the production transport.
if (initialStorage) readPreference(initialStorage, configuredBaseUrl());
const mode = ref<DataMode>("live");
const isReload =
  (
    performance.getEntriesByType("navigation")[0] as
      PerformanceNavigationTiming | undefined
  )?.type === "reload";
const scenario = ref<ScenarioId | null>(
  trialMode
    ? trialScenario
    : initialStorage
      ? readInitialScenario(initialStorage, configuredBaseUrl(), isReload)
      : null,
);
const sessionId = ref<string | null>(null);
const messages = ref<Message[]>([]);
const selectedId = ref<number | null>(null);
const pending = ref(false);
const notice = ref("");
const draft = ref("");
const controller = shallowRef<AbortController>();
let sequence = 0;
let messageId = 0;
let initialized = false;
const client = createAgentClient();
const selected = computed(() =>
  messages.value.find((m) => m.id === selectedId.value),
);
// A greeting remains in history but cannot masquerade as a business result.
const result = computed(() =>
  selected.value?.result?.conversation
    ? null
    : (selected.value?.result ?? null),
);
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
      demo_selected: scenario.value !== null,
    });
}
function forget() {
  const s = storage();
  if (s) clearSession(s, key());
  sessionId.value = null;
}
function cancel() {
  if (!pending.value) return;
  controller.value?.abort();
  sequence++;
  const active = messages.value.find((m) => m.state === "pending");
  if (active) {
    active.state = "cancelled";
    active.uncertain = true;
  }
  pending.value = false;
  notice.value = "已停止等待；服务端可能仍在分析，请先恢复会话确认结果。";
}
function reset() {
  cancel();
  forget();
  messages.value = [];
  selectedId.value = null;
  draft.value = "";
  notice.value = "";
}
function startEnterpriseAnalysis() {
  reset();
  mode.value = "live";
  scenario.value = trialMode ? trialScenario : null;
  // Start blank, not by restoring an earlier enterprise or Demo conversation.
  // Only browser pointers are cleared; backend history and facts are untouched.
  forget();
  rememberPreference();
}
function setMode(value: DataMode) {
  // Compatibility setter: there is no local response mode in the application.
  if (value === "live") mode.value = "live";
}
function setScenario(value: ScenarioId | undefined) {
  if (trialMode) value = trialScenario;
  if (scenario.value === (value ?? null)) return;
  reset();
  scenario.value = value ?? null;
  rememberPreference();
  notice.value = value
    ? value === "kq_z112_review_slim" ? "已切换精简评审子集：按至少满足1片动态筛选，标识已脱敏，不代表完整企业BOM。" : value === "kq_z112_review_slim_synthetic" ? "已切换精简评审推演：含合成补充库存，不代表真实企业生产能力。" : value === "review_real_bom_simulation" ? "已切换评审推演：真实BOM与合成补充库存，不能作为真实库存结论。" : "已切换到独立合成 Demo，不会修改企业事实。"
    : "已切换到企业事实查询。";
  void restoreSession();
}
async function restoreSession(): Promise<BackendTurn[] | null> {
  if (pending.value) return null;
  if (!sessionId.value) {
    const s = storage();
    const pointer = s ? readSession(s, key(), scenario.value) : null;
    sessionId.value = pointer?.session_id ?? null;
  }
  if (!sessionId.value) return null;
  const restoringId = sessionId.value;
  const restoringScenario = scenario.value;
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
        restoringId,
        restoringScenario ?? undefined,
        after,
        abort.signal,
      );
      if (
        page.session_id !== restoringId ||
        (page.scenario_id ?? null) !== restoringScenario
      )
        throw new QueryError("session", "会话来源不一致，请重新开始分析。");
      if (!page.turns.length) break;
      for (const turn of page.turns) {
        if (
          turn.response.session_id !== restoringId ||
          (turn.response.scenario_id ?? null) !== restoringScenario
        )
          throw new QueryError(
            "session",
            "会话来源不一致，请新建企业分析或选择原数据空间。",
          );
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
      result: adaptBackendResponse(turn.response, turn.user_query),
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
      notice.value = restoringScenario?.startsWith("kq_z112_review_slim")
        ? "当前会话属于旧数据版本或已失效，请新建分析；不会用新版数据解释旧结果。"
        : "当前会话已失效，请新建分析。";
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
    // Create and save the pointer before querying so timeout/refresh can recover the server turn.
    if (!sessionId.value) {
      const session = await client.createSession(
        scenario.value ?? undefined,
        abort.signal,
      );
      if (token !== sequence || abort.signal.aborted) return;
      if ((session.scenario_id ?? null) !== scenario.value)
        throw new QueryError(
          "mapping",
          "会话来源不一致，未发送分析请求，请新建分析。",
        );
      sessionId.value = session.session_id;
      remember();
    }
    const response = await client.queryAgent(
      {
        message: text,
        session_id: sessionId.value,
        scenario_id: scenario.value ?? undefined,
        persist_session: true,
      },
      abort.signal,
    );
    if (token !== sequence || abort.signal.aborted) return;
    if (
      response.session_id !== sessionId.value ||
      (response.scenario_id ?? null) !== scenario.value
    )
      throw new QueryError("mapping", "会话来源不一致，请恢复会话后重试。");
    const data = adaptBackendResponse(response, text);
    message.sequenceNo = (message.attemptAfter ?? 0) + 1;
    remember();
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
    current.uncertain = true;
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
  if (previous.uncertain && sessionId.value) {
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
    if (isReload) void restoreSession();
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
    startEnterpriseAnalysis,
    setMode,
    setScenario,
    restoreSession,
    select,
  };
}
