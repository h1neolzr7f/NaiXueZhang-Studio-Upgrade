// Deep Module for selecting and creating NAI Character Reference Cards.
// It normalizes all reference sources before a DOM Adapter renders them.

import { api, invalidatePluginConfig } from "./api.js?v=a73081883e";

export function characterReferenceLabel(reference) {
  const mine = reference && (reference.is_custom || reference.source === "custom") ? "我的 OC · " : "";
  if (String(reference?.kind || "").toLowerCase() === "oc" || String(reference?.char_caption || "").trim()) {
    const caption = String(reference.char_caption || "").trim();
    const hint = caption
      ? caption.slice(0, 48) + (caption.length > 48 ? "…" : "")
      : (reference.identity || []).join(", ");
    return `${mine}${reference.label} · OC · ${hint}`;
  }
  return `${mine}${reference?.label || reference?.id || "未命名角色"} — ${(reference?.identity || []).join(", ")}`;
}

function normalizeLibraryReference(item, gender) {
  return {
    id: item.id,
    label: item.label,
    gender: item.gender || gender,
    identity: item.identity || [item.tag || `${item.id}_(arknights)`],
    source: item.source || "ark-library",
  };
}

export function mergeCharacterReferences(presets, libraryItems, gender) {
  const seen = new Set();
  const merged = [];
  for (const reference of presets || []) {
    const id = String(reference.id || characterReferenceLabel(reference));
    if (seen.has(id)) continue;
    seen.add(id);
    merged.push(reference);
  }
  for (const raw of libraryItems || []) {
    const reference = normalizeLibraryReference(raw, gender);
    const id = String(reference.id || reference.label);
    if (seen.has(id)) continue;
    seen.add(id);
    merged.push(reference);
  }
  return merged;
}

export function filterCharacterReferences(references, query, { onlyCustom = false } = {}) {
  const needle = String(query || "").trim().toLowerCase();
  return (references || []).filter((reference) => {
    if (onlyCustom && !(reference.is_custom || reference.source === "custom")) return false;
    if (!needle) return true;
    return [
      reference.label,
      reference.id,
      ...(reference.identity || []),
      reference.char_caption,
    ].some((value) => String(value || "").toLowerCase().includes(needle));
  });
}

export async function loadCharacterReferences(gender, { includeLibrary = true } = {}) {
  const presetPromise = api(`/api/plugin/char-swap/presets?gender=${gender}`)
    .catch(() => ({ presets: [] }));
  if (!includeLibrary) {
    const presetResult = await presetPromise;
    return presetResult.presets || [];
  }
  const [presetResult, libraryResult] = await Promise.all([
    presetPromise,
    api(`/api/plugin/char-swap/ark-library?gender=${gender}&limit=120`)
      .catch(() => ({ items: [] })),
  ]);
  return mergeCharacterReferences(presetResult.presets, libraryResult.items, gender);
}

export async function saveCustomCharacterReference({ label, gender, charCaption }) {
  const result = await api("/api/plugin/char-swap/presets", {
    method: "POST",
    body: JSON.stringify({ label, gender, kind: "oc", char_caption: charCaption }),
  });
  invalidatePluginConfig();
  return { ...(result.preset || {}), is_custom: true, source: "custom" };
}
