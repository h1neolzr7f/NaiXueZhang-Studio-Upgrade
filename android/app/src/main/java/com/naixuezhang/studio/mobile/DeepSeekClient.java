package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class DeepSeekClient {
    private static final String API = "https://api.deepseek.com/v1/chat/completions";
    private static final String MODEL = "deepseek-chat";
    private static final int LIMIT = 512 * 1024;
    private static final Pattern JSON_BLOCK = Pattern.compile("\\{[\\s\\S]*\\}");
    private static final String OPTIMIZE_SYSTEM = ""
        + "你是 NovelAI 资深咒语顾问。把用户给出的绘图咒语改写成更适合 NovelAI 出图的版本。"
        + "只返回一个 JSON 对象，不要 Markdown。"
        + "字段：prompt, uc, char_captions(可选数组), base_caption(可选), notes(可选，≤80字)。"
        + "面向 nai-diffusion，不要 SD/ComfyUI/LoRA 语法。"
        + "保留角色、动作、构图和氛围；去掉重复冲突 tag；不要输出 steps/seed/width。";
    private static final String DESCRIBE_SYSTEM = ""
        + "你是 NovelAI 角色标签助手。把用户的中文或英文角色描述转成 Danbooru 风格槽位咒语。"
        + "只返回一个 JSON 对象，不要 Markdown。"
        + "字段：label, gender(female|male), identity(数组，角色身份 tag),"
        + " appearance(数组，发色瞳色体态等), char_caption(完整槽位咒语，逗号分隔)。"
        + "identity 至少一项；不要写 SD/LoRA 语法；不要发明官方角色精确 tag，除非用户明确提到。";

    private final TokenStore tokens;

    DeepSeekClient(TokenStore tokens) {
        this.tokens = tokens;
    }

    JSONObject status() throws Exception {
        JSONObject out = new JSONObject();
        boolean has = tokens.hasDeepSeek();
        out.put("ok", true);
        out.put("has_api_key", has);
        out.put("has_deepseek", has);
        out.put("provider", "DeepSeek");
        out.put("model", MODEL);
        out.put("api_base", "https://api.deepseek.com/v1");
        out.put("message", has ? "DeepSeek 已配置" : "DeepSeek API Key is not configured");
        return out;
    }

    JSONObject optimize(JSONObject comment) throws Exception {
        if (!tokens.hasDeepSeek()) {
            throw new IllegalStateException("DeepSeek API Key is not configured");
        }
        JSONObject src = comment == null ? new JSONObject() : comment;
        JSONObject before = snapshot(src);
        JSONObject user = new JSONObject();
        user.put("task", "optimize_nai_prompt");
        user.put("original", before);
        user.put("hints", new JSONObject()
            .put("model_family", "novelai_nai_diffusion_v4")
            .put("keep_char_slot_count", before.optJSONArray("char_captions") == null
                ? 0 : before.optJSONArray("char_captions").length()));
        JSONObject parsed = chatJson(OPTIMIZE_SYSTEM, user);
        JSONObject texts = new JSONObject();
        texts.put("prompt", firstNonEmpty(parsed.optString("prompt"), before.optString("prompt")));
        texts.put("uc", parsed.has("uc") ? String.valueOf(parsed.opt("uc")) : before.optString("uc"));
        texts.put("base_caption", firstNonEmpty(
            parsed.optString("base_caption"),
            parsed.optString("prompt"),
            before.optString("base_caption")
        ));
        texts.put("char_captions", parsed.opt("char_captions") instanceof JSONArray
            ? parsed.optJSONArray("char_captions")
            : before.opt("char_captions"));
        JSONObject patched = applyTexts(src, texts);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("provider", "llm");
        out.put("profile", "nai_smart");
        out.put("label", "智能优化");
        out.put("texts", snapshot(patched));
        out.put("before", before);
        out.put("comment", patched);
        out.put("notes", JsonUtil.str(parsed, "notes"));
        out.put("model", MODEL);
        out.put("generation_calls", 0);
        return out;
    }

    JSONObject describeCharacter(String rawText, String genderHint) throws Exception {
        if (!tokens.hasDeepSeek()) {
            throw new IllegalStateException("DeepSeek API Key is not configured");
        }
        String text = String.valueOf(rawText == null ? "" : rawText).trim();
        if (text.isEmpty()) throw new IllegalArgumentException("先写角色描述");
        if (text.length() > 800) text = text.substring(0, 800);
        String gender = "male".equalsIgnoreCase(genderHint) ? "male" : "female";
        JSONObject user = new JSONObject();
        user.put("task", "describe_character");
        user.put("text", text);
        user.put("preferred_gender", gender);
        JSONObject parsed = chatJson(DESCRIBE_SYSTEM, user);
        String label = firstNonEmpty(JsonUtil.str(parsed, "label"), JsonUtil.str(parsed, "name"), text);
        String genderOut = JsonUtil.str(parsed, "gender").toLowerCase(Locale.ROOT);
        if (!"male".equals(genderOut) && !"female".equals(genderOut)) genderOut = gender;
        JSONArray identity = asStringArray(parsed.opt("identity"));
        if (identity.length() == 0) identity.put(label);
        JSONArray appearance = asStringArray(parsed.opt("appearance"));
        String caption = firstNonEmpty(JsonUtil.str(parsed, "char_caption"), join(identity, appearance));
        JSONObject item = new JSONObject();
        item.put("id", "typed");
        item.put("label", label);
        item.put("name", label);
        item.put("gender", genderOut);
        item.put("kind", "oc");
        item.put("source", "deepseek");
        item.put("identity", identity);
        item.put("appearance", appearance);
        item.put("char_caption", caption);
        item.put("tag", identity.optString(0, label));
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("item", item);
        out.put("record", item);
        out.put("message", "DeepSeek 已写成角色槽");
        out.put("generation_calls", 0);
        return out;
    }

    private JSONObject chatJson(String system, JSONObject user) throws Exception {
        JSONObject body = new JSONObject();
        body.put("model", MODEL);
        body.put("temperature", 0.3);
        body.put("max_tokens", 1200);
        body.put("response_format", new JSONObject().put("type", "json_object"));
        JSONArray messages = new JSONArray();
        messages.put(new JSONObject().put("role", "system").put("content", system));
        messages.put(new JSONObject().put("role", "user").put("content", user.toString()));
        body.put("messages", messages);
        Map<String, String> headers = new HashMap<>();
        headers.put("Authorization", "Bearer " + tokens.getDeepSeek());
        headers.put("Content-Type", "application/json");
        headers.put("Accept", "application/json");
        headers.put("User-Agent", "NaiXueZhang-Phone/1.6");
        HttpOutbound.Result result = HttpOutbound.postJson(API, headers, body.toString(), 60000, LIMIT, tokens.routeOnline());
        if (result.status == 401) throw new IllegalStateException("DeepSeek Key 无效或已过期");
        if (result.status == 429) throw new IllegalStateException("DeepSeek 请求太频繁，请稍后再试");
        if (result.status < 200 || result.status >= 300) {
            throw new IllegalStateException("DeepSeek 返回 HTTP " + result.status);
        }
        JSONObject raw = JsonUtil.obj(result.text());
        JSONArray choices = raw.optJSONArray("choices");
        JSONObject message = choices != null && choices.length() > 0
            ? choices.optJSONObject(0).optJSONObject("message")
            : null;
        String content = message == null ? "" : String.valueOf(message.opt("content"));
        return extractJson(content);
    }

    static JSONObject applyTexts(JSONObject comment, JSONObject texts) throws Exception {
        JSONObject patched = comment == null ? new JSONObject() : new JSONObject(comment.toString());
        String prompt = JsonUtil.str(texts, "prompt");
        String uc = texts != null && texts.has("uc")
            ? String.valueOf(texts.opt("uc"))
            : JsonUtil.str(patched, "uc");
        String base = firstNonEmpty(JsonUtil.str(texts, "base_caption"), prompt);
        JSONArray incoming = texts == null ? null : texts.optJSONArray("char_captions");
        if (incoming != null && incoming.length() > 0) {
            JSONObject v4 = JsonUtil.parseMaybe(patched.opt("v4_prompt"));
            JSONObject cap = JsonUtil.parseMaybe(v4.opt("caption"));
            JSONArray existing = cap.optJSONArray("char_captions");
            if (existing == null) existing = new JSONArray();
            JSONArray merged = new JSONArray();
            for (int i = 0; i < incoming.length(); i++) {
                Object raw = incoming.opt(i);
                String text = raw instanceof JSONObject
                    ? JsonUtil.first((JSONObject) raw, "char_caption", "caption")
                    : String.valueOf(raw == null ? "" : raw).trim();
                JSONObject old = i < existing.length() ? existing.optJSONObject(i) : null;
                JSONArray centers = old != null ? old.optJSONArray("centers") : null;
                if (centers == null || centers.length() == 0) {
                    centers = new JSONArray().put(new JSONObject().put("x", 0.5).put("y", 0.5));
                }
                JSONObject slot = new JSONObject();
                slot.put("char_caption", text);
                slot.put("centers", centers);
                merged.put(slot);
            }
            cap.put("char_captions", merged);
            cap.put("base_caption", base);
            v4.put("caption", cap);
            patched.put("v4_prompt", v4);
            patched.put("prompt", base.isEmpty() ? prompt : base);
        } else {
            patched.put("prompt", prompt.isEmpty() ? base : prompt);
            JSONObject v4 = JsonUtil.parseMaybe(patched.opt("v4_prompt"));
            if (v4.length() > 0 && !base.isEmpty()) {
                JSONObject cap = JsonUtil.parseMaybe(v4.opt("caption"));
                cap.put("base_caption", base);
                v4.put("caption", cap);
                patched.put("v4_prompt", v4);
            }
        }
        if (uc != null) patched.put("uc", uc);
        return patched;
    }

    static JSONObject snapshot(JSONObject comment) throws Exception {
        JSONObject src = comment == null ? new JSONObject() : comment;
        JSONObject v4 = JsonUtil.parseMaybe(src.opt("v4_prompt"));
        JSONObject cap = JsonUtil.parseMaybe(v4.opt("caption"));
        JSONArray chars = new JSONArray();
        JSONArray raw = cap.optJSONArray("char_captions");
        if (raw != null) {
            for (int i = 0; i < raw.length(); i++) {
                JSONObject item = raw.optJSONObject(i);
                chars.put(item == null ? "" : item.optString("char_caption"));
            }
        }
        String base = firstNonEmpty(cap.optString("base_caption"), src.optString("prompt"));
        JSONObject out = new JSONObject();
        out.put("prompt", firstNonEmpty(src.optString("prompt"), base));
        out.put("base_caption", base);
        out.put("uc", firstNonEmpty(src.optString("uc"), src.optString("negative_prompt")));
        out.put("char_captions", chars);
        return out;
    }

    private static JSONObject extractJson(String raw) throws Exception {
        String text = String.valueOf(raw == null ? "" : raw).trim();
        if (text.startsWith("```")) {
            int start = text.indexOf('{');
            int end = text.lastIndexOf('}');
            if (start >= 0 && end > start) text = text.substring(start, end + 1);
        }
        try {
            return new JSONObject(text);
        } catch (Exception ignored) {
            Matcher match = JSON_BLOCK.matcher(text);
            if (match.find()) return new JSONObject(match.group());
            throw new IllegalStateException("DeepSeek 返回无法解析");
        }
    }

    private static JSONArray asStringArray(Object raw) {
        JSONArray out = new JSONArray();
        if (raw instanceof JSONArray) {
            JSONArray src = (JSONArray) raw;
            for (int i = 0; i < src.length(); i++) {
                String item = String.valueOf(src.opt(i) == null ? "" : src.opt(i)).trim();
                if (!item.isEmpty()) out.put(item);
            }
            return out;
        }
        if (raw instanceof String) {
            for (String part : String.valueOf(raw).split("[,\\n]")) {
                String item = part.trim();
                if (!item.isEmpty()) out.put(item);
            }
        }
        return out;
    }

    private static String join(JSONArray identity, JSONArray appearance) {
        StringBuilder out = new StringBuilder();
        appendAll(out, identity);
        appendAll(out, appearance);
        return out.toString();
    }

    private static void appendAll(StringBuilder out, JSONArray items) {
        if (items == null) return;
        for (int i = 0; i < items.length(); i++) {
            String item = String.valueOf(items.opt(i) == null ? "" : items.opt(i)).trim();
            if (item.isEmpty()) continue;
            if (out.length() > 0) out.append(", ");
            out.append(item);
        }
    }

    private static String firstNonEmpty(String... values) {
        if (values == null) return "";
        for (String value : values) {
            if (value != null && !value.trim().isEmpty()) return value.trim();
        }
        return "";
    }
}
