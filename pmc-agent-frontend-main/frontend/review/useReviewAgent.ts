// Authorized account/product state; product and material catalogs come from HTTP only.
import { computed, ref, shallowRef } from "vue";
import { QueryError, type AgentResult, type BackendTurn } from "../src/data/model";
import { createAgentClient } from "../src/services/apiClient";
import { adaptBackendResponse } from "../src/services/responseAdapter";
import { reviewRequest, type ReviewProduct } from "./reviewClient";
import { configureScenarios } from "./scenarioPolicy";

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
const mode = ref("live"), scenario = ref<import("../src/data/model").ScenarioId>();
const catalog = ref<ReviewProduct[]>([]), productCode = ref<string | null>(null);
const currentProduct = computed(() => catalog.value.find(p => p.product_code === productCode.value));
const analysisMode = ref("full");
const currentScope = computed(() => currentProduct.value?.modes.find(m => m.mode === analysisMode.value));
const materials = ref<{material_code: string; name: string | null; qty_per: string; stock_qty: string | null; unit: string | null}[]>([]);
async function chooseProduct(code: string, requestedMode?: string) {
  const product = catalog.value.find(p => p.product_code === code);
  if (!product || pending.value) return false;
  const scope = product.modes.find(m => m.mode === (requestedMode ?? product.default_mode));
  if (!scope) return false;
  reset(true); productCode.value = code; analysisMode.value = scope.mode; scenario.value = scope.scenario_id ?? undefined;
  materials.value = [];
  const selecting = version;
  const selectingTransition = transition;
  sessionStorage.setItem("pmc-authorized-review-selection-v2", JSON.stringify({product_code: code, analysis_mode: scope.mode, dataset_version: scope.dataset_version}));
  try {
    const data = await reviewRequest("/api/v1/review/products/" + encodeURIComponent(code) + "/materials?analysis_mode=" + encodeURIComponent(scope.mode));
    if (selecting !== version || productCode.value !== code) return false;
    if (data.analysis_mode !== scope.mode || data.dataset_version !== scope.dataset_version) throw new Error("Scope mismatch");
    materials.value = data.materials;
  }
  catch { if (selecting !== version) return false; materials.value = []; notice.value = "物料目录暂不可读取，请重试。"; }
  await restoreSession();
  return selectingTransition === transition && productCode.value === code;
}
async function initialize() {
  try {
    catalog.value = (await reviewRequest("/api/v1/review/catalog")).products;
    configureScenarios(catalog.value.flatMap(p => p.modes.map(m => m.scenario_id)));
    const saved = JSON.parse(sessionStorage.getItem("pmc-authorized-review-selection-v2") ?? "null");
    const p = catalog.value.find(p => p.product_code === saved?.product_code);
    const scope = p?.modes.find(m => m.mode === saved?.analysis_mode && m.dataset_version === saved?.dataset_version);
    if (p && scope) await chooseProduct(p.product_code, scope.mode);
  } catch { notice.value = "无法读取授权产品目录，请检查登录及连接后刷新。"; }
}
const sessionId = ref<string | null>(null), messages = ref<Message[]>([]);
const selectedId = ref<number | null>(null), pending = ref(false);
const notice = ref(""), draft = ref("");
const controller = shallowRef<AbortController>();
const client = createAgentClient({ baseUrl: "/" });
const storageKey = () => "pmc-authorized-review-session-v2:" + productCode.value + ":" + analysisMode.value + ":" + (currentScope.value?.dataset_version ?? "published");
let version = 0, messageId = 0, initialized = false;
let transition = 0;
let resolving = false;
const selected = computed(() => messages.value.find(m => m.id === selectedId.value));
const result = computed(() => selected.value?.result?.conversation ? null : selected.value?.result ?? null);
function save() {
  try {
    if (sessionId.value) sessionStorage.setItem(storageKey(), JSON.stringify({ session_id: sessionId.value, product_code: productCode.value,
      analysis_mode: analysisMode.value, dataset_version: currentScope.value?.dataset_version }));
    else sessionStorage.removeItem(storageKey());
  } catch { /* Storage unavailable: live HTTP still works. */ }
}
function cancel() {
  if (!pending.value) return;
  controller.value?.abort();
  version++;
  const message = messages.value.find(m => m.state === "pending");
  if (message) { message.state = "cancelled"; message.uncertain = true; }
  pending.value = false;
  notice.value = "已停止等待，请恢复会话确认服务端结果。";
}
function reset(preservePointer = false) {
  cancel(); version++; transition++;
  sessionId.value = null; if (!preservePointer) save(); messages.value = [];
  selectedId.value = null; draft.value = ""; notice.value = "";
}
async function restoreSession(): Promise<BackendTurn[] | null> {
  if (pending.value) return null;
  if (!productCode.value) return [];
  if (!sessionId.value) {
    try {
      const pointer = JSON.parse(sessionStorage.getItem(storageKey()) ?? "null");
      if (pointer?.product_code === productCode.value && pointer.analysis_mode === analysisMode.value && pointer.dataset_version === currentScope.value?.dataset_version && typeof pointer.session_id === "string") sessionId.value = pointer.session_id;
    } catch { /* Ignore malformed pointers, never select another data space. */ }
  }
  if (!sessionId.value) return [];
  const restoring = sessionId.value, token = ++version;
  const abort = new AbortController(); controller.value = abort; pending.value = true;
  try {
    const turns: BackendTurn[] = [];
    let after = 0;
    for (;;) {
      const page = await client.getSession(restoring, scenario.value, after, abort.signal);
      const metadata = page as unknown as {review_product: string; review_mode: string; dataset_version: string | null};
      if (page.session_id !== restoring || (page.scenario_id ?? null) !== (scenario.value ?? null) || metadata.review_product !== productCode.value || metadata.review_mode !== analysisMode.value || metadata.dataset_version !== currentScope.value?.dataset_version) throw new QueryError("session", "会话来源不一致，请新建分析。");
      for (const turn of page.turns) {
        if (turn.sequence_no <= after || turn.response.session_id !== restoring || (turn.response.scenario_id ?? null) !== (scenario.value ?? null))
          throw new QueryError("mapping", "会话记录暂无法确认。");
        after = turn.sequence_no; turns.push(turn);
      }
      if (page.turns.length < 200) break;
    }
    if (token !== version || abort.signal.aborted) return null;
    messages.value = turns.map(t => ({ id: ++messageId, question: t.user_query, requestedAt: t.created_at,
      sequenceNo: t.sequence_no, state: "done", result: adaptBackendResponse(t.response, t.user_query) }));
    selectedId.value = messages.value.at(-1)?.id ?? null;
    notice.value = "已恢复当前账号、当前产品的会话。";
    return turns;
  } catch (error) {
    if (token !== version || abort.signal.aborted) return null;
    if (error instanceof QueryError && error.code === "session") {
      sessionId.value = null; save(); messages.value = []; selectedId.value = null;
      notice.value = "会话已失效或不属于当前账号，请新建分析。";
    } else notice.value = "暂时无法恢复会话，请检查连接后重试。";
    return null;
  } finally { if (token === version) pending.value = false; }
}
async function send(candidate: unknown = draft.value) {
  const text = typeof candidate === "string" ? candidate.trim() : "";
  if (!text || pending.value || resolving) return;
  resolving = true;
  const resolvingVersion = version;
  try {
    const resolved = await reviewRequest("/api/v1/review/resolve", { message: text });
    if (resolvingVersion !== version) return;
    const target = resolved.product_code ?? productCode.value ?? (resolved.catalog_query ? catalog.value[0]?.product_code : null);
    if (target && (target !== productCode.value || (resolved.analysis_mode && resolved.analysis_mode !== analysisMode.value)) && !(await chooseProduct(target, resolved.analysis_mode ?? undefined))) return;
  } catch {
    if (resolvingVersion !== version) return;
    const failed: Message = { id: ++messageId, question: text, requestedAt: new Date().toLocaleTimeString("zh-CN"), state: "error",
      error: new QueryError("invalid", "问题中的产品不可访问，或连接暂时异常。") };
    messages.value.push(failed); selectedId.value = failed.id;
    notice.value = "问题中的产品不可访问，或连接暂时异常。";
    return;
  }
  finally { resolving = false; }
  if (!productCode.value) { notice.value = "请先选择已授权产品，或在问题中明确产品编码。"; return; }
  const token = ++version, abort = new AbortController(); controller.value = abort;
  const message: Message = { id: ++messageId, question: text, requestedAt: new Date().toLocaleTimeString("zh-CN"), state: "pending",
    attemptAfter: messages.value.at(-1)?.sequenceNo ?? 0 };
  messages.value.push(message); selectedId.value = message.id;
  pending.value = true; notice.value = ""; draft.value = "";
  try {
    if (!sessionId.value) {
      const session = await reviewRequest("/api/v1/agent/sessions", { product_code: productCode.value, analysis_mode: analysisMode.value, scenario_id: scenario.value ?? null }, abort.signal);
      if (token !== version || abort.signal.aborted) return;
      if (typeof session.session_id !== "string" || !session.session_id || (session.scenario_id ?? null) !== (scenario.value ?? null) || session.review_product !== productCode.value || session.review_mode !== analysisMode.value || session.dataset_version !== currentScope.value?.dataset_version) throw new QueryError("mapping", "会话来源不一致，未发送分析请求。");
      sessionId.value = session.session_id; save();
    }
    if (!sessionId.value) throw new QueryError("session", "请重新创建分析会话。");
    const response = await client.queryAgent({ message: text, session_id: sessionId.value, scenario_id: scenario.value, persist_session: true }, abort.signal);
    if (token !== version || abort.signal.aborted) return;
    const metadata = response as unknown as {review_product: string; review_mode: string; dataset_version: string | null};
    if (response.session_id !== sessionId.value || (response.scenario_id ?? null) !== (scenario.value ?? null) || metadata.review_product !== productCode.value || metadata.review_mode !== analysisMode.value || metadata.dataset_version !== currentScope.value?.dataset_version) throw new QueryError("mapping", "会话来源不一致，请恢复后重试。");
    const vm = adaptBackendResponse(response, text);
    const current = messages.value.find(m => m.id === message.id)!;
    current.result = vm; current.state = "done"; current.sequenceNo = (message.attemptAfter ?? 0) + 1; save();
  } catch (error) {
    if (token !== version || abort.signal.aborted) return;
    const current = messages.value.find(m => m.id === message.id)!;
    current.error = error instanceof QueryError ? error : new QueryError("network", "请求失败，请检查连接后重试。");
    current.state = "error"; current.uncertain = true; draft.value = text;
  } finally { if (token === version) pending.value = false; }
}
async function retry() {
  const previous = selected.value;
  if (!previous || pending.value) return;
  if (previous.uncertain && sessionId.value) {
    const turns = await restoreSession();
    if (turns === null) return;
    if (turns.some(t => t.sequence_no > (previous.attemptAfter ?? 0) && t.user_query === previous.question)) return;
  }
  return send(previous.question);
}
export function useAgent() {
  if (!initialized) { initialized = true; void initialize(); }
  return { catalog, productCode, currentProduct, currentScope, analysisMode, materials, chooseProduct, mode, scenario, sessionId, messages, selectedId, selected, result, pending, notice, draft,
    send, retry, cancel, reset, restoreSession, select: (id: number) => { if (!pending.value) selectedId.value = id; } };
}
