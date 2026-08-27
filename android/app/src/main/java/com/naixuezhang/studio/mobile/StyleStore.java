package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

final class StyleStore {
    private static final String PREFS = "nai_phone_custom_styles";
    private static final String KEY = "items";
    private final SharedPreferences prefs;
    private final JSONArray bundled;

    StyleStore(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        bundled = readBundled(context);
    }

    JSONObject search(String query, int limit) {
        String needle = String.valueOf(query == null ? "" : query).trim().toLowerCase(Locale.ROOT);
        int cap = Math.max(1, Math.min(limit <= 0 ? 40 : limit, 80));
        JSONArray items = new JSONArray();
        try {
            JSONArray custom = readCustom();
            for (int i = 0; i < custom.length() && items.length() < cap; i++) {
                JSONObject item = custom.optJSONObject(i);
                if (item == null) continue;
                if (!needle.isEmpty() && !hay(item).contains(needle)) continue;
                items.put(wrap(item, "custom-style:" + item.optString("id"), "我的画风"));
            }
            for (int i = 0; i < bundled.length() && items.length() < cap; i++) {
                JSONObject item = bundled.optJSONObject(i);
                if (item == null) continue;
                if (!needle.isEmpty() && !hay(item).contains(needle)) continue;
                items.put(wrap(item, "style:" + item.optString("id"), "内置画风"));
            }
        } catch (Exception ignored) {}
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("q", query == null ? "" : query);
            out.put("total", items.length());
            out.put("items", items);
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject add(JSONObject raw) throws Exception {
        String label = JsonUtil.first(raw, "label", "name");
        if (label.isEmpty()) throw new IllegalArgumentException("自定义画风要有名字");
        String tag = JsonUtil.first(raw, "tag", "style", "replace");
        if (tag.isEmpty()) throw new IllegalArgumentException("自定义画风要有标签");
        JSONObject item = new JSONObject();
        String id = JsonUtil.str(raw, "id");
        if (id.isEmpty()) id = "s" + System.currentTimeMillis();
        item.put("id", id);
        item.put("label", label);
        item.put("name", label);
        item.put("tag", tag);
        item.put("kind", "style");
        item.put("source", "phone-custom");
        JSONArray all = readCustom();
        JSONArray next = new JSONArray();
        next.put(item);
        for (int i = 0; i < all.length() && next.length() < 80; i++) {
            JSONObject old = all.optJSONObject(i);
            if (old != null && !id.equals(old.optString("id"))) next.put(old);
        }
        prefs.edit().putString(KEY, next.toString()).apply();
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("item", item);
        out.put("message", "已保存自定义画风");
        return out;
    }

    JSONObject remove(String id) throws Exception {
        String want = String.valueOf(id == null ? "" : id).trim();
        JSONArray all = readCustom();
        JSONArray next = new JSONArray();
        for (int i = 0; i < all.length(); i++) {
            JSONObject item = all.optJSONObject(i);
            if (item != null && !want.equals(item.optString("id"))) next.put(item);
        }
        prefs.edit().putString(KEY, next.toString()).apply();
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("message", "已删除画风");
        return out;
    }

    private JSONObject wrap(JSONObject item, String referenceId, String source) throws Exception {
        JSONObject out = new JSONObject();
        out.put("reference_id", referenceId);
        out.put("label", JsonUtil.first(item, "label", "name", "tag", "id"));
        out.put("source", source);
        out.put("kind", "style");
        out.put("record", item);
        return out;
    }

    private static String hay(JSONObject item) {
        return (JsonUtil.str(item, "label") + " " + JsonUtil.str(item, "name") + " "
            + JsonUtil.str(item, "tag") + " " + JsonUtil.str(item, "id")).toLowerCase(Locale.ROOT);
    }

    private JSONArray readCustom() {
        try {
            return new JSONArray(prefs.getString(KEY, "[]"));
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    private static JSONArray readBundled(Context context) {
        try (InputStream in = context.getAssets().open("data/phone_style_index.json");
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
            JSONObject raw = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
            JSONArray styles = raw.optJSONArray("styles");
            return styles == null ? new JSONArray() : styles;
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }
}
