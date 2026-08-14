import { useEffect, useState } from "react";
import { StudioPage } from "./pages/StudioPage";
import { GeneratedPage } from "./pages/GeneratedPage";
import { ButlerPage } from "./pages/ButlerPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RemixPage } from "./pages/RemixPage";
import { ProgressPage } from "./pages/ProgressPage";
import { PixivPage } from "./pages/PixivPage";
import { PipelinePage } from "./pages/PipelinePage";
import { DirectorPage } from "./pages/DirectorPage";
import { TagsPage } from "./pages/TagsPage";
import { OpsPage } from "./pages/OpsPage";
import { CompliancePage } from "./pages/CompliancePage";
import {
  currentHref,
  routeFromPath,
  type WorkspaceRoute,
} from "./routes";

function titleFor(route: WorkspaceRoute): string {
  switch (route) {
    case "studio":
      return "工作台";
    case "generated":
      return "生成库";
    case "butler":
      return "助手";
    case "settings":
      return "设置";
    case "remix":
      return "换角";
    case "progress":
      return "爬虫";
    case "pixiv":
      return "发布";
    case "pipeline":
      return "后处理";
    case "director":
      return "导演台";
    case "tags":
      return "分类";
    case "ops":
      return "运营";
    case "compliance":
      return "合规";
    default:
      return "图库";
  }
}

export function App() {
  const [href, setHref] = useState(() => currentHref());
  const path = href.split("?")[0] || "/app";
  const search = href.includes("?") ? href.slice(href.indexOf("?")) : "";
  const route = routeFromPath(path);

  useEffect(() => {
    const onPop = () => setHref(currentHref());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    document.title = `${titleFor(route)} | Nai学长工作室`;
  }, [route]);

  useEffect(() => {
    if (route !== "gallery") return;
    window.location.replace("/");
  }, [route]);

  return (
    <div className="workspace">
      {route !== "gallery" ? (
        <div className="ws-pagehead">
          <a href="/" className="ws-back">
            ← 返回图库
          </a>
          <h1>{titleFor(route)}</h1>
        </div>
      ) : null}
      <main className="ws-main">
        {route === "gallery" ? <p className="ws-status">正在打开图库…</p> : null}
        {route === "studio" ? <StudioPage search={search} /> : null}
        {route === "generated" ? <GeneratedPage search={search} /> : null}
        {route === "butler" ? <ButlerPage /> : null}
        {route === "settings" ? <SettingsPage /> : null}
        {route === "remix" ? <RemixPage search={search} /> : null}
        {route === "progress" ? <ProgressPage /> : null}
        {route === "pixiv" ? <PixivPage /> : null}
        {route === "pipeline" ? <PipelinePage /> : null}
        {route === "director" ? <DirectorPage /> : null}
        {route === "tags" ? <TagsPage /> : null}
        {route === "ops" ? <OpsPage /> : null}
        {route === "compliance" ? <CompliancePage /> : null}
      </main>
    </div>
  );
}
