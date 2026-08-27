package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

final class NaiGenerator {
    private static final String IMAGE_API = "https://image.novelai.net/ai/generate-image";
    private static final int MAX_FREE_LONG_EDGE = 1216;
    private static final int MAX_FREE_STEPS = 28;
    private static final int MAX_FREE_PIXELS = 1024 * 1024;
    private static final int MAX_PNG = 25 * 1024 * 1024;
    private final TokenStore tokens;

    NaiGenerator(TokenStore tokens) {
        this.tokens = tokens;
    }

    int concurrency() {
        return Math.max(1, tokens.concurrency());
    }

    byte[] generatePng(JSONObject comment, boolean forceFree) throws Exception {
        String token = tokens.lease(180000);
        if (token.isEmpty()) throw new IllegalStateException("missing_token");
        try {
            return generatePngWith(token, comment, forceFree);
        } finally {
            tokens.release(token);
        }
    }

    byte[] generatePngWith(String token, JSONObject comment, boolean forceFree) throws Exception {
        if (token == null || token.trim().isEmpty()) throw new IllegalStateException("missing_token");
        JSONObject payload = buildPayload(comment, forceFree);
        JSONObject body = new JSONObject();
        body.put("input", payload.optString("input"));
        body.put("model", payload.optString("model"));
        body.put("action", "generate");
        body.put("parameters", payload.optJSONObject("parameters"));
        Map<String, String> headers = new HashMap<>();
        headers.put("Authorization", "Bearer " + token);
        headers.put("Content-Type", "application/json");
        headers.put("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36");
        headers.put("Referer", "https://novelai.net/");
        HttpOutbound.Result result;
        try {
            result = HttpOutbound.postJson(IMAGE_API, headers, body.toString(), 180000, MAX_PNG, tokens.routeNai());
        } catch (Exception error) {
            throw new NaiError(
                JobStore.friendlyGenerateError(error.getMessage()),
                HttpOutbound.isTransport(error),
                HttpOutbound.isTransport(error) ? "connection_closed" : "generate_failed"
            );
        }
        if (result.status == 401) throw new NaiError("NovelAI Token 无效或过期，去设置里重填", false, "provider_unavailable");
        if (result.status == 429) throw new NaiError("NovelAI 限流了，稍后再手动重试", true, "rate_limited");
        if (result.status >= 500) throw new NaiError("NovelAI 服务出错 " + result.status + "，不要自动重试", true, "http_5xx");
        if (result.status >= 400) throw new NaiError("NovelAI 拒绝了这次出图 " + result.status, false, "generate_failed");
        return extractPng(result.body);
    }

    JSONObject buildPayload(JSONObject comment, boolean forceFree) throws Exception {
        JSONObject src = comment == null ? new JSONObject() : comment;
        int width = src.optInt("width", 832);
        int height = src.optInt("height", 1216);
        int steps = src.optInt("steps", 28);
        boolean resized = false;
        if (forceFree) {
            int[] fitted = fitFree(width, height);
            width = fitted[0];
            height = fitted[1];
            resized = fitted[2] == 1;
            steps = Math.min(steps, MAX_FREE_STEPS);
        }
        JSONObject v4 = JsonUtil.parseMaybe(src.opt("v4_prompt"));
        JSONObject cap = JsonUtil.parseMaybe(v4.opt("caption"));
        String base = firstNonEmpty(cap.optString("base_caption"), src.optString("prompt"));
        cap.put("base_caption", base);
        if (!(cap.opt("char_captions") instanceof JSONArray)) cap.put("char_captions", new JSONArray());
        v4.put("caption", cap);
        v4.put("use_coords", v4.optBoolean("use_coords", true));
        String negative = firstNonEmpty(src.optString("negative_prompt"), src.optString("uc"));
        JSONObject neg = JsonUtil.parseMaybe(src.opt("v4_negative_prompt"));
        JSONObject negCap = JsonUtil.parseMaybe(neg.opt("caption"));
        negCap.put("base_caption", firstNonEmpty(negCap.optString("base_caption"), negative));
        JSONArray chars = cap.optJSONArray("char_captions");
        JSONArray negChars = negCap.optJSONArray("char_captions");
        if (negChars == null) negChars = new JSONArray();
        if (chars != null) {
            while (negChars.length() < chars.length()) {
                JSONObject slot = chars.optJSONObject(negChars.length());
                JSONArray centers = slot != null ? slot.optJSONArray("centers") : null;
                JSONObject pad = new JSONObject();
                pad.put("char_caption", "");
                pad.put("centers", centers != null && centers.length() > 0 ? centers : new JSONArray().put(center()));
                negChars.put(pad);
            }
        }
        negCap.put("char_captions", negChars);
        neg.put("caption", negCap);
        neg.put("use_coords", neg.optBoolean("use_coords", true));
        JSONObject parameters = new JSONObject();
        parameters.put("params_version", src.optInt("params_version", 3));
        parameters.put("width", width);
        parameters.put("height", height);
        parameters.put("scale", src.optDouble("scale", 5));
        parameters.put("sampler", firstNonEmpty(src.optString("sampler"), "k_euler_ancestral"));
        parameters.put("steps", steps);
        parameters.put("n_samples", 1);
        parameters.put("ucPreset", 0);
        parameters.put("qualityToggle", src.optBoolean("qualityToggle", true));
        parameters.put("autoSmea", src.optBoolean("autoSmea", false));
        parameters.put("negative_prompt", negative);
        parameters.put("legacy", false);
        parameters.put("legacy_uc", false);
        parameters.put("add_original_image", true);
        parameters.put("characterPrompts", src.optJSONArray("characterPrompts") == null ? new JSONArray() : src.optJSONArray("characterPrompts"));
        parameters.put("uc", negative);
        parameters.put("v4_prompt", v4);
        parameters.put("v4_negative_prompt", neg);
        parameters.put("noise_schedule", firstNonEmpty(src.optString("noise_schedule"), "karras"));
        parameters.put("cfg_rescale", src.opt("cfg_rescale") == null ? 0 : src.opt("cfg_rescale"));
        parameters.put("use_coords", v4.optBoolean("use_coords", true));
        if (src.has("seed") && !"".equals(String.valueOf(src.opt("seed")))) {
            try {
                int seed = Integer.parseInt(String.valueOf(src.opt("seed")));
                if (seed == -1 || seed >= 0) parameters.put("seed", seed);
            } catch (Exception ignored) {}
        }
        JSONObject out = new JSONObject();
        out.put("input", base);
        out.put("model", inferModel(src.optString("Source"), src.optString("model")));
        out.put("action", "generate");
        out.put("parameters", parameters);
        out.put("free_eligible", forceFree && steps <= MAX_FREE_STEPS && Math.max(width, height) <= MAX_FREE_LONG_EDGE && width * height <= MAX_FREE_PIXELS);
        out.put("resized_for_free", resized);
        return out;
    }

    private static int[] fitFree(int width, int height) {
        if (width <= 0 || height <= 0) return new int[]{832, 1216, 1};
        int longEdge = Math.max(width, height);
        int pixels = width * height;
        if (longEdge <= MAX_FREE_LONG_EDGE && pixels <= MAX_FREE_PIXELS) return new int[]{width, height, 0};
        double scale = Math.min(MAX_FREE_LONG_EDGE / (double) longEdge, Math.sqrt(MAX_FREE_PIXELS / (double) pixels));
        int newWidth = Math.max(64, ((int) (width * scale) / 64) * 64);
        int newHeight = Math.max(64, ((int) (height * scale) / 64) * 64);
        while (newWidth * newHeight > MAX_FREE_PIXELS) {
            if (newWidth >= newHeight && newWidth > 64) newWidth -= 64;
            else if (newHeight > 64) newHeight -= 64;
            else break;
        }
        return new int[]{newWidth, newHeight, 1};
    }

    private static String inferModel(String source, String explicit) {
        if (explicit != null && explicit.startsWith("nai-diffusion-")) return explicit;
        String value = source == null ? "" : source;
        String lower = value.toLowerCase(java.util.Locale.ROOT);
        if (value.contains("V4.5") || lower.contains("v4.5")) return "nai-diffusion-4-5-full";
        if (value.contains("V4") || lower.contains("v4")) return "nai-diffusion-4-full";
        return "nai-diffusion-4-5-full";
    }

    private static byte[] extractPng(byte[] zipBytes) throws Exception {
        if (zipBytes != null && zipBytes.length >= 8 && zipBytes[0] == (byte) 0x89 && zipBytes[1] == 0x50) {
            return zipBytes;
        }
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(zipBytes))) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (entry.isDirectory()) continue;
                String name = String.valueOf(entry.getName()).toLowerCase(java.util.Locale.ROOT);
                if (!name.endsWith(".png")) continue;
                byte[] data = HttpOutbound.readBounded(zip, MAX_PNG);
                if (data.length >= 8 && data[0] == (byte) 0x89 && data[1] == 0x50) return data;
            }
        }
        throw new IllegalStateException("NovelAI response zip did not contain a PNG");
    }

    private static JSONObject center() throws Exception {
        JSONObject c = new JSONObject();
        c.put("x", 0.5);
        c.put("y", 0.5);
        return c;
    }

    private static String firstNonEmpty(String... values) {
        if (values == null) return "";
        for (String value : values) {
            if (value != null && !value.trim().isEmpty()) return value;
        }
        return "";
    }

    static final class NaiError extends Exception {
        final boolean billingUncertain;
        final String code;

        NaiError(String message, boolean billingUncertain, String code) {
            super(message);
            this.billingUncertain = billingUncertain;
            this.code = code;
        }
    }
}
