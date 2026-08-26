package com.naixuezhang.studio.mobile;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

final class CharLibrary {
    private final JSONObject presets;
    private final JSONObject ark;
    private final JSONObject aliases;
    private final CustomCharStore custom;

    CharLibrary(Context context, CustomCharStore custom) {
        presets = readAssetObject(context, "data/char_presets.json");
        ark = readAssetObject(context, "data/ark_char_library.json");
        aliases = readAssetObject(context, "data/ark_cn_aliases.json");
        this.custom = custom;
    }

    JSONObject listPresets(String gender) {
        JSONArray items = presets.optJSONArray(normalizeGender(gender, "female"));
        if (items == null) items = new JSONArray();
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("presets", items);
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject searchAll(String gender, String query, int limit) {
        String bucket = normalizeGender(gender, "female");
        String needle = String.valueOf(query == null ? "" : query).trim().toLowerCase(Locale.ROOT);
        int cap = Math.max(1, Math.min(limit <= 0 ? 24 : limit, 80));
        JSONArray items = new JSONArray();
        try {
            JSONArray customItems = custom == null ? new JSONArray() : custom.list(bucket).optJSONArray("items");
            if (customItems != null) {
                for (int i = 0; i < customItems.length() && items.length() < cap; i++) {
                    JSONObject item = customItems.optJSONObject(i);
                    if (item == null) continue;
                    if (!needle.isEmpty() && !hay(item).contains(needle)) continue;
                    items.put(wrap(item, "custom:" + bucket + ":" + item.optString("id"), "我的角色"));
                }
            }
            JSONArray presets = this.presets.optJSONArray(bucket);
            if (presets != null) {
                for (int i = 0; i < presets.length() && items.length() < cap; i++) {
                    JSONObject item = presets.optJSONObject(i);
                    if (item == null) continue;
                    if (!needle.isEmpty() && !hay(item).contains(needle)) continue;
                    items.put(wrap(item, "preset:" + bucket + ":" + item.optString("id"), "常用角色"));
                }
            }
            JSONArray arkItems = searchArk(bucket, query, cap).optJSONArray("items");
            if (arkItems != null) {
                for (int i = 0; i < arkItems.length() && items.length() < cap; i++) {
                    JSONObject item = arkItems.optJSONObject(i);
                    if (item == null) continue;
                    items.put(wrap(item, "ark:" + bucket + ":" + item.optString("id"), "内置 D 站角色库"));
                }
            }
        } catch (Exception ignored) {}
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("q", query == null ? "" : query);
            out.put("gender", bucket);
            out.put("total", items.length());
            out.put("items", items);
        } catch (Exception ignored) {}
        return out;
    }

    private JSONObject wrap(JSONObject item, String referenceId, String source) throws Exception {
        JSONObject out = new JSONObject();
        out.put("reference_id", referenceId);
        out.put("label", JsonUtil.first(item, "label", "name", "id"));
        out.put("source", source);
        out.put("record", item);
        return out;
    }

    JSONObject searchArk(String gender, String query, int limit) {
        String bucket = normalizeGender(gender, "female");
        JSONArray pool = ark.optJSONArray(bucket);
        if (pool == null) pool = new JSONArray();
        String needle = String.valueOf(query == null ? "" : query).trim().toLowerCase(Locale.ROOT);
        int cap = Math.max(1, Math.min(limit <= 0 ? 20 : limit, 200));
        JSONArray items = new JSONArray();
        for (int i = 0; i < pool.length() && items.length() < cap; i++) {
            JSONObject item = pool.optJSONObject(i);
            if (item == null) continue;
            if (needle.isEmpty() || hay(item).contains(needle)) items.put(item);
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("q", query == null ? "" : query);
            out.put("gender", bucket);
            out.put("total", items.length());
            out.put("items", items);
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject resolve(String referenceId) {
        String[] parts = String.valueOf(referenceId == null ? "" : referenceId).split(":", 3);
        if (parts.length != 3) return null;
        String kind = parts[0];
        String gender = normalizeGender(parts[1], "");
        String id = parts[2];
        if (gender.isEmpty() || id.isEmpty()) return null;
        JSONArray pool;
        if ("custom".equals(kind) && custom != null) {
            return custom.get(gender, id);
        }
        if ("preset".equals(kind)) {
            pool = presets.optJSONArray(gender);
        } else if ("ark".equals(kind)) {
            pool = ark.optJSONArray(gender);
        } else {
            return null;
        }
        if (pool == null) return null;
        for (int i = 0; i < pool.length(); i++) {
            JSONObject item = pool.optJSONObject(i);
            if (item != null && id.equals(JsonUtil.str(item, "id"))) return item;
        }
        return null;
    }

    private String hay(JSONObject item) {
        List<String> bits = new ArrayList<>();
        bits.add(JsonUtil.str(item, "label"));
        bits.add(JsonUtil.str(item, "tag"));
        bits.add(JsonUtil.str(item, "id"));
        String tag = JsonUtil.str(item, "tag");
        if (tag.endsWith("_(arknights)")) bits.add(tag.substring(0, tag.length() - "_(arknights)".length()));
        JSONArray identity = item.optJSONArray("identity");
        if (identity != null) {
            for (int i = 0; i < identity.length(); i++) bits.add(String.valueOf(identity.opt(i)));
        }
        JSONArray extra = aliases.optJSONArray(tag);
        if (extra != null) {
            for (int i = 0; i < extra.length(); i++) bits.add(String.valueOf(extra.opt(i)));
        }
        return String.join(" ", bits).toLowerCase(Locale.ROOT);
    }

    private static String normalizeGender(String gender, String fallback) {
        String value = String.valueOf(gender == null ? "" : gender).trim().toLowerCase(Locale.ROOT);
        if ("male".equals(value) || "female".equals(value)) return value;
        return fallback;
    }

    private static JSONObject readAssetObject(Context context, String name) {
        try (InputStream in = context.getAssets().open(name);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
            return new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }
}
