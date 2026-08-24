(function () {
  const $ = (id) => document.getElementById(id);
  function show(id, data) {
    $(id).textContent = JSON.stringify(data, null, 2);
  }
  async function refresh() {
    show("pipelineConfig", "加载中...");
    const [config, status, backlog] = await Promise.all([
      window.ApiClient.get("/api/pipeline/config"),
      window.ApiClient.get("/api/pipeline/status"),
      window.ApiClient.get("/api/pipeline/backlog"),
    ]);
    show("pipelineConfig", config);
    show("pipelineStatus", status);
    show("pipelineBacklog", backlog);
  }
  document.addEventListener("DOMContentLoaded", () => {
    $("refreshPipeline").addEventListener("click", () => refresh().catch(err => show("pipelineStatus", { error: String(err.message || err) })));
    $("cancelPipeline")?.addEventListener("click", () => {
      window.ApiClient.request("/api/pipeline/cancel", { method: "POST" })
        .then(() => refresh())
        .catch((err) => show("pipelineStatus", { error: String(err.message || err) }));
    });
    refresh().catch(err => show("pipelineStatus", { error: String(err.message || err) }));
  });
})();
