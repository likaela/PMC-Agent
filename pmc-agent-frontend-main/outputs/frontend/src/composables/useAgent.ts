import { computed, ref, shallowRef } from "vue";
import { QueryError, type AgentResult, type DataMode } from "../data/model";
import { createMockService } from "../services/mockService";
import { createLiveService } from "../services/apiClient";

interface Message {
  id: number;
  question: string;
  requestedAt: string;
  state: "pending" | "done" | "error" | "cancelled";
  result?: AgentResult;
  error?: QueryError;
}
const mode = ref<DataMode>(
  import.meta.env.VITE_DATA_MODE === "live" ? "live" : "mock",
);
const messages = ref<Message[]>([]);
const selectedId = ref<number | null>(null);
const pending = ref(false);
const notice = ref("");
const draft = ref("");
const controller = shallowRef<AbortController>();
let sequence = 0;
let messageId = 0;
let mockService = createMockService();
const liveService = createLiveService();
const selected = computed(() =>
  messages.value.find((m) => m.id === selectedId.value),
);
const result = computed(() => selected.value?.result);

function cancel() {
  if (!pending.value) return;
  controller.value?.abort();
  sequence++;
  const active = messages.value.find((m) => m.state === "pending");
  if (active) active.state = "cancelled";
  pending.value = false;
  notice.value = "已取消本次请求，可以修改问题或重试。";
}
function reset() {
  cancel();
  messages.value = [];
  selectedId.value = null;
  draft.value = "";
  notice.value = "";
  mockService = createMockService();
}
function setMode(value: DataMode) {
  if (mode.value !== value) {
    reset();
    mode.value = value;
    notice.value = "数据模式已切换，旧对话与结果已清除。";
  }
}
async function send(text = draft.value) {
  if (!text.trim() || pending.value) return;
  const id = ++messageId;
  const token = ++sequence;
  const abort = new AbortController();
  controller.value = abort;
  messages.value.push({
    id,
    question: text.trim(),
    state: "pending",
    requestedAt: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
  });
  selectedId.value = id;
  pending.value = true;
  notice.value = "";
  draft.value = "";
  try {
    const data = await (
      mode.value === "mock" ? mockService : liveService
    ).query({ text }, abort.signal);
    if (token !== sequence || abort.signal.aborted) return;
    const message = messages.value.find((m) => m.id === id)!;
    message.result = data;
    message.state = "done";
  } catch (error) {
    if (token !== sequence || abort.signal.aborted) return;
    const message = messages.value.find((m) => m.id === id)!;
    message.error =
      error instanceof QueryError
        ? error
        : new QueryError("network", "请求失败，请重试。");
    message.state = "error";
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
function retry() {
  if (selected.value) return send(selected.value.question);
}
export function useAgent() {
  return {
    mode,
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
    select,
  };
}
