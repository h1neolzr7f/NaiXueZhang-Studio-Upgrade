import { useEffect, useState } from "react";
import { get, post } from "../api";
import { navigate, studioPath } from "../routes";

type CharSlot = {
  index?: number;
  char_caption?: string;
  summary?: string;
  gender?: string;
};
type Preset = { id?: string; label?: string; gender?: string };
type ExtractPayload = {
  ok?: boolean;
  data?: { chars?: CharSlot[]; base_caption?: string; work_id?: number | string };
  chars?: CharSlot[];
  base_caption?: string;
};
type TransformPayload = {
  ok?: boolean;
  patched_comment?: Record<string, unknown>;
  chars?: CharSlot[];
  base_caption?: string;
  message?: string;
};
type QueueWork = {
  work_id?: number | string;
  id?: number | string;
  gallery_id?: string;
  title?: string;
  page_index?: number;
};
type PreviewItem = {
  work_id?: number;
  ok?: boolean;
  skipped?: boolean;
  message?: string;
  char_count?: number;
};
type BatchStatus = {
  id?: string;
  status?: string;
  message?: string;
  done?: number;
  total?: number;
  ok_count?: number;
  fail_count?: number;
};

function parseSearch(search: string) {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return {
    workId: params.get("from") || params.get("work") || "",
    galleryId: params.get("gallery") || "site",
    pageIndex: Math.max(0, Number(params.get("page") || 0) || 0),
  };
}

type Replacement = {
  target_char_index: number;
  preset_id: string;
  gender: string;
  mode: string;
};

function replacementsFromPicks(
  chars: CharSlot[],
  picks: Record<number, string>,
  gender: string,
): Replacement[] {
  const replacements: Replacement[] = [];
  chars.forEach((slot, index) => {
    const presetId = picks[index] || picks[Number(slot.index)] || "";
    if (!presetId) return;
    replacements.push({
      target_char_index: Number(slot.index ?? index),
      preset_id: presetId,
      gender,
      mode: gender === "male" ? "replace_male" : "replace_female",
    });
  });
  return replacements;
}

export function RemixPage({ search }: { search: string }) {
  const { workId: initialWork, galleryId: initialGallery, pageIndex } = parseSearch(search);
  const [workId, setWorkId] = useState(initialWork);
  const [galleryId, setGalleryId] = useState(initialGallery);
  const [chars, setChars] = useState<CharSlot[]>([]);
  const [baseCaption, setBaseCaption] = useState("");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [gender, setGender] = useState("female");
  const [picks, setPicks] = useState<Record<number, string>>({});
  const [comment, setComment] = useState<Record<string, unknown> | null>(null);
  const [queue, setQueue] = useState<QueueWork[]>([]);
  const [batchPreset, setBatchPreset] = useState("");
  const [forceFree, setForceFree] = useState(true);
  const [confirmPaid, setConfirmPaid] = useState(false);
  const [preview, setPreview] = useState<PreviewItem[]>([]);
  const [taskId, setTaskId] = useState("");
  const [batch, setBatch] = useState<BatchStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    setWorkId(initialWork);
    setGalleryId(initialGallery);
  }, [initialWork, initialGallery]);

  useEffect(() => {
    get<{ presets?: Preset[] }>(`/api/plugin/char-swap/presets?gender=${encodeURIComponent(gender)}`)
      .then((payload) => setPresets(payload.presets || []))
      .catch((err: Error) => setError(err.message));
  }, [gender]);

  useEffect(() => {
    get<{ items?: QueueWork[] }>("/api/queue/works?gallery_id=site&page=1&page_size=60")
      .then((payload) => setQueue(payload.items || []))
      .catch(() => undefined);
  }, []);

  async function extract(nextWork = workId, nextGallery = galleryId, signal?: AbortSignal) {
    if (!nextWork.trim()) {
      setError("请填写作品 ID");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = await get<ExtractPayload>(
        `/api/plugin/char-swap/extract?work_id=${encodeURIComponent(nextWork)}&page_index=${pageIndex}&gallery_id=${encodeURIComponent(nextGallery)}`,
        signal ? { signal } : undefined,
      );
      if (signal?.aborted) return;
      const data = payload.data || payload;
      setChars(data.chars || []);
      setBaseCaption(String(data.base_caption || ""));
      setComment(null);
      setStatus(`已解析 ${ (data.chars || []).length } 个角色槽`);
    } catch (err) {
      if (signal?.aborted) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }

  useEffect(() => {
    if (!initialWork) return;
    const ac = new AbortController();
    void extract(initialWork, initialGallery, ac.signal);
    return () => ac.abort();
  }, [initialWork, initialGallery, pageIndex]);

  function buildRecipe() {
    const replacements = replacementsFromPicks(chars, picks, gender);
    if (replacements.length) {
      return {
        auto_sanitize: true,
        preserve_action: true,
        preserve_center: true,
        transform: {
          enabled: true,
          mode: "replace_multi",
          gender,
          replacements,
        },
        sanitize: { enabled: true, filter_racial: true, filter_gore: true, filter_creature: false },
      };
    }
    if (batchPreset) {
      return {
        auto_sanitize: true,
        preserve_action: true,
        preserve_center: true,
        transform: {
          enabled: true,
          mode: gender === "male" ? "replace_male" : "replace_female",
          gender,
          preset_id: batchPreset,
          target_char_index: gender === "male" ? "auto_male" : "auto_female",
        },
        sanitize: { enabled: true, filter_racial: true, filter_gore: true, filter_creature: false },
      };
    }
    return null;
  }

  function buildTargets() {
    const seen = new Set<string>();
    const targets: { gallery_id: string; work_id: number; page_index: number; patched_comment?: Record<string, unknown>; frozen_comment?: boolean }[] = [];
    const push = (raw: QueueWork, patched?: Record<string, unknown> | null) => {
      const id = Number(raw.work_id || raw.id);
      if (!id) return;
      const gallery = String(raw.gallery_id || galleryId || "site");
      const page = Number(raw.page_index || 0) || 0;
      const key = `${gallery}:${id}:${page}`;
      if (seen.has(key)) return;
      seen.add(key);
      const item: (typeof targets)[number] = { gallery_id: gallery, work_id: id, page_index: page };
      if (patched) {
        item.patched_comment = patched;
        item.frozen_comment = true;
      }
      targets.push(item);
    };
    if (workId) push({ work_id: workId, gallery_id: galleryId, page_index: pageIndex }, comment);
    queue.forEach((item) => push(item));
    return targets;
  }

  async function transform() {
    const replacements = replacementsFromPicks(chars, picks, gender);
    if (!replacements.length) {
      setError("请至少为一个槽位选择预设");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = await post<TransformPayload>("/api/plugin/char-swap/transform", {
        mode: "replace_multi",
        target_work_id: workId,
        target_page_index: pageIndex,
        gallery_id: galleryId,
        gender,
        preserve_action: true,
        preserve_center: true,
        replacements,
      });
      setChars(payload.chars || chars);
      setBaseCaption(String(payload.base_caption || baseCaption));
      setComment(payload.patched_comment || null);
      setStatus("换角草稿已生成，尚未调用 NAI。确认后再去工作台出图。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function previewBatch() {
    const recipe = buildRecipe();
    const targets = buildTargets();
    if (!recipe) {
      setError("请先为槽位选预设，或给批量选一个统一预设");
      return;
    }
    if (!targets.length) {
      setError("待生成队列为空，也没有当前作品");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = await post<{ items?: PreviewItem[]; ready?: number; total?: number; message?: string }>(
        "/api/plugin/char-swap/batch/preview",
        { targets, recipe },
      );
      setPreview(payload.items || []);
      setStatus(payload.message || `预检 ${payload.ready || 0}/${payload.total || targets.length}，未扣 Anlas`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runBatch() {
    const recipe = buildRecipe();
    const targets = buildTargets();
    if (!recipe || !targets.length) {
      setError("请先完成预检");
      return;
    }
    if (!preview.length) {
      setError("请先点「零费用预检」");
      return;
    }
    if (!forceFree && !confirmPaid) {
      setError("付费出图需要勾选确认。默认请保持 force_free。");
      return;
    }
    if (!forceFree && !window.confirm(`将按配方生成 ${targets.length} 张，可能消耗 Anlas。未自动重试 unknown。继续？`)) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const auth = await post<{
        requires_ticket?: boolean;
        ticket?: string;
        message?: string;
        needs_confirmation?: boolean;
      }>("/api/plugin/char-swap/batch/authorize", {
        targets,
        recipe,
        force_free: forceFree,
        generate: true,
        preview_only: false,
      });
      let ticket = "";
      if (auth.requires_ticket) {
        const ok = window.confirm(
          auth.message || "这次不是免费标准路径，可能消耗 Anlas。确认后才会签发一次性授权。",
        );
        if (!ok) {
          setError("已取消非免费出图");
          return;
        }
        const issued = await post<{ ticket?: string }>("/api/plugin/char-swap/batch/authorize", {
          targets,
          recipe,
          force_free: forceFree,
          generate: true,
          preview_only: false,
          confirmed: true,
        });
        ticket = issued.ticket || "";
      }
      const payload = await post<{ ok?: boolean; task_id?: string; message?: string }>(
        "/api/plugin/char-swap/batch/run",
        {
          targets,
          recipe,
          force_free: forceFree,
          generate: true,
          preview_only: false,
          authorization_ticket: ticket,
        },
      );
      if (!payload.ok) throw new Error(payload.message || "启动失败");
      setTaskId(String(payload.task_id || ""));
      setStatus(payload.message || "批量已启动");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let timer = 0;
    const tick = () => {
      get<{ batch?: BatchStatus }>(`/api/plugin/char-swap/batch/status?task_id=${encodeURIComponent(taskId)}`)
        .then((payload) => {
          if (cancelled) return;
          const next = payload.batch || null;
          setBatch(next);
          const state = String(next?.status || "");
          if (["running", "cancelling", "queued", "pending", ""].includes(state)) {
            timer = window.setTimeout(tick, 2000);
          }
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message);
        });
    };
    tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [taskId]);

  return (
    <section className="ws-panel">
      <h2>换角</h2>
      <p className="ws-status">单张先本地抽出角色槽并套预设，不会扣 Anlas。批量必须先预检；默认 force_free，unknown 未自动重试。</p>
      <div className="ws-toolbar">
        <input value={workId} onChange={(event) => setWorkId(event.target.value)} placeholder="作品 ID" aria-label="作品 ID" />
        <select value={galleryId} onChange={(event) => setGalleryId(event.target.value)} aria-label="图库">
          <option value="site">主图库</option>
          <option value="codex">自选库</option>
          <option value="qqgroup">QQ 图库</option>
        </select>
        <select value={gender} onChange={(event) => setGender(event.target.value)} aria-label="预设性别">
          <option value="female">女性预设</option>
          <option value="male">男性预设</option>
        </select>
        <button className="ws-btn ghost" disabled={busy} onClick={() => void extract()}>
          解析槽位
        </button>
      </div>
      {baseCaption ? <p className="ws-prompt">{baseCaption}</p> : null}
      <div className="ws-slots">
        {chars.map((slot, index) => {
          const slotIndex = Number(slot.index ?? index);
          return (
            <label key={slotIndex} className="ws-slot">
              <span>
                槽 {slotIndex + 1}
                {slot.gender ? ` · ${slot.gender}` : ""}
                {slot.summary ? ` · ${slot.summary}` : ""}
              </span>
              <small>{(slot.char_caption || "").slice(0, 160)}</small>
              <select
                value={picks[slotIndex] || ""}
                onChange={(event) => setPicks((current) => ({ ...current, [slotIndex]: event.target.value }))}
                aria-label={`槽 ${slotIndex + 1} 预设`}
              >
                <option value="">保持原角色</option>
                {presets.map((preset) => (
                  <option key={String(preset.id)} value={String(preset.id)}>
                    {preset.label || preset.id}
                  </option>
                ))}
              </select>
            </label>
          );
        })}
      </div>
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy || !chars.length} onClick={() => void transform()}>
          生成换角草稿
        </button>
        <button
          className="ws-btn ghost"
          disabled={!workId}
          onClick={() => navigate(studioPath(workId, galleryId, pageIndex))}
        >
          去工作台出图
        </button>
      </div>
      {comment ? <p className="ws-status ok">已得到 patched_comment，工作台导入同一作品即可使用冻结快照。</p> : null}

      <h3>批量换角</h3>
      <p className="ws-status">目标来自当前作品 + 待生成队列（{queue.length} 项）。没有槽位挑选时，用统一预设套 auto 性别槽。</p>
      <div className="ws-toolbar">
        <select value={batchPreset} onChange={(event) => setBatchPreset(event.target.value)} aria-label="批量统一预设">
          <option value="">不使用统一预设</option>
          {presets.map((preset) => (
            <option key={`batch-${preset.id}`} value={String(preset.id)}>
              {preset.label || preset.id}
            </option>
          ))}
        </select>
        <label className="ws-check">
          <input type="checkbox" checked={forceFree} onChange={(event) => setForceFree(event.target.checked)} />
          force_free（默认开启）
        </label>
        <label className="ws-check">
          <input type="checkbox" checked={confirmPaid} onChange={(event) => setConfirmPaid(event.target.checked)} />
          确认付费出图
        </label>
      </div>
      <div className="ws-actions">
        <button className="ws-btn" disabled={busy} onClick={() => void previewBatch()}>
          零费用预检
        </button>
        <button className="ws-btn ghost" disabled={busy || !preview.length} onClick={() => void runBatch()}>
          确认后生成
        </button>
        {taskId ? (
          <button
            className="ws-btn ghost"
            disabled={busy}
            onClick={() => void post(`/api/plugin/char-swap/batch/cancel?task_id=${encodeURIComponent(taskId)}`, {}).then(() => setStatus("已请求取消"))}
          >
            取消
          </button>
        ) : null}
      </div>
      {preview.length ? (
        <ul className="ws-list">
          {preview.slice(0, 12).map((item) => (
            <li key={String(item.work_id)}>
              #{item.work_id} · {item.ok ? "可处理" : "跳过"} {item.message || ""}
            </li>
          ))}
        </ul>
      ) : null}
      {batch ? (
        <p className="ws-status">
          任务 {batch.status || "unknown"} · {batch.done || 0}/{batch.total || 0} · 成功 {batch.ok_count || 0}
          {batch.message ? ` · ${batch.message}` : ""} · 未自动重试
        </p>
      ) : null}
      {status ? <p className="ws-status ok">{status}</p> : null}
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
