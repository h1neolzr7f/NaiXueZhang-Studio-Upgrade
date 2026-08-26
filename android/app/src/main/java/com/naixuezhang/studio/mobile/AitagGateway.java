package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

final class AitagGateway {
    private static final String SITE = "https://aitag.win";
    private static final String CDN = "https://ai-img.10118899.xyz";
    private static final Pattern WORK_ID = Pattern.compile("^[A-Za-z0-9_-]{1,128}$");
    private static final Pattern PART = Pattern.compile("^[A-Za-z0-9_-]{1,180}$");
    private static final int JSON_LIMIT = 8 * 1024 * 1024;
    private static final int IMAGE_LIMIT = 8 * 1024 * 1024;
    static final String CHROME_UA = BrowserSession.UA;
    static final String DESKTOP_UA = "Pixiv-NAI-Gallery/aitag";
    private final TokenStore tokens;
    private volatile String lastVia = "";

    AitagGateway(TokenStore tokens) {
        this.tokens = tokens;
    }

    JSONObject search(String query, int page, boolean naiOnly) throws Exception {
        String q = query == null ? "" : query.trim();
        String url = SITE + "/api/ai_works_search?page=" + Math.max(1, page)
            + "&page_size=60&q=" + enc(q) + "&prompt=&sort=new&time_range=all";
        JSONObject raw = fetchJson(url);
        JSONObject root = raw.optJSONObject("data");
        if (root == null) root = raw;
        JSONArray source = firstArray(root, "works", "items", "results");
        if (source.length() == 0) source = firstArray(raw, "works", "items", "results");
        JSONArray naiItems = new JSONArray();
        JSONArray safeItems = new JSONArray();
        for (int i = 0; i < source.length(); i++) {
            JSONObject work = normalizeWork(source.optJSONObject(i));
            if (work == null || !looksSafe(work)) continue;
            safeItems.put(work);
            if (looksNai(work)) naiItems.put(work);
        }
        JSONArray items = naiOnly && naiItems.length() > 0 ? naiItems : safeItems;
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("source", "aitag-online");
        out.put("query", q);
        out.put("page", Math.max(1, page));
        out.put("page_size", 60);
        out.put("items", items);
        out.put("works", items);
        out.put("relaxed", naiOnly && naiItems.length() == 0 && safeItems.length() > 0);
        out.put("via", lastVia);
        out.put("generation_calls", 0);
        return out;
    }

    JSONObject probe() {
        JSONObject out = new JSONObject();
        try {
            JSONObject result = search("arknights", 1, false);
            JSONArray items = result.optJSONArray("items");
            int count = items == null ? 0 : items.length();
            out.put("ok", count > 0 || result.optBoolean("ok", false));
            out.put("via", lastVia);
            out.put("item_count", count);
            out.put("message", count > 0
                ? ("在线库已接通（" + (lastVia.isEmpty() ? "java" : lastVia) + "），搜到 " + count + " 条")
                : "在线库通了，但这页没有结果");
        } catch (Exception error) {
            try {
                out.put("ok", false);
                out.put("via", lastVia);
                out.put("item_count", 0);
                out.put("detail", error.getMessage());
                out.put("message", error.getMessage() == null ? "在线库暂时打不开" : error.getMessage());
            } catch (Exception ignored) {}
        }
        try {
            JSONObject net = tokens.networkStatus();
            out.put("proxy", net.optString("proxy"));
            out.put("detected_proxy", net.optString("detected_proxy"));
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject work(String workId) throws Exception {
        String id = String.valueOf(workId == null ? "" : workId).trim();
        if (!WORK_ID.matcher(id).matches()) throw new IllegalArgumentException("AITag work id is invalid");
        JSONObject raw = fetchJson(SITE + "/api/work/" + enc(id));
        JSONObject root = raw.optJSONObject("data");
        if (root == null) root = raw;
        JSONObject workRaw = root.optJSONObject("work");
        if (workRaw == null) workRaw = root;
        JSONObject work = normalizeWork(workRaw);
        JSONArray images = firstArray(root, "images", "artworks", "pages");
        if (images.length() == 0 && work != null) images = work.optJSONArray("images");
        JSONArray normalized = new JSONArray();
        if (images != null) {
            for (int i = 0; i < images.length(); i++) {
                JSONObject image = normalizeImage(images.optJSONObject(i), id, i);
                if (image != null) normalized.put(image);
            }
        }
        if (work == null) work = new JSONObject();
        work.put("images", normalized);
        int count = Math.max(work.optInt("image_count", 0), normalized.length());
        work.put("image_count", count);
        work.put("work_id", JsonUtil.first(work, "work_id", "id").isEmpty() ? id : JsonUtil.first(work, "work_id", "id"));
        work.put("id", work.optString("work_id"));
        work.put("external_url", "https://aitag.win/i/" + work.optString("work_id"));
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("work", work);
        out.put("images", normalized);
        out.put("source", "aitag-online");
        out.put("external_url", work.optString("external_url"));
        out.put("character_candidates", new JSONArray());
        out.put("generation_calls", 0);
        return out;
    }

    HttpOutbound.Result cover(String workId) throws Exception {
        JSONObject detail = work(workId);
        JSONArray images = detail.optJSONArray("images");
        JSONObject image = images != null && images.length() > 0 ? images.optJSONObject(0) : null;
        if (image == null) throw new IllegalStateException("AITag image was unavailable");
        return fetchImage(cdnUrl(image));
    }

    HttpOutbound.Result image(String type, String author, String file) throws Exception {
        if (!PART.matcher(type).matches() || !PART.matcher(author).matches()) {
            throw new IllegalArgumentException("invalid AITag image path");
        }
        String name = file.endsWith(".webp") ? file : file + ".webp";
        if (!name.toLowerCase(Locale.ROOT).endsWith(".webp")) {
            throw new IllegalArgumentException("invalid AITag image path");
        }
        return fetchImage(CDN + "/" + enc(type) + "/" + enc(author) + "/" + enc(name));
    }

    private JSONObject normalizeWork(JSONObject raw) throws Exception {
        if (raw == null) return null;
        JSONObject src = raw;
        JSONObject nested = JsonUtil.nested(raw, "work", "item", "result", "data");
        if (nested.length() > 0 && (nested.has("id") || nested.has("work_id") || nested.has("title"))) {
            src = nested;
        }
        String workId = JsonUtil.first(src, "work_id", "workId", "id");
        if (workId.isEmpty()) return null;
        JSONObject work = new JSONObject();
        work.put("work_id", workId);
        work.put("id", workId);
        work.put("title", JsonUtil.stripHtml(JsonUtil.first(src, "title", "name", "label")));
        work.put("creator", JsonUtil.first(src, "username", "userName"));
        work.put("ai_type", JsonUtil.first(src, "AI_type", "ai_type", "aiType"));
        work.put("user_id", JsonUtil.first(src, "userId", "userid", "author_id"));
        work.put("tags", JsonUtil.arr(src, "tags"));
        work.put("metadata", src);
        JSONArray images = firstArray(raw.has("images") ? raw : src, "images", "pages", "artworks");
        JSONArray normalized = new JSONArray();
        for (int i = 0; i < images.length(); i++) {
            JSONObject image = normalizeImage(images.optJSONObject(i), workId, i);
            if (image != null) normalized.put(image);
        }
        if (normalized.length() == 0) {
            JSONObject cover = new JSONObject();
            cover.put("thumbnail_url", "/api/nai/aitag/cover/" + enc(workId));
            cover.put("url", cover.optString("thumbnail_url"));
            normalized.put(cover);
        }
        work.put("images", normalized);
        int count = imageCount(src, raw);
        if (count <= 0) count = normalized.length();
        work.put("image_count", count);
        work.put("external_url", "https://aitag.win/i/" + workId);
        return work;
    }

    private JSONObject normalizeImage(JSONObject raw, String workId, int index) throws Exception {
        if (raw == null) return null;
        JSONObject image = new JSONObject();
        String imageId = JsonUtil.first(raw, "image_id", "imageId", "id");
        if (imageId.isEmpty()) imageId = workId + "_p" + index;
        image.put("image_id", imageId);
        image.put("id", imageId);
        image.put("page_index", index);
        image.put("work_id", workId);
        image.put("author_id", JsonUtil.first(raw, "author_id", "authorId", "userid"));
        image.put("image_type", JsonUtil.first(raw, "image_type", "imageType"));
        image.put("file_name", JsonUtil.first(raw, "file_name", "fileName"));
        image.put("model", JsonUtil.first(raw, "model"));
        image.put("prompt_text", JsonUtil.first(raw, "prompt_text", "promptText"));
        image.put("width", raw.opt("width"));
        image.put("height", raw.opt("height"));
        Object aiJson = raw.opt("ai_json");
        if (aiJson == null) aiJson = raw.opt("aiJson");
        if (aiJson != null) image.put("ai_json", aiJson);
        String type = image.optString("image_type");
        String author = image.optString("author_id");
        String file = image.optString("file_name");
        String proxy = "";
        if (!type.isEmpty() && !author.isEmpty() && !file.isEmpty()) {
            if (!file.toLowerCase(Locale.ROOT).endsWith(".webp")) file = file + ".webp";
            proxy = "/api/nai/aitag/image/" + enc(type) + "/" + enc(author) + "/" + enc(file);
        }
        if (proxy.isEmpty()) proxy = "/api/nai/aitag/cover/" + enc(workId);
        image.put("url", proxy);
        image.put("thumbnail_url", proxy);
        image.put("remote_url", JsonUtil.first(raw, "url", "image_url", "thumbnail_url"));
        return image;
    }

    private boolean looksNai(JSONObject work) {
        StringBuilder blob = new StringBuilder();
        blob.append(JsonUtil.str(work, "ai_type")).append(' ');
        JSONObject meta = work.optJSONObject("metadata");
        if (meta != null) {
            blob.append(JsonUtil.first(meta, "model", "Source", "Software", "AI_type", "ai_type")).append(' ');
        }
        JSONArray images = work.optJSONArray("images");
        if (images != null) {
            for (int i = 0; i < images.length(); i++) {
                JSONObject image = images.optJSONObject(i);
                if (image != null) blob.append(JsonUtil.str(image, "model")).append(' ');
            }
        }
        String text = blob.toString().toLowerCase(Locale.ROOT);
        return text.contains("novelai") || text.contains("nai-diffusion") || text.contains("novel ai") || text.contains("nai");
    }

    private boolean looksSafe(JSONObject work) {
        StringBuilder blob = new StringBuilder();
        JSONObject meta = work.optJSONObject("metadata");
        if (meta != null) blob.append(JsonUtil.first(meta, "rating", "safety")).append(' ');
        JSONArray tags = work.optJSONArray("tags");
        if (tags != null) {
            for (int i = 0; i < tags.length(); i++) blob.append(tags.opt(i)).append(' ');
        }
        String text = blob.toString().toLowerCase(Locale.ROOT).replace('_', '-');
        return !text.contains("r-18") && !text.contains("r18") && !text.contains("nsfw") && !text.contains("explicit");
    }

    private String cdnUrl(JSONObject image) {
        String type = JsonUtil.str(image, "image_type");
        String author = JsonUtil.str(image, "author_id");
        String file = JsonUtil.str(image, "file_name");
        if (type.isEmpty() || author.isEmpty() || file.isEmpty()) {
            throw new IllegalStateException("AITag image was unavailable");
        }
        if (!file.toLowerCase(Locale.ROOT).endsWith(".webp")) file = file + ".webp";
        return CDN + "/" + enc(type) + "/" + enc(author) + "/" + enc(file);
    }

    private JSONObject fetchJson(String url) throws Exception {
        Exception last = null;
        BrowserSession browser = BrowserSession.get();
        if (browser != null) {
            try {
                JSONObject parsed = browser.fetchJson(url, 45000);
                lastVia = "webview";
                return parsed;
            } catch (Exception error) {
                last = error;
            }
        }
        for (String ua : new String[]{CHROME_UA, DESKTOP_UA}) {
            Map<String, String> headers = jsonHeaders(ua);
            for (HttpOutbound.Route route : tokens.onlineCandidates()) {
                try {
                    HttpOutbound.Result result = HttpOutbound.get(url, headers, 12000, JSON_LIMIT, route);
                    if (BrowserSession.looksBlocked(result.status, result.text()) || result.status < 200 || result.status >= 300) {
                        last = new IllegalStateException("AITag returned HTTP " + result.status);
                        continue;
                    }
                    if (looksHtml(result.text())) {
                        last = new IllegalStateException("AITag returned HTTP 403");
                        continue;
                    }
                    JSONObject parsed = JsonUtil.obj(result.text());
                    if (parsed.length() == 0 && result.text().trim().isEmpty()) {
                        last = new IllegalStateException("AITag empty");
                        continue;
                    }
                    lastVia = route.label();
                    return parsed;
                } catch (Exception error) {
                    last = error;
                }
            }
        }
        throw last != null ? last : new IllegalStateException("在线库暂时打不开");
    }

    private HttpOutbound.Result fetchImage(String url) throws Exception {
        if (!url.startsWith(CDN + "/")) throw new IllegalStateException("AITag image response escaped the fixed CDN origin");
        Exception last = null;
        Map<String, String> headers = imageHeaders();
        for (HttpOutbound.Route route : tokens.onlineCandidates()) {
            try {
                HttpOutbound.Result result = HttpOutbound.get(url, headers, 30000, IMAGE_LIMIT, route);
                if (result.status == 200 && result.body.length > 32 && !looksHtml(result.text())) {
                    lastVia = route.label();
                    return result;
                }
                last = new IllegalStateException("AITag image was unavailable");
            } catch (Exception error) {
                last = error;
            }
        }
        BrowserSession browser = BrowserSession.get();
        if (browser != null) {
            try {
                HttpOutbound.Result result = browser.fetchBytes(url, 45000, IMAGE_LIMIT);
                lastVia = "webview";
                return result;
            } catch (Exception error) {
                last = error;
            }
        }
        throw last != null ? last : new IllegalStateException("AITag image was unavailable");
    }

    private Map<String, String> jsonHeaders(String ua) {
        Map<String, String> headers = new HashMap<String, String>();
        headers.put("Accept", "application/json");
        headers.put("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8");
        headers.put("User-Agent", ua);
        headers.put("Referer", SITE + "/");
        headers.put("Origin", SITE);
        headers.put("Sec-Fetch-Dest", "empty");
        headers.put("Sec-Fetch-Mode", "cors");
        headers.put("Sec-Fetch-Site", "same-origin");
        String cookie = BrowserSession.cookiesFor(SITE + "/");
        if (!cookie.isEmpty()) headers.put("Cookie", cookie);
        return headers;
    }

    private Map<String, String> imageHeaders() {
        Map<String, String> headers = new HashMap<String, String>();
        headers.put("Accept", "image/webp,image/*,*/*;q=0.8");
        headers.put("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8");
        headers.put("User-Agent", CHROME_UA);
        headers.put("Referer", SITE + "/");
        String cookie = BrowserSession.cookiesFor(SITE + "/");
        if (!cookie.isEmpty()) headers.put("Cookie", cookie);
        return headers;
    }

    private static boolean looksHtml(String text) {
        String value = String.valueOf(text == null ? "" : text).trim();
        return value.startsWith("<!DOCTYPE") || value.startsWith("<html") || value.contains("Just a moment");
    }

    private static int imageCount(JSONObject src, JSONObject raw) {
        for (JSONObject obj : new JSONObject[]{src, raw}) {
            if (obj == null) continue;
            for (String key : new String[]{"image_count", "imageCount", "page_count", "pageCount"}) {
                int n = obj.optInt(key, -1);
                if (n > 0) return n;
            }
            JSONArray originals = obj.optJSONArray("original_urls");
            if (originals == null) originals = obj.optJSONArray("originalUrls");
            if (originals != null && originals.length() > 0) return originals.length();
        }
        return 0;
    }

    private static JSONArray firstArray(JSONObject obj, String... keys) {
        if (obj == null) return new JSONArray();
        for (String key : keys) {
            JSONArray found = obj.optJSONArray(key);
            if (found != null) return found;
        }
        return new JSONArray();
    }

    private static String enc(String value) {
        try {
            return URLEncoder.encode(String.valueOf(value == null ? "" : value), StandardCharsets.UTF_8.name())
                .replace("+", "%20");
        } catch (Exception e) {
            return "";
        }
    }
}
