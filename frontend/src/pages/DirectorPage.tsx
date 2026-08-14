import { useEffect, useState } from "react";
import { get, post } from "../api";

type DirectorTool = { id?: string; label?: string; name?: string };
type DirectorSource = {
  source_id?: string;
  id?: string;
  title?: string;
  label?: string;
  thumb_url?: string;
  cover_url?: string;
  image_url?: string;
};
type DirectorPreview = {
  ok?: boolean;
  ready?: boolean;
  preview_id?: string;
  estimated_outputs?: number;
  billing?: { message?: string };
  blocking_issues?: { message?: string }[];
  message?: string;
};
type DirectorBatch = { task_id?: string; status?: string; message?: string };

export function DirectorPage() {
  const [tools, setTools] = useState<DirectorTool[]>([]);
  const [tool, setTool] = useState("");
  const [sources, setSources] = useState<DirectorSource[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [preview, setPreview] = useState<DirectorPreview | null>(null);
  const [batch, setBatch] = useState<DirectorBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function refreshSources() {
    get<{ items?: DirectorSource[]; sources?: DirectorSource[] }>("/api/director/sources?kind=generated&mode=single")
      .then((payload) => setSources(payload.items || payload.sources || []))
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    get<{ tools?: DirectorTool[] }>("/api/director/catalog")
      .then((payload) => {
        const list = payload.tools || [];
        setTools(list);
        if (!tool && list[0]?.id) setTool(String(list[0].id));
      })
      .catch((err: Error) => setError(err.message));
    refreshSources();
    get<{ batch?: DirectorBatch }>("/api/director/jobs/status")
      .then((payload) => setBatch(payload.batch || null))
      .catch(() => undefined);
  }, []);

  function toggle(sourceId: string) {
    setPicked((current) => (current.includes(sourceId) ? current.filter((id) => id !== sourceId) : [...current, sourceId]));
    setPreview(null);
  }

  function recipe() {
    return { tool };
  }

  function selectedSources() {
    return sources
      .filter((item) => picked.includes(String(item.source_id || item.id)))
      .map((item) => ({ source_id: item.source_id || item.id, ...item }));
  }

  async function runPreview() {
    if (!picked.length) {
      setError("请先选择来源图");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await post<DirectorPreview>("/api/director/preview", {
        sources: selectedSources(),
        recipe: recipe(),
      });
      setPreview(result);
      setNotice(result.billing?.message || "预检完成，未调用 NovelAI");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmStart() {
    if (!preview?.preview_id) {
      setError("请先完成零费用预检");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await post<DirectorBatch>("/api/director/jobs", {
        sources: selectedSources(),
        recipe: recipe(),
        confirmed: true,
        preview_id: preview.preview_id,
      });
      setBatch(result);
      setNotice(result.message || "导演任务已提交；失败项不会自动重扣");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ws-panel">
      <h2>导演台</h2>
      <p className="ws-status">必须先预检。预检不扣 Anlas；确认后才可能产生费用。失败不会自动重试。</p>
      <div className="ws-toolbar">
        <select value={tool} onChange={(event) => setTool(event.target.value)} aria-label="导演工具">
          {tools.map((item) => (
            <option key={String(item.id)} value={String(item.id)}>
              {item.label || item.name || item.id}
            </option>
          ))}
        </select>
      </div>
      <div className="ws-grid compact">
        {sources.slice(0, 24).map((item) => {
          const id = String(item.source_id || item.id || "");
          const src = item.thumb_url || item.cover_url || item.image_url || "";
          const active = picked.includes(id);
          return (
            <article className={active ? "ws-card selected" : "ws-card"} key={id} onClick={() => toggle(id)}>
              {src ? <img src={src} alt={item.label || item.title || id} loading="lazy" /> : <div style={{ height: 120 }} />}
              <div className="meta">{item.label || item.title || id}</div>
            </article>
          );
        })}
      </div>
      <div className="ws-actions">
        <button className="ws-btn ghost" disabled={busy} onClick={() => void runPreview()}>
          零费用预检
        </button>
        <button className="ws-btn" disabled={busy || !preview?.preview_id} onClick={() => void confirmStart()}>
          确认执行
        </button>
      </div>
      {preview ? (
        <p className="ws-status">
          预估输出 {preview.estimated_outputs ?? 0} 张
          {preview.ready ? " · 可提交" : " · 未就绪"}
        </p>
      ) : null}
      {(preview?.blocking_issues || []).map((item) => (
        <p className="ws-status err" key={item.message}>
          {item.message}
        </p>
      ))}
      {batch?.status ? <p className="ws-status">当前任务 {batch.status} {batch.message || ""}</p> : null}
      <p className="ws-status">
        表情/线稿等完整参数请打开 <a href="/director">导演台详情</a>。
      </p>
      {notice ? <p className="ws-status ok">{notice}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
