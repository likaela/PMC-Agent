import { QueryError, type AgentResult } from "../data/model";

// Deliberately unimplemented until a real schema and redacted responses are provided.
// Do not infer nested fields, statuses or business numbers from text.
export function adaptBackendResponse(_payload: unknown): AgentResult {
  throw new QueryError(
    "mapping",
    "真实响应字段映射尚未配置。请先核验后端 schema 与真实样例。",
  );
}
