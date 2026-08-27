package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.Socket;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

final class TokenStore {
    private static final String PREFS = "nai_phone_secrets";
    private static final String KEY = "novelai_token";
    private static final String DEEPSEEK_KEY = "deepseek_api_key";
    private static final String PROXY = "http_proxy";
    private static final String ONLINE_PROXY = "online_use_proxy";
    private static final String NAI_PROXY = "nai_use_proxy";
    private final SharedPreferences prefs;
    private final Set<String> busy = new LinkedHashSet<String>();

    TokenStore(Context context) {
        prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    synchronized String get() {
        List<String> tokens = list();
        return tokens.isEmpty() ? "" : tokens.get(0);
    }

    synchronized List<String> list() {
        return parseTokens(prefs.getString(KEY, ""));
    }

    synchronized int count() {
        return list().size();
    }

    synchronized int concurrency() {
        return Math.max(0, count());
    }

    synchronized boolean hasToken() {
        return count() > 0;
    }

    synchronized void set(String raw) {
        List<String> tokens = parseTokens(raw);
        prefs.edit().putString(KEY, String.join("\n", tokens)).apply();
    }

    synchronized void clear() {
        prefs.edit().remove(KEY).apply();
        synchronized (busy) {
            busy.clear();
            busy.notifyAll();
        }
    }

    String lease(long timeoutMs) {
        long deadline = System.currentTimeMillis() + Math.max(1000, timeoutMs);
        while (System.currentTimeMillis() < deadline) {
            List<String> tokens = list();
            if (tokens.isEmpty()) return "";
            synchronized (busy) {
                for (String token : tokens) {
                    if (busy.add(token)) return token;
                }
                try {
                    busy.wait(200);
                } catch (InterruptedException ignored) {
                    Thread.currentThread().interrupt();
                    String fallback = tokens.get(0);
                    busy.add(fallback);
                    return fallback;
                }
            }
        }
        List<String> tokens = list();
        if (tokens.isEmpty()) return "";
        synchronized (busy) {
            String fallback = tokens.get(0);
            busy.add(fallback);
            return fallback;
        }
    }

    void release(String token) {
        if (token == null || token.isEmpty()) return;
        synchronized (busy) {
            busy.remove(token);
            busy.notifyAll();
        }
    }

    synchronized org.json.JSONObject tokenStatus() {
        org.json.JSONObject out = new org.json.JSONObject();
        try {
            int n = count();
            out.put("ok", n > 0);
            out.put("has_token", n > 0);
            out.put("token_count", n);
            out.put("enabled_count", n);
            out.put("concurrency", n);
            out.put("slots", n);
            out.put("message", n <= 0
                ? "NAI token is not configured"
                : ("已配置 " + n + " 个 Token，可 " + n + " 路并发"));
        } catch (Exception ignored) {}
        return out;
    }

    static List<String> parseTokens(String raw) {
        String text = String.valueOf(raw == null ? "" : raw).replace('\r', '\n').replace(',', '\n');
        List<String> out = new ArrayList<String>();
        Set<String> seen = new LinkedHashSet<String>();
        for (String line : text.split("\n")) {
            String token = line.trim();
            if (token.regionMatches(true, 0, "Bearer ", 0, 7)) token = token.substring(7).trim();
            if (token.isEmpty() || token.startsWith("#")) continue;
            if (seen.add(token)) out.add(token);
        }
        return out;
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
        List<HttpOutbound.Route> routes = onlineCandidates();
        return routes.isEmpty() ? HttpOutbound.Route.direct() : routes.get(0);
    }

    synchronized HttpOutbound.Route routeNai() {
        if (!naiUseProxy()) return HttpOutbound.Route.direct();
        return customOrSystem();
    }

    synchronized List<HttpOutbound.Route> onlineCandidates() {
        List<HttpOutbound.Route> out = new ArrayList<HttpOutbound.Route>();
        Set<String> seen = new LinkedHashSet<String>();
        Proxy custom = parseProxy(getProxy());
        Proxy detected = detectLocalProxy();
        if (onlineUseProxy()) {
            addRoute(out, seen, custom != null ? HttpOutbound.Route.custom(custom) : null);
            addRoute(out, seen, detected != null ? HttpOutbound.Route.custom(detected) : null);
            addRoute(out, seen, HttpOutbound.Route.system());
            addRoute(out, seen, HttpOutbound.Route.direct());
        } else {
            addRoute(out, seen, HttpOutbound.Route.direct());
            addRoute(out, seen, custom != null ? HttpOutbound.Route.custom(custom) : null);
            addRoute(out, seen, detected != null ? HttpOutbound.Route.custom(detected) : null);
        }
        return out;
    }

    synchronized org.json.JSONObject networkStatus() {
        org.json.JSONObject out = new org.json.JSONObject();
        try {
            Proxy detected = detectLocalProxy();
            String detectedText = "";
            if (detected != null && detected.address() instanceof InetSocketAddress) {
                InetSocketAddress address = (InetSocketAddress) detected.address();
                detectedText = (detected.type() == Proxy.Type.SOCKS ? "socks5://" : "http://")
                    + address.getHostString() + ":" + address.getPort();
            }
            out.put("ok", true);
            out.put("proxy", getProxy());
            out.put("has_proxy", !getProxy().isEmpty());
            out.put("detected_proxy", detectedText);
            out.put("online_use_proxy", onlineUseProxy());
            out.put("nai_use_proxy", naiUseProxy());
            out.put("message", "搜图走代理，出图默认直连");
        } catch (Exception ignored) {}
        return out;
    }

    private HttpOutbound.Route customOrSystem() {
        Proxy proxy = parseProxy(getProxy());
        if (proxy != null) return HttpOutbound.Route.custom(proxy);
        Proxy detected = detectLocalProxy();
        if (detected != null) return HttpOutbound.Route.custom(detected);
        return HttpOutbound.Route.system();
    }

    private static void addRoute(List<HttpOutbound.Route> out, Set<String> seen, HttpOutbound.Route route) {
        if (route == null) return;
        String key = route.label();
        if (seen.add(key)) out.add(route);
    }

    private static volatile Proxy detectedProxy;
    private static volatile long detectedAt;

    static Proxy detectLocalProxy() {
        long now = System.currentTimeMillis();
        if (now - detectedAt < 15000) return detectedProxy;
        int[] httpPorts = {7890, 7897, 10809, 6152, 9191, 2080, 20171, 12334, 10808, 8118, 8888};
        for (int port : httpPorts) {
            if (canConnect("127.0.0.1", port, 220)) {
                detectedProxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress("127.0.0.1", port));
                detectedAt = now;
                return detectedProxy;
            }
        }
        int[] socksPorts = {7891, 1080};
        for (int port : socksPorts) {
            if (canConnect("127.0.0.1", port, 220)) {
                detectedProxy = new Proxy(Proxy.Type.SOCKS, new InetSocketAddress("127.0.0.1", port));
                detectedAt = now;
                return detectedProxy;
            }
        }
        detectedProxy = null;
        detectedAt = now;
        return null;
    }

    static boolean canConnect(String host, int port, int timeoutMs) {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), Math.max(80, timeoutMs));
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static Proxy parseProxy(String raw) {
        String value = String.valueOf(raw == null ? "" : raw).trim();
        if (value.isEmpty()) return null;
        value = value.replace('：', ':').replace(" ", "");
        if (value.matches("^[0-9]{2,5}$")) value = "127.0.0.1:" + value;
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
