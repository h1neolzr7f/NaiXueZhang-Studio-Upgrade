package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

final class PipelineStore {
    private static final String PREFS = "nai_phone_pipeline";
    private final SharedPreferences prefs;
    private final ImageStore images;

    PipelineStore(Context context, ImageStore images) {
        this.prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        this.images = images;
    }

    boolean autoAfterGenerate() {
        return prefs.getBoolean("auto_after_generate", true);
    }

    boolean upscaleEnabled() {
        return prefs.getBoolean("upscale", true);
    }

    boolean metadataEnabled() {
        return prefs.getBoolean("metadata", true);
    }

    int scale() {
        return Math.max(2, Math.min(prefs.getInt("scale", 2), 4));
    }

    byte[] process(byte[] png) {
        return PhonePipeline.process(png, upscaleEnabled(), scale(), metadataEnabled());
    }

    JSONObject processId(String id) throws Exception {
        byte[] original = images.readOriginal(id);
        if (original.length == 0) original = images.read(id);
        if (original.length == 0) throw new IllegalStateException("没有这张生成图");
        byte[] processed = process(original);
        images.saveFinal(id, processed);
        if (autoAfterGenerate()) images.exportOne(id + "-final", processed);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("id", id);
        out.put("upscale", upscaleEnabled());
        out.put("scale", scale());
        out.put("metadata", metadataEnabled());
        out.put("mosaic", false);
        out.put("message", "已完成本机流水线：超分 " + (upscaleEnabled() ? scale() + "x" : "关") + "，清元数据" + (metadataEnabled() ? "开" : "关"));
        return out;
    }

    JSONObject config() throws Exception {
        JSONObject cfg = new JSONObject();
        cfg.put("auto_after_generate", autoAfterGenerate());
        cfg.put("save_to_gallery", true);
        cfg.put("upscale", upscaleEnabled());
        cfg.put("scale", scale());
        cfg.put("metadata", metadataEnabled());
        cfg.put("mosaic", false);
        cfg.put("mosaic_available", false);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("config", cfg);
        out.put("message", "手机流水线：超分+清元数据。打码需要电脑 ANR 模型，不打进 APK。");
        return out;
    }

    JSONObject setConfig(JSONObject payload) throws Exception {
        SharedPreferences.Editor edit = prefs.edit();
        if (payload != null && payload.has("auto_after_generate")) {
            edit.putBoolean("auto_after_generate", payload.optBoolean("auto_after_generate"));
        }
        if (payload != null && payload.has("upscale")) {
            edit.putBoolean("upscale", payload.optBoolean("upscale"));
        }
        if (payload != null && payload.has("metadata")) {
            edit.putBoolean("metadata", payload.optBoolean("metadata"));
        }
        if (payload != null && payload.has("scale")) {
            edit.putInt("scale", Math.max(2, Math.min(payload.optInt("scale", 2), 4)));
        }
        edit.apply();
        return config();
    }

    JSONObject status() throws Exception {
        int pending = 0;
        for (String id : images.originalIds()) {
            if (!images.hasFinal(id)) pending += 1;
        }
        JSONObject job = new JSONObject();
        job.put("status", pending > 0 ? "backlog" : "idle");
        JSONObject backlog = new JSONObject();
        backlog.put("count", pending);
        backlog.put("pending", pending);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("job", job);
        out.put("backlog", backlog);
        out.put("saved", images.pendingCount());
        return out;
    }

    JSONObject runMissing() throws Exception {
        int done = 0;
        for (String id : images.originalIds()) {
            if (images.hasFinal(id)) continue;
            try {
                processId(id);
                done += 1;
            } catch (Exception ignored) {}
        }
        int exported = images.exportMissing();
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("processed", done);
        out.put("exported", exported);
        out.put("message", "流水线补跑完成：处理 " + done + " 张，补存相册 " + exported + " 张。打码未执行（需要电脑 ANR）。");
        return out;
    }
}
