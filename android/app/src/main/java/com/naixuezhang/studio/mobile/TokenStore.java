package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

final class TokenStore {
    private static final String PREFS = "nai_phone_secrets";
    private static final String KEY = "novelai_token";
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
}
