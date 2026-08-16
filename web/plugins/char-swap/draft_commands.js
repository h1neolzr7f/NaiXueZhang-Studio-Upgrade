// Deep Module for Studio Draft state transitions and write commands.
// DOM rendering stays behind panel.js; this Module owns draft invariants.

import {
  state,
  extractCache,
  draftPageCache,
  draftCacheKey,
  persistDraftCache,
  saveCurrentDraftToCache,
  buildStyleBundleFallback,
  normalizeGalleryId,
} from "./state.js?v=f80b97d795";
import { api, deepClone, loadPluginConfig } from "./api.js?v=0411b73ad6";
import { attachDraftToPayload } from "./draft_helpers.js?v=71bb7ead54";

export function activeGalleryId(explicitGalleryId) {
  const currentUrl = new URL(window.location.href);
  return normalizeGalleryId(
    explicitGalleryId
    || currentUrl.searchParams.get("gallery")
    || currentUrl.searchParams.get("gallery_id")
    || state.galleryId
    || "site"
  );
}

export async function loadExtract(workId, pageIndex) {
  const galleryId = activeGalleryId();
  state.galleryId = galleryId;
  const key = `${galleryId}:${workId}:${pageIndex}`;
  if (extractCache.has(key)) return extractCache.get(key);
  const params = new URLSearchParams({
    work_id: String(workId),
    page_index: String(pageIndex),
    gallery_id: galleryId,
  });
  const res = await api(`/api/plugin/char-swap/extract?${params.toString()}`);
  extractCache.set(key, res);
  return res;
}

export function styleStateFromResponse(res) {
  state.styleSlots = (res && res.style_slots) || [];
  state.styleBundle = (res && res.style_bundle) || buildStyleBundleFallback(state.styleSlots);
}

export function applyTransformResponse(res) {
  state.draft = res.patched_comment;
  state.draftChars = res.chars || [];
  styleStateFromResponse(res);
  return res;
}

export function pageCacheEntryFromResponse(res) {
  return {
    cacheVersion: 8,
    draft: deepClone(res.patched_comment),
    draftChars: deepClone(res.chars || []),
    styleSlots: deepClone(res.style_slots || []),
    styleBundle: deepClone(res.style_bundle || buildStyleBundleFallback(res.style_slots || [])),
    lastRemoved: [],
  };
}

export function cacheTransformResponse(workId, pageIndex, res) {
  draftPageCache.set(draftCacheKey(workId, pageIndex), pageCacheEntryFromResponse(res));
}

export function flushDraftCache() {
  persistDraftCache();
}

export function resetDraftFromOriginal() {
  if (!state.original) return false;
  state.draft = deepClone(state.original.comment);
  state.draftChars = deepClone(state.original.chars || []);
  const originalCaption = state.original.comment?.v4_prompt?.caption;
  const draftCaption = state.draft?.v4_prompt?.caption;
  if (originalCaption && draftCaption) {
    draftCaption.char_captions = deepClone(originalCaption.char_captions || []);
  }
  state.styleSlots = deepClone(state.original.style_slots || []);
  state.styleBundle = deepClone(
    state.original.style_bundle || buildStyleBundleFallback(state.original.style_slots || [])
  );
  state.lastRemoved = [];
  state.seedBeforeRandom = null;
  return true;
}

export function originalSeed() {
  const seed = state.original?.comment?.seed;
  if (seed === undefined || seed === null || seed === "") return null;
  const value = Number(seed);
  return Number.isFinite(value) ? Math.trunc(value) : null;
}

export function setDraftSeed(value) {
  if (!state.draft) return;
  if (value === "" || value === null || value === undefined) {
    delete state.draft.seed;
    return;
  }
  const seed = Number(value);
  if (!Number.isFinite(seed)) return;
  state.draft.seed = seed === -1 ? -1 : Math.max(0, Math.trunc(seed));
}

export function draftAiJson() {
  if (!state.original || !state.draft) return null;
  const aiJson = deepClone(state.original.ai_json);
  aiJson.Comment = deepClone(state.draft);
  return aiJson;
}

export async function runTransformCommand(body) {
  const cfg = await loadPluginConfig();
  const galleryId = activeGalleryId(body.gallery_id);
  state.galleryId = galleryId;
  const payload = {
    preserve_action: cfg.preserve_action === true,
    preserve_center: cfg.preserve_center !== false,
    replace_creature: cfg.replace_creature_slots !== false,
    gallery_id: galleryId,
    ...body,
  };
  attachDraftToPayload(
    payload,
    body.target_work_id != null ? body.target_work_id : state.workId,
    body.target_page_index != null ? body.target_page_index : state.pageIndex,
  );
  const res = await api("/api/plugin/char-swap/transform", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  applyTransformResponse(res);
  saveCurrentDraftToCache();
  return res;
}

export async function runSanitizeCommand() {
  if (!state.draft) return null;
  const cfg = await loadPluginConfig();
  const res = await api("/api/plugin/char-swap/sanitize", {
    method: "POST",
    body: JSON.stringify({
      patched_comment: state.draft,
      filter_racial: cfg.sanitize_racial !== false,
      filter_gore: cfg.sanitize_gore !== false,
      filter_creature: false,
    }),
  });
  state.draft = res.patched_comment;
  state.lastRemoved = res.removed || [];
  return res;
}
