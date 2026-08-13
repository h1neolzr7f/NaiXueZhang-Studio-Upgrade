import { useEffect, useMemo, useState } from "react";
import { get, post } from "../api";
import { workIdOf } from "../comment";
import { galleryPath, navigate, remixPath, studioPath, type GalleryQuery } from "../routes";

type GalleryItem = {
  work_id?: number | string;
  id?: number | string;
  title?: string;
  thumb_url?: string;
  cover_url?: string;
  thumb?: string;
  gallery_id?: string;
  tags?: string[];
  prompt?: string;
};

type SearchPayload = {
  items?: GalleryItem[];
  total?: number;
  error?: string;
  message_zh?: string;
};

type WorkLite = {
  work_id?: number | string;
  title?: string;
  tags?: string[];
  thumb_url?: string;
  cover_url?: string;
  page_count?: number;
  prompt?: string;
  images?: { url?: string; thumb_url?: string }[];
};

type GalleryOption = { id?: string; gallery_id?: string; label?: string; name?: string };
type GroupOption = { key?: string; id?: string; name?: string; label?: string } | string;

function thumbOf(item: { thumb_url?: string; cover_url?: string; thumb?: string }): string {
  return String(item.thumb_url || item.cover_url || item.thumb || "");
}

function parseQuery(search: string): GalleryQuery & { q: string; galleryId: string; page: number } {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return {
    galleryId: params.get("gallery") || "site",
    q: params.get("q") || "",
    page: Math.max(1, Number(params.get("page") || 1) || 1),
    sort: params.get("sort") || "new",
    timeRange: params.get("time") || "all",
    prompt: params.get("prompt") || "",
    group: params.get("group") || "",
    view: params.get("view") || "all",
  };
}

function groupKey(item: GroupOption): string {
  if (typeof item === "string") return item;
  return String(item.key || item.id || item.name || item.label || "");
}

function groupLabel(item: GroupOption): string {
  if (typeof item === "string") return item;
  return String(item.label || item.name || item.key || item.id || "");
}

export function GalleryPage({ search }: { search: string }) {
  const query = parseQuery(search);
  const { galleryId, q, page, sort = "new", timeRange = "all", prompt = "", group = "", view = "all" } = query;
  const [draft, setDraft] = useState(q);
  const [promptDraft, setPromptDraft] = useState(prompt);
  const [data, setData] = useState<SearchPayload>({ items: [] });
  const [galleries, setGalleries] = useState<GalleryOption[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<WorkLite | null>(null);
  const [favorited, setFavorited] = useState(false);
  const [queued, setQueued] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function go(next: Partial<GalleryQuery>) {
    navigate(
      galleryPath({
        galleryId,
        q: draft,
        page,
        sort,
        timeRange,
        prompt: promptDraft,
        group,
        view,
        ...next,
      }),
    );
  }

  useEffect(() => {
    setDraft(q);
    setPromptDraft(prompt);
  }, [q, prompt]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (draft !== q) {
        navigate(
          galleryPath({
            galleryId,
            q: draft,
            page: 1,
            sort,
            timeRange,
            prompt: promptDraft,
            group,
            view,
          }),
        );
      }
    }, 280);
    return () => window.clearTimeout(timer);
  }, [draft, galleryId, q, sort, timeRange, promptDraft, group, view]);

  useEffect(() => {
    get<{ items?: GalleryOption[] }>("/api/galleries")
      .then((payload) => setGalleries(payload.items || []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    get<{ items?: GroupOption[] }>(`/api/galleries/${encodeURIComponent(galleryId)}/groups`)
      .then((payload) => setGroups(payload.items || []))
      .catch(() => setGroups([]));
  }, [galleryId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      q,
      gallery_id: galleryId,
      page: String(page),
      page_size: "60",
      sort,
      time_range: timeRange,
    });
    if (prompt.trim()) params.set("prompt", prompt.trim());
    if (group.trim()) params.set("group", group.trim());
    const path =
      view === "favorites"
        ? `/api/favorites/works?${params.toString()}`
        : view === "queue"
          ? `/api/queue/works?${params.toString()}`
          : `/api/ai_works_search?${params.toString()}`;
    get<SearchPayload>(path)
      .then((payload) => {
        if (!cancelled) setData(payload || { items: [] });
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "搜索失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [q, galleryId, page, sort, timeRange, prompt, group, view]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    const params = `gallery_id=${encodeURIComponent(galleryId)}`;
    get<WorkLite>(`/api/work/${encodeURIComponent(selected)}/lite?${params}`)
      .then((payload) => {
        if (!cancelled) setDetail(payload);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    get<{ favorited?: boolean }>(`/api/favorites/${encodeURIComponent(selected)}?${params}`)
      .then((payload) => {
        if (!cancelled) setFavorited(Boolean(payload.favorited));
      })
      .catch(() => undefined);
    get<{ queued?: boolean }>(`/api/queue/${encodeURIComponent(selected)}?${params}`)
      .then((payload) => {
        if (!cancelled) setQueued(Boolean(payload.queued));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selected, galleryId]);

  const items = useMemo(() => data.items || [], [data]);
  const galleryOptions =
    galleries.length > 0
      ? galleries
      : [
          { id: "site", label: "主图库" },
          { id: "codex", label: "自选库" },
          { id: "qqgroup", label: "QQ 图库" },
        ];

  async function toggleFavorite() {
    if (!selected) return;
    const result = await post<{ favorited?: boolean }>(
      `/api/favorites/${encodeURIComponent(selected)}/toggle?gallery_id=${encodeURIComponent(galleryId)}`,
      {},
    );
    setFavorited(Boolean(result.favorited));
  }

  async function toggleQueue() {
    if (!selected) return;
    const result = await post<{ queued?: boolean }>(
      `/api/queue/${encodeURIComponent(selected)}/toggle?gallery_id=${encodeURIComponent(galleryId)}`,
      {},
    );
    setQueued(Boolean(result.queued));
  }

  return (
    <section className="ws-split">
      <div>
        <div className="ws-toolbar">
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="搜索标题 / 标签" aria-label="搜索图库" />
          <input
            value={promptDraft}
            onChange={(event) => setPromptDraft(event.target.value)}
            onBlur={() => promptDraft !== prompt && go({ prompt: promptDraft, page: 1 })}
            onKeyDown={(event) => {
              if (event.key === "Enter") go({ prompt: promptDraft, page: 1 });
            }}
            placeholder="按 prompt 过滤"
            aria-label="prompt 过滤"
          />
          <select value={galleryId} onChange={(event) => go({ galleryId: event.target.value, page: 1, group: "" })} aria-label="图库">
            {galleryOptions.map((item) => {
              const id = String(item.id || item.gallery_id || "");
              return (
                <option key={id} value={id}>
                  {item.label || item.name || id}
                </option>
              );
            })}
          </select>
          <select value={sort} onChange={(event) => go({ sort: event.target.value, page: 1 })} aria-label="排序">
            <option value="new">最新</option>
            <option value="old">最早</option>
            <option value="count">页数</option>
          </select>
          <select value={timeRange} onChange={(event) => go({ timeRange: event.target.value, page: 1 })} aria-label="时间">
            <option value="all">全部时间</option>
            <option value="week">近一周</option>
            <option value="month">近一月</option>
            <option value="year">近一年</option>
          </select>
          <select value={group} onChange={(event) => go({ group: event.target.value, page: 1 })} aria-label="分组">
            <option value="">全部分组</option>
            {groups.map((item) => {
              const key = groupKey(item);
              return (
                <option key={key} value={key}>
                  {groupLabel(item)}
                </option>
              );
            })}
          </select>
          <select value={view} onChange={(event) => go({ view: event.target.value, page: 1 })} aria-label="视图">
            <option value="all">全部</option>
            <option value="favorites">收藏</option>
            <option value="queue">待生成</option>
          </select>
          <span className="ws-status">{loading ? "加载中…" : `共 ${data.total ?? items.length} 条`}</span>
        </div>
        {error ? <p className="ws-status err">{error}</p> : null}
        <div className="ws-grid">
          {items.map((item) => {
            const workId = workIdOf(item.work_id ?? item.id);
            const src = thumbOf(item);
            const gid = item.gallery_id || galleryId;
            const active = selected === workId;
            return (
              <article className={active ? "ws-card selected" : "ws-card"} key={`${gid}:${workId}`}>
                {src ? (
                  <img
                    src={src}
                    alt={item.title || workId}
                    loading="lazy"
                    onClick={() => setSelected(workId)}
                  />
                ) : (
                  <div style={{ height: 220 }} onClick={() => setSelected(workId)} />
                )}
                <div className="meta">
                  <button className="link" type="button" onClick={() => workId && navigate(studioPath(workId, gid))}>
                    {item.title || `#${workId}`}
                  </button>
                  {workId ? (
                    <a href={`/i/${encodeURIComponent(workId)}${gid !== "site" ? `?gallery=${encodeURIComponent(gid)}` : ""}`}>
                      详情
                    </a>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
        <div className="ws-actions" style={{ marginTop: 16 }}>
          <button className="ws-btn ghost" disabled={page <= 1} onClick={() => go({ page: page - 1 })}>
            上一页
          </button>
          <button className="ws-btn ghost" onClick={() => go({ page: page + 1 })}>
            下一页
          </button>
        </div>
      </div>
      <aside className="ws-detail">
        {detail ? (
          <>
            <img src={thumbOf(detail)} alt={String(detail.title || selected)} />
            <h2>{detail.title || `#${selected}`}</h2>
            <p className="ws-status">{(detail.tags || []).slice(0, 12).join(" · ")}</p>
            {detail.prompt ? <p className="ws-prompt">{detail.prompt}</p> : null}
            <div className="ws-actions">
              <button className="ws-btn" onClick={() => navigate(studioPath(selected, galleryId))}>
                去工作台
              </button>
              <button className="ws-btn ghost" onClick={() => navigate(remixPath(selected, galleryId))}>
                换角
              </button>
              <button className="ws-btn ghost" onClick={() => void toggleFavorite()}>
                {favorited ? "取消收藏" : "收藏"}
              </button>
              <button className="ws-btn ghost" onClick={() => void toggleQueue()}>
                {queued ? "移出队列" : "加入待生成"}
              </button>
            </div>
          </>
        ) : (
          <p className="ws-status">点选一张图查看筛选后的作品，并从这里进工作台或换角。经典图库仍保留完整 atlas。</p>
        )}
      </aside>
    </section>
  );
}
