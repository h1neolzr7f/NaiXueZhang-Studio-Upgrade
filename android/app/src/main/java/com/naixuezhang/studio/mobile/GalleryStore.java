package com.naixuezhang.studio.mobile;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

final class GalleryStore {
    private final File indexFile;

    GalleryStore(Context context) {
        File root = new File(context.getApplicationContext().getFilesDir(), "gallery");
        if (!root.exists()) root.mkdirs();
        this.indexFile = new File(root, "albums.json");
    }

    synchronized JSONObject create(String albumId, String title, JSONObject source) throws Exception {
        String id = normalize(albumId);
        if (id.isEmpty()) throw new IllegalArgumentException("缺少图库任务 id");
        JSONObject album = find(id);
        if (album == null) {
            album = new JSONObject();
            album.put("album_id", id);
            album.put("task_id", id);
            album.put("title", title == null || title.trim().isEmpty() ? "本机生成" : title);
            album.put("created_at", System.currentTimeMillis());
            album.put("image_count", 0);
            album.put("images", new JSONArray());
            JSONObject src = source == null ? new JSONObject() : source;
            album.put("source_work_id", JsonUtil.first(src, "work_id", "source_work_id"));
            album.put("source_title", JsonUtil.first(src, "title", "source_title"));
            JSONArray all = readAll();
            JSONArray next = new JSONArray();
            next.put(album);
            for (int i = 0; i < all.length() && next.length() < 200; i++) next.put(all.opt(i));
            writeAll(next);
        }
        return copy(album);
    }

    synchronized void addImage(String albumId, String imageId, String imageUrl, JSONObject meta) {
        String id = normalize(albumId);
        if (id.isEmpty() || imageId == null || imageId.trim().isEmpty()) return;
        try {
            JSONArray all = readAll();
            int found = indexOf(all, id);
            if (found < 0) return;
            JSONObject album = all.optJSONObject(found);
            if (album == null) return;
            JSONArray images = album.optJSONArray("images");
            if (images == null) images = new JSONArray();
            JSONObject image = new JSONObject();
            image.put("id", imageId);
            image.put("image_id", imageId);
            image.put("page_index", images.length());
            image.put("image_url", imageUrl);
            image.put("thumbnail_url", imageUrl);
            image.put("created_at", System.currentTimeMillis());
            if (meta != null) {
                image.put("title", JsonUtil.first(meta, "title", "source_title"));
            }
            images.put(image);
            album.put("images", images);
            album.put("image_count", images.length());
            album.put("cover_url", images.optJSONObject(0).optString("image_url"));
            all.put(found, album);
            writeAll(all);
        } catch (Exception ignored) {}
    }

    synchronized JSONObject list() {
        JSONArray stored = readAll();
        JSONArray albums = new JSONArray();
        try {
            for (int i = 0; i < stored.length(); i++) {
                JSONObject album = stored.optJSONObject(i);
                if (album == null) continue;
                JSONObject row = new JSONObject();
                row.put("album_id", album.optString("album_id"));
                row.put("task_id", album.optString("task_id"));
                row.put("title", album.optString("title"));
                row.put("image_count", album.optInt("image_count", 0));
                row.put("cover_url", album.optString("cover_url"));
                row.put("created_at", album.optLong("created_at"));
                row.put("source_work_id", album.optString("source_work_id"));
                albums.put(row);
            }
        } catch (Exception ignored) {}
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("albums", albums);
            out.put("items", albums);
            out.put("total", albums.length());
            out.put("grouped", true);
        } catch (Exception ignored) {}
        return out;
    }

    synchronized JSONObject remove(String albumId) throws Exception {
        String id = normalize(albumId);
        if (id.isEmpty()) throw new IllegalArgumentException("缺少图库任务 id");
        JSONArray all = readAll();
        JSONArray next = new JSONArray();
        JSONObject removed = null;
        for (int i = 0; i < all.length(); i++) {
            JSONObject album = all.optJSONObject(i);
            if (album != null && id.equals(album.optString("album_id"))) removed = album;
            else if (album != null) next.put(album);
        }
        if (removed == null) throw new IllegalArgumentException("图库里没有这个任务");
        writeAll(next);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("album_id", id);
        out.put("removed", removed);
        out.put("message", "已删除这组图");
        return out;
    }

    synchronized List<String> imageIds(String albumId) {
        List<String> ids = new ArrayList<String>();
        JSONObject album = find(normalize(albumId));
        if (album == null) return ids;
        JSONArray images = album.optJSONArray("images");
        if (images == null) return ids;
        for (int i = 0; i < images.length(); i++) {
            JSONObject image = images.optJSONObject(i);
            if (image == null) continue;
            String imageId = JsonUtil.first(image, "id", "image_id");
            if (!imageId.isEmpty()) ids.add(imageId);
        }
        return ids;
    }

    synchronized JSONObject get(String albumId) {
        JSONObject album = find(normalize(albumId));
        if (album == null) return null;
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("album", album);
            out.put("images", album.optJSONArray("images") == null ? new JSONArray() : album.optJSONArray("images"));
            out.put("grouped", true);
        } catch (Exception ignored) {}
        return out;
    }

    private JSONObject find(String id) {
        JSONArray all = readAll();
        int found = indexOf(all, id);
        return found < 0 ? null : all.optJSONObject(found);
    }

    private static int indexOf(JSONArray all, String id) {
        for (int i = 0; i < all.length(); i++) {
            JSONObject album = all.optJSONObject(i);
            if (album != null && id.equals(album.optString("album_id"))) return i;
        }
        return -1;
    }

    private JSONArray readAll() {
        if (!indexFile.isFile()) return new JSONArray();
        try {
            byte[] data = new byte[(int) indexFile.length()];
            try (FileInputStream in = new FileInputStream(indexFile)) {
                int n = in.read(data);
                if (n != data.length) return new JSONArray();
            }
            return new JSONArray(new String(data, StandardCharsets.UTF_8));
        } catch (Exception e) {
            return new JSONArray();
        }
    }

    private void writeAll(JSONArray items) throws Exception {
        File parent = indexFile.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        try (FileOutputStream out = new FileOutputStream(indexFile)) {
            out.write(items.toString().getBytes(StandardCharsets.UTF_8));
        }
    }

    private static JSONObject copy(JSONObject item) throws Exception {
        return new JSONObject(item.toString());
    }

    private static String normalize(String value) {
        return String.valueOf(value == null ? "" : value).replaceAll("[^A-Za-z0-9_-]", "");
    }
}
