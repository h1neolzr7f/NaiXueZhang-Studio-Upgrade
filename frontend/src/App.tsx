import { useEffect, useState } from "react";
import { GalleryPage } from "./pages/GalleryPage";
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
  EXTRA_ROUTES,
  ROUTES,
  currentHref,
  navigate,
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
      return "小镜";
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
    function onClick(event: MouseEvent) {
      const target = event.target as HTMLElement | null;
      const link = target?.closest("a");
      if (!link || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const raw = link.getAttribute("href") || "";
      if (!raw.startsWith("/app")) return;
      event.preventDefault();
      navigate(raw);
    }
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  useEffect(() => {
    document.title = `${titleFor(route)} | Nai学长工作室`;
  }, [route]);

  return (
    <div className="workspace">
      <nav className="ws-nav" aria-label="工作区导航">
        <span className="ws-brand">工作区</span>
        {ROUTES.map((item) => (
          <a
            key={item.id}
            href={item.path}
            className={route === item.id ? "active" : ""}
            aria-current={route === item.id ? "page" : undefined}
            onClick={(event) => {
              event.preventDefault();
              navigate(item.path);
            }}
          >
            {item.label}
          </a>
        ))}
        {EXTRA_ROUTES.map((item) => (
          <a
            key={item.id}
            href={item.path}
            className={route === item.id ? "active" : ""}
            aria-current={route === item.id ? "page" : undefined}
            onClick={(event) => {
              event.preventDefault();
              navigate(item.path);
            }}
          >
            {item.label}
          </a>
        ))}
        <a className="legacy" href="/">
          经典图库
        </a>
      </nav>
      <main className={route === "gallery" ? "ws-main wide" : "ws-main"}>
        {route === "gallery" ? <GalleryPage search={search} /> : null}
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
