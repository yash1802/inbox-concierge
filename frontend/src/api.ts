const rawBase = import.meta.env.VITE_API_BASE_URL ?? "";
const API_BASE = typeof rawBase === "string" ? rawBase.replace(/\/+$/, "") : "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = JSON.parse(text) as { detail?: string };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export type Me = { id: string; email: string };

export async function getMe(): Promise<Me | null> {
  try {
    return await apiFetch<Me>("/api/me");
  } catch {
    return null;
  }
}

export type Category = { id: string; name: string; is_system: boolean };

export async function listCategories(): Promise<Category[]> {
  return apiFetch<Category[]>("/api/categories");
}

export async function addCategoriesCsv(names: string): Promise<{ job_id: string; added: string[] }> {
  return apiFetch("/api/categories", {
    method: "POST",
    body: JSON.stringify({ names }),
  });
}

export async function startRecategorizeAll(): Promise<{ job_id: string }> {
  return apiFetch("/api/categories/recategorize-all", { method: "POST" });
}

export async function deleteCategory(id: string): Promise<void> {
  await apiFetch(`/api/categories/${id}`, { method: "DELETE" });
}

export async function startSync(): Promise<{ job_id: string }> {
  return apiFetch("/api/sync", { method: "POST" });
}

export type JobStatus = {
  id: string;
  kind: string;
  status: string;
  error_message: string | null;
  batches_done: number;
  batches_total: number | null;
  allowed_labels_snapshot: string[] | null;
  started_at: string | null;
  finished_at: string | null;
};

export async function getJob(jobId: string): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/api/jobs/${jobId}`);
}

export type ThreadRow = {
  id: string;
  gmail_thread_id: string;
  subject: string;
  snippet: string;
  internal_date: number;
  from_addr: string | null;
  categories: string[];
};

export type ThreadsPage = {
  items: ThreadRow[];
  next_cursor_internal_date: number | null;
  next_cursor_id: string | null;
};

export async function fetchThreadsPage(params: {
  limit: number;
  cursor_internal_date?: number;
  cursor_id?: string;
  category_ids?: string[];
  from_ts?: number;
  to_ts?: number;
}): Promise<ThreadsPage> {
  const sp = new URLSearchParams();
  sp.set("limit", String(params.limit));
  if (params.cursor_internal_date != null && params.cursor_id) {
    sp.set("cursor_internal_date", String(params.cursor_internal_date));
    sp.set("cursor_id", params.cursor_id);
  }
  if (params.category_ids?.length) {
    for (const id of params.category_ids) sp.append("category_ids", id);
  }
  if (params.from_ts != null) sp.set("from_ts", String(params.from_ts));
  if (params.to_ts != null) sp.set("to_ts", String(params.to_ts));
  return apiFetch<ThreadsPage>(`/api/threads?${sp.toString()}`);
}

export function googleLoginUrl(): string {
  return `${API_BASE}/api/auth/google/login`;
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/google/logout", { method: "POST" });
}
