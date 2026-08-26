package com.naixuezhang.studio.mobile;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.Locale;

final class LocalStudioServer implements LocalHttpServer.Handler {
    private final Context context;
    private final TokenStore tokens;
    private final CustomCharStore customChars;
    private final CharLibrary library;
    private final AitagGateway aitag;
    private final FavoriteStore favorites;
    private final DeepSeekClient deepseek;
    private final JobStore jobs;
    private final ImageStore images;
    private final PipelineStore pipeline;
    private final OutputCatalog outputs;
    private final LocalHttpServer http;
    private int port;

    LocalStudioServer(Context context) {
        this.context = context.getApplicationContext();
        this.tokens = new TokenStore(this.context);
        this.customChars = new CustomCharStore(this.context);
        this.library = new CharLibrary(this.context, this.customChars);
        this.aitag = new AitagGateway(this.tokens);
        this.favorites = new FavoriteStore(this.context, this.aitag);
        this.deepseek = new DeepSeekClient(this.tokens);
        this.images = new ImageStore(this.context);
        this.pipeline = new PipelineStore(this.context, this.images);
        this.outputs = new OutputCatalog(this.context);
        this.jobs = new JobStore(new NaiGenerator(this.tokens), this.images, this.pipeline, this.outputs, this.favorites);
        this.http = new LocalHttpServer(this);
    }

    int start() throws Exception {
        port = http.start(18797);
        return port;
    }

    int getPort() {
        return port;
    }

    @Override
    public LocalHttpServer.Response handle(LocalHttpServer.Request request) throws Exception {
        String path = request.path;
        if (path.length() > 1 && path.endsWith("/")) path = path.substring(0, path.length() - 1);
        if ("GET".equals(request.method) && ("/m".equals(path) || path.startsWith("/m/"))) {
            return asset("www/m/index.html", "text/html; charset=utf-8");
        }
        if ("GET".equals(request.method) && path.startsWith("/assets/")) {
            return staticAsset(path);
        }
        if ("GET".equals(request.method) && "/favicon.ico".equals(path)) {
            return LocalHttpServer.Response.text(204, "");
        }
        if ("GET".equals(request.method) && "/api/session-token".equals(path)) {
            return json(200, "{\"ok\":true,\"token\":\"phone-local\"}");
        }
        if ("GET".equals(request.method) && "/api/mobile/status".equals(path)) {
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("standalone", true);
            out.put("loopback", true);
            out.put("remote_listen", false);
            out.put("has_token", tokens.hasToken());
            out.put("has_deepseek", tokens.hasDeepSeek());
            out.put("has_ai_key", tokens.hasDeepSeek());
            out.put("online_use_proxy", tokens.onlineUseProxy());
            out.put("nai_use_proxy", tokens.naiUseProxy());
            out.put("has_proxy", !tokens.getProxy().isEmpty());
            return json(200, out.toString());
        }
        if ("GET".equals(request.method) && "/api/nai/status".equals(path)) {
            JSONObject out = new JSONObject();
            boolean has = tokens.hasToken();
            out.put("ok", has);
            out.put("has_token", has);
            out.put("has_deepseek", tokens.hasDeepSeek());
            out.put("online_use_proxy", tokens.onlineUseProxy());
            out.put("nai_use_proxy", tokens.naiUseProxy());
            out.put("has_proxy", !tokens.getProxy().isEmpty());
            out.put("message", has ? "token configured" : "NAI token is not configured");
            return json(200, out.toString());
        }
        if ("GET".equals(request.method) && "/api/nai/network".equals(path)) {
            return json(200, tokens.networkStatus().toString());
        }
        if ("POST".equals(request.method) && "/api/nai/network".equals(path)) {
            try {
                JSONObject payload = JsonUtil.obj(request.text());
                tokens.setNetwork(
                    JsonUtil.first(payload, "proxy", "http_proxy"),
                    payload.has("online_use_proxy") ? payload.optBoolean("online_use_proxy", true) : true,
                    payload.has("nai_use_proxy") ? payload.optBoolean("nai_use_proxy", false) : false
                );
                return json(200, tokens.networkStatus().toString());
            } catch (Exception error) {
                return json(400, errorJson(error.getMessage()));
            }
        }
        if ("POST".equals(request.method) && "/api/nai/token".equals(path)) {
            JSONObject payload = JsonUtil.obj(request.text());
            String token = JsonUtil.str(payload, "token");
            if (token.isEmpty()) tokens.clear();
            else tokens.set(token);
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("has_token", tokens.hasToken());
            out.put("message", tokens.hasToken() ? "已保存到本机" : "已清除");
            return json(200, out.toString());
        }
        if ("GET".equals(request.method) && "/api/ai/status".equals(path)) {
            return json(200, deepseek.status().toString());
        }
        if ("POST".equals(request.method) && "/api/ai/key".equals(path)) {
            JSONObject payload = JsonUtil.obj(request.text());
            String key = JsonUtil.first(payload, "api_key", "key", "token");
            if (key.isEmpty()) tokens.clearDeepSeek();
            else tokens.setDeepSeek(key);
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("has_api_key", tokens.hasDeepSeek());
            out.put("has_deepseek", tokens.hasDeepSeek());
            out.put("message", tokens.hasDeepSeek() ? "DeepSeek 已保存到本机" : "已清除 DeepSeek");
            return json(200, out.toString());
        }
        if ("POST".equals(request.method) && "/api/studio/optimize".equals(path)) {
            try {
                JSONObject payload = JsonUtil.obj(request.text());
                JSONObject comment = payload.optJSONObject("comment");
                if (comment == null) comment = payload.optJSONObject("patched_comment");
                if (comment == null) return json(400, "{\"ok\":false,\"detail\":\"comment is required\"}");
                return json(200, deepseek.optimize(comment).toString());
            } catch (Exception error) {
                return json(400, errorJson(error.getMessage()));
            }
        }
        if ("POST".equals(request.method) && "/api/mobile/char-describe".equals(path)) {
            try {
                JSONObject payload = JsonUtil.obj(request.text());
                return json(200, deepseek.describeCharacter(
                    JsonUtil.first(payload, "text", "description"),
                    JsonUtil.str(payload, "gender")
                ).toString());
            } catch (Exception error) {
                return json(400, errorJson(error.getMessage()));
            }
        }
        if ("GET".equals(request.method) && "/api/mobile/outputs".equals(path)) {
            return json(200, outputs.list(images).toString());
        }
        if ("GET".equals(request.method) && "/api/nai/aitag/probe".equals(path)) {
            return json(200, aitag.probe().toString());
        }
        if ("GET".equals(request.method) && "/api/nai/aitag/search".equals(path)) {
            return json(200, aitag.search(request.query("q"), parseInt(request.query("page"), 1), true).toString());
        }
        if ("GET".equals(request.method) && "/api/nai/aitag/favorites".equals(path)) {
            return json(200, favorites.ids().toString());
        }
        if ("GET".equals(request.method) && "/api/nai/aitag/favorites/works".equals(path)) {
            return json(200, favorites.works(request.query("q")).toString());
        }
        if ("GET".equals(request.method) && "/api/mobile/library/works".equals(path)) {
            return json(200, favorites.works(request.query("q")).toString());
        }
        if ("GET".equals(request.method) && path.startsWith("/api/mobile/library/work/")) {
            String id = LocalHttpServer.decode(path.substring("/api/mobile/library/work/".length()));
            JSONObject local = favorites.workPayload(id);
            if (local == null) return json(404, "{\"ok\":false,\"detail\":\"本地库没有这个作品\"}");
            return json(200, local.toString());
        }
        if ("POST".equals(request.method) && path.startsWith("/api/nai/aitag/favorites/") && path.endsWith("/toggle")) {
            String id = path.substring("/api/nai/aitag/favorites/".length(), path.length() - "/toggle".length());
            try {
                return json(200, favorites.toggle(LocalHttpServer.decode(id), JsonUtil.obj(request.text())).toString());
            } catch (Exception error) {
                return json(400, errorJson(error.getMessage()));
            }
        }
        if ("GET".equals(request.method) && path.startsWith("/api/mobile/favorite-image/")) {
            String rest = path.substring("/api/mobile/favorite-image/".length());
            String[] parts = rest.split("/");
            if (parts.length < 2) return json(400, "{\"ok\":false,\"detail\":\"invalid favorite image\"}");
            File image = favorites.imageFile(LocalHttpServer.decode(parts[0]), parseInt(parts[1], 0));
            if (image == null) return json(404, "{\"ok\":false,\"detail\":\"favorite image not found\"}");
            return new LocalHttpServer.Response(200, favorites.contentType(image), favorites.readImage(image));
        }
        if ("GET".equals(request.method) && path.startsWith("/api/nai/aitag/work/")) {
            String id = path.substring("/api/nai/aitag/work/".length());
            if (id.contains("/")) return json(404, "{\"ok\":false,\"detail\":\"not found\"}");
            String workId = LocalHttpServer.decode(id);
            try {
                JSONObject payload = aitag.work(workId);
                favorites.overlayLocalImages(payload, workId);
                return json(200, payload.toString());
            } catch (Exception error) {
                JSONObject local = favorites.workPayload(workId);
                if (local != null) return json(200, local.toString());
                return json(400, errorJson(error.getMessage()));
            }
        }
        if ("GET".equals(request.method) && path.startsWith("/api/nai/aitag/cover/")) {
            String id = LocalHttpServer.decode(path.substring("/api/nai/aitag/cover/".length()));
            HttpOutbound.Result image = aitag.cover(id);
            return new LocalHttpServer.Response(200, image.contentType, image.body);
        }
        if ("GET".equals(request.method) && path.startsWith("/api/nai/aitag/image/")) {
            String rest = path.substring("/api/nai/aitag/image/".length());
            String[] parts = rest.split("/");
            if (parts.length < 3) return json(400, "{\"ok\":false,\"detail\":\"invalid AITag image path\"}");
            HttpOutbound.Result image = aitag.image(
                LocalHttpServer.decode(parts[0]),
                LocalHttpServer.decode(parts[1]),
                LocalHttpServer.decode(parts[2])
            );
            return new LocalHttpServer.Response(200, image.contentType, image.body);
        }
        if ("GET".equals(request.method) && "/api/plugin/char-swap/presets".equals(path)) {
            return json(200, library.listPresets(request.query("gender")).toString());
        }
        if ("GET".equals(request.method) && "/api/plugin/char-swap/search".equals(path)) {
            return json(200, library.searchAll(request.query("gender"), request.query("q"), parseInt(request.query("limit"), 24)).toString());
        }
        if ("GET".equals(request.method) && "/api/plugin/char-swap/ark-library".equals(path)) {
            return json(200, library.searchArk(request.query("gender"), request.query("q"), parseInt(request.query("limit"), 20)).toString());
        }
        if ("GET".equals(request.method) && "/api/plugin/char-swap/custom".equals(path)) {
            return json(200, customChars.list(request.query("gender")).toString());
        }
        if ("POST".equals(request.method) && "/api/plugin/char-swap/custom".equals(path)) {
            return json(200, customChars.add(JsonUtil.obj(request.text())).toString());
        }
        if ("POST".equals(request.method) && "/api/plugin/char-swap/custom/delete".equals(path)) {
            return json(200, customChars.remove(JsonUtil.str(JsonUtil.obj(request.text()), "id")).toString());
        }
        if ("POST".equals(request.method) && "/api/nai/generate".equals(path)) {
            JSONObject payload = JsonUtil.obj(request.text());
            JSONObject comment = payload.optJSONObject("patched_comment");
            if (comment == null) return json(400, "{\"ok\":false,\"detail\":\"patched_comment is required\"}");
            if (!tokens.hasToken()) return json(400, "{\"ok\":false,\"detail\":\"NovelAI token is not configured\"}");
            boolean forceFree = !payload.has("force_free") || payload.optBoolean("force_free", true);
            return json(200, jobs.start(comment, forceFree).toString());
        }
        if ("GET".equals(request.method) && "/api/nai/jobs".equals(path)) {
            JSONObject job = jobs.get(request.query("task_id"));
            if (job == null) return json(404, "{\"ok\":false,\"detail\":\"generation task not found\"}");
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("job", job);
            return json(200, out.toString());
        }
        if ("GET".equals(request.method) && path.startsWith("/api/mobile/output/")) {
            String name = path.substring("/api/mobile/output/".length()).replace(".png", "");
            File file = images.file(name);
            if (file == null) return json(404, "{\"ok\":false,\"detail\":\"image not found\"}");
            return new LocalHttpServer.Response(200, "image/png", readFile(file));
        }
        if ("GET".equals(request.method) && "/api/pipeline/config".equals(path)) {
            return json(200, pipeline.config().toString());
        }
        if ("POST".equals(request.method) && "/api/pipeline/config".equals(path)) {
            return json(200, pipeline.setConfig(JsonUtil.obj(request.text())).toString());
        }
        if ("GET".equals(request.method) && "/api/pipeline/status".equals(path)) {
            return json(200, pipeline.status().toString());
        }
        if ("POST".equals(request.method) && "/api/pipeline/run".equals(path)) {
            return json(200, pipeline.runMissing().toString());
        }
        if ("/api/queue/works".equals(path) || path.startsWith("/api/plugin/char-swap/batch/")) {
            return json(400, "{\"ok\":false,\"detail\":\"手机独立版不读取电脑待生成队列\"}");
        }
        return json(404, "{\"ok\":false,\"detail\":\"not found\"}");
    }

    private LocalHttpServer.Response staticAsset(String path) throws Exception {
        String relative = path.substring("/assets/".length());
        String mapped;
        if (relative.startsWith("m/")) mapped = "www/m/" + relative.substring(2);
        else if (relative.startsWith("shared/")) mapped = "www/shared/" + relative.substring(7);
        else return json(404, "{\"ok\":false,\"detail\":\"not found\"}");
        if (mapped.contains("..")) return json(404, "{\"ok\":false,\"detail\":\"not found\"}");
        String type = "text/plain; charset=utf-8";
        String lower = mapped.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".js")) type = "application/javascript; charset=utf-8";
        else if (lower.endsWith(".css")) type = "text/css; charset=utf-8";
        else if (lower.endsWith(".html")) type = "text/html; charset=utf-8";
        else if (lower.endsWith(".json")) type = "application/json; charset=utf-8";
        return asset(mapped, type);
    }

    private LocalHttpServer.Response asset(String name, String type) throws Exception {
        try (InputStream in = context.getAssets().open(name);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
            return new LocalHttpServer.Response(200, type, out.toByteArray());
        } catch (Exception e) {
            return json(404, "{\"ok\":false,\"detail\":\"asset not found\"}");
        }
    }

    private static LocalHttpServer.Response json(int status, String body) {
        return LocalHttpServer.Response.json(status, body);
    }

    private static String errorJson(String message) {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", false);
            out.put("detail", message == null || message.trim().isEmpty() ? "request failed" : message);
        } catch (Exception ignored) {}
        return out.toString();
    }

    private static int parseInt(String raw, int fallback) {
        try {
            return Integer.parseInt(String.valueOf(raw == null ? "" : raw).trim());
        } catch (Exception e) {
            return fallback;
        }
    }

    private static byte[] readFile(File file) throws Exception {
        byte[] data = new byte[(int) file.length()];
        try (FileInputStream in = new FileInputStream(file)) {
            int n = in.read(data);
            if (n != data.length) throw new IllegalStateException("read failed");
        }
        return data;
    }
}
