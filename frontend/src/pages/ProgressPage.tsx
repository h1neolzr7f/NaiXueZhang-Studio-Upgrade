import { useEffect, useState } from "react";
import { get, post } from "../api";

type CrawlerTarget = {
  name?: string;
  running?: boolean;
  pid?: number;
  phase?: string;
  message?: string;
};
type CrawlerStatus = {
  targets?: Record<string, CrawlerTarget>;
  running?: boolean;
  message?: string;
  watchdog?: { enabled?: boolean; reason?: string };
};
type CrawlerReport = {
  last_run?: string;
  message?: string;
  imported?: number;
  skipped?: number;
  errors?: number;
  search_query?: string;
};

export function ProgressPage() {
  const [status, setStatus] = useState<CrawlerStatus | null>(null);
  const [report, setReport] = useState<CrawlerReport | null>(null);
  const [target, setTarget] = useState("pixiv");
  const [watch, setWatch] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function refresh() {
    get<{ status?: CrawlerStatus }>("/api/crawler/status")
      .then((payload) => setStatus(payload.status || null))
      .catch((err: Error) => setError(err.message));
    get<{ report?: CrawlerReport }>("/api/crawler/report")
      .then((payload) => setReport(payload.report || null))
      .catch(() => undefined);
  }

  useEffect(() => {
    let cancelled = false;
    function poll() {
      get<{ status?: CrawlerStatus }>("/api/crawler/status")
        .then((payload) => {
          if (!cancelled) setStatus(payload.status || null);
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
      get<{ report?: CrawlerReport }>("/api/crawler/report")
        .then((payload) => {
          if (!cancelled) setReport(payload.report || null);
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

  async function run(path: string, extra: Record<string, unknown> = {}) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await post<{ message?: string; status?: CrawlerStatus }>(path, {
        target,
        watch,
        ...extra,
      });
      setNotice(result.message || "已提交");
      if (result.status) setStatus(result.status);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const targets = status?.targets || {};
  const rows = Object.keys(targets).length
    ? Object.entries(targets)
    : ([["pixiv", { running: Boolean(status?.running), message: status?.message }]] as [string, CrawlerTarget][]);

  return (
    <section className="ws-panel">
      <h2>爬虫</h2>
      <p className="ws-status">
        空库会拒绝新采集。完整任务表和断点仍在 <a href="/progress">经典爬虫页</a>。
      </p>
      <div className="ws-toolbar">
        <select value={target} onChange={(event) => setTarget(event.target.value)} aria-label="采集目标">
          <option value="pixiv">Pixiv</option>
          <option value="site">站点图库</option>
        </select>
        <label className="ws-check">
          <input type="checkbox" checked={watch} onChange={(event) => setWatch(event.target.checked)} />
          看门狗
        </label>
      </div>
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void run("/api/crawler/start")}>
          启动
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void run("/api/crawler/stop")}>
          停止
        </button>
        <button className="ws-btn ghost" disabled={busy || target !== "pixiv"} onClick={() => void run("/api/crawler/autopilot")}>
          甩手采集
        </button>
      </div>
      <ul className="ws-list">
        {rows.map(([name, item]) => (
          <li key={name}>
            <strong>{name}</strong>
            {item.running ? " · 运行中" : " · 已停"}
            {item.phase ? ` · ${item.phase}` : ""}
            {item.message ? ` · ${item.message}` : ""}
          </li>
        ))}
      </ul>
      {report ? (
        <p className="ws-status">
          最近：{report.last_run || "无"} · 导入 {report.imported ?? 0} · 跳过 {report.skipped ?? 0}
          {report.search_query ? ` · ${report.search_query}` : ""}
        </p>
      ) : null}
      {status?.watchdog ? (
        <p className="ws-status">
          看门狗 {status.watchdog.enabled ? "开" : "关"}
          {status.watchdog.reason ? ` · ${status.watchdog.reason}` : ""}
        </p>
      ) : null}
      {notice ? <p className="ws-status ok">{notice}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
