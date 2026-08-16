// Deep Module for NAI Style Reference selection and style-tag interpretation.

import { state, buildStyleBundleFallback } from "./state.js?v=f80b97d795";
import { api, loadPluginConfig, invalidatePluginConfig } from "./api.js?v=a73081883e";

export function presetStyle(preset) {
  if (!preset) return "";
  if (preset.style != null) return String(preset.style);
  if (preset.replace != null) return String(preset.replace);
  return "";
}

export function stylePresetDetail(preset) {
  return String(presetStyle(preset) || "").trim() || "（清空当前识别画风）";
}

export function styleBundleFindText(bundle) {
  if (!bundle) return "";
  const direct = String(bundle.combined || bundle.combined_all || "").trim();
  if (direct) return direct;
  for (const group of Array.isArray(bundle.groups) ? bundle.groups : []) {
    const text = String(group.combined || "").trim();
    if (text) return text;
  }
  return "";
}

export function styleBundleFromSelection(selection = {}) {
  if (selection.bundle) return selection.bundle;
  if (selection.slots) return buildStyleBundleFallback(selection.slots);
  return state.styleBundle || buildStyleBundleFallback(state.styleSlots || []);
}

export function styleFindCandidates(selection = {}) {
  const candidates = [];
  const push = (value) => {
    const text = String(value || "").trim();
    if (text && !candidates.includes(text)) candidates.push(text);
  };
  push(selection.combined);
  const bundle = styleBundleFromSelection(selection);
  push(bundle.combined);
  push(bundle.combined_all);
  for (const group of bundle.groups || []) {
    push(group.combined);
    const tags = (group.tags || []).map((tag) => String(tag || "").trim()).filter(Boolean);
    if (tags.length) {
      push(tags.join(", "));
      push(tags.join(","));
      push(tags.join(",  "));
    }
    tags.forEach(push);
  }
  return candidates;
}

export function styleTags(selection = {}) {
  const tags = [];
  const push = (value) => {
    const text = String(value || "").trim();
    if (text && !tags.includes(text)) tags.push(text);
  };
  const bundle = styleBundleFromSelection(selection);
  const groups = Array.isArray(bundle.groups) ? bundle.groups : [];
  const wanted = String(selection.combined || "").trim();
  const primary = (wanted && groups.find((group) => String(group.combined || "").trim() === wanted)) || groups[0];
  (primary?.tags || []).forEach(push);
  groups.forEach((group) => (group.tags || []).forEach(push));
  (selection.slots || state.styleSlots || []).forEach((slot) => push(slot.tag));
  return tags;
}

export function normalizeStyleReference(body, fallbackId = "") {
  return {
    id: String(body.id || fallbackId || "").trim(),
    label: String(body.label || "").trim(),
    style: String(body.style != null ? body.style : (body.replace || "")).trim(),
  };
}

export async function loadStyleReferences(force = false) {
  const config = await loadPluginConfig(force);
  return config.style_presets || [];
}
