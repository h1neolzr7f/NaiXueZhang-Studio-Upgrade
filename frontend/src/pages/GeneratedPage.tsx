import { useEffect, useState } from "react";
import { del, get, post } from "../api";
import { generatedPath, navigate, studioPath } from "../routes";

type GeneratedItem = {
  id?: string;
  image_url?: string;
  thumb_url?: string;
};
type SourcePrompt = { base_caption?: string; chars?: { caption?: string; summary?: string }[] };
type GeneratedGroup = {
  group_id?: string;
  work_id?: number | string;
  source_gallery_id?: string;
  source_title?: string;
  title?: string;
  cover_url?: string;
  cover_thumb?: string;
  thumb_url?: string;
  count?: number;
  image_count?: number;
  items?: GeneratedItem[];
  source_prompt?: SourcePrompt;
  source?: { work_id?: number | string; title?: string; url?: string };
};
type GeneratedPayload = {
  groups?: GeneratedGroup[];
  batch?: { status?: string; message?: string; done?: number; total?: number };
  queue?: { status?: string; message?: string };
};
type TrashItem = {
  trash_id?: string;
  kind?: string;
  group_id?: string;
  created_at?: string;
  file_count?: number;
};

function parseGroup(search: string): string {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return params.get("group") || "";
}

export function GeneratedPage({ search }: { search: string }) {
  const groupId = parseGroup(search);
  const [payload, setPayload] = useState<GeneratedPayload>({ groups: [] });
  const [detail, setDetail] = useState<GeneratedGroup | null>(null);
  const [trash, setTrash] = useState<TrashItem[]>([]);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState("");
  const [notice, setNotice] = useState("");

  function refresh() {
    get<GeneratedPayload>("/api/generated")
      .then(setPayload)
      .catch((err: Error) => setError(err.message));
    get<{ items?: TrashItem[] }>("/api/generated/trash")
      .then((data) => setTrash(data.items || []))
      .catch(() => undefined);
  }

  useEffect(() => {
    let cancelled = false;
    get<GeneratedPayload>("/api/generated")
      .then((next) => {
        if (!cancelled) setPayload(next);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    get<{ items?: TrashItem[] }>("/api/generated/trash")
      .then((data) => {
        if (!cancelled) setTrash(data.items || []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const running = payload.batch?.status === "running" || payload.queue?.status === "running";
    if (!running) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      get<GeneratedPayload>("/api/generated")
        .then((next) => {
          if (!cancelled) setPayload(next);
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [payload.batch?.status, payload.queue?.status]);

  useEffect(() => {
    if (!groupId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    get<{ ok?: boolean; group?: GeneratedGroup; source_prompt?: SourcePrompt; source?: GeneratedGroup["source"] }>(
      `/api/generated/${encodeURIComponent(groupId)}`,
    )
      .then((data) => {
        if (cancelled) return;
        const group = data.group || (data as GeneratedGroup);
        setDetail({ ...group, source_prompt: data.source_prompt || group.source_prompt, source: data.source || group.source });
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  async function removeGroup(id: string) {
    if (!window.confirm("删除这组生成图？文件会进入回收站，不会直接销毁。")) return;
    try {
      const result = await del<{ trash_id?: string }>(`/api/generated/group/${encodeURIComponent(id)}`);
      setPreview("");
      setNotice(result.trash_id ? `已移入回收站 ${result.trash_id.slice(0, 8)}…` : "已移入回收站");
      navigate(generatedPath());
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function removeItem(id: string) {
    if (!window.confirm("删除这张生成图？文件会进入回收站。")) return;
    try {
      await del(`/api/generated/item/${encodeURIComponent(id)}`);
      setPreview("");
      if (groupId) {
        const data = await get<{ group?: GeneratedGroup; source_prompt?: SourcePrompt }>(
          `/api/generated/${encodeURIComponent(groupId)}`,
        );
        setDetail({ ...(data.group || data), source_prompt: data.source_prompt });
      }
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function restore(id: string) {
    try {
      await post(`/api/generated/trash/${encodeURIComponent(id)}/restore`, {});
      setNotice("已从回收站恢复");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const groups = payload.groups || [];
  const batch = payload.batch;
  const items = detail?.items || [];
  const source = detail?.source_prompt;
  const sourceWork = String(detail?.source?.work_id || detail?.work_id || "");
  const sourceGallery = String(detail?.source_gallery_id || "site");

  return (
    <section>
      <p className="ws-status">
        队列 {payload.queue?.status || "idle"}
        {batch?.status ? ` · 批量 ${batch.status} ${batch.done || 0}/${batch.total || 0}` : ""}
        {batch?.message ? ` · ${batch.message}` : ""}
      </p>
      {notice ? <p className="ws-status ok">{notice}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
      {groupId && detail ? (
        <div className="ws-panel" style={{ marginBottom: 16 }}>
          <div className="ws-actions">
            <button className="ws-btn ghost" onClick={() => navigate(generatedPath())}>
              返回列表
            </button>
            {sourceWork ? (
              <button className="ws-btn ghost" onClick={() => navigate(studioPath(sourceWork, sourceGallery))}>
                用来源再出图
              </button>
            ) : null}
            <button className="ws-btn ghost" onClick={() => void removeGroup(groupId)}>
              删除这组
            </button>
          </div>
          <strong>{detail.source_title || detail.title || groupId}</strong>
          {source?.base_caption ? <p className="ws-status">{source.base_caption}</p> : null}
          {(source?.chars || []).map((item, index) => (
            <p className="ws-status" key={`${item.summary}-${index}`}>
              {item.summary || item.caption}
            </p>
          ))}
          <div className="ws-grid">
            {items.map((item) => {
              const src = String(item.image_url || item.thumb_url || "");
              const id = String(item.id || "");
              return (
                <article className="ws-card" key={id || src}>
                  {src ? <img src={src} alt="" loading="lazy" onClick={() => setPreview(src)} /> : null}
                  {id ? (
                    <button className="ws-btn ghost" type="button" onClick={() => void removeItem(id)}>
                      删除这张
                    </button>
                  ) : null}
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="ws-grid">
          {groups.map((item) => {
            const id = String(item.group_id || "");
            const src = String(item.cover_thumb || item.cover_url || item.thumb_url || "");
            return (
              <article className="ws-card" key={id} onClick={() => id && navigate(generatedPath(id))}>
                {src ? <img src={src} alt={item.source_title || id} loading="lazy" /> : null}
                <div className="meta">
                  {item.source_title || item.title || id} · {item.count || item.image_count || 0}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {trash.length ? (
        <div className="ws-panel" style={{ marginTop: 18 }}>
          <h2>回收站</h2>
          {trash.map((item) => (
            <div className="ws-task" key={String(item.trash_id)}>
              <span>
                {item.kind || "item"} · {item.group_id || ""} · {item.file_count || 0} 个文件 · {item.created_at || ""}
              </span>
              <button className="ws-btn ghost" type="button" onClick={() => item.trash_id && void restore(item.trash_id)}>
                恢复
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {preview ? (
        <button className="ws-lightbox" onClick={() => setPreview("")} aria-label="关闭预览">
          <img src={preview} alt="" />
        </button>
      ) : null}
    </section>
  );
}
