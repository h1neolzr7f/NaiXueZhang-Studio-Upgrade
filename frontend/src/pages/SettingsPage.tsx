import { useEffect, useState } from "react";
import { get, post } from "../api";

type TokenStatus = {
  has_token?: boolean;
  tokens?: { id?: string; label?: string; provider?: string; enabled?: boolean }[];
};
type SettingsConfig = {
  prefs?: Record<string, unknown>;
  ai?: {
    configured?: boolean;
    provider?: string;
    api_base?: string;
    model?: string;
    has_api_key?: boolean;
  };
};
type UsageSummary = { anlas?: number; jobs?: number; recent?: { at?: string; kind?: string; detail?: string }[] };

export function SettingsPage() {
  const [status, setStatus] = useState<TokenStatus | null>(null);
  const [config, setConfig] = useState<SettingsConfig | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [token, setToken] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function refresh() {
    get<TokenStatus>("/api/nai/status").then(setStatus).catch((err: Error) => setError(err.message));
    get<SettingsConfig>("/api/settings/config")
      .then((payload) => {
        setConfig(payload);
        setApiBase(String(payload.ai?.api_base || ""));
        setModel(String(payload.ai?.model || ""));
      })
      .catch((err: Error) => setError(err.message));
    get<{ summary?: UsageSummary; recent?: UsageSummary["recent"] }>("/api/settings/usage")
      .then((payload) => setUsage({ ...(payload.summary || {}), recent: payload.recent }))
      .catch(() => undefined);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function saveToken() {
    const value = token.trim();
    if (!value) {
      setError("请粘贴 NovelAI token");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await post("/api/nai/token", { token: value, provider: "novelai" });
      setToken("");
      setMessage("已保存到本机加密存储");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveAi() {
    setBusy(true);
    setError("");
    try {
      await post("/api/settings/config", {
        ai: {
          api_base: apiBase.trim(),
          model: model.trim(),
          api_key: apiKey.trim(),
        },
      });
      setApiKey("");
      setMessage("聊天/识图配置已保存");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function testAi() {
    setBusy(true);
    setError("");
    try {
      const result = await post<{ ok?: boolean; message?: string }>("/api/settings/ai-test", {});
      setMessage(result.message || (result.ok ? "连接正常" : "测试完成"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function rebuildKnowledge() {
    setBusy(true);
    setError("");
    try {
      const result = await post<{ message?: string; workflow_id?: string }>("/api/settings/knowledge/rebuild", {});
      setMessage(result.message || "已提交本地知识库增量更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="ws-panel">
      <h2>出图账号</h2>
      <p className="ws-status">{status?.has_token ? "已配置 NovelAI token" : "尚未配置 token"}</p>
      <ul className="ws-status">
        {(status?.tokens || []).map((item) => (
          <li key={String(item.id)}>
            {item.label || item.id} · {item.provider} {item.enabled === false ? "（停用）" : ""}
          </li>
        ))}
      </ul>
      <input
        type="password"
        value={token}
        onChange={(event) => setToken(event.target.value)}
        placeholder="pst-…"
        autoComplete="off"
        aria-label="NovelAI token"
      />
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void saveToken()}>
          保存 token
        </button>
      </div>

      <h2>聊天 / 识图</h2>
      <p className="ws-status">
        {config?.ai?.has_api_key || config?.ai?.configured ? "已配置上游" : "尚未配置"}
        {config?.ai?.provider ? ` · ${config.ai.provider}` : ""}
      </p>
      <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} placeholder="https://api.example.com/v1" aria-label="API Base" />
      <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="模型名" aria-label="模型" />
      <input
        type="password"
        value={apiKey}
        onChange={(event) => setApiKey(event.target.value)}
        placeholder="sk-…（留空则不改）"
        autoComplete="off"
        aria-label="API Key"
      />
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void saveAi()}>
          保存上游
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void testAi()}>
          测试连接
        </button>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void rebuildKnowledge()}>
          更新本地说明
        </button>
      </div>
      {usage ? (
        <p className="ws-status">
          用量账本 {usage.jobs != null ? `· 任务 ${usage.jobs}` : ""}
          {usage.anlas != null ? ` · Anlas 记录 ${usage.anlas}` : ""}
        </p>
      ) : null}
      <p className="ws-status">
        端口、代理和完整偏好请打开 <a href="/settings">设置详情</a>。
      </p>
      {message ? <p className="ws-status ok">{message}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
