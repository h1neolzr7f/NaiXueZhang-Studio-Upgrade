package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.Locale;

final class TokenStore {
    private static final String PREFS = "nai_phone_secrets";
    private static final String KEY = "novelai_token";
    private static final String DEEPSEEK_KEY = "deepseek_api_key";
    private static final String PROXY = "http_proxy";
    private static final String ONLINE_PROXY = "online_use_proxy";
    private static final String NAI_PROXY = "nai_use_proxy";
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

    synchronized String getProxy() {
        return String.valueOf(prefs.getString(PROXY, "")).trim();
    }

    synchronized boolean onlineUseProxy() {
        return prefs.getBoolean(ONLINE_PROXY, true);
    }

    synchronized boolean naiUseProxy() {
        return prefs.getBoolean(NAI_PROXY, false);
    }

    synchronized void setNetwork(String proxy, boolean onlineUseProxy, boolean naiUseProxy) {
        String value = String.valueOf(proxy == null ? "" : proxy).trim();
        if (!value.isEmpty() && parseProxy(value) == null) {
            throw new IllegalArgumentException("代理只允许本机或局域网，例如 http://127.0.0.1:7890");
        }
        prefs.edit()
            .putString(PROXY, value)
            .putBoolean(ONLINE_PROXY, onlineUseProxy)
            .putBoolean(NAI_PROXY, naiUseProxy)
            .apply();
    }

    synchronized HttpOutbound.Route routeOnline() {
        if (!onlineUseProxy()) return HttpOutbound.Route.direct();
        return customOrSystem();
    }

    synchronized HttpOutbound.Route routeNai() {
        if (!naiUseProxy()) return HttpOutbound.Route.direct();
        return customOrSystem();
    }

    synchronized org.json.JSONObject networkStatus() {
        org.json.JSONObject out = new org.json.JSONObject();
        try {
            out.put("ok", true);
            out.put("proxy", getProxy());
            out.put("has_proxy", !getProxy().isEmpty());
            out.put("online_use_proxy", onlineUseProxy());
            out.put("nai_use_proxy", naiUseProxy());
            out.put("message", "搜图走代理，出图默认直连");
        } catch (Exception ignored) {}
        return out;
    }

    private HttpOutbound.Route customOrSystem() {
        Proxy proxy = parseProxy(getProxy());
        if (proxy != null) return HttpOutbound.Route.custom(proxy);
        return HttpOutbound.Route.system();
    }

    static Proxy parseProxy(String raw) {
        String value = String.valueOf(raw == null ? "" : raw).trim();
        if (value.isEmpty()) return null;
        value = value.replaceFirst("(?i)^socks5h://", "socks5://");
        boolean socks = value.toLowerCase(Locale.ROOT).startsWith("socks5://") || value.toLowerCase(Locale.ROOT).startsWith("socks://");
        value = value.replaceFirst("(?i)^(https?|socks5|socks)://", "");
        int slash = value.indexOf('/');
        if (slash >= 0) value = value.substring(0, slash);
        int colon = value.lastIndexOf(':');
        if (colon <= 0 || colon == value.length() - 1) return null;
        String host = value.substring(0, colon).trim();
        if (host.startsWith("[") && host.endsWith("]")) host = host.substring(1, host.length() - 1);
        int port;
        try {
            port = Integer.parseInt(value.substring(colon + 1).trim());
        } catch (Exception e) {
            return null;
        }
        if (port <= 0 || port > 65535 || !isPrivateHost(host)) return null;
        return new Proxy(socks ? Proxy.Type.SOCKS : Proxy.Type.HTTP, new InetSocketAddress(host, port));
    }

    private static boolean isPrivateHost(String host) {
        String value = String.valueOf(host == null ? "" : host).trim().toLowerCase(Locale.ROOT);
        if (value.isEmpty()) return false;
        if ("localhost".equals(value) || "127.0.0.1".equals(value) || "::1".equals(value)) return true;
        if (value.startsWith("10.")) return true;
        if (value.startsWith("192.168.")) return true;
        if (value.startsWith("172.")) {
            String[] parts = value.split("\\.");
            if (parts.length >= 2) {
                try {
                    int second = Integer.parseInt(parts[1]);
                    return second >= 16 && second <= 31;
                } catch (Exception ignored) {
                    return false;
                }
            }
        }
        return false;
    }
}
