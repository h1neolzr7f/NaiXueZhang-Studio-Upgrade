(function () {
  const DEFAULT_TIMEOUT_MS = 15000;

  function withTimeout(signal, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs || DEFAULT_TIMEOUT_MS);
    if (signal) {
      if (signal.aborted) controller.abort();
      else signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
    return { signal: controller.signal, clear: () => clearTimeout(timer) };
  }

  let sessionTokenPromise = null;
  function clearSessionToken() {
    sessionTokenPromise = null;
  }
  function getSessionToken() {
    if (!sessionTokenPromise) {
      sessionTokenPromise = fetch("/api/session-token", { cache: "no-store" })
        .then((res) => {
          if (!res.ok) throw new Error("session-token " + res.status);
          return res.json();
        })
        .then((data) => {
          const token = (data && data.token) || "";
          if (!token) throw new Error("empty session token");
          return token;
        })
        .catch((err) => {
          sessionTokenPromise = null;
          throw err;
        });
    }
    return sessionTokenPromise;
  }

  function toastSessionLost() {
    const msg = "会话失效，请刷新页面后重试";
    try {
      if (window.UiToast && typeof window.UiToast.err === "function") {
        window.UiToast.err(msg);
        return;
      }
    } catch (_) { /* ignore */ }
    try { console.warn(msg); } catch (_) { /* ignore */ }
  }

  async function raw(path, options) {
    const baseOpts = Object.assign({}, options || {});
    const method = (baseOpts.method || "GET").toUpperCase();
    const mutating = method !== "GET" && method !== "HEAD" && method !== "OPTIONS";
    let retriedAuth = false;
    while (true) {
      const opts = Object.assign({}, baseOpts);
      opts.headers = Object.assign({}, baseOpts.headers || {});
      if (mutating) {
        try {
          const token = await getSessionToken();
          opts.headers = Object.assign({}, opts.headers, { "X-Session-Token": token });
        } catch (_) {
          toastSessionLost();
          const err = new Error("会话失效，写操作未发送");
          err.status = 403;
          throw err;
        }
      }
      const timeout = withTimeout(opts.signal, opts.timeoutMs);
      delete opts.timeoutMs;
      opts.signal = timeout.signal;
      try {
        const res = await fetch(path, opts);
        if (
          mutating
          && !retriedAuth
          && (res.status === 401 || res.status === 403)
        ) {
          retriedAuth = true;
          clearSessionToken();
          continue;
        }
        return res;
      } finally {
        timeout.clear();
      }
    }
  }

  async function request(path, options) {
    const opts = options || {};
    const init = {
      method: opts.method || "GET",
      headers: Object.assign({}, opts.headers || {}),
      cache: opts.cache || "no-store",
      signal: opts.signal,
      timeoutMs: opts.timeoutMs,
    };
    if (opts.body !== undefined) {
      const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
      if (isForm) {
        init.body = opts.body;
        delete init.headers["Content-Type"];
        delete init.headers["content-type"];
      } else {
        init.headers["Content-Type"] = init.headers["Content-Type"] || "application/json";
        init.body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
      }
    }
    const res = await raw(path, init);
    const contentType = res.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await res.json()
      : await res.text();
    if (!res.ok) {
      const rawDetail = payload && payload.detail;
      let message = `${path} ${res.status}`;
      if (typeof rawDetail === "string" && rawDetail.trim()) {
        message = rawDetail;
      } else if (Array.isArray(rawDetail)) {
        message = rawDetail
          .map((item) => (typeof item === "string" ? item : (item && item.msg) || JSON.stringify(item)))
          .filter(Boolean)
          .join("；") || message;
      } else if (rawDetail && typeof rawDetail === "object") {
        message = rawDetail.message || rawDetail.msg || JSON.stringify(rawDetail);
      } else if (payload && typeof payload === "string" && payload.trim()) {
        message = payload;
      }
      const err = new Error(message);
      err.status = res.status;
      err.payload = payload;
      err.detail = rawDetail;
      throw err;
    }
    return payload;
  }

  function get(path, options) {
    return request(path, Object.assign({}, options || {}, { method: "GET" }));
  }

  function post(path, body, options) {
    return request(path, Object.assign({}, options || {}, { method: "POST", body }));
  }

  function fetchJson(path, options) {
    return request(path, options || {});
  }

  async function pollJob(taskId, onProgress, options) {
    const opts = options || {};
    const intervalMs = Number(opts.intervalMs) > 0 ? Number(opts.intervalMs) : 800;
    const timeoutMs = Number(opts.timeoutMs) > 0 ? Number(opts.timeoutMs) : 30 * 60 * 1000;
    const started = Date.now();
    const id = String(taskId || "").trim();
    if (!id) throw new Error("missing generation task_id");
    while (true) {
      const data = await get("/api/nai/jobs?task_id=" + encodeURIComponent(id));
      const job = (data && (data.job || data.batch)) || data || {};
      if (typeof onProgress === "function") onProgress(job);
      const status = String(job.status || "");
      if (job.terminal || ["done", "error", "cancelled", "unknown"].indexOf(status) >= 0) {
        return job;
      }
      if (Date.now() - started > timeoutMs) {
        throw new Error("生成任务等待超时");
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }

  window.ApiClient = {
    raw,
    request,
    get,
    post,
    fetchJson,
    pollJob,
    clearSessionToken,
  };
})();
