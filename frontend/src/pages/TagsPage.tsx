import { useEffect, useMemo, useState } from "react";
import { get } from "../api";
import { navigate, remixPath, studioPath } from "../routes";

const FACET_LABELS: Record<string, string> = {
  character: "角色",
  copyright: "作品",
  artist: "画师",
  action: "动作",
  clothing: "服装",
  scene: "场景",
  composition: "构图",
  other: "其他",
};

type FacetItem = {
  facet?: string;
  tag?: string;
  display_tag?: string;
  work_count?: number;
};

type TagWork = {
  id?: number | string;
  work_id?: number | string;
  title?: string;
  thumb_url?: string;
  thumb_path?: string;
  cover_url?: string;
};

function thumbOf(item: TagWork): string {
  if (item.thumb_url || item.cover_url) return String(item.thumb_url || item.cover_url);
  const path = String(item.thumb_path || "").replaceAll("\\", "/");
  if (!path) return "";
  return (
    "/data/images/" +
    path
      .split("/")
      .filter(Boolean)
      .map(encodeURIComponent)
      .join("/")
  );
}

function workIdOf(item: TagWork): string {
  return String(item.work_id || item.id || "");
}

export function TagsPage() {
  const [facets, setFacets] = useState<string[]>(Object.keys(FACET_LABELS));
  const [facet, setFacet] = useState("character");
  const [items, setItems] = useState<FacetItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [works, setWorks] = useState<TagWork[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "60", sort: "new" });
    selected.forEach((value) => params.append("selection", value));
    return params.toString();
  }, [page, selected]);

  useEffect(() => {
    get<{ facets?: string[]; items?: FacetItem[] }>(
      `/api/nai-tags?facet=${encodeURIComponent(facet)}&limit=80`,
    )
      .then((payload) => {
        if (payload.facets?.length) setFacets(payload.facets);
        setItems(payload.items || []);
      })
      .catch((err: Error) => setError(err.message));
  }, [facet]);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    get<{ items?: TagWork[]; total?: number }>(`/api/nai-tags/works?${query}`)
      .then((payload) => {
        if (cancelled) return;
        setWorks(payload.items || []);
        setTotal(Number(payload.total || 0));
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  function toggle(item: FacetItem) {
    const key = `${item.facet || facet}:${item.tag}`;
    setPage(1);
    setSelected((current) => (current.includes(key) ? current.filter((value) => value !== key) : [...current, key]));
  }

  return (
    <section className="ws-split">
      <div>
        <h2>分类</h2>
        <p className="ws-status">按 NAI 标签面筛选主图库。点选作品可去工作台或换角，不会扣 Anlas。</p>
        <div className="ws-chips">
          {facets.map((name) => (
            <button
              key={name}
              type="button"
              className={facet === name ? "ws-chip active" : "ws-chip"}
              aria-pressed={facet === name}
              onClick={() => setFacet(name)}
            >
              {FACET_LABELS[name] || name}
            </button>
          ))}
        </div>
        <div className="ws-chips wrap">
          {items.map((item) => {
            const key = `${item.facet || facet}:${item.tag}`;
            return (
              <button
                key={key}
                type="button"
                className={selected.includes(key) ? "ws-chip active" : "ws-chip"}
                onClick={() => toggle(item)}
              >
                {item.display_tag || item.tag} · {item.work_count || 0}
              </button>
            );
          })}
        </div>
        {selected.length ? (
          <div className="ws-actions">
            <span className="ws-status">已组合 {selected.length} 个标签</span>
            <button
              className="ws-btn ghost"
              type="button"
              onClick={() => {
                setSelected([]);
                setPage(1);
              }}
            >
              清空
            </button>
          </div>
        ) : null}
        <p className="ws-status">{busy ? "加载中…" : `共 ${total} 件`}</p>
        <div className="ws-grid">
          {works.map((item) => {
            const id = workIdOf(item);
            return (
              <button
                key={id}
                type="button"
                className="ws-card"
                onClick={() => navigate(studioPath(id, "site"))}
              >
                {thumbOf(item) ? <img src={thumbOf(item)} alt="" /> : <div className="ws-missing" />}
                <span>{item.title || `#${id}`}</span>
              </button>
            );
          })}
        </div>
        <div className="ws-actions" style={{ marginTop: 16 }}>
          <button className="ws-btn ghost" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
            上一页
          </button>
          <button className="ws-btn ghost" disabled={works.length < 60} onClick={() => setPage((value) => value + 1)}>
            下一页
          </button>
        </div>
      </div>
      <aside className="ws-detail">
        <h2>已选标签</h2>
        {selected.length ? (
          <ul className="ws-list">
            {selected.map((key) => (
              <li key={key}>
                {key}
                <button className="link" type="button" onClick={() => setSelected((current) => current.filter((value) => value !== key))}>
                  移除
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="ws-status">先选角色/画师等标签，再打开作品。</p>
        )}
        {works[0] ? (
          <div className="ws-actions">
            <button className="ws-btn" onClick={() => navigate(studioPath(workIdOf(works[0]), "site"))}>
              打开首张工作台
            </button>
            <button className="ws-btn ghost" onClick={() => navigate(remixPath(workIdOf(works[0]), "site"))}>
              换角
            </button>
          </div>
        ) : null}
        {error ? <p className="ws-status err">{error}</p> : null}
      </aside>
    </section>
  );
}
