package com.naixuezhang.studio.mobile;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Map;

final class HttpOutbound {
    static final class Result {
        final int status;
        final byte[] body;
        final String contentType;

        Result(int status, byte[] body, String contentType) {
            this.status = status;
            this.body = body == null ? new byte[0] : body;
            this.contentType = contentType == null ? "application/octet-stream" : contentType;
        }

        String text() {
            return new String(body, StandardCharsets.UTF_8);
        }
    }

    static final class Route {
        static final int DIRECT = 0;
        static final int SYSTEM = 1;
        static final int CUSTOM = 2;
        final int kind;
        final Proxy proxy;

        private Route(int kind, Proxy proxy) {
            this.kind = kind;
            this.proxy = proxy;
        }

        static Route direct() {
            return new Route(DIRECT, Proxy.NO_PROXY);
        }

        static Route system() {
            return new Route(SYSTEM, null);
        }

        static Route custom(Proxy proxy) {
            return new Route(CUSTOM, proxy == null ? Proxy.NO_PROXY : proxy);
        }

        String label() {
            if (kind == DIRECT) return "direct";
            if (kind == SYSTEM) return "system";
            if (proxy == null || proxy == Proxy.NO_PROXY) return "custom";
            return "custom:" + proxy.address();
        }
    }

    private HttpOutbound() {}

    static Result get(String url, Map<String, String> headers, int timeoutMs, int maxBytes) throws Exception {
        return execute("GET", url, headers, null, timeoutMs, maxBytes, Route.system());
    }

    static Result get(String url, Map<String, String> headers, int timeoutMs, int maxBytes, Route route) throws Exception {
        return execute("GET", url, headers, null, timeoutMs, maxBytes, route);
    }

    static Result postJson(String url, Map<String, String> headers, String json, int timeoutMs, int maxBytes) throws Exception {
        return execute("POST", url, headers, json == null ? new byte[0] : json.getBytes(StandardCharsets.UTF_8), timeoutMs, maxBytes, Route.system());
    }

    static Result postJson(String url, Map<String, String> headers, String json, int timeoutMs, int maxBytes, Route route) throws Exception {
        return execute("POST", url, headers, json == null ? new byte[0] : json.getBytes(StandardCharsets.UTF_8), timeoutMs, maxBytes, route);
    }

    private static Result execute(
        String method,
        String url,
        Map<String, String> headers,
        byte[] body,
        int timeoutMs,
        int maxBytes,
        Route route
    ) throws Exception {
        Exception last = null;
        int attempts = "GET".equalsIgnoreCase(method) ? 2 : 1;
        for (int attempt = 0; attempt < attempts; attempt++) {
            try {
                return executeOnce(method, url, headers, body, timeoutMs, maxBytes, route);
            } catch (Exception error) {
                last = error;
                if (attempt + 1 < attempts && isTransport(error)) {
                    try {
                        Thread.sleep(350);
                    } catch (InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                        throw wrapTransport(error);
                    }
                    continue;
                }
                throw wrapTransport(error);
            }
        }
        throw wrapTransport(last);
    }

    private static Result executeOnce(
        String method,
        String url,
        Map<String, String> headers,
        byte[] body,
        int timeoutMs,
        int maxBytes,
        Route route
    ) throws Exception {
        String current = url;
        byte[] payload = body;
        String verb = method;
        for (int hop = 0; hop < 6; hop++) {
            HttpURLConnection conn = open(current, route);
            try {
                conn.setInstanceFollowRedirects(false);
                conn.setConnectTimeout(Math.min(15000, Math.max(4000, timeoutMs)));
                conn.setReadTimeout(Math.max(8000, timeoutMs));
                conn.setRequestMethod(verb);
                conn.setRequestProperty("Connection", "close");
                if (headers != null) {
                    for (Map.Entry<String, String> entry : headers.entrySet()) {
                        if (entry.getKey() != null && entry.getValue() != null) {
                            conn.setRequestProperty(entry.getKey(), entry.getValue());
                        }
                    }
                }
                attachCookies(conn, current, headers);
                if (payload != null && ("POST".equals(verb) || "PUT".equals(verb))) {
                    conn.setDoOutput(true);
                    if (conn.getRequestProperty("Content-Type") == null) {
                        conn.setRequestProperty("Content-Type", "application/json");
                    }
                    try (OutputStream out = conn.getOutputStream()) {
                        out.write(payload);
                    }
                }
                int status = conn.getResponseCode();
                if (status >= 300 && status < 400) {
                    String location = conn.getHeaderField("Location");
                    String next = resolveSafeRedirect(current, location);
                    if (next == null) {
                        return new Result(status, new byte[0], "text/plain");
                    }
                    current = next;
                    if (status == 303 || ((status == 301 || status == 302) && "POST".equals(verb))) {
                        verb = "GET";
                        payload = null;
                    }
                    continue;
                }
                InputStream stream = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
                byte[] data = readBounded(stream, maxBytes);
                String type = conn.getContentType();
                return new Result(status, data, type);
            } finally {
                try {
                    conn.disconnect();
                } catch (Exception ignored) {}
            }
        }
        throw new IllegalStateException("too many redirects");
    }

    static boolean isTransport(Throwable error) {
        if (error instanceof java.net.SocketException || error instanceof java.net.SocketTimeoutException) {
            return true;
        }
        String raw = error == null ? "" : String.valueOf(error.getMessage()).toLowerCase(Locale.ROOT);
        return raw.contains("connection closed")
            || raw.contains("connection reset")
            || raw.contains("broken pipe")
            || raw.contains("unexpected end")
            || raw.contains("failed to connect")
            || raw.contains("timeout")
            || raw.contains("timed out");
    }

    static Exception wrapTransport(Exception error) {
        if (error == null) return new IllegalStateException("网络中断");
        if (!isTransport(error)) return error;
        return new IllegalStateException("网络中断，再试一次", error);
    }

    private static void attachCookies(HttpURLConnection conn, String url, Map<String, String> headers) {
        if (headers != null && headers.containsKey("Cookie")) return;
        try {
            String cookie = android.webkit.CookieManager.getInstance().getCookie(url);
            if (cookie != null && !cookie.trim().isEmpty()) {
                conn.setRequestProperty("Cookie", cookie);
            }
        } catch (Throwable ignored) {}
    }

    static String resolveSafeRedirect(String current, String location) {
        if (location == null || location.trim().isEmpty()) return null;
        try {
            URL next = new URL(new URL(current), location.trim());
            String host = next.getHost() == null ? "" : next.getHost().toLowerCase(Locale.ROOT);
            if ("www.aitag.win".equals(host)) host = "aitag.win";
            boolean allowed = "aitag.win".equals(host) || "ai-img.10118899.xyz".equals(host);
            if (!allowed) return null;
            String protocol = next.getProtocol() == null ? "" : next.getProtocol().toLowerCase(Locale.ROOT);
            if ("http".equals(protocol)) {
                return new URL("https", host, next.getPort(), next.getFile()).toString();
            }
            if (!"https".equals(protocol)) return null;
            if ("www.aitag.win".equalsIgnoreCase(next.getHost())) {
                return new URL("https", "aitag.win", next.getPort(), next.getFile()).toString();
            }
            return next.toString();
        } catch (Exception e) {
            return null;
        }
    }

    private static HttpURLConnection open(String url, Route route) throws Exception {
        URL parsed = new URL(url);
        if (route == null || route.kind == Route.SYSTEM) {
            return (HttpURLConnection) parsed.openConnection();
        }
        if (route.kind == Route.DIRECT) {
            return (HttpURLConnection) parsed.openConnection(Proxy.NO_PROXY);
        }
        return (HttpURLConnection) parsed.openConnection(route.proxy == null ? Proxy.NO_PROXY : route.proxy);
    }

    static byte[] readBounded(InputStream stream, int maxBytes) throws Exception {
        if (stream == null) return new byte[0];
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        int total = 0;
        while ((n = stream.read(buf)) >= 0) {
            total += n;
            if (total > maxBytes) throw new IllegalStateException("response exceeded limit");
            out.write(buf, 0, n);
        }
        return out.toByteArray();
    }
}
