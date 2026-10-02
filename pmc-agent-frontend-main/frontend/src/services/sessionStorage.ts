import type { ScenarioId } from "../data/model";
export interface SessionPointer {
  session_id: string;
  scenario_id?: ScenarioId;
}
export interface PointerStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}
export interface SessionPreference {
  mode: "mock" | "live";
  scenario_id?: ScenarioId;
}
export function preferenceKey(baseUrl: string): string {
  return sessionKey(baseUrl) + ":preference";
}
export function readPreference(
  storage: PointerStorage,
  baseUrl: string,
): SessionPreference | null {
  try {
    const p = JSON.parse(storage.getItem(preferenceKey(baseUrl)) ?? "null");
    if (
      !p ||
      !["mock", "live"].includes(p.mode) ||
      (p.scenario_id !== undefined &&
        p.scenario_id !== "demo_scenario_50_vs_100")
    )
      return null;
    return p;
  } catch {
    return null;
  }
}
export function savePreference(
  storage: PointerStorage,
  baseUrl: string,
  preference: SessionPreference,
): void {
  try {
    storage.setItem(preferenceKey(baseUrl), JSON.stringify(preference));
  } catch {
    /* Optional browser cache. */
  }
}
export function sessionKey(baseUrl: string, scenarioId?: ScenarioId): string {
  return `pmc-agent:v1.14.1:${baseUrl.replace(/\/+$/, "")}:${scenarioId ?? "enterprise"}`;
}
// Cache only an opaque pointer; facts and answers remain in the backend conversation store.
export function saveSession(
  storage: PointerStorage,
  key: string,
  pointer: SessionPointer,
): void {
  try {
    storage.setItem(key, JSON.stringify(pointer));
  } catch {
    /* Storage unavailable: in-memory session remains usable. */
  }
}
export function readSession(
  storage: PointerStorage,
  key: string,
  scenarioId?: ScenarioId,
): SessionPointer | null {
  try {
    const value = storage.getItem(key);
    if (!value) return null;
    const p = JSON.parse(value);
    if (
      !p ||
      typeof p.session_id !== "string" ||
      !p.session_id ||
      p.scenario_id !== scenarioId
    ) {
      storage.removeItem(key);
      return null;
    }
    return p;
  } catch {
    clearSession(storage, key);
    return null;
  }
}
export function clearSession(storage: PointerStorage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    /* Safe on restricted browsers. */
  }
}
