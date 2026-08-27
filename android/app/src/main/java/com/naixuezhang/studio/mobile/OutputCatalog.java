package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

final class OutputCatalog {
    private static final String PREFS = "nai_phone_outputs";
    private static final String KEY = "items";
    private final SharedPreferences prefs;

    OutputCatalog(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    synchronized void add(String id, JSONObject source) {
        if (id == null || id.trim().isEmpty()) return;
        try {
            JSONObject item = new JSONObject();
            item.put("id", id);
            item.put("image_url", "/api/mobile/output/" + id + ".png");
            item.put("created_at", System.currentTimeMillis());
            JSONObject src = source == null ? new JSONObject() : source;
            item.put("title", JsonUtil.first(src, "title", "source_title"));
            item.put("work_id", JsonUtil.first(src, "work_id", "remote_work_id"));
            item.put("thumb", JsonUtil.first(src, "thumb", "source_thumb"));
            JSONArray next = new JSONArray();
            next.put(item);
            JSONArray all = readAll();
            for (int i = 0; i < all.length() && next.length() < 80; i++) {
                JSONObject old = all.optJSONObject(i);
                if (old != null && !id.equals(old.optString("id"))) next.put(old);
            }
            prefs.edit().putString(KEY, next.toString()).apply();
        } catch (Exception ignored) {}
    }

    synchronized JSONObject list(ImageStore images) throws Exception {
        JSONArray stored = readAll();
        JSONArray items = new JSONArray();
        for (int i = 0; i < stored.length(); i++) {
            JSONObject item = stored.optJSONObject(i);
            if (item == null) continue;
            if (images != null && images.file(item.optString("id")) == null) continue;
            items.put(item);
        }
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("items", items);
        out.put("total", items.length());
        return out;
    }

    private JSONArray readAll() {
        try {
            return new JSONArray(prefs.getString(KEY, "[]"));
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }
}
