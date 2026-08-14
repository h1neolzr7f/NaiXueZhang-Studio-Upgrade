package com.naixuezhang.studio.mobile;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

final class LocalHttpServer {
    interface Handler {
        Response handle(Request request) throws Exception;
    }

    static final class Request {
        final String method;
        final String path;
        final Map<String, String> query;
        final Map<String, String> headers;
        final byte[] body;

        Request(String method, String path, Map<String, String> query, Map<String, String> headers, byte[] body) {
            this.method = method;
            this.path = path;
            this.query = query;
            this.headers = headers;
            this.body = body == null ? new byte[0] : body;
        }

        String text() {
            return new String(body, StandardCharsets.UTF_8);
        }

        String query(String key) {
            String value = query.get(key);
            return value == null ? "" : value;
        }
    }

    static final class Response {
        final int status;
        final String contentType;
        final byte[] body;

        Response(int status, String contentType, byte[] body) {
            this.status = status;
            this.contentType = contentType;
            this.body = body == null ? new byte[0] : body;
        }

        static Response json(int status, String json) {
            return new Response(status, "application/json; charset=utf-8", json.getBytes(StandardCharsets.UTF_8));
        }

        static Response text(int status, String text) {
            return new Response(status, "text/plain; charset=utf-8", text.getBytes(StandardCharsets.UTF_8));
        }
    }

    private final Handler handler;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private ServerSocket server;
    private ExecutorService pool;
    private int port;

    LocalHttpServer(Handler handler) {
        this.handler = handler;
    }

    synchronized int start(int preferredPort) throws IOException {
        if (running.get()) return port;
        try {
            server = new ServerSocket(preferredPort, 32, InetAddress.getByName("127.0.0.1"));
        } catch (IOException bindError) {
            server = new ServerSocket(0, 32, InetAddress.getByName("127.0.0.1"));
        }
        port = server.getLocalPort();
        pool = Executors.newCachedThreadPool();
        running.set(true);
        Thread accept = new Thread(this::acceptLoop, "nai-local-http");
        accept.setDaemon(true);
        accept.start();
        return port;
    }

    int getPort() {
        return port;
    }

    private void acceptLoop() {
        while (running.get()) {
            try {
                Socket socket = server.accept();
                pool.execute(() -> handleSocket(socket));
            } catch (Exception ignored) {
                if (!running.get()) return;
            }
        }
    }

    private void handleSocket(Socket socket) {
        try (Socket ignored = socket;
             InputStream raw = new BufferedInputStream(socket.getInputStream());
             OutputStream out = socket.getOutputStream()) {
            Request request = readRequest(raw);
            Response response;
            try {
                response = handler.handle(request);
            } catch (Exception error) {
                String message = error.getMessage() == null ? "internal error" : error.getMessage();
                response = Response.json(500, "{\"ok\":false,\"detail\":" + jsonString(message) + "}");
            }
            writeResponse(out, response);
        } catch (Exception ignored) {
        }
    }

    private Request readRequest(InputStream in) throws Exception {
        String first = readLine(in);
        if (first == null || first.isEmpty()) throw new IOException("empty request");
        String[] parts = first.split(" ");
        if (parts.length < 2) throw new IOException("bad request line");
        String method = parts[0].toUpperCase(Locale.ROOT);
        String target = parts[1];
        String path = target;
        Map<String, String> query = new HashMap<>();
        int q = target.indexOf('?');
        if (q >= 0) {
            path = target.substring(0, q);
            query.putAll(parseQuery(target.substring(q + 1)));
        }
        Map<String, String> headers = new HashMap<>();
        while (true) {
            String line = readLine(in);
            if (line == null || line.isEmpty()) break;
            int colon = line.indexOf(':');
            if (colon > 0) {
                headers.put(line.substring(0, colon).trim().toLowerCase(Locale.ROOT), line.substring(colon + 1).trim());
            }
        }
        int length = 0;
        try {
            length = Integer.parseInt(headers.getOrDefault("content-length", "0"));
        } catch (Exception ignored) {}
        if (length < 0 || length > 8 * 1024 * 1024) throw new IOException("body too large");
        byte[] body = new byte[length];
        int read = 0;
        while (read < length) {
            int n = in.read(body, read, length - read);
            if (n < 0) break;
            read += n;
        }
        return new Request(method, path, query, headers, body);
    }

    private void writeResponse(OutputStream out, Response response) throws IOException {
        String reason = response.status == 200 ? "OK" : (response.status == 404 ? "Not Found" : "Error");
        String header = "HTTP/1.1 " + response.status + " " + reason + "\r\n"
            + "Content-Type: " + response.contentType + "\r\n"
            + "Content-Length: " + response.body.length + "\r\n"
            + "Cache-Control: no-store\r\n"
            + "Connection: close\r\n\r\n";
        out.write(header.getBytes(StandardCharsets.US_ASCII));
        out.write(response.body);
        out.flush();
    }

    private static String readLine(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int prev = 0;
        while (true) {
            int ch = in.read();
            if (ch < 0) break;
            if (ch == '\n') break;
            if (ch != '\r') out.write(ch);
            prev = ch;
            if (out.size() > 16 * 1024) throw new IOException("header too long");
        }
        if (out.size() == 0 && prev == 0) return null;
        return out.toString("UTF-8");
    }

    static Map<String, String> parseQuery(String raw) {
        if (raw == null || raw.isEmpty()) return Collections.emptyMap();
        Map<String, String> out = new HashMap<>();
        for (String part : raw.split("&")) {
            int eq = part.indexOf('=');
            String key = eq >= 0 ? part.substring(0, eq) : part;
            String value = eq >= 0 ? part.substring(eq + 1) : "";
            out.put(decode(key), decode(value));
        }
        return out;
    }

    static String decode(String value) {
        try {
            return URLDecoder.decode(value, "UTF-8");
        } catch (Exception e) {
            return value;
        }
    }

    static String jsonString(String value) {
        return "\"" + String.valueOf(value == null ? "" : value)
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "") + "\"";
    }
}
