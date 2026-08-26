package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

final class TokenStore {
    private static final String PREFS = "nai_phone_secrets";
    private static final String KEY = "novelai_token";
    private static final String DEEPSEEK_KEY = "deepseek_api_key";
    private final SharedPreferences prefs;

    TokenStore(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    synchronized String get() {
        return String.valueOf(prefs.getString(KEY, "")).trim();
    }

    synchronized boolean hasToken() {
        return !get().isEmpty();
    }

    synchronized void set(String raw) {
        String token = String.valueOf(raw == null ? "" : raw).trim();
        if (token.regionMatches(true, 0, "Bearer ", 0, 7)) {
            token = token.substring(7).trim();
        }
        prefs.edit().putString(KEY, token).apply();
    }

    synchronized void clear() {
        prefs.edit().remove(KEY).apply();
    }

    synchronized String getDeepSeek() {
        return String.valueOf(prefs.getString(DEEPSEEK_KEY, "")).trim();
    }

    synchronized boolean hasDeepSeek() {
        return !getDeepSeek().isEmpty();
    }

    synchronized void setDeepSeek(String raw) {
        String key = String.valueOf(raw == null ? "" : raw).trim();
        if (key.regionMatches(true, 0, "Bearer ", 0, 7)) {
            key = key.substring(7).trim();
        }
        prefs.edit().putString(DEEPSEEK_KEY, key).apply();
    }

    synchronized void clearDeepSeek() {
        prefs.edit().remove(DEEPSEEK_KEY).apply();
    }
}
