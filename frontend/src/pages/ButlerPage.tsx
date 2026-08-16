import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { get, post } from "../api";
import { compressImage, type ImageAttachment } from "../image";

type ChatMessage = { id?: number; role: string; content: string; preview?: string };
type PendingAction = {
  confirmation_id?: string;
  label?: string;
  summary?: string;
  risk?: string;
  lane?: string;
  work_order?: { retry_policy?: string; cost?: { anlas_estimate?: string } };
};
type ToolResult = {
  tool?: string;
  message?: string;
  ok?: boolean;
  items?: { image_url?: string; work_id?: number | string; gallery_id?: string; title?: string; thumb?: string }[];
};
type ChatResponse = {
  reply?: string;
  pending_actions?: PendingAction[];
  rejected_actions?: { tool?: string; reason?: string }[];
  tool_results?: ToolResult[];
  workflow_id?: string;
};
type ButlerStatus = {
  ai?: { configured?: boolean; model?: string; provider?: string };
  generation?: { configured?: boolean };
  pending_count?: number;
  workflow?: { status?: string; message?: string };
};
type ButlerTask = {
  id?: string;
  workflow_id?: string;
  title?: string;
  status?: string;
  message?: string;
  terminal?: boolean;
  capabilities?: { can_cancel?: boolean; can_retry?: boolean; can_resume?: boolean };
};
type CompareCandidate = {
  gallery_id: string;
  work_id: string;
  page_index: number;
  title?: string;
  thumb?: string;
};
type CompanionMemory = { id?: string; text?: string; status?: string; agent?: string };
type CompanionState = {
  quiet?: { enabled?: boolean; start?: string; end?: string; max_events_per_hour?: number };
  memories?: CompanionMemory[];
  handoff?: { from_agent?: string; to_agent?: string; note?: string; consumed?: boolean } | null;
  tts?: { enabled?: boolean; core?: boolean };
};

export function ButlerPage() {
  const [status, setStatus] = useState<ButlerStatus | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [rejected, setRejected] = useState<{ tool?: string; reason?: string }[]>([]);
  const [results, setResults] = useState<ToolResult[]>([]);
  const [tasks, setTasks] = useState<ButlerTask[]>([]);
  const [draft, setDraft] = useState("");
  const [attachment, setAttachment] = useState<ImageAttachment | null>(null);
  const [compare, setCompare] = useState<CompareCandidate[]>([]);
  const [compareGallery, setCompareGallery] = useState("site");
  const [compareWork, setCompareWork] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [companion, setCompanion] = useState<CompanionState | null>(null);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [quietOn, setQuietOn] = useState(false);

  function refreshStatus() {
    get<ButlerStatus>("/api/butler/status").then(setStatus).catch((err: Error) => setError(err.message));
    get<{ tasks?: ButlerTask[] }>("/api/butler/tasks?limit=12")
      .then((payload) => setTasks(payload.tasks || []))
      .catch(() => undefined);
  }

  function refreshCompanion() {
    get<CompanionState>("/api/companion/state")
      .then((payload) => {
        setCompanion(payload);
        setQuietOn(Boolean(payload.quiet?.enabled));
      })
      .catch(() => undefined);
  }

  useEffect(() => {
    refreshStatus();
    refreshCompanion();
    get<{ messages?: ChatMessage[] }>("/api/butler/history")
      .then((payload) => setMessages(payload.messages || []))
      .catch(() => undefined);
  }, []);

  async function onPickImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setAttachment(await compressImage(file));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function addCompare() {
    const workId = compareWork.trim();
    if (!workId) return;
    if (compare.some((item) => item.work_id === workId && item.gallery_id === compareGallery)) return;
    if (compare.length >= 4) {
      setError("固定对比最多 4 张");
      return;
    }
    setCompare((current) => [
      ...current,
      { gallery_id: compareGallery, work_id: workId, page_index: 0, title: `#${workId}` },
    ]);
    setCompareWork("");
  }

  function pinFromResult(item: { work_id?: number | string; gallery_id?: string; title?: string; thumb?: string; image_url?: string }) {
    const workId = String(item.work_id || "").trim();
    if (!workId) return;
    addCompareCandidate({
      gallery_id: item.gallery_id || "site",
      work_id: workId,
      page_index: 0,
      title: item.title || `#${workId}`,
      thumb: item.thumb || item.image_url || "",
    });
  }

  function addCompareCandidate(item: CompareCandidate) {
    setCompare((current) => {
      if (current.some((row) => row.work_id === item.work_id && row.gallery_id === item.gallery_id)) return current;
      if (current.length >= 4) return current;
      return [...current, item];
    });
  }

  async function send(event?: FormEvent, extras?: { intent?: string; comparison?: CompareCandidate[]; text?: string }) {
    event?.preventDefault();
    const comparison = extras?.comparison;
    const message =
      (extras?.text || "").trim() ||
      draft.trim() ||
      (attachment ? "请看这张图片，说明画面内容并给我具体建议。" : "") ||
      (comparison ? "请比较这些固定候选。" : "");
    if (!message || busy) return;
    setDraft("");
    setBusy(true);
    setError("");
    setMessages((current) => [
      ...current,
      {
        role: "user",
        content: attachment ? `🖼 已附图片：${attachment.name}\n${message}` : message,
        preview: attachment?.data_url,
      },
    ]);
    try {
      const history = messages.slice(-8).map((item) => ({ role: item.role, content: item.content }));
      const data = await post<ChatResponse>(
        "/api/butler/chat",
        {
          message,
          history,
          image: extras?.intent === "gallery_audit" ? null : attachment,
          intent: extras?.intent || "",
          ...(comparison ? { comparison } : {}),
        },
        { timeoutMs: 150000 },
      );
      setMessages((current) => [...current, { role: "assistant", content: data.reply || "任务计划已生成。" }]);
      setPending(data.pending_actions || []);
      setRejected(data.rejected_actions || []);
      setResults(data.tool_results || []);
      setAttachment(null);
      refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(item: PendingAction, approve: boolean) {
    if (!item.confirmation_id) return;
    setBusy(true);
    setError("");
    try {
      const data = await post<ChatResponse & { message?: string; cancelled?: boolean }>(
        "/api/butler/confirm",
        { confirmation_id: item.confirmation_id, approve },
        { timeoutMs: 300000 },
      );
      setPending((current) => current.filter((row) => row.confirmation_id !== item.confirmation_id));
      setMessages((current) => [
        ...current,
        { role: "assistant", content: data.message || data.reply || (data.cancelled ? "已取消" : "已确认执行") },
      ]);
      if (data.tool_results) setResults(data.tool_results);
      refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function taskAction(task: ButlerTask, action: "cancel" | "retry" | "resume") {
    const id = String(task.workflow_id || task.id || "");
    if (!id) return;
    setBusy(true);
    try {
      await post(`/api/butler/tasks/${encodeURIComponent(id)}/${action}`, {}, { timeoutMs: 60000 });
      refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ws-split">
      <div className="ws-panel">
        <h2>助手能帮你做什么</h2>
        <p className="ws-status">客服小祥负责维护和教学，助手凑企鹅负责出图。涉及生图、写入或投稿时会先问你确认。</p>
        <ul className="ws-status">
          <li>AI：{status?.ai?.configured ? `${status.ai.provider || ""} ${status.ai.model || ""}` : "未配置"}</li>
          <li>出图 Token：{status?.generation?.configured ? "已配置" : "未配置"}</li>
          <li>待确认：{status?.pending_count ?? pending.length}</li>
          <li>后台：{status?.workflow?.status || "idle"} {status?.workflow?.message || ""}</li>
          <li>TTS：未纳入核心木桶（{companion?.tts?.enabled ? "开" : "关"}）</li>
        </ul>
        <div className="ws-compare">
          <strong>已确认偏好 / 防打扰 / 人格交接</strong>
          <p className="ws-status">记忆必须你确认后才会跨会话复述。没有窥屏、键鼠钩子或 God Agent。</p>
          <label className="ws-check">
            <input
              type="checkbox"
              checked={quietOn}
              onChange={(event) => {
                const enabled = event.target.checked;
                setQuietOn(enabled);
                void post("/api/companion/quiet", { enabled }).then(() => refreshCompanion());
              }}
            />
            静默时段 {companion?.quiet?.start || "22:00"}–{companion?.quiet?.end || "08:00"}
          </label>
          <div className="ws-inline">
            <input
              value={memoryDraft}
              onChange={(event) => setMemoryDraft(event.target.value)}
              placeholder="一条待确认偏好，例如：竖图优先"
            />
            <button
              className="ws-btn ghost"
              type="button"
              onClick={() => {
                if (!memoryDraft.trim()) return;
                void post("/api/companion/memory/propose", { text: memoryDraft.trim(), source: "user" }).then(() => {
                  setMemoryDraft("");
                  refreshCompanion();
                });
              }}
            >
              提议记住
            </button>
          </div>
          {(companion?.memories || []).slice(0, 8).map((item) => (
            <div className="ws-compare-item" key={item.id || item.text}>
              <span>
                {item.status === "confirmed" ? "已确认" : item.status === "forgotten" ? "已忘" : "待确认"} · {item.text}
              </span>
              {item.status === "proposed" ? (
                <button
                  className="ws-btn ghost"
                  type="button"
                  onClick={() => void post("/api/companion/memory/confirm", { id: item.id, confirm: true }).then(refreshCompanion)}
                >
                  确认
                </button>
              ) : item.status === "confirmed" ? (
                <button
                  className="ws-btn ghost"
                  type="button"
                  onClick={() => void post("/api/companion/memory/forget", { id: item.id }).then(refreshCompanion)}
                >
                  忘记
                </button>
              ) : null}
            </div>
          ))}
          <div className="ws-actions">
            <button
              className="ws-btn ghost"
              type="button"
              onClick={() => void post("/api/companion/handoff", { from_agent: "sakiko", to_agent: "tomori", note: "维护这边先交给出图。" }).then(refreshCompanion)}
            >
              小祥 → 凑企鹅
            </button>
            <button
              className="ws-btn ghost"
              type="button"
              onClick={() => void post("/api/companion/handoff", { from_agent: "tomori", to_agent: "sakiko", note: "出图这边先交给维护。" }).then(refreshCompanion)}
            >
              凑企鹅 → 小祥
            </button>
          </div>
        </div>
        <div className="ws-compare">
          <strong>固定对比（2–4 张，明确比较才会识图）</strong>
          <div className="ws-inline">
            <select value={compareGallery} onChange={(event) => setCompareGallery(event.target.value)} aria-label="对比图库">
              <option value="site">主图库</option>
              <option value="codex">自选库</option>
              <option value="qqgroup">QQ 图库</option>
            </select>
            <input value={compareWork} onChange={(event) => setCompareWork(event.target.value)} placeholder="作品 ID" />
            <button className="ws-btn ghost" type="button" onClick={addCompare}>
              加入
            </button>
          </div>
          {compare.map((item) => (
            <div className="ws-compare-item" key={`${item.gallery_id}:${item.work_id}`}>
              <span>
                {item.gallery_id} #{item.work_id}
              </span>
              <button className="ws-btn ghost" type="button" onClick={() => setCompare((current) => current.filter((row) => row !== item))}>
                移除
              </button>
            </div>
          ))}
          <button
            className="ws-btn"
            type="button"
            disabled={busy || compare.length < 2}
            onClick={() => void send(undefined, { intent: "gallery_compare", comparison: compare })}
          >
            比较这些候选
          </button>
        </div>
        {tasks.length ? (
          <div className="ws-tasks">
            <strong>任务流</strong>
            {tasks.map((task) => (
              <div key={String(task.workflow_id || task.id)} className="ws-task">
                <span>
                  {task.title || task.status} · {task.message || ""}
                </span>
                <div className="ws-actions">
                  {task.capabilities?.can_cancel ? (
                    <button className="ws-btn ghost" type="button" disabled={busy} onClick={() => void taskAction(task, "cancel")}>
                      取消
                    </button>
                  ) : null}
                  {task.capabilities?.can_retry ? (
                    <button className="ws-btn ghost" type="button" disabled={busy} onClick={() => void taskAction(task, "retry")}>
                      重试
                    </button>
                  ) : null}
                  {task.capabilities?.can_resume ? (
                    <button className="ws-btn ghost" type="button" disabled={busy} onClick={() => void taskAction(task, "resume")}>
                      继续
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <a className="ws-status" href="/butler">
          需要形象和完整任务面板时，打开完整助手
        </a>
      </div>
      <div className="ws-panel">
        <div className="ws-chat" aria-live="polite">
          {messages.length === 0 ? (
            <div className="ws-empty">
              <p>还没有对话。可以试试：</p>
              <div className="ws-actions">
                {["帮我看看图库里有什么", "这张图怎么改更好看", "比较这两张哪个更适合发"].map((hint) => (
                  <button
                    key={hint}
                    className="ws-btn ghost"
                    type="button"
                    disabled={busy}
                    onClick={() => void send(undefined, { text: hint })}
                  >
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {messages.map((item, index) => (
            <div key={item.id || index} className={"ws-bubble " + (item.role === "user" ? "user" : "assistant")}>
              {item.preview ? <img src={item.preview} alt="" /> : null}
              {item.content}
            </div>
          ))}
        </div>
        {pending.map((item) => (
          <div className="ws-pending" key={item.confirmation_id || item.label}>
            <strong>{item.label || "等待确认"}</strong>
            <p>{item.summary || "这项操作需要确认。"}</p>
            <small>
              {item.lane ? `车道 ${item.lane}` : "确认工单"}
              {item.work_order?.retry_policy ? ` · ${item.work_order.retry_policy}` : ""}
              {item.work_order?.cost?.anlas_estimate ? ` · Anlas ${item.work_order.cost.anlas_estimate}` : ""}
            </small>
            <div className="ws-actions">
              <button className="ws-btn" disabled={busy} onClick={() => void confirm(item, true)}>
                确认执行
              </button>
              <button className="ws-btn ghost" disabled={busy} onClick={() => void confirm(item, false)}>
                取消
              </button>
            </div>
          </div>
        ))}
        {rejected.map((item, index) => (
          <p className="ws-status err" key={`${item.tool}-${index}`}>
            {item.tool || "动作"}已拦截：{item.reason}
          </p>
        ))}
        {results.map((item, index) => (
          <div className="ws-result" key={`${item.tool}-${index}`}>
            <p className="ws-status">
              {item.tool || "工具"}：{item.message || (item.ok ? "完成" : "失败")}
            </p>
            <div className="ws-actions">
              {(item.items || []).map((row, rowIndex) => {
                const src = String(row.image_url || row.thumb || "");
                return src ? (
                  <button
                    key={`${src}-${rowIndex}`}
                    className="ws-btn ghost"
                    type="button"
                    onClick={() => pinFromResult(row)}
                  >
                    {src ? <img className="ws-mini" src={src} alt="" /> : null}
                    加入对比
                  </button>
                ) : null;
              })}
            </div>
          </div>
        ))}
        {error ? <p className="ws-status err">{error}</p> : null}
        {attachment ? (
          <div className="ws-attach">
            <img src={attachment.data_url} alt={attachment.name} />
            <span>{attachment.name}</span>
            <button className="ws-btn ghost" type="button" onClick={() => setAttachment(null)}>
              移除
            </button>
          </div>
        ) : null}
        <form className="ws-compose" onSubmit={(event) => void send(event)}>
          <textarea
            rows={3}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="给客服小祥或助手凑企鹅下达任务或提问…"
            disabled={busy}
          />
          <div className="ws-actions">
            <label className="ws-btn ghost">
              附图片
              <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void onPickImage(event)} />
            </label>
            <button className="ws-btn" disabled={busy || (!draft.trim() && !attachment)}>
              {busy ? "规划中…" : "发送"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
