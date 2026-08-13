import { KeyboardEvent, useEffect, useState } from "react";
import { get, pollJob, post } from "../api";
import { commentFromTexts, textsFromComment, type CommentMap } from "../comment";
import { generatedPath, navigate, remixPath, studioPath } from "../routes";

type StudioImport = {
  ok?: boolean;
  work_id?: number | string;
  title?: string;
  thumb?: string;
  comment?: CommentMap;
  texts?: { prompt?: string; uc?: string; base_caption?: string; char_captions?: unknown[] };
  params?: { width?: number; height?: number; steps?: number; scale?: number; sampler?: string; seed?: number };
};

type StudioConfig = {
  samplers?: string[];
  size_presets?: { id?: string; label?: string; width?: number; height?: number }[];
  defaults?: { width?: number; height?: number; steps?: number; scale?: number; sampler?: string };
};

type TokenStatus = { has_token?: boolean; message?: string };
type QueueItem = { work_id?: number | string; title?: string; gallery_id?: string };
type GenerateResult = { ok?: boolean; message?: string; error?: string; task_id?: string; queued?: boolean };

const COPY_MAX = 8;
const DEFAULTS = { width: 832, height: 1216, steps: 28, scale: 5, sampler: "k_euler_ancestral" };

function parseSearch(search: string) {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return {
    workId: params.get("work") || "",
    galleryId: params.get("gallery") || "site",
    pageIndex: Math.max(0, Number(params.get("page") || 0) || 0),
  };
}

function asNumber(value: unknown, fallback: number): number {
  const next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

export function StudioPage({ search }: { search: string }) {
  const { workId, galleryId, pageIndex } = parseSearch(search);
  const [draft, setDraft] = useState<StudioImport | null>(null);
  const [config, setConfig] = useState<StudioConfig>({});
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [importId, setImportId] = useState(workId);
  const [prompt, setPrompt] = useState("");
  const [baseCaption, setBaseCaption] = useState("");
  const [charCaptions, setCharCaptions] = useState("");
  const [uc, setUc] = useState("");
  const [width, setWidth] = useState(DEFAULTS.width);
  const [height, setHeight] = useState(DEFAULTS.height);
  const [steps, setSteps] = useState(DEFAULTS.steps);
  const [scale, setScale] = useState(DEFAULTS.scale);
  const [sampler, setSampler] = useState(DEFAULTS.sampler);
  const [seed, setSeed] = useState("");
  const [copies, setCopies] = useState(1);
  const [forceFree, setForceFree] = useState(true);
  const [vibeUrl, setVibeUrl] = useState("");
  const [charRefUrl, setCharRefUrl] = useState("");
  const [token, setToken] = useState<TokenStatus | null>(null);
  const [preview, setPreview] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [undo, setUndo] = useState<string[]>([]);

  useEffect(() => {
    get<TokenStatus>("/api/nai/status").then(setToken).catch(() => setToken(null));
    get<StudioConfig>("/api/studio/config")
      .then((payload) => {
        setConfig(payload);
        const defaults = payload.defaults || {};
        setWidth(asNumber(defaults.width, DEFAULTS.width));
        setHeight(asNumber(defaults.height, DEFAULTS.height));
        setSteps(asNumber(defaults.steps, DEFAULTS.steps));
        setScale(asNumber(defaults.scale, DEFAULTS.scale));
        setSampler(String(defaults.sampler || DEFAULTS.sampler));
      })
      .catch(() => undefined);
    get<{ items?: QueueItem[] }>("/api/studio/queue")
      .then((payload) => setQueue(payload.items || []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setImportId(workId);
    if (!workId) {
      setDraft(null);
      return;
    }
    let cancelled = false;
    const query = new URLSearchParams({
      work_id: workId,
      page_index: String(pageIndex),
      gallery_id: galleryId,
    });
    get<StudioImport>("/api/studio/import?" + query.toString())
      .then((payload) => {
        if (cancelled) return;
        applyImport(payload);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [workId, galleryId, pageIndex]);

  function snapshotFields() {
    return JSON.stringify({
      prompt,
      baseCaption,
      charCaptions,
      uc,
      width,
      height,
      steps,
      scale,
      sampler,
      seed,
      copies,
      comment: draft?.comment || {},
    });
  }

  function pushUndo() {
    setUndo((current) => [...current.slice(-11), snapshotFields()]);
  }

  function restoreUndo() {
    const last = undo[undo.length - 1];
    if (!last) return;
    const parsed = JSON.parse(last) as Record<string, unknown>;
    setPrompt(String(parsed.prompt || ""));
    setBaseCaption(String(parsed.baseCaption || ""));
    setCharCaptions(String(parsed.charCaptions || ""));
    setUc(String(parsed.uc || ""));
    setWidth(asNumber(parsed.width, width));
    setHeight(asNumber(parsed.height, height));
    setSteps(asNumber(parsed.steps, steps));
    setScale(asNumber(parsed.scale, scale));
    setSampler(String(parsed.sampler || sampler));
    setSeed(String(parsed.seed || ""));
    setCopies(asNumber(parsed.copies, copies));
    if (parsed.comment && typeof parsed.comment === "object") {
      setDraft((current) => ({ ...(current || {}), comment: parsed.comment as CommentMap }));
    }
    setUndo((current) => current.slice(0, -1));
  }

  function applyImport(payload: StudioImport) {
    setDraft(payload);
    const snapshot = textsFromComment(payload.comment);
    const texts = payload.texts;
    const nextPrompt = String(texts?.prompt || snapshot.prompt || "");
    const nextBase = String(texts?.base_caption || snapshot.baseCaption || nextPrompt);
    const chars = Array.isArray(texts?.char_captions)
      ? texts.char_captions
          .map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object" && "char_caption" in item) {
              return String((item as { char_caption?: string }).char_caption || "");
            }
            return "";
          })
          .filter(Boolean)
      : snapshot.charCaptions;
    setPrompt(nextPrompt);
    setBaseCaption(nextBase);
    setCharCaptions(chars.join("\n"));
    setUc(String(texts?.uc || snapshot.uc || ""));
    const params = { ...(payload.params || {}), ...(payload.comment || {}) };
    setWidth(asNumber(params.width, DEFAULTS.width));
    setHeight(asNumber(params.height, DEFAULTS.height));
    setSteps(asNumber(params.steps, DEFAULTS.steps));
    setScale(asNumber(params.scale, DEFAULTS.scale));
    setSampler(String(params.sampler || DEFAULTS.sampler));
    setSeed(params.seed == null || params.seed === -1 ? "" : String(params.seed));
    setError("");
  }

  function currentComment(): CommentMap {
    const texts = textsFromComment(draft?.comment);
    texts.prompt = prompt.trim();
    texts.uc = uc.trim();
    texts.baseCaption = baseCaption.trim() || texts.prompt;
    texts.charCaptions = charCaptions
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const comment = commentFromTexts(draft?.comment, texts);
    comment.width = width;
    comment.height = height;
    comment.steps = steps;
    comment.scale = scale;
    comment.sampler = sampler;
    comment.seed = seed.trim() === "" ? -1 : Number(seed);
    if (vibeUrl.trim()) {
      comment.xianyun_vibe = {
        reference_images: [vibeUrl.trim()],
        reference_strength_multiple: [0.6],
        reference_information_extracted_multiple: [1.0],
      };
    }
    if (charRefUrl.trim()) {
      comment.reference_image_multiple = [charRefUrl.trim()];
      comment.reference_strength_multiple = [0.6];
    }
    return comment;
  }

  async function applySanitize() {
    pushUndo();
    setBusy(true);
    setError("");
    try {
      const result = await post<{ comment?: CommentMap; texts?: StudioImport["texts"]; message?: string }>(
        "/api/studio/sanitize",
        { comment: currentComment(), filter_racial: true, filter_gore: true },
      );
      if (result.comment) applyImport({ ...draft, comment: result.comment, texts: result.texts });
      setStatus(result.message || "已净化敏感/无效标签");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    const comment = currentComment();
    if (!String(comment.prompt || "").trim()) {
      setError("没有可用于生图的 Prompt");
      return;
    }
    const seedPolicy = seed.trim() === "" || Number(seed) < 0 ? "random" : "increment";
    setBusy(true);
    setError("");
    setStatus("正在提交冻结快照…");
    try {
      const result = await post<GenerateResult>("/api/nai/generate", {
        patched_comment: comment,
        frozen_comment: true,
        work_id: workId || null,
        page_index: pageIndex,
        source_gallery_id: galleryId,
        source_title: draft?.title || "",
        source_thumb: draft?.thumb || "",
        copies: Math.max(1, Math.min(COPY_MAX, copies)),
        force_free: forceFree,
        prompt_profile: "native",
        seed_policy: seedPolicy,
      });
      if (!result.ok) {
        throw new Error(String(result.message || result.error || "生成失败"));
      }
      const taskId = String(result.task_id || "");
      if (!taskId) {
        setStatus(result.queued ? "已入队" : result.message || "已开始生成");
        return;
      }
      setStatus(result.queued ? "已入队，等待执行…" : "生成中…");
      const job = await pollJob(taskId, (progress) => {
        setStatus(String(progress.message || progress.status || "生成中…"));
        const items = Array.isArray(progress.items) ? progress.items : [];
        const lastOk = [...items].reverse().find((item) => {
          const row = item as { ok?: boolean; image_url?: string };
          return Boolean(row && row.ok && row.image_url);
        }) as { image_url?: string } | undefined;
        if (lastOk?.image_url) setPreview(lastOk.image_url);
      });
      const jobStatus = String(job.status || "");
      if (jobStatus === "done") {
        setStatus("生成完成");
        navigate(generatedPath());
        return;
      }
      if (jobStatus === "unknown") {
        setError("任务结果未知，未自动重试。请到生成库核对，避免重复扣 Anlas。");
        setStatus("");
        return;
      }
      throw new Error(String(job.message || job.error || `任务结束：${jobStatus || "error"}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function onPromptKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void generate();
    }
  }

  const samplers = config.samplers?.length ? config.samplers : [DEFAULTS.sampler];
  const presets = config.size_presets || [];

  return (
    <section className="ws-studio">
      <div className="ws-panel">
        <h2>生图工作台</h2>
        <p className="ws-status">
          {workId ? `作品 #${workId} · ${galleryId}` : "空白草稿也可以出图；从图库点选会冻结点击时的 comment。"}
        </p>
        <p className={"ws-chip " + (token?.has_token ? "ok" : "warn")}>
          {token?.has_token ? "Token 已配置" : "尚未配置 Token"}
        </p>
        {draft?.thumb ? <img className="ws-thumb" src={draft.thumb} alt="" /> : null}
        {preview ? <img className="ws-thumb" src={preview} alt="最近生成" /> : null}
        <div className="ws-inline">
          <input
            value={importId}
            onChange={(event) => setImportId(event.target.value)}
            placeholder="作品 ID"
            aria-label="按 ID 导入"
          />
          <button
            className="ws-btn ghost"
            type="button"
            onClick={() => importId.trim() && navigate(studioPath(importId.trim(), galleryId, pageIndex))}
          >
            导入
          </button>
        </div>
        {queue.length ? (
          <div>
            <p className="ws-status">待生成队列</p>
            <div className="ws-actions">
              {queue.slice(0, 8).map((item) => {
                const id = String(item.work_id || "");
                return (
                  <button
                    key={id}
                    className="ws-btn ghost"
                    type="button"
                    onClick={() => id && navigate(studioPath(id, item.gallery_id || "site"))}
                  >
                    #{id} {item.title || ""}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
        <a className="ws-status" href={workId ? remixPath(workId, galleryId, pageIndex) : "/app/remix"}>
          去换角
        </a>
        <a className="ws-status" href={workId ? `/studio?work=${encodeURIComponent(workId)}` : "/studio"}>
          打开经典工作台
        </a>
      </div>
      <div className="ws-panel">
        <label htmlFor="ws-prompt">主 Prompt</label>
        <textarea id="ws-prompt" rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={onPromptKey} />
        <label htmlFor="ws-base">Base / 场景</label>
        <textarea id="ws-base" rows={3} value={baseCaption} onChange={(event) => setBaseCaption(event.target.value)} />
        <label htmlFor="ws-chars">角色槽（每行一个）</label>
        <textarea id="ws-chars" rows={3} value={charCaptions} onChange={(event) => setCharCaptions(event.target.value)} />
        <label htmlFor="ws-uc">Negative / UC</label>
        <textarea id="ws-uc" rows={3} value={uc} onChange={(event) => setUc(event.target.value)} />
        <div className="ws-presets">
          {presets.map((item) => (
            <button
              key={item.id || item.label}
              className="ws-btn ghost"
              type="button"
              onClick={() => {
                setWidth(asNumber(item.width, width));
                setHeight(asNumber(item.height, height));
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="ws-params">
          <label>
            宽
            <input type="number" min={64} step={64} value={width} onChange={(event) => setWidth(asNumber(event.target.value, width))} />
          </label>
          <label>
            高
            <input type="number" min={64} step={64} value={height} onChange={(event) => setHeight(asNumber(event.target.value, height))} />
          </label>
          <label>
            Steps
            <input type="number" min={1} max={50} value={steps} onChange={(event) => setSteps(asNumber(event.target.value, steps))} />
          </label>
          <label>
            CFG
            <input type="number" min={1} max={20} step={0.1} value={scale} onChange={(event) => setScale(asNumber(event.target.value, scale))} />
          </label>
          <label>
            Seed
            <input value={seed} placeholder="空=随机" onChange={(event) => setSeed(event.target.value)} />
          </label>
          <label>
            Sampler
            <select value={sampler} onChange={(event) => setSampler(event.target.value)}>
              {samplers.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            份数（最多 {COPY_MAX}）
            <input
              type="number"
              min={1}
              max={COPY_MAX}
              value={copies}
              onChange={(event) => setCopies(Math.max(1, Math.min(COPY_MAX, asNumber(event.target.value, 1))))}
            />
          </label>
        </div>
        <label htmlFor="ws-vibe">Vibe URL（可选）</label>
        <input id="ws-vibe" value={vibeUrl} onChange={(event) => setVibeUrl(event.target.value)} placeholder="https://… 或 /data/images/…" />
        <label htmlFor="ws-charref">角色参考 URL（可选）</label>
        <input id="ws-charref" value={charRefUrl} onChange={(event) => setCharRefUrl(event.target.value)} />
        <label className="ws-check">
          <input type="checkbox" checked={forceFree} onChange={(event) => setForceFree(event.target.checked)} />
          走免费标准尺寸（关闭后可能消耗 Anlas）
        </label>
        <div className="ws-actions">
          <button className="ws-btn ghost" type="button" disabled={busy} onClick={() => void applySanitize()}>
            净化标签
          </button>
          <button className="ws-btn ghost" type="button" disabled={!undo.length} onClick={restoreUndo}>
            撤销
          </button>
          <button className="ws-btn" type="button" disabled={busy} onClick={() => void generate()}>
            {busy ? "处理中…" : "冻结并生成"}
          </button>
        </div>
        {status ? <p className="ws-status ok">{status}</p> : null}
        {error ? <p className="ws-status err">{error}</p> : null}
      </div>
    </section>
  );
}
