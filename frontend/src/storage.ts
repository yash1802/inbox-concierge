import type { ThreadRow } from "./api";

const key = (userId: string) => `inbox_concierge_threads_${userId}`;

export function loadThreadCache(userId: string): ThreadRow[] {
  try {
    const raw = localStorage.getItem(key(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ThreadRow[];
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

export function saveThreadCache(userId: string, threads: ThreadRow[]): void {
  localStorage.setItem(key(userId), JSON.stringify(threads));
}

export function mergeThreadsById(a: ThreadRow[], b: ThreadRow[]): ThreadRow[] {
  const map = new Map<string, ThreadRow>();
  for (const t of [...a, ...b]) {
    map.set(t.id, t);
  }
  return [...map.values()].sort((x, y) => y.internal_date - x.internal_date);
}
