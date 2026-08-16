// DOM page Adapter for the CharSwap workbench.
// The rest of the feature receives stable operations instead of sharing modal
// lifecycle and draft-preview DOM details.

import { instructionFromAiJson } from "./api.js?v=0411b73ad6";

export function byId(id, root = document) {
  if (root === document) return document.getElementById(id);
  return root.querySelector(`#${id}`);
}

export function query(selector, root = document) {
  return root.querySelector(selector);
}

export function renderDraftPreview(aiJson) {
  const preview = byId("charSwapDraftPreview");
  if (!preview) return;
  const text = instructionFromAiJson(aiJson);
  preview.textContent = text || "（暂无草稿指令）";
}

export function dismissModals() {
  document.querySelectorAll(".char-swap-modal-backdrop").forEach((element) => element.remove());
}

export function createModal({ className = "", html = "" } = {}) {
  const previousFocus = document.activeElement;
  const backdrop = document.createElement("div");
  backdrop.className = "char-swap-modal-backdrop";
  const modal = document.createElement("div");
  modal.className = `char-swap-modal${className ? ` ${className}` : ""}`;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.innerHTML = html;
  const onEscape = (event) => {
    if (event.key === "Escape") close();
  };
  function close() {
    backdrop.remove();
    document.removeEventListener("keydown", onEscape);
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  }
  function mount() {
    document.addEventListener("keydown", onEscape);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    return modal;
  }
  return { backdrop, modal, close, mount, previousFocus };
}
