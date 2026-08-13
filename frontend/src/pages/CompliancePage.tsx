import { useEffect, useState } from "react";
import { del, get, post } from "../api";

type NoticeStatus = {
  required?: boolean;
  accepted_current?: boolean;
  notice_version?: string;
};

type BlacklistItem = {
  author_id?: number;
  author_name?: string;
  reason?: string;
  scope?: string;
  local_works?: number;
  cleanup_required?: boolean;
};

type BlockedItem = {
  work_id?: number;
  source_url?: string;
  reason?: string;
};

export function CompliancePage() {
  const [notice, setNotice] = useState<NoticeStatus | null>(null);
  const [blacklist, setBlacklist] = useState<BlacklistItem[]>([]);
  const [blocked, setBlocked] = useState<BlockedItem[]>([]);
  const [authorId, setAuthorId] = useState("");
  const [authorName, setAuthorName] = useState("");
  const [reason, setReason] = useState("");
  const [workId, setWorkId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [noticeText, setNoticeText] = useState("");

  function refresh() {
    get<NoticeStatus>("/api/compliance/notice/status")
      .then(setNotice)
      .catch((err: Error) => setError(err.message));
    get<{ items?: BlacklistItem[] }>("/api/compliance/blacklist")
      .then((payload) => setBlacklist(payload.items || []))
      .catch((err: Error) => setError(err.message));
    get<{ items?: BlockedItem[] }>("/api/compliance/blocked")
      .then((payload) => setBlocked(payload.items || []))
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    refresh();
  }, []);

  async function acceptNotice() {
    setBusy(true);
    setError("");
    try {
      await post("/api/compliance/notice/accept", {});
      setNoticeText("已在本机记录责任声明。");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addAuthor() {
    const id = Number(authorId);
    if (!id || !authorName.trim()) {
      setError("作者 ID 和名字必填");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await post("/api/compliance/blacklist", {
        author_id: id,
        author_name: authorName.trim(),
        reason: reason.trim(),
        scope: "crawl",
      });
      setAuthorId("");
      setAuthorName("");
      setReason("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addBlocked() {
    const id = Number(workId);
    if (!id) {
      setError("请填写要拦截的作品 ID");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await post("/api/compliance/blocked", { work_id: id, reason: reason.trim() });
      setWorkId("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ws-panel">
      <h2>合规与来源</h2>
      <p className="ws-status">
        黑名单默认只拦爬取（scope=crawl），不会删本地文件。清理删除请走{" "}
        <a href="/compliance">经典合规页</a> 并二次确认。
      </p>
      <h3>责任声明 {notice?.accepted_current ? "已接受" : "待确认"}</h3>
      <p className="ws-prompt">本机图库、爬虫和发布由你自己负责来源与内容合规。接受记录只写在本机。</p>
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy || notice?.accepted_current} onClick={() => void acceptNotice()}>
          接受当前版本
        </button>
      </div>
      {noticeText ? <p className="ws-status ok">{noticeText}</p> : null}

      <h3>作者黑名单</h3>
      <div className="ws-toolbar">
        <input value={authorId} onChange={(event) => setAuthorId(event.target.value)} placeholder="作者 ID" aria-label="作者 ID" />
        <input value={authorName} onChange={(event) => setAuthorName(event.target.value)} placeholder="作者名" aria-label="作者名" />
        <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="原因（可选）" aria-label="原因" />
        <button className="ws-btn" disabled={busy} onClick={() => void addAuthor()}>
          加入黑名单
        </button>
      </div>
      <ul className="ws-list">
        {blacklist.map((item) => (
          <li key={String(item.author_id)}>
            {item.author_name} · {item.author_id} · {item.scope}
            {item.cleanup_required ? " · 仍有本地作品，清理请用经典页" : ""}
            <button
              className="link"
              type="button"
              onClick={() => void del(`/api/compliance/blacklist/${item.author_id}`).then(refresh).catch((err: Error) => setError(err.message))}
            >
              移除
            </button>
          </li>
        ))}
      </ul>

      <h3>拦截作品</h3>
      <div className="ws-toolbar">
        <input value={workId} onChange={(event) => setWorkId(event.target.value)} placeholder="作品 ID" aria-label="拦截作品 ID" />
        <button className="ws-btn" disabled={busy} onClick={() => void addBlocked()}>
          拦截
        </button>
      </div>
      <ul className="ws-list">
        {blocked.slice(0, 20).map((item) => (
          <li key={String(item.work_id)}>
            #{item.work_id} {item.reason ? `· ${item.reason}` : ""}
            <button
              className="link"
              type="button"
              onClick={() => void del(`/api/compliance/blocked/${item.work_id}`).then(refresh).catch((err: Error) => setError(err.message))}
            >
              移除
            </button>
          </li>
        ))}
      </ul>
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
