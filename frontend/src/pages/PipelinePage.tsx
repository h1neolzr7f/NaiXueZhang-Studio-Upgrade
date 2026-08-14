import { useEffect, useState } from "react";
import { get, post } from "../api";

type PipelineConfig = {
  auto_after_generate?: boolean;
  keep_original?: boolean;
  upscale?: { enabled?: boolean; scale?: number };
  mosaic?: { enabled?: boolean };
  metadata?: { enabled?: boolean };
};
type PipelineStatus = {
  job?: { status?: string; message?: string; current?: string };
  backlog?: { pending?: number; total?: number; message?: string };
};

export function PipelinePage() {
  const [config, setConfig] = useState<PipelineConfig>({});
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function refresh() {
    get<{ config?: PipelineConfig }>("/api/pipeline/config")
      .then((payload) => setConfig(payload.config || {}))
      .catch((err: Error) => setError(err.message));
    get<PipelineStatus>("/api/pipeline/status").then(setStatus).catch(() => undefined);
  }

  useEffect(() => {
    let cancelled = false;
    function poll() {
      get<{ config?: PipelineConfig }>("/api/pipeline/config")
        .then((payload) => {
          if (!cancelled) setConfig(payload.config || {});
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
      get<PipelineStatus>("/api/pipeline/status")
        .then((next) => {
          if (!cancelled) setStatus(next);
        })
        .catch(() => undefined);
    }
    poll();
    const timer = window.setInterval(poll, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function save() {
    setBusy(true);
    setError("");
    try {
      await post("/api/pipeline/config", config);
      setNotice("后处理配置已保存");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    setError("");
    try {
      const result = await post<{ message?: string }>("/api/pipeline/run", { only_missing: true });
      setNotice(result.message || "已启动后处理");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ws-panel">
      <h2>后处理</h2>
      <p className="ws-status">
        任务 {status?.job?.status || "空闲"}
        {status?.backlog?.pending != null ? ` · 积压 ${status.backlog.pending}` : ""}
      </p>
      <label className="ws-check">
        <input
          type="checkbox"
          checked={Boolean(config.auto_after_generate)}
          onChange={(event) => setConfig({ ...config, auto_after_generate: event.target.checked })}
        />
        出图后自动跑流水线
      </label>
      <label className="ws-check">
        <input
          type="checkbox"
          checked={Boolean(config.upscale?.enabled)}
          onChange={(event) => setConfig({ ...config, upscale: { ...config.upscale, enabled: event.target.checked } })}
        />
        超分
      </label>
      <label className="ws-check">
        <input
          type="checkbox"
          checked={Boolean(config.mosaic?.enabled)}
          onChange={(event) => setConfig({ ...config, mosaic: { ...config.mosaic, enabled: event.target.checked } })}
        />
        打码
      </label>
      <label className="ws-check">
        <input
          type="checkbox"
          checked={Boolean(config.metadata?.enabled ?? true)}
          onChange={(event) => setConfig({ ...config, metadata: { ...config.metadata, enabled: event.target.checked } })}
        />
        清元数据
      </label>
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void save()}>
          保存
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void run()}>
          处理积压
        </button>
      </div>
      <p className="ws-status">
        ANR 路径和逐张复核请打开 <a href="/pipeline">后处理详情</a>。
      </p>
      {notice ? <p className="ws-status ok">{notice}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
