export type WorkspaceRoute =
  | "gallery"
  | "studio"
  | "generated"
  | "butler"
  | "settings"
  | "remix"
  | "progress"
  | "pixiv"
  | "pipeline"
  | "director"
  | "tags"
  | "ops"
  | "compliance";

export const ROUTES: { id: WorkspaceRoute; path: string; label: string }[] = [
  { id: "gallery", path: "/", label: "图库" },
  { id: "studio", path: "/studio", label: "工作台" },
  { id: "generated", path: "/generated", label: "生成库" },
  { id: "remix", path: "/remix", label: "换角" },
  { id: "butler", path: "/butler", label: "助手" },
  { id: "progress", path: "/progress", label: "爬虫" },
  { id: "pixiv", path: "/pixiv", label: "发布" },
  { id: "settings", path: "/settings", label: "设置" },
];

export const EXTRA_ROUTES: { id: WorkspaceRoute; path: string; label: string }[] = [
  { id: "tags", path: "/nai-tags", label: "分类" },
  { id: "director", path: "/director", label: "导演台" },
  { id: "pipeline", path: "/pipeline", label: "后处理" },
  { id: "ops", path: "/ops", label: "运营" },
  { id: "compliance", path: "/compliance", label: "合规" },
];

export function routeFromPath(pathname: string): WorkspaceRoute {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path.startsWith("/app/studio")) return "studio";
  if (path.startsWith("/app/generated")) return "generated";
  if (path.startsWith("/app/butler")) return "butler";
  if (path.startsWith("/app/settings")) return "settings";
  if (path.startsWith("/app/remix")) return "remix";
  if (path.startsWith("/app/progress")) return "progress";
  if (path.startsWith("/app/pixiv")) return "pixiv";
  if (path.startsWith("/app/pipeline")) return "pipeline";
  if (path.startsWith("/app/director")) return "director";
  if (path.startsWith("/app/tags")) return "tags";
  if (path.startsWith("/app/ops")) return "ops";
  if (path.startsWith("/app/compliance")) return "compliance";
  return "gallery";
}

export function currentHref(): string {
  return window.location.pathname + window.location.search;
}

export function navigate(path: string) {
  if (currentHref() === path) return;
  // Classic HTML pages are the real product. Always leave the React shell
  // so a leftover /app bookmark cannot trap the user in a stub.
  window.location.assign(path);
}

export function studioPath(workId: string, galleryId: string, pageIndex = 0): string {
  const query = new URLSearchParams();
  if (workId) query.set("from", workId);
  if (galleryId && galleryId !== "site") query.set("gallery", galleryId);
  if (pageIndex > 0) query.set("page", String(pageIndex));
  const encoded = query.toString();
  return "/studio" + (encoded ? `?${encoded}` : "");
}

export type GalleryQuery = {
  galleryId?: string;
  q?: string;
  page?: number;
  sort?: string;
  timeRange?: string;
  prompt?: string;
  group?: string;
  view?: string;
};

export function galleryPath(galleryId: string | GalleryQuery, q = "", page = 1): string {
  const query: GalleryQuery = typeof galleryId === "string" ? { galleryId, q, page } : galleryId;
  const params = new URLSearchParams();
  const gid = query.galleryId || "site";
  if (gid !== "site") params.set("gallery", gid);
  if ((query.q || "").trim()) params.set("q", (query.q || "").trim());
  if ((query.prompt || "").trim()) params.set("prompt", (query.prompt || "").trim());
  if ((query.group || "").trim()) params.set("group", (query.group || "").trim());
  const sort = query.sort || "new";
  if (sort && sort !== "new") params.set("sort", sort);
  const timeRange = query.timeRange || "all";
  if (timeRange && timeRange !== "all") params.set("time", timeRange);
  const view = query.view || "";
  if (view && view !== "all") params.set("view", view);
  if ((query.page || 1) > 1) params.set("page", String(query.page));
  const encoded = params.toString();
  return "/" + (encoded ? `?${encoded}` : "");
}

export function generatedPath(groupId = ""): string {
  if (!groupId) return "/generated";
  return "/generated?g=" + encodeURIComponent(groupId);
}

export function remixPath(workId = "", galleryId = "site", pageIndex = 0): string {
  const query = new URLSearchParams();
  if (workId) query.set("from", workId);
  if (galleryId && galleryId !== "site") query.set("gallery", galleryId);
  if (pageIndex > 0) query.set("page", String(pageIndex));
  const encoded = query.toString();
  return "/remix" + (encoded ? `?${encoded}` : "");
}
