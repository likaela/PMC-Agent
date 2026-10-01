import { QueryError, type AgentQueryService } from "../data/model";
import { adaptBackendResponse } from "./responseAdapter";

// Replace these two hooks only AFTER verifying the backend's actual contract.
type Transport = (
  baseUrl: string,
  text: string,
  signal: AbortSignal,
) => Promise<unknown>;
type Adapter = typeof adaptBackendResponse;
export function createLiveService(
  transport?: Transport,
  adapter: Adapter = adaptBackendResponse,
): AgentQueryService {
  return {
    async query(input, signal) {
      const baseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
      if (!baseUrl || !transport)
        throw new QueryError(
          "unconfigured",
          "接口尚未配置。等待组员提供真实请求契约和响应样例后接入。",
        );
      let payload: unknown;
      try {
        payload = await transport(baseUrl, input.text, signal);
      } catch (error) {
        if (signal.aborted || error instanceof QueryError) throw error;
        throw new QueryError("network", "请求失败，请检查后端连接后重试。");
      }
      try {
        return adapter(payload);
      } catch (error) {
        console.error(
          "[PMC-Agent] response adapter failed",
          error instanceof Error ? error.message : "Unknown mapping error",
        );
        throw error instanceof QueryError
          ? error
          : new QueryError("mapping", "响应暂无法完整展示，请检查字段映射。");
      }
    },
  };
}
