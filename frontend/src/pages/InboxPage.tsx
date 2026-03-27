import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import { useNavigate } from "react-router-dom";
import {
  addCategoriesCsv,
  deleteCategory,
  fetchThreadsPage,
  getJob,
  getMe,
  listCategories,
  logout,
  startRecategorizeAll,
  startSync,
  type Category,
  type ThreadRow,
  type ThreadsPage,
} from "../api";
import { loadThreadCache, mergeThreadsById, saveThreadCache } from "../storage";

const INBOX_DEBUG = "[inbox]";

function formatDate(ms: number): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(ms));
  } catch {
    return String(ms);
  }
}

export function InboxPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const sidebarCardRef = useRef<HTMLDivElement | null>(null);
  const listScrollRef = useRef<HTMLDivElement | null>(null);
  const appliedSidebarHRef = useRef<number | null>(null);
  const filteredRef = useRef<ThreadRow[]>([]);
  const serverEndRef = useRef(false);
  const prefetchingRef = useRef(false);
  const userIdRef = useRef<string | undefined>(undefined);
  const prefetchMoreRef = useRef<() => Promise<void>>(async () => {});
  const nextCursorRef = useRef<{ internal_date: number; id: string } | null>(null);
  /** Bumps when `activeJobId` changes so stale job-poll ticks skip setState after await. */
  const jobPollGenRef = useRef(0);

  const meQuery = useQuery({ queryKey: ["me"], queryFn: getMe });
  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: listCategories,
    enabled: !!meQuery.data,
  });

  const userId = meQuery.data?.id;
  userIdRef.current = userId;

  const [buffer, setBuffer] = useState<ThreadRow[]>([]);
  const [nextCursor, setNextCursor] = useState<{
    internal_date: number;
    id: string;
  } | null>(null);
  const [serverEnd, setServerEnd] = useState(false);
  const [prefetching, setPrefetching] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobKind, setJobKind] = useState<string | null>(null);
  const [newCats, setNewCats] = useState("");
  const [selectedCategoryIds, setSelectedCategoryIds] = useState<string[]>([]);
  const [fromDate, setFromDate] = useState<Date | undefined>();
  const [toDate, setToDate] = useState<Date | undefined>();
  const [dateRangePicker, setDateRangePicker] = useState<"from" | "to" | null>(null);
  const dateRangeSectionRef = useRef<HTMLDivElement | null>(null);
  /** md+: main column max-height tracks sidebar card; updates only when height changes by ≥2px to avoid observer↔state loops */
  const [mainColumnMaxPx, setMainColumnMaxPx] = useState<number | null>(null);

  useEffect(() => {
    serverEndRef.current = serverEnd;
  }, [serverEnd]);

  useEffect(() => {
    nextCursorRef.current = nextCursor;
  }, [nextCursor]);

  useEffect(() => {
    if (dateRangePicker === null) return;
    const onPointerDown = (e: PointerEvent) => {
      const el = dateRangeSectionRef.current;
      if (el && e.target instanceof Node && el.contains(e.target)) return;
      setDateRangePicker(null);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [dateRangePicker]);

  useEffect(() => {
    if (dateRangePicker === null) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDateRangePicker(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [dateRangePicker]);

  useEffect(() => {
    if (!meQuery.data) return;
    appliedSidebarHRef.current = null;
    const card = sidebarCardRef.current;
    if (!card) return;
    let raf = 0;
    const apply = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const c = sidebarCardRef.current;
        if (!c) return;
        const wide = window.matchMedia("(min-width: 768px)").matches;
        if (!wide) {
          if (appliedSidebarHRef.current !== null) {
            appliedSidebarHRef.current = null;
            setMainColumnMaxPx(null);
          }
          return;
        }
        const h = Math.round(c.getBoundingClientRect().height);
        const prev = appliedSidebarHRef.current;
        if (prev === null || Math.abs(h - prev) >= 2) {
          appliedSidebarHRef.current = h;
          setMainColumnMaxPx(h);
        }
      });
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(card);
    window.addEventListener("resize", apply);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("resize", apply);
    };
  }, [meQuery.data?.id]);

  useEffect(() => {
    if (!userId) return;
    setBuffer(loadThreadCache(userId));
    setNextCursor(null);
    setServerEnd(false);
  }, [userId]);

  useEffect(() => {
    if (meQuery.isFetched && meQuery.data === null) {
      navigate("/login");
    }
  }, [meQuery.isFetched, meQuery.data, navigate]);

  /** Merge newest page from API into buffer. Updates cursor/serverEnd only while pagination not started (cursor null). */
  const mergeFirstPageIntoBuffer = useCallback((page: ThreadsPage) => {
    if (!userId) return;
    const lockPagination = nextCursorRef.current !== null;
    setBuffer((prev) => {
      const merged = mergeThreadsById(prev, page.items);
      saveThreadCache(userId, merged);
      console.log(INBOX_DEBUG, "mergeFirstPageIntoBuffer", {
        apiItems: page.items.length,
        bufferLen: merged.length,
        paginationLocked: lockPagination,
      });
      return merged;
    });
    if (!lockPagination) {
      setNextCursor(
        page.next_cursor_internal_date != null && page.next_cursor_id
          ? { internal_date: page.next_cursor_internal_date, id: page.next_cursor_id }
          : null,
      );
      setServerEnd(page.items.length < 200 || !page.next_cursor_id);
    }
  }, [userId]);

  const refreshLatest200 = useCallback(async () => {
    if (!userId) return;
    const page = await fetchThreadsPage({ limit: 200 });
    mergeFirstPageIntoBuffer(page);
  }, [mergeFirstPageIntoBuffer, userId]);

  useEffect(() => {
    if (!userId) return;
    void refreshLatest200();
  }, [userId, refreshLatest200]);

  const beginJobPoll = useCallback((jobId: string, kind: string) => {
    setActiveJobId(jobId);
    setJobKind(kind);
  }, []);

  useEffect(() => {
    if (!activeJobId) return;
    const myGen = ++jobPollGenRef.current;
    let cancelled = false;
    const tick = async () => {
      try {
        const j = await getJob(activeJobId);
        if (cancelled || myGen !== jobPollGenRef.current) return;
        if (j.status === "completed" || j.status === "failed") {
          setActiveJobId(null);
          setJobKind(null);
          if (j.status === "completed" && userId) {
            const page = await fetchThreadsPage({ limit: 200 });
            if (cancelled || myGen !== jobPollGenRef.current) return;
            mergeFirstPageIntoBuffer(page);
            await qc.refetchQueries({ queryKey: ["categories"] });
          }
          return;
        }
        const page = await fetchThreadsPage({ limit: 200 });
        if (cancelled || myGen !== jobPollGenRef.current) return;
        mergeFirstPageIntoBuffer(page);
      } catch {
        /* ignore */
      }
    };
    const id = window.setInterval(tick, 1200);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [activeJobId, mergeFirstPageIntoBuffer, qc, userId]);

  const autoSyncKey = userId ? `auto_sync_${userId}` : null;
  useEffect(() => {
    if (!userId || !autoSyncKey) return;
    if (sessionStorage.getItem(autoSyncKey)) return;
    sessionStorage.setItem(autoSyncKey, "1");
    void (async () => {
      try {
        const { job_id } = await startSync();
        beginJobPoll(job_id, "sync");
      } catch {
        sessionStorage.removeItem(autoSyncKey);
      }
    })();
  }, [autoSyncKey, beginJobPoll, userId]);

  const syncMutation = useMutation({
    mutationFn: startSync,
    onSuccess: (d) => beginJobPoll(d.job_id, "sync"),
  });

  const addCatsMutation = useMutation({
    mutationFn: () => addCategoriesCsv(newCats),
    onSuccess: (d) => {
      setNewCats("");
      beginJobPoll(d.job_id, "recategorize");
    },
  });

  const recategorizeAllMutation = useMutation({
    mutationFn: startRecategorizeAll,
    onSuccess: (d) => beginJobPoll(d.job_id, "recategorize"),
  });

  const filtered = useMemo(() => {
    const fromTs = fromDate ? new Date(fromDate).setHours(0, 0, 0, 0) : undefined;
    const toTs = toDate ? new Date(toDate).setHours(23, 59, 59, 999) : undefined;
    const nameById = new Map((categoriesQuery.data ?? []).map((c) => [c.id, c.name]));
    return buffer.filter((t) => {
      if (fromTs != null && t.internal_date < fromTs) return false;
      if (toTs != null && t.internal_date > toTs) return false;
      if (selectedCategoryIds.length) {
        const names = new Set(t.categories);
        const need = selectedCategoryIds.map((id) => nameById.get(id)).filter(Boolean) as string[];
        if (!need.every((n) => names.has(n))) return false;
      }
      return true;
    });
  }, [buffer, categoriesQuery.data, fromDate, selectedCategoryIds, toDate]);

  filteredRef.current = filtered;

  useEffect(() => {
    console.log(INBOX_DEBUG, "buffer/filtered", {
      bufferLen: buffer.length,
      filteredLen: filtered.length,
      serverEnd,
      prefetching,
    });
  }, [buffer.length, filtered.length, serverEnd, prefetching]);

  const visible = filtered;
  const listEnd = serverEnd && filtered.length > 0;

  const prefetchMore = useCallback(async () => {
    if (!userId || serverEnd || prefetchingRef.current) return;
    prefetchingRef.current = true;
    setPrefetching(true);
    try {
      const cursor = nextCursor;
      console.log(INBOX_DEBUG, "prefetchMore start", {
        cursor,
        serverEnd,
      });
      const page = await fetchThreadsPage({
        limit: 200,
        cursor_internal_date: cursor?.internal_date,
        cursor_id: cursor?.id,
      });
      setBuffer((prev) => {
        const merged = mergeThreadsById(prev, page.items);
        saveThreadCache(userId, merged);
        console.log(INBOX_DEBUG, "prefetchMore merged", {
          pageItems: page.items.length,
          bufferAfter: merged.length,
        });
        return merged;
      });
      setNextCursor(
        page.next_cursor_internal_date != null && page.next_cursor_id
          ? { internal_date: page.next_cursor_internal_date, id: page.next_cursor_id }
          : null,
      );
      if (page.items.length === 0 || !page.next_cursor_id) {
        setServerEnd(true);
      }
    } finally {
      prefetchingRef.current = false;
      setPrefetching(false);
    }
  }, [nextCursor, serverEnd, userId]);

  prefetchMoreRef.current = prefetchMore;

  useEffect(() => {
    const root = listScrollRef.current;
    const target = sentinelRef.current;
    if (!root || !target) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const fLen = filteredRef.current.length;
          const atEnd = serverEndRef.current;
          const pf = prefetchingRef.current;
          const uid = userIdRef.current;
          console.log(INBOX_DEBUG, "sentinel intersect", {
            filteredLen: fLen,
            serverEnd: atEnd,
            prefetching: pf,
            hasUserId: !!uid,
          });
          if (!uid || atEnd || pf) continue;
          void prefetchMoreRef.current();
        }
      },
      { root, rootMargin: "160px", threshold: 0 },
    );
    io.observe(target);
    return () => io.disconnect();
  }, [filtered.length, mainColumnMaxPx, activeJobId, meQuery.data?.id]);

  const toggleCat = (id: string) => {
    setSelectedCategoryIds((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  };

  const onLogout = async () => {
    await logout();
    qc.clear();
    navigate("/login");
  };

  const onDeleteCategory = async (c: Category) => {
    if (!c.is_system) {
      await deleteCategory(c.id);
      setSelectedCategoryIds((s) => s.filter((x) => x !== c.id));
      qc.setQueryData<Category[]>(["categories"], (old) =>
        (old ?? []).filter((x) => x.id !== c.id),
      );
      await qc.refetchQueries({ queryKey: ["categories"] });
      await refreshLatest200();
    }
  };

  if (!meQuery.data) {
    return (
      <div className="flex min-h-full items-center justify-center text-zinc-400">Loading…</div>
    );
  }

  const busy = !!activeJobId;
  const globalBusy =
    busy ||
    syncMutation.isPending ||
    addCatsMutation.isPending ||
    recategorizeAllMutation.isPending;
  const jobLabel =
    jobKind === "recategorize"
      ? "Re-categorizing…"
      : jobKind === "sync"
        ? "Syncing Gmail…"
        : "Working…";
  const syncActiveForEmptyState =
    syncMutation.isPending || (!!activeJobId && jobKind === "sync");

  return (
    <div className="mx-auto flex min-h-full max-w-6xl flex-col gap-6 px-4 py-8 md:flex-row md:items-start md:px-8">
      <aside className="md:w-72 md:shrink-0">
        <div
          ref={sidebarCardRef}
          className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-zinc-500">Signed in</p>
              <p className="mt-1 truncate text-sm font-medium text-white">{meQuery.data.email}</p>
            </div>
            <button
              type="button"
              onClick={() => void onLogout()}
              className="text-xs text-zinc-500 hover:text-zinc-300"
            >
              Log out
            </button>
          </div>
          <button
            type="button"
            disabled={globalBusy}
            onClick={() => syncMutation.mutate()}
            className="mt-5 w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm font-medium text-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Fetch new mail
          </button>
          <button
            type="button"
            disabled={globalBusy}
            onClick={() => recategorizeAllMutation.mutate()}
            className="mt-3 w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm font-medium text-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Re-categorize all
          </button>
          <div className="mt-6 border-t border-zinc-800 pt-5">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">New categories</p>
            <textarea
              value={newCats}
              onChange={(e) => setNewCats(e.target.value)}
              placeholder="Jobs, Receipts, …"
              rows={2}
              disabled={globalBusy}
              className="mt-2 w-full resize-none rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 disabled:cursor-not-allowed disabled:opacity-40"
            />
            <button
              type="button"
              disabled={globalBusy || !newCats.trim()}
              onClick={() => addCatsMutation.mutate()}
              className="mt-2 w-full rounded-xl bg-white px-3 py-2 text-sm font-medium text-zinc-900 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Go
            </button>
          </div>
          <div className="mt-6 border-t border-zinc-800 pt-5">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Filter categories</p>
            <div className="mt-2 flex max-h-40 flex-col gap-2 overflow-y-auto pr-1">
              {(categoriesQuery.data ?? []).map((c) => (
                <label
                  key={c.id}
                  className="flex cursor-pointer items-center justify-between gap-2 text-sm text-zinc-300"
                >
                  <span className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selectedCategoryIds.includes(c.id)}
                      onChange={() => toggleCat(c.id)}
                      className="rounded border-zinc-600 bg-zinc-900"
                    />
                    <span className="truncate">{c.name}</span>
                  </span>
                  {!c.is_system && (
                    <button
                      type="button"
                      disabled={globalBusy}
                      className="text-xs text-red-400 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-40"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        void onDeleteCategory(c);
                      }}
                    >
                      delete
                    </button>
                  )}
                </label>
              ))}
            </div>
          </div>
          <div ref={dateRangeSectionRef} className="mt-6 border-t border-zinc-800 pt-5">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Date range</p>
            <div className="mt-2 flex flex-col gap-2">
              <div className="relative">
                <button
                  type="button"
                  onClick={() =>
                    setDateRangePicker((o) => (o === "from" ? null : "from"))
                  }
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-left text-sm text-zinc-200"
                >
                  From: {fromDate ? fromDate.toDateString() : "Any"}
                </button>
                {dateRangePicker === "from" && (
                  <div className="absolute z-20 mt-2 rounded-xl border border-zinc-800 bg-zinc-950 p-2 shadow-xl">
                    <DayPicker
                      mode="single"
                      selected={fromDate}
                      onSelect={(d) => {
                        setFromDate(d);
                        setDateRangePicker(null);
                      }}
                    />
                  </div>
                )}
              </div>
              <div className="relative">
                <button
                  type="button"
                  onClick={() =>
                    setDateRangePicker((o) => (o === "to" ? null : "to"))
                  }
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-2 text-left text-sm text-zinc-200"
                >
                  To: {toDate ? toDate.toDateString() : "Any"}
                </button>
                {dateRangePicker === "to" && (
                  <div className="absolute z-20 mt-2 rounded-xl border border-zinc-800 bg-zinc-950 p-2 shadow-xl">
                    <DayPicker
                      mode="single"
                      selected={toDate}
                      onSelect={(d) => {
                        setToDate(d);
                        setDateRangePicker(null);
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </aside>

      <main
        className="flex min-h-0 min-w-0 flex-1 flex-col md:overflow-hidden"
        style={mainColumnMaxPx != null ? { maxHeight: mainColumnMaxPx } : undefined}
      >
        {globalBusy && (
          <div className="mb-4 shrink-0 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            {activeJobId ? jobLabel : "Starting…"} Only one of fetch, re-categorize, or add categories can run at a
            time. You can keep browsing existing threads below.
          </div>
        )}
        <header className="mb-4 shrink-0 md:mb-6">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-white">Inbox</h1>
            <p className="mt-1 text-sm text-zinc-500">
              Threads are classified with GPT-4o-mini. Open a category to filter.
            </p>
          </div>
        </header>
        <div
          ref={listScrollRef}
          className="max-h-[min(70vh,28rem)] overflow-y-auto overflow-x-hidden overscroll-y-contain md:max-h-none md:min-h-0 md:flex-1"
        >
          <ul className="flex flex-col gap-3">
            {visible.map((t) => (
              <li
                key={t.id}
                className="rounded-2xl border border-zinc-800 bg-zinc-900/40 px-5 py-4 transition hover:border-zinc-700"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-zinc-500">{formatDate(t.internal_date)}</span>
                  {t.categories.map((cat) => (
                    <span
                      key={cat}
                      className="rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-zinc-200"
                    >
                      {cat}
                    </span>
                  ))}
                </div>
                <h2 className="mt-2 text-base font-medium text-white">{t.subject}</h2>
                <p className="mt-1 line-clamp-2 text-sm text-zinc-400">{t.snippet}</p>
              </li>
            ))}
          </ul>
          <div ref={sentinelRef} className="h-8 shrink-0" />
          {listEnd && <p className="mt-4 text-center text-sm text-zinc-500">end</p>}
          {!visible.length && syncActiveForEmptyState && (
            <p className="mt-10 text-center text-sm text-zinc-500">
              New threads will appear here as they are classified.
            </p>
          )}
          {!visible.length && !globalBusy && (
            <p className="mt-10 text-center text-sm text-zinc-500">
              No threads yet. Use &quot;Fetch new mail&quot; to sync.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
