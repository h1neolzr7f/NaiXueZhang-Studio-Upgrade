package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

final class FavoriteStore {
    private static final int COMPRESS_EDGE = 720;
    private static final int COMPRESS_QUALITY = 72;
    private static final int MAX_PAGES = 40;
    private final File root;
    private final File indexFile;
    private final AitagGateway aitag;

    FavoriteStore(Context context, AitagGateway aitag) {
        this.aitag = aitag;
        this.root = new File(context.getApplicationContext().getFilesDir(), "favorites");
        if (!this.root.exists()) this.root.mkdirs();
        this.indexFile = new File(this.root, "index.json");
    }

    synchronized JSONObject list() {
        JSONObject out = new JSONObject();
        try {
            JSONArray index = readIndex();
            out.put("ok", true);
            out.put("items", index);
            out.put("total", index.length());
        } catch (Exception ignored) {}
        return out;
    }

    synchronized JSONObject works() {
        return works("");
    }

    synchronized JSONObject works(String query) {
        String needle = String.valueOf(query == null ? "" : query).trim().toLowerCase(java.util.Locale.ROOT);
        JSONArray items = new JSONArray();
        JSONArray index = readIndex();
        for (int i = 0; i < index.length(); i++) {
            JSONObject row = index.optJSONObject(i);
            if (row == null) continue;
            if (!needle.isEmpty() && !hay(row).contains(needle)) continue;
            JSONObject item = new JSONObject();
            try {
                String id = row.optString("work_id");
                item.put("work_id", id);
                item.put("id", id);
                item.put("title", row.optString("title"));
                item.put("creator", row.optString("creator"));
                item.put("image_count", row.optInt("image_count", 0));
                item.put("tags", row.optJSONArray("tags") == null ? new JSONArray() : row.optJSONArray("tags"));
                item.put("favorited", true);
                item.put("local", true);
                item.put("gallery_id", "phone-local");
                item.put("kind", row.optString("kind", "aitag"));
                item.put("save_state", row.optString("save_state", "pending"));
                item.put("last_error", row.optString("last_error"));
                JSONArray images = new JSONArray();
                JSONObject cover = new JSONObject();
                String local = imageFile(id, 0) != null
                    ? localUrl(id, 0)
                    : "/api/nai/aitag/cover/" + id;
                cover.put("url", local);
                cover.put("thumbnail_url", local);
                images.put(cover);
                item.put("images", images);
                items.put(item);
            } catch (Exception ignored) {}
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("items", items);
            out.put("works", items);
            out.put("generation_calls", 0);
        } catch (Exception ignored) {}
        return out;
    }

    synchronized boolean has(String workId) {
        return find(readIndex(), normalizeId(workId)) >= 0;
    }

    synchronized JSONObject ids() {
        JSONArray ids = new JSONArray();
        JSONArray index = readIndex();
        for (int i = 0; i < index.length(); i++) {
            JSONObject row = index.optJSONObject(i);
            if (row != null) ids.put(row.optString("work_id"));
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("ids", ids);
        } catch (Exception ignored) {}
        return out;
    }

    synchronized JSONObject toggle(String workId, JSONObject snapshot) throws Exception {
        String id = normalizeId(workId);
        if (id.isEmpty()) throw new IllegalArgumentException("缺少作品 id");
        JSONArray index = readIndex();
        int found = find(index, id);
        JSONObject out = new JSONObject();
        if (found >= 0) {
            JSONArray next = new JSONArray();
            for (int i = 0; i < index.length(); i++) {
                if (i != found) next.put(index.opt(i));
            }
            writeIndex(next);
            deleteDir(new File(root, id));
            out.put("ok", true);
            out.put("favorited", false);
            out.put("message", "已取消收藏");
            return out;
        }
        JSONObject row = new JSONObject();
        row.put("work_id", id);
        row.put("title", snapshot == null ? id : JsonUtil.first(snapshot, "title"));
        row.put("creator", snapshot == null ? "" : JsonUtil.first(snapshot, "creator"));
        row.put("image_count", snapshot == null ? 0 : snapshot.optInt("image_count", 0));
        row.put("tags", snapshot == null ? new JSONArray() : JsonUtil.arr(snapshot, "tags"));
        row.put("cover_url", snapshot == null ? "" : JsonUtil.first(snapshot, "cover_url"));
        row.put("added_at", System.currentTimeMillis());
        row.put("kind", "aitag");
        row.put("save_state", "pending");
        JSONArray next = new JSONArray();
        next.put(row);
        for (int i = 0; i < index.length(); i++) next.put(index.opt(i));
        writeIndex(next);
        File dir = new File(root, id);
        if (!dir.exists()) dir.mkdirs();
        writeText(new File(dir, "snapshot.json"), (snapshot == null ? new JSONObject() : snapshot).toString());
        JSONObject payload = absorbSnapshot(id, snapshot, row);
        writeSnapshotImage(id, snapshot);
        overlayLocalImages(payload, id);
        boolean prompts = payloadHasPrompts(payload);
        writeText(new File(dir, "work.json"), payload.toString());
        updateRow(id, payload.optJSONObject("work"), Math.max(row.optInt("image_count", 0), imageCountOf(payload)), prompts ? "ready" : "pending");
        startEnrich(id);
        out.put("ok", true);
        out.put("favorited", true);
        out.put("remix_ready", prompts);
        out.put("save_state", prompts ? "ready" : "pending");
        out.put("message", prompts
            ? "已入库。咒语已齐，可以换角。原图下不下都行。"
            : "已加入本地库。先收了封面和能拿到的咒语，原图后补。");
        return out;
    }

    synchronized JSONObject importGenerated(String imageId, JSONObject comment, byte[] png) throws Exception {
        return importGeneratedPage(imageId, 0, comment, png, 1);
    }

    synchronized JSONObject importGeneratedPage(String albumId, int pageIndex, JSONObject comment, byte[] png, int total) throws Exception {
        String rawId = String.valueOf(albumId == null ? "" : albumId).trim();
        String id = normalizeId("g" + rawId);
        if (id.length() < 2) throw new IllegalArgumentException("缺少生成图 id");
        int index = Math.max(0, pageIndex);
        File dir = new File(root, id);
        if (!dir.exists()) dir.mkdirs();
        JSONObject payload = workPayload(id);
        if (payload == null) {
            payload = new JSONObject();
            payload.put("ok", true);
            payload.put("source", "phone-local");
            payload.put("generation_calls", 0);
            JSONObject work = new JSONObject();
            work.put("work_id", id);
            work.put("id", id);
            work.put("title", comment == null ? id : JsonUtil.first(comment, "title", "source_title"));
            if (work.optString("title").isEmpty()) work.put("title", "本机生成");
            work.put("creator", "phone-local");
            work.put("gallery_id", "phone-local");
            work.put("images", new JSONArray());
            work.put("image_count", 0);
            payload.put("work", work);
            payload.put("images", work.optJSONArray("images"));
        }
        JSONObject work = payload.optJSONObject("work");
        if (work == null) work = new JSONObject();
        JSONArray images = payload.optJSONArray("images");
        if (images == null) images = work.optJSONArray("images");
        if (images == null) images = new JSONArray();
        while (images.length() <= index) images.put(new JSONObject());
        JSONObject image = images.optJSONObject(index);
        if (image == null) image = new JSONObject();
        image.put("image_id", id + "_p" + index);
        image.put("id", id + "_p" + index);
        image.put("page_index", index);
        image.put("ai_json", comment == null ? new JSONObject() : comment);
        image.put("url", localUrl(id, index));
        image.put("thumbnail_url", localUrl(id, index));
        images.put(index, image);
        work.put("images", images);
        work.put("image_count", Math.max(total, images.length()));
        work.put("gallery_id", "phone-local");
        if (comment != null && work.optString("title").isEmpty()) {
            work.put("title", JsonUtil.first(comment, "title", "source_title"));
        }
        payload.put("work", work);
        payload.put("images", images);
        payload.put("source", "phone-local");
        payload.put("generation_calls", 0);
        writeText(new File(dir, "work.json"), payload.toString());
        if (png != null && png.length > 0) writeBytes(new File(dir, "p" + index + ".orig"), png);
        JSONArray indexRows = readIndex();
        int found = find(indexRows, id);
        JSONObject row = found >= 0 ? indexRows.optJSONObject(found) : new JSONObject();
        if (row == null) row = new JSONObject();
        row.put("work_id", id);
        row.put("title", work.optString("title"));
        row.put("creator", "phone-local");
        row.put("image_count", work.optInt("image_count", images.length()));
        row.put("kind", "generated");
        row.put("save_state", "ready");
        row.put("added_at", System.currentTimeMillis());
        if (found >= 0) indexRows.put(found, row);
        else {
            JSONArray next = new JSONArray();
            next.put(row);
            for (int i = 0; i < indexRows.length(); i++) next.put(indexRows.opt(i));
            indexRows = next;
        }
        writeIndex(indexRows);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("work_id", id);
        out.put("message", "生成图已入本地库，可继续换角");
        return out;
    }

    synchronized boolean canRemix(String workId) {
        String id = normalizeId(workId);
        if (id.isEmpty()) return false;
        if (DemoWorks.isDemo(id)) return true;
        if (id.startsWith("g")) return has(id);
        if (!has(id)) return false;
        if ("ready".equals(rowState(id))) return true;
        return payloadHasPrompts(workPayload(id));
    }

    static boolean payloadHasPrompts(JSONObject payload) {
        if (payload == null) return false;
        JSONArray images = payload.optJSONArray("images");
        if (images == null && payload.optJSONObject("work") != null) {
            images = payload.optJSONObject("work").optJSONArray("images");
        }
        if (images == null) return false;
        for (int i = 0; i < images.length(); i++) {
            JSONObject image = images.optJSONObject(i);
            if (image == null) continue;
            if (!JsonUtil.str(image, "prompt_text").isEmpty()) return true;
            JSONObject ai = JsonUtil.parseMaybe(image.opt("ai_json"));
            if (ai == null) ai = new JSONObject();
            JSONObject comment = JsonUtil.parseMaybe(ai.opt("Comment"));
            if (comment == null) comment = JsonUtil.parseMaybe(image.opt("metadata"));
            if (comment == null) comment = new JSONObject();
            if (!JsonUtil.str(comment, "prompt").isEmpty()) return true;
            JSONObject v4 = JsonUtil.parseMaybe(comment.opt("v4_prompt"));
            JSONObject cap = JsonUtil.parseMaybe(v4.opt("caption"));
            if (cap != null && !JsonUtil.str(cap, "base_caption").isEmpty()) return true;
            JSONArray slots = cap == null ? null : cap.optJSONArray("char_captions");
            if (slots == null) continue;
            for (int s = 0; s < slots.length(); s++) {
                JSONObject slot = slots.optJSONObject(s);
                if (slot != null && !JsonUtil.str(slot, "char_caption").isEmpty()) return true;
            }
        }
        return false;
    }

    synchronized void ensureDemo() {
        if (has(DemoWorks.WORK_ID)) return;
        try {
            JSONObject payload = DemoWorks.payload();
            JSONObject work = payload.optJSONObject("work");
            File dir = new File(root, DemoWorks.WORK_ID);
            if (!dir.exists()) dir.mkdirs();
            writeText(new File(dir, "work.json"), payload.toString());
            JSONArray images = payload.optJSONArray("images");
            int count = images == null ? 0 : images.length();
            for (int i = 0; i < count; i++) {
                writeBytes(new File(dir, "p" + i + ".orig"), DemoWorks.png(i));
            }
            JSONObject row = new JSONObject();
            row.put("work_id", DemoWorks.WORK_ID);
            row.put("title", work == null ? "内置样例" : work.optString("title"));
            row.put("creator", "phone-demo");
            row.put("image_count", count);
            row.put("kind", "demo");
            row.put("save_state", "ready");
            row.put("added_at", System.currentTimeMillis());
            JSONArray next = new JSONArray();
            next.put(row);
            JSONArray index = readIndex();
            for (int i = 0; i < index.length(); i++) next.put(index.opt(i));
            writeIndex(next);
        } catch (Exception ignored) {}
    }

    synchronized JSONObject workPayload(String workId) {
        String id = normalizeId(workId);
        File file = new File(new File(root, id), "work.json");
        if (!file.isFile()) return null;
        try {
            JSONObject payload = JsonUtil.obj(readText(file));
            overlayLocalImages(payload, id);
            payload.put("source", "phone-local");
            payload.put("local", true);
            payload.put("save_state", rowState(id));
            if (payload.optJSONObject("work") != null) {
                payload.getJSONObject("work").put("gallery_id", "phone-local");
            }
            return payload;
        } catch (Exception e) {
            return null;
        }
    }

    synchronized void overlayLocalImages(JSONObject payload, String workId) {
        if (payload == null) return;
        String id = normalizeId(workId);
        JSONObject work = payload.optJSONObject("work");
        JSONArray images = payload.optJSONArray("images");
        if (images == null && work != null) images = work.optJSONArray("images");
        if (images == null) return;
        for (int i = 0; i < images.length(); i++) {
            JSONObject image = images.optJSONObject(i);
            if (image == null) continue;
            File file = imageFile(id, i);
            if (file == null) continue;
            String url = localUrl(id, i);
            try {
                image.put("url", url);
                image.put("thumbnail_url", url);
                image.put("local", true);
            } catch (Exception ignored) {}
        }
        if (work != null) {
            try { work.put("images", images); } catch (Exception ignored) {}
        }
    }

    synchronized File imageFile(String workId, int index) {
        File dir = new File(root, normalizeId(workId));
        File orig = new File(dir, "p" + index + ".orig");
        if (orig.isFile()) return orig;
        File jpg = new File(dir, "p" + index + ".jpg");
        return jpg.isFile() ? jpg : null;
    }

    synchronized String contentType(File file) {
        if (file == null) return "application/octet-stream";
        String name = file.getName().toLowerCase();
        if (name.endsWith(".jpg")) return "image/jpeg";
        return "application/octet-stream";
    }

    synchronized byte[] readImage(File file) throws Exception {
        byte[] data = new byte[(int) file.length()];
        try (FileInputStream in = new FileInputStream(file)) {
            int n = in.read(data);
            if (n != data.length) throw new IllegalStateException("read failed");
        }
        return data;
    }

    private void startEnrich(String workId) {
        new Thread(() -> {
            try {
                enrich(workId);
            } catch (Exception error) {
                if (!canRemix(workId)) mark(workId, "partial", error.getMessage());
            }
        }, "fav-" + workId).start();
    }

    private JSONObject absorbSnapshot(String id, JSONObject snapshot, JSONObject row) throws Exception {
        JSONObject payload = stubWork(id, row);
        if (snapshot == null) return payload;
        JSONObject workIn = snapshot.optJSONObject("work");
        if (workIn != null && workIn.length() > 0) {
            payload.put("work", workIn);
            if (payload.optJSONObject("work") != null) {
                payload.getJSONObject("work").put("work_id", id);
                payload.getJSONObject("work").put("id", id);
            }
        }
        JSONArray images = snapshot.optJSONArray("images");
        if (images == null && workIn != null) images = workIn.optJSONArray("images");
        if (images != null && images.length() > 0) {
            payload.put("images", images);
            if (payload.optJSONObject("work") != null) payload.getJSONObject("work").put("images", images);
        } else if (!JsonUtil.str(snapshot, "prompt_text").isEmpty() || snapshot.opt("ai_json") != null) {
            JSONArray slot = payload.optJSONArray("images");
            JSONObject image = slot != null && slot.length() > 0 ? slot.optJSONObject(0) : new JSONObject();
            if (image == null) image = new JSONObject();
            if (!JsonUtil.str(snapshot, "prompt_text").isEmpty()) image.put("prompt_text", snapshot.optString("prompt_text"));
            if (snapshot.opt("ai_json") != null) image.put("ai_json", snapshot.opt("ai_json"));
            JSONArray next = new JSONArray().put(image);
            payload.put("images", next);
            if (payload.optJSONObject("work") != null) payload.getJSONObject("work").put("images", next);
        }
        return payload;
    }

    private boolean writeSnapshotImage(String id, JSONObject snapshot) {
        if (snapshot == null) return false;
        String raw = JsonUtil.first(snapshot, "cover_jpeg", "image_jpeg", "cover_data_url");
        if (raw.isEmpty()) return false;
        int comma = raw.indexOf(',');
        if (comma >= 0) raw = raw.substring(comma + 1);
        try {
            byte[] data = android.util.Base64.decode(raw, android.util.Base64.DEFAULT);
            if (data == null || data.length < 32 || data.length > 2500000) return false;
            writeBytes(new File(new File(root, id), "p0.jpg"), compress(data));
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    private static int imageCountOf(JSONObject payload) {
        if (payload == null) return 0;
        JSONArray images = payload.optJSONArray("images");
        if (images == null && payload.optJSONObject("work") != null) {
            images = payload.optJSONObject("work").optJSONArray("images");
        }
        return images == null ? 0 : images.length();
    }

    private JSONObject mergePayload(JSONObject existing, JSONObject incoming) {
        if (incoming == null) return existing == null ? new JSONObject() : existing;
        if (existing == null || !payloadHasPrompts(existing)) return incoming;
        if (!payloadHasPrompts(incoming)) {
            try {
                JSONObject next = new JSONObject(existing.toString());
                JSONArray more = incoming.optJSONArray("images");
                JSONArray have = next.optJSONArray("images");
                if (more != null && (have == null || more.length() > have.length())) {
                    next.put("images", more);
                    if (next.optJSONObject("work") != null) next.getJSONObject("work").put("images", more);
                }
                return next;
            } catch (Exception ignored) {
                return existing;
            }
        }
        return incoming;
    }

    private JSONObject stubWork(String id, JSONObject row) throws Exception {
        JSONObject work = new JSONObject();
        work.put("work_id", id);
        work.put("id", id);
        work.put("title", row.optString("title", id));
        work.put("creator", row.optString("creator"));
        work.put("image_count", row.optInt("image_count", 1));
        work.put("tags", row.optJSONArray("tags") == null ? new JSONArray() : row.optJSONArray("tags"));
        JSONObject cover = new JSONObject();
        cover.put("url", row.optString("cover_url"));
        cover.put("thumbnail_url", row.optString("cover_url"));
        JSONArray images = new JSONArray().put(cover);
        work.put("images", images);
        JSONObject payload = new JSONObject();
        payload.put("ok", true);
        payload.put("work", work);
        payload.put("images", images);
        payload.put("save_state", "pending");
        payload.put("generation_calls", 0);
        return payload;
    }

    private String rowState(String workId) {
        JSONArray index = readIndex();
        int found = find(index, workId);
        JSONObject row = found >= 0 ? index.optJSONObject(found) : null;
        return row == null ? "pending" : row.optString("save_state", "pending");
    }

    private void enrich(String workId) throws Exception {
        JSONObject detail = aitag.work(workId);
        synchronized (this) {
            File dir = new File(root, workId);
            if (!dir.exists()) dir.mkdirs();
            JSONObject existing = workPayload(workId);
            JSONObject merged = mergePayload(existing, detail);
            writeText(new File(dir, "work.json"), merged.toString());
            boolean prompts = payloadHasPrompts(merged);
            JSONArray images = merged.optJSONArray("images");
            updateRow(workId, merged.optJSONObject("work"), images == null ? 0 : images.length(), prompts ? "ready" : "partial");
            if (!prompts) mark(workId, "partial", "这套还没有 NovelAI 咒语，换不了角");
        }
        if (imageFile(workId, 0) != null) return;
        try {
            JSONObject payload = workPayload(workId);
            JSONArray images = payload == null ? null : payload.optJSONArray("images");
            JSONObject first = images != null && images.length() > 0 ? images.optJSONObject(0) : null;
            HttpOutbound.Result img = fetchImage(first, workId);
            if (img != null && img.body != null && img.body.length > 32) {
                writeBytes(new File(new File(root, workId), "p0.jpg"), compress(img.body));
            }
        } catch (Exception ignored) {}
    }

    private HttpOutbound.Result fetchImage(JSONObject image, String workId) throws Exception {
        String type = JsonUtil.str(image, "image_type");
        String author = JsonUtil.str(image, "author_id");
        String file = JsonUtil.str(image, "file_name");
        if (!type.isEmpty() && !author.isEmpty() && !file.isEmpty()) {
            return aitag.image(type, author, file);
        }
        return aitag.cover(workId);
    }

    private byte[] compress(byte[] data) {
        try {
            Bitmap bitmap = BitmapFactory.decodeByteArray(data, 0, data.length);
            if (bitmap == null) return data;
            int width = bitmap.getWidth();
            int height = bitmap.getHeight();
            int longEdge = Math.max(width, height);
            if (longEdge > COMPRESS_EDGE) {
                float scale = COMPRESS_EDGE / (float) longEdge;
                bitmap = Bitmap.createScaledBitmap(
                    bitmap,
                    Math.max(1, Math.round(width * scale)),
                    Math.max(1, Math.round(height * scale)),
                    true
                );
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            bitmap.compress(Bitmap.CompressFormat.JPEG, COMPRESS_QUALITY, out);
            return out.toByteArray();
        } catch (Exception e) {
            return data;
        }
    }

    private synchronized void updateRow(String workId, JSONObject work, int imageCount, String state) {
        JSONArray index = readIndex();
        int found = find(index, workId);
        if (found < 0) return;
        JSONObject row = index.optJSONObject(found);
        if (row == null) return;
        try {
            if (work != null) {
                if (!JsonUtil.str(work, "title").isEmpty()) row.put("title", work.optString("title"));
                if (!JsonUtil.str(work, "creator").isEmpty()) row.put("creator", work.optString("creator"));
                row.put("image_count", Math.max(imageCount, work.optInt("image_count", 0)));
                if (work.optJSONArray("tags") != null) row.put("tags", work.optJSONArray("tags"));
            } else if (imageCount > 0) {
                row.put("image_count", imageCount);
            }
            row.put("save_state", state);
            index.put(found, row);
            writeIndex(index);
        } catch (Exception ignored) {}
    }

    private synchronized void mark(String workId, String state) {
        mark(workId, state, "");
    }

    private synchronized void mark(String workId, String state, String error) {
        JSONArray index = readIndex();
        int found = find(index, workId);
        if (found < 0) return;
        JSONObject row = index.optJSONObject(found);
        if (row == null) return;
        try {
            row.put("save_state", state);
            if (error != null && !error.trim().isEmpty()) row.put("last_error", error);
            index.put(found, row);
            writeIndex(index);
        } catch (Exception ignored) {}
    }

    private JSONArray readIndex() {
        if (!indexFile.isFile()) return new JSONArray();
        try {
            return new JSONArray(readText(indexFile));
        } catch (Exception e) {
            return new JSONArray();
        }
    }

    private void writeIndex(JSONArray items) throws Exception {
        writeText(indexFile, items.toString());
    }

    private static int find(JSONArray index, String workId) {
        for (int i = 0; i < index.length(); i++) {
            JSONObject row = index.optJSONObject(i);
            if (row != null && workId.equals(row.optString("work_id"))) return i;
        }
        return -1;
    }

    private static String hay(JSONObject row) {
        StringBuilder blob = new StringBuilder();
        blob.append(row.optString("title")).append(' ');
        blob.append(row.optString("creator")).append(' ');
        blob.append(row.optString("work_id")).append(' ');
        blob.append(row.optString("kind")).append(' ');
        org.json.JSONArray tags = row.optJSONArray("tags");
        if (tags != null) {
            for (int i = 0; i < tags.length(); i++) blob.append(tags.opt(i)).append(' ');
        }
        return blob.toString().toLowerCase(java.util.Locale.ROOT);
    }

    private static String localUrl(String workId, int index) {
        return "/api/mobile/favorite-image/" + workId + "/" + index;
    }

    private static String normalizeId(String workId) {
        return String.valueOf(workId == null ? "" : workId).replaceAll("[^A-Za-z0-9_-]", "");
    }

    private static void writeText(File file, String text) throws Exception {
        writeBytes(file, String.valueOf(text == null ? "" : text).getBytes(StandardCharsets.UTF_8));
    }

    private static void writeBytes(File file, byte[] data) throws Exception {
        File parent = file.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(data == null ? new byte[0] : data);
        }
    }

    private static String readText(File file) throws Exception {
        return new String(readAll(file), StandardCharsets.UTF_8);
    }

    private static byte[] readAll(File file) throws Exception {
        byte[] data = new byte[(int) file.length()];
        try (FileInputStream in = new FileInputStream(file)) {
            int n = in.read(data);
            if (n != data.length) throw new IllegalStateException("read failed");
        }
        return data;
    }

    private static void deleteDir(File dir) {
        if (dir == null || !dir.exists()) return;
        File[] files = dir.listFiles();
        if (files != null) {
            for (File file : files) {
                if (file.isDirectory()) deleteDir(file);
                else file.delete();
            }
        }
        dir.delete();
    }
}
