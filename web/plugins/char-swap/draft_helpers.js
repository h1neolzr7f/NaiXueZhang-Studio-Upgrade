import { BATCH_MAX_DEFAULT, draftCacheKey, draftPageCache, normalizeWorkId, state } from "./state.js?v=f80b97d795";
import { deepClone } from "./api.js?v=980573fcbd";

export function getBatchMax() {
  const v = state.pluginConfig && state.pluginConfig.batch_target_max;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : BATCH_MAX_DEFAULT;
}

export function draftCommentForPage(workId, pageIndex) {
  if (
    normalizeWorkId(workId) === normalizeWorkId(state.workId)
    && Number(pageIndex) === Number(state.pageIndex)
    && state.draft
  ) {
    return deepClone(state.draft);
  }
  const cached = draftPageCache.get(draftCacheKey(workId, pageIndex));
  return cached && cached.draft ? deepClone(cached.draft) : null;
}

export function attachDraftToPayload(payload, workId, pageIndex) {
  const draft = draftCommentForPage(workId, pageIndex);
  if (draft && draft.v4_prompt) {
    payload.patched_comment = draft;
  }
  return payload;
}
