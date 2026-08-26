package com.naixuezhang.studio.mobile;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
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
        HttpURLConnection conn = open(url, route);
        conn.setInstanceFollowRedirects(false);
        conn.setConnectTimeout(Math.max(3000, timeoutMs));
        conn.setReadTimeout(Math.max(3000, timeoutMs));
        conn.setRequestMethod(method);
        if (headers != null) {
            for (Map.Entry<String, String> entry : headers.entrySet()) {
                conn.setRequestProperty(entry.getKey(), entry.getValue());
            }
        }
        if (body != null) {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", conn.getRequestProperty("Content-Type") == null
                ? "application/json"
                : conn.getRequestProperty("Content-Type"));
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body);
            }
        }
        int status = conn.getResponseCode();
        InputStream stream = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
        byte[] data = readBounded(stream, maxBytes);
        String type = conn.getContentType();
        conn.disconnect();
        return new Result(status, data, type);
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
