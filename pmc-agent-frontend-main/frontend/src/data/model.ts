// Frontend display model only. This is NOT an agreed backend schema.
export type DataMode = "mock" | "live";
export type ResultStatus =
  | "partial"
  | "ready"
  | "inventory"
  | "zero"
  | "no-facts"
  | "conflict"
  | "uncalculable"
  | "purchase";
export type MaterialState =
  "shortage" | "unknown" | "sufficient" | "published" | "no-facts";
export interface Material {
  id: string;
  name: string;
  spec: string;
  required: number | null;
  available: number | null;
  shortage: number | null;
  unit: string;
  state: MaterialState;
  sourceIds: string[];
}
export interface Source {
  id: string;
  title: string;
  kind: "项目资料示例" | "人工构造演示样例";
  scope: string;
  reference: string;
  version: string | null;
  publishedAt: string | null;
  conditions: string;
}
export interface AgentResult {
  id: string;
  status: ResultStatus;
  product: string | null;
  quantity: number | null;
  quantityUnit: string;
  title: string;
  answer: string;
  conclusion: string;
  nextAction: string;
  materials: Material[];
  sources: Source[];
  warnings: string[];
  purchase?: {
    material: string;
    shortage: number;
    safetyStock: number;
    suggested: number;
    unit: string;
    note: string;
  };
}
export type ErrorCode = "network" | "mapping" | "unconfigured" | "unsupported";
export class QueryError extends Error {
  constructor(
    public code: ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "QueryError";
  }
}
export interface QueryInput {
  text: string;
}
export interface AgentQueryService {
  query(input: QueryInput, signal: AbortSignal): Promise<AgentResult>;
}
export interface Scenario {
  id: string;
  label: string;
  prompt: string;
  category: "project" | "synthetic";
  result?: AgentResult;
  error?: "network" | "mapping";
}
export const statusText: Record<ResultStatus, string> = {
  partial: "部分数据 · 已知缺料",
  ready: "所列物料齐套",
  inventory: "库存已提供",
  zero: "库存为零",
  "no-facts": "暂无已发布数据",
  conflict: "条件冲突",
  uncalculable: "无法计算",
  purchase: "独立采购样例",
};
export const materialText: Record<MaterialState, string> = {
  shortage: "缺料",
  unknown: "待补充库存",
  sufficient: "满足需求",
  published: "已提供库存",
  "no-facts": "无已发布事实",
};
export const formatNumber = (v: number | null | undefined) =>
  v == null ? "未提供" : new Intl.NumberFormat("zh-CN").format(v);
