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

    boolean mosaicEnabled() {
        return prefs.getBoolean("mosaic", true);
    }

    int scale() {
        return Math.max(2, Math.min(prefs.getInt("scale", 2), 4));
    }

    String mosaicMethod() {
        return LightMosaic.normalizeMethod(prefs.getString("mosaic_method", "像素"));
    }

    int mosaicIntensity() {
        return LightMosaic.normalizeIntensity(prefs.getInt("mosaic_intensity", 36));
    }

    int estimateMs() {
        int ms = 350;
        if (upscaleEnabled()) ms += 280 * scale() * scale();
        if (mosaicEnabled()) ms += 900;
        if (metadataEnabled()) ms += 180;
        return ms;
    }

    String summary() {
        StringBuilder text = new StringBuilder();
        text.append("超分 ").append(upscaleEnabled() ? scale() + "x" : "关");
        text.append("，轻量打码 ").append(mosaicEnabled() ? mosaicMethod() : "关");
        text.append("，清元数据").append(metadataEnabled() ? "开" : "关");
        return text.toString();
    }

    byte[] process(byte[] png) {
        return PhonePipeline.process(
            png,
            upscaleEnabled(),
            scale(),
            mosaicEnabled(),
            mosaicMethod(),
            mosaicIntensity(),
            metadataEnabled()
        );
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
        out.put("mosaic", mosaicEnabled());
        out.put("mosaic_method", mosaicMethod());
        out.put("message", "已完成本机流水线：" + summary());
        return out;
    }

    JSONObject config() throws Exception {
        JSONObject cfg = new JSONObject();
        cfg.put("auto_after_generate", autoAfterGenerate());
        cfg.put("save_to_gallery", true);
        cfg.put("upscale", upscaleEnabled());
        cfg.put("scale", scale());
        cfg.put("metadata", metadataEnabled());
        cfg.put("mosaic", mosaicEnabled());
        cfg.put("mosaic_available", true);
        cfg.put("mosaic_mode", "light");
        cfg.put("mosaic_method", mosaicMethod());
        cfg.put("mosaic_intensity", mosaicIntensity());
        cfg.put("estimate_ms", estimateMs());
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("config", cfg);
        out.put("message", "手机流水线：超分 + 轻量打码 + 清元数据。打码是肤色区域像素/模糊，不是电脑 ANR/YOLO，漏打请自己看一眼。");
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
        if (payload != null && payload.has("mosaic")) {
            edit.putBoolean("mosaic", payload.optBoolean("mosaic"));
        }
        if (payload != null && payload.has("scale")) {
            edit.putInt("scale", Math.max(2, Math.min(payload.optInt("scale", 2), 4)));
        }
        if (payload != null && payload.has("mosaic_method")) {
            edit.putString("mosaic_method", LightMosaic.normalizeMethod(payload.optString("mosaic_method")));
        }
        if (payload != null && payload.has("mosaic_intensity")) {
            edit.putInt("mosaic_intensity", LightMosaic.normalizeIntensity(payload.optInt("mosaic_intensity", 36)));
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
        out.put("message", "流水线补跑完成：处理 " + done + " 张，补存相册 " + exported + " 张。" + summary());
        return out;
    }
}
