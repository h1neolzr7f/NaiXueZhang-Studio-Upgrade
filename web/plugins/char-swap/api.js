// API and communication helpers for CharSwap plugin

import { state } from "./state.js?v=f80b97d795";

export function $(sel, root) {
  return (root || document).querySelector(sel);
}

export function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

export function esc(s) {
  if (typeof window.escapeHtml === "function") return window.escapeHtml(s);
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

export function setMsg(el, text, ok, html) {
  if (!el) return;
  el.className = "char-swap-msg " + (ok ? "ok" : "err");
  el.replaceChildren();
  if (html && text && typeof text !== "string") {
    el.appendChild(text);
  } else {
    el.textContent = text == null ? "" : String(text);
  }
  el.style.display = text ? "" : "none";
}

export function flashMsg(el, text, ok) {
  setMsg(el, text, ok);
  if (el && el._timer) clearTimeout(el._timer);
  if (el) {
    el._timer = setTimeout(() => {
      el.style.display = "none";
    }, 4500);
  }
}

export function copyText(text) {
  const ta = document.createElement("textarea");
  ta.value = text || "";
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
  } catch (err) {
    console.error("Copy failed:", err);
  }
  document.body.removeChild(ta);
}

export function instructionFromAiJson(aiJson) {
  if (!window.NAI || typeof window.NAI.convert !== "function") return "";
  const res = window.NAI.convert(aiJson || {});
  return (res && (res.txt || res.instruction)) || "";
}

const ADHOC_BODY_ENDPOINTS = new Set([
  "/api/plugin/char-swap/transform",
  "/api/plugin/char-swap/batch/preview",
  "/api/plugin/char-swap/batch/authorize",
  "/api/plugin/char-swap/batch/run",
]);

export async function api(path, opts) {
  // Temporary clothing layers belong only to transform requests, never config/preset saves.
  const endpoint = String(path || "").split("?", 1)[0];
  if (opts && opts.body && typeof opts.body === "string" && ADHOC_BODY_ENDPOINTS.has(endpoint)) {
    try {
      const bodyObj = JSON.parse(opts.body);
      const adhoc = getAdhocLayers();
      if (adhoc.clothing) bodyObj.clothing = adhoc.clothing;
      if (adhoc.extra) bodyObj.extra = adhoc.extra;
      if (adhoc.remove && adhoc.remove.length) bodyObj.remove = adhoc.remove;
      opts.body = JSON.stringify(bodyObj);
    } catch (e) { /* ignore */ }
  }
  return await ApiClient.fetchJson(path, opts);
}

export function getAdhocLayers() {
  const get = (id) => ((document.getElementById(id) || {}).value || "").trim();
  const removeStr = get("adhocRemove");
  return {
    clothing: get("adhocClothing"),
    extra: get("adhocExtra"),
    remove: removeStr ? removeStr.split(",").map(s => s.trim()).filter(Boolean) : [],
  };
}

export async function loadPluginConfig(force) {
  if (!force && state.pluginConfig) return state.pluginConfig;
  const res = await api("/api/plugin/char-swap/config");
  state.pluginConfig = res.config;
  return res.config;
}

export function invalidatePluginConfig() {
  state.pluginConfig = null;
}
