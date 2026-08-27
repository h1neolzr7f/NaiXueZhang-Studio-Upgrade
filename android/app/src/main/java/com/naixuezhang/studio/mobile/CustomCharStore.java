package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Locale;

final class CustomCharStore {
    private static final String PREFS = "nai_phone_custom_chars";
    private static final String KEY = "items";
    private final SharedPreferences prefs;

    CustomCharStore(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    synchronized JSONObject list(String gender) {
        String bucket = normalizeGender(gender);
        JSONArray all = readAll();
        JSONArray items = new JSONArray();
        for (int i = 0; i < all.length(); i++) {
            JSONObject item = all.optJSONObject(i);
            if (item == null) continue;
            if (bucket.isEmpty() || bucket.equals(item.optString("gender"))) items.put(item);
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("items", items);
            out.put("total", items.length());
        } catch (Exception ignored) {}
        return out;
    }

    synchronized JSONObject add(JSONObject raw) throws Exception {
        String label = JsonUtil.str(raw, "label");
        if (label.isEmpty()) label = JsonUtil.str(raw, "name");
        if (label.isEmpty()) throw new IllegalArgumentException("OC 要有名字");
        String gender = normalizeGender(JsonUtil.str(raw, "gender"));
        if (gender.isEmpty()) gender = "female";
        JSONObject item = new JSONObject();
        String id = JsonUtil.str(raw, "id");
        if (id.isEmpty()) id = "c" + System.currentTimeMillis();
        item.put("id", id);
        item.put("label", label);
        item.put("name", label);
        item.put("gender", gender);
        item.put("kind", "oc");
        item.put("oc_mode", raw.optBoolean("oc_mode", !JsonUtil.str(raw, "char_caption").isEmpty()));
        item.put("source", "phone-custom");
        item.put("tag", JsonUtil.first(raw, "tag", "trigger"));
        item.put("char_caption", JsonUtil.str(raw, "char_caption"));
        item.put("clothing", JsonUtil.str(raw, "clothing"));
        item.put("extra", JsonUtil.first(raw, "extra", "extra_tags"));
        item.put("remove", JsonUtil.first(raw, "remove", "remove_tags"));
        item.put("identity", raw.has("identity") ? raw.opt("identity") : new JSONArray().put(label));
        item.put("appearance", raw.has("appearance") ? raw.opt("appearance") : new JSONArray());
        item.put("body", raw.has("body") ? raw.opt("body") : new JSONArray());
        if (item.optBoolean("oc_mode") && JsonUtil.str(item, "char_caption").isEmpty()) {
            throw new IllegalArgumentException("群友 OC 请填写整段角色咒语");
        }
        JSONArray all = readAll();
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
        out.put("message", "已保存 OC");
        return out;
    }

    synchronized JSONObject remove(String id) throws Exception {
        String want = String.valueOf(id == null ? "" : id).trim();
        JSONArray all = readAll();
        JSONArray next = new JSONArray();
        for (int i = 0; i < all.length(); i++) {
            JSONObject item = all.optJSONObject(i);
            if (item != null && !want.equals(item.optString("id"))) next.put(item);
        }
        prefs.edit().putString(KEY, next.toString()).apply();
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("message", "已删除");
        return out;
    }

    synchronized JSONObject get(String gender, String id) {
        String want = String.valueOf(id == null ? "" : id).trim();
        String bucket = normalizeGender(gender);
        JSONArray all = readAll();
        for (int i = 0; i < all.length(); i++) {
            JSONObject item = all.optJSONObject(i);
            if (item == null) continue;
            if (!want.equals(item.optString("id"))) continue;
            if (bucket.isEmpty() || bucket.equals(item.optString("gender"))) return item;
        }
        return null;
    }

    private JSONArray readAll() {
        try {
            return new JSONArray(prefs.getString(KEY, "[]"));
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    private static String normalizeGender(String gender) {
        String value = String.valueOf(gender == null ? "" : gender).trim().toLowerCase(Locale.ROOT);
        if ("male".equals(value) || "female".equals(value)) return value;
        return "";
    }
}
