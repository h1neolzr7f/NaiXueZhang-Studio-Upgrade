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
            out.put("ok", true);
            out.put("items", readIndex());
            out.put("total", readIndex().length());
        } catch (Exception ignored) {}
        return out;
    }

    synchronized JSONObject works() {
        JSONArray items = new JSONArray();
        JSONArray index = readIndex();
        for (int i = 0; i < index.length(); i++) {
            JSONObject row = index.optJSONObject(i);
            if (row == null) continue;
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
                item.put("save_state", row.optString("save_state", "pending"));
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
        row.put("save_state", "pending");
        JSONArray next = new JSONArray();
        next.put(row);
        for (int i = 0; i < index.length(); i++) next.put(index.opt(i));
        writeIndex(next);
        File dir = new File(root, id);
        if (!dir.exists()) dir.mkdirs();
        writeText(new File(dir, "snapshot.json"), (snapshot == null ? new JSONObject() : snapshot).toString());
        startDownload(id);
        out.put("ok", true);
        out.put("favorited", true);
        out.put("message", "已收藏，正在把数据和图片存到本机");
        return out;
    }

    synchronized JSONObject workPayload(String workId) {
        String id = normalizeId(workId);
        File file = new File(new File(root, id), "work.json");
        if (!file.isFile()) return null;
        try {
            JSONObject payload = JsonUtil.obj(readText(file));
            overlayLocalImages(payload, id);
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

    private void startDownload(String workId) {
        new Thread(() -> {
            try {
                download(workId);
            } catch (Exception ignored) {
                mark(workId, "partial");
            }
        }, "fav-" + workId).start();
    }

    private void download(String workId) throws Exception {
        JSONObject detail = aitag.work(workId);
        JSONObject work = detail.optJSONObject("work");
        JSONArray images = detail.optJSONArray("images");
        if (images == null) images = new JSONArray();
        synchronized (this) {
            File dir = new File(root, workId);
            if (!dir.exists()) dir.mkdirs();
            writeText(new File(dir, "work.json"), detail.toString());
            updateRow(workId, work, images.length(), "saving");
        }
        int saved = 0;
        int limit = Math.min(images.length(), MAX_PAGES);
        for (int i = 0; i < limit; i++) {
            JSONObject image = images.optJSONObject(i);
            if (image == null) continue;
            try {
                HttpOutbound.Result result = fetchImage(image, workId);
                byte[] data = result.body;
                File dir = new File(root, workId);
                if (i == 0) {
                    writeBytes(new File(dir, "p0.orig"), data);
                } else {
                    writeBytes(new File(dir, "p" + i + ".jpg"), compress(data));
                }
                saved += 1;
            } catch (Exception ignored) {}
        }
        mark(workId, saved > 0 ? "ready" : "partial");
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
        JSONArray index = readIndex();
        int found = find(index, workId);
        if (found < 0) return;
        JSONObject row = index.optJSONObject(found);
        if (row == null) return;
        try {
            row.put("save_state", state);
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
