import { useEffect, useState } from "react";
import { get, post } from "../api";

type PixivAccount = {
  id?: string;
  label?: string;
  username?: string;
  user_name?: string;
  active?: boolean;
  has_refresh_token?: boolean;
};
type PixivJob = {
  status?: string;
  message?: string;
  step?: string;
  progress?: { percent?: number; label?: string };
};
type PixivStatus = {
  pixiv?: { configured?: boolean; username?: string; message?: string };
  ai?: { configured?: boolean };
  job?: PixivJob;
};
type PixivGroup = {
  group_id?: string;
  id?: string;
  source_title?: string;
  title?: string;
  count?: number;
  cover_url?: string;
  image_ids?: string[];
};
type HistoryItem = { title?: string; url?: string; created_at?: string; account_label?: string };

export function PixivPage() {
  const [status, setStatus] = useState<PixivStatus | null>(null);
  const [accounts, setAccounts] = useState<PixivAccount[]>([]);
  const [groups, setGroups] = useState<PixivGroup[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [token, setToken] = useState("");
  const [label, setLabel] = useState("");
  const [groupId, setGroupId] = useState("");
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [tags, setTags] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function refresh() {
    get<PixivStatus>("/api/pixiv/status").then(setStatus).catch((err: Error) => setError(err.message));
    get<{ accounts?: PixivAccount[] }>("/api/pixiv/accounts")
      .then((payload) => setAccounts(payload.accounts || []))
      .catch(() => undefined);
    get<{ groups?: PixivGroup[]; items?: PixivGroup[] }>("/api/pixiv/groups")
      .then((payload) => setGroups(payload.groups || payload.items || []))
      .catch(() => undefined);
    get<{ items?: HistoryItem[] }>("/api/pixiv/history?limit=12")
      .then((payload) => setHistory(payload.items || []))
      .catch(() => undefined);
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const running = String(status?.job?.status || "") === "running";
    if (!running) return;
    const timer = window.setInterval(() => {
      get<PixivStatus>("/api/pixiv/status")
        .then(setStatus)
        .catch((err: Error) => setError(err.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [status?.job?.status]);

  const activeAccount = accounts.find((account) => account.active);

  async function addAccount() {
    if (!token.trim()) {
      setError("请粘贴 Pixiv refresh token");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await post("/api/pixiv/accounts", { refresh_token: token.trim(), label: label.trim() });
      setToken("");
      setNotice("账号已写入本机加密存储");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function switchAccount(accountId: string) {
    setBusy(true);
    setError("");
    try {
      await post("/api/pixiv/accounts/switch", { account_id: accountId });
      setNotice("已切换活跃账号");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function browserLogin() {
    if (!window.confirm("将打开本机 Chrome 登录 Pixiv，不会上传作品，也不会扣 Anlas。继续？")) return;
    setBusy(true);
    setError("");
    try {
      const payload = await post<{ ok?: boolean; message?: string }>("/api/pixiv/auth/browser-login", {
        account_id: activeAccount?.id,
        label: label.trim(),
      });
      setNotice(payload.message || "浏览器登录已完成");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function probeSelectors() {
    setBusy(true);
    setError("");
    try {
      const payload = await post<{ ok?: boolean; message?: string }>("/api/pixiv/upload-selector-probe", {
        account_id: activeAccount?.id,
        headless: true,
      });
      setNotice(payload.message || "选择器探测完成，未上传任何文件");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function publishPayload() {
    const group = groups.find((item) => String(item.group_id || item.id) === groupId);
    return {
      account_id: activeAccount?.id,
      group_id: groupId,
      image_ids: group?.image_ids || [],
      title: title.trim(),
      caption: caption.trim(),
      tags: tags.trim().split(/\s+/).filter(Boolean).slice(0, 10),
    };
  }

  async function publish(kind: "upload" | "launch") {
    if (!groupId) {
      setError("请先选择一个生成组");
      return;
    }
    if (!title.trim()) {
      setError("标题不能为空，避免后端静默改用 AI 文案");
      return;
    }
    if (!confirmed) {
      setError("请勾选确认后再投稿。这会打开本机 Chrome，不是 Anlas 扣费。");
      return;
    }
    const action = kind === "upload" ? "仅浏览器上传所选组" : "一键起号（后处理 + 上传）";
    if (!window.confirm(`${action}。会弹出 Chrome，不会调用 NAI。继续？`)) return;
    setBusy(true);
    setError("");
    try {
      const path = kind === "upload" ? "/api/pixiv/upload" : "/api/pixiv/launch";
      const payload = await post<{ ok?: boolean; message?: string }>(path, publishPayload());
      setNotice(payload.message || (kind === "upload" ? "上传已启动" : "一键起号已启动"));
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ws-panel">
      <h2>发布</h2>
      <p className="ws-status">
        {status?.pixiv?.configured ? `Pixiv 已登录${status.pixiv.username ? ` · ${status.pixiv.username}` : ""}` : "尚未配置 Pixiv 账号"}
        {status?.job?.status ? ` · 任务 ${status.job.status}` : ""}
        {status?.job?.message ? ` · ${status.job.message}` : ""}
      </p>
      <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="账号备注" aria-label="账号备注" />
      <input
        type="password"
        value={token}
        onChange={(event) => setToken(event.target.value)}
        placeholder="refresh_token"
        autoComplete="off"
        aria-label="Pixiv refresh token"
      />
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void addAccount()}>
          添加账号
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void browserLogin()}>
          浏览器登录
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void probeSelectors()}>
          探测上传页（不上传）
        </button>
      </div>
      <ul className="ws-list">
        {accounts.map((account) => (
          <li key={String(account.id)}>
            {account.label || account.username || account.user_name || account.id}
            {account.active ? " · 当前" : ""}
            {!account.active && account.id ? (
              <button className="link" type="button" onClick={() => void switchAccount(String(account.id))}>
                切换
              </button>
            ) : null}
          </li>
        ))}
      </ul>

      <h3>上传所选组</h3>
      <p className="ws-status">投稿走本机 Chrome，不是 NAI force_free。标题必填；一键起号会先跑后处理再上传。</p>
      <select value={groupId} onChange={(event) => setGroupId(event.target.value)} aria-label="生成组">
        <option value="">选择生成组</option>
        {groups.slice(0, 40).map((group) => {
          const id = String(group.group_id || group.id || "");
          return (
            <option key={id} value={id}>
              {group.source_title || group.title || id} · {group.count || group.image_ids?.length || 0}
            </option>
          );
        })}
      </select>
      <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" aria-label="投稿标题" />
      <textarea value={caption} onChange={(event) => setCaption(event.target.value)} placeholder="简介" aria-label="投稿简介" />
      <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="标签，空格分隔" aria-label="投稿标签" />
      <label className="ws-check">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        确认打开本机 Chrome 投稿（不是 Anlas）
      </label>
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void publish("upload")}>
          上传所选组
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void publish("launch")}>
          一键起号
        </button>
      </div>

      <h3>最近投稿</h3>
      <ul className="ws-list">
        {history.map((item, index) => (
          <li key={`${item.url || item.title || index}`}>
            {item.title || "无标题"}
            {item.created_at ? ` · ${item.created_at}` : ""}
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer">
                打开
              </a>
            ) : null}
          </li>
        ))}
      </ul>
      {notice ? <p className="ws-status ok">{notice}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
