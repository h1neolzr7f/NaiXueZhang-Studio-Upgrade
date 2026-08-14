package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

final class JsonUtil {
    private JsonUtil() {}

    static JSONObject obj(String raw) {
        if (raw == null || raw.trim().isEmpty()) return new JSONObject();
        try {
            return new JSONObject(raw);
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }

    static JSONObject obj(JSONObject value) {
        return value == null ? new JSONObject() : value;
    }

    static String str(JSONObject obj, String key) {
        if (obj == null || !obj.has(key) || obj.isNull(key)) return "";
        return String.valueOf(obj.opt(key)).trim();
    }

    static String first(JSONObject obj, String... keys) {
        if (obj == null) return "";
        for (String key : keys) {
            String value = str(obj, key);
            if (!value.isEmpty() && !"null".equals(value)) return value;
        }
        return "";
    }

    static JSONArray arr(JSONObject obj, String... keys) {
        if (obj == null) return new JSONArray();
        for (String key : keys) {
            JSONArray found = obj.optJSONArray(key);
            if (found != null) return found;
        }
        return new JSONArray();
    }

    static JSONObject nested(JSONObject obj, String... keys) {
        if (obj == null) return new JSONObject();
        for (String key : keys) {
            JSONObject found = obj.optJSONObject(key);
            if (found != null) return found;
        }
        return new JSONObject();
    }

    static JSONObject parseMaybe(Object value) {
        if (value instanceof JSONObject) return (JSONObject) value;
        if (value instanceof String) return obj((String) value);
        return new JSONObject();
    }

    static String stripHtml(String value) {
        return String.valueOf(value == null ? "" : value)
            .replace("<br />", "\n")
            .replaceAll("<[^>]+>", "")
            .trim();
    }
}
