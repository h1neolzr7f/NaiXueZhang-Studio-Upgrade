package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

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
        return prefs.getBoolean("mosaic", false);
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

    int mosaicSensitivity() {
        return LightMosaic.normalizeSensitivity(prefs.getInt("mosaic_sensitivity", 8));
    }

    int mosaicDilate() {
        return LightMosaic.normalizeDilate(prefs.getInt("mosaic_dilate", 28));
    }

    List<String> mosaicParts() {
        return LightMosaic.parseParts(prefs.getString("mosaic_parts", LightMosaic.joinParts(null)));
    }

    int estimateMs() {
        int ms = 180;
        if (upscaleEnabled()) ms += 280 * scale() * scale();
        if (mosaicEnabled()) ms += OnnxCensor.available() ? 2600 : 900;
        if (metadataEnabled()) ms += 180;
        return ms;
    }

    String summary() {
        StringBuilder text = new StringBuilder();
        text.append("超分 ").append(upscaleEnabled() ? scale() + "x" : "关");
        text.append("，打码 ").append(mosaicEnabled() ? (OnnxCensor.available() ? "ONNX " : "轻量 ") + mosaicMethod() : "关");
        text.append("，清元数据").append(metadataEnabled() ? "开" : "关");
        return text.toString();
    }

    byte[] process(byte[] png) {
        return process(png, mosaicEnabled());
    }

    byte[] processWithoutMosaic(byte[] png) {
        return process(png, false);
    }

    byte[] processMosaicOnly(byte[] png) {
        return PhonePipeline.process(
            png,
            false,
            2,
            true,
            mosaicMethod(),
            mosaicIntensity(),
            false,
            mosaicParts(),
            mosaicSensitivity(),
            mosaicDilate()
        );
    }

    byte[] process(byte[] png, boolean mosaic) {
        return PhonePipeline.process(
            png,
            upscaleEnabled(),
            scale(),
            mosaic,
            mosaicMethod(),
            mosaicIntensity(),
            metadataEnabled(),
            mosaicParts(),
            mosaicSensitivity(),
            mosaicDilate()
        );
    }

    JSONObject processId(String id) throws Exception {
        return processId(id, mosaicEnabled());
    }

    JSONObject processId(String id, boolean mosaic) throws Exception {
        byte[] original = images.readOriginal(id);
        if (original.length == 0) original = images.read(id);
        if (original.length == 0) throw new IllegalStateException("没有这张生成图");
        byte[] processed = process(original, mosaic);
        if (processed != original) images.saveFinal(id, processed);
        if (autoAfterGenerate()) images.exportOne(id + (mosaic || upscaleEnabled() || metadataEnabled() ? "-final" : ""), processed);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("id", id);
        out.put("upscale", upscaleEnabled());
        out.put("scale", scale());
        out.put("metadata", metadataEnabled());
        out.put("mosaic", mosaic);
        out.put("mosaic_method", mosaicMethod());
        out.put("message", mosaic
            ? ("已完成本机流水线：" + summary())
            : ("已入库。打码关着，原图未打码。"));
        return out;
    }

    JSONObject applyMosaicId(String id) throws Exception {
        return processId(id, true);
    }

    JSONObject applyAlbum(GalleryStore gallery, String albumId) throws Exception {
        if (gallery == null) throw new IllegalArgumentException("图库不可用");
        List<String> ids = gallery.imageIds(albumId);
        if (ids.isEmpty()) throw new IllegalArgumentException("这组还没有图");
        int done = 0;
        for (String id : ids) {
            applyMosaicId(id);
            done += 1;
        }
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("album_id", albumId);
        out.put("processed", done);
        out.put("mosaic", true);
        out.put("mosaic_method", mosaicMethod());
        out.put("message", "已对这组 " + done + " 张打码（" + mosaicMethod() + "）。原图还留着。");
        return out;
    }

    JSONObject config() throws Exception {
        JSONArray parts = new JSONArray();
        for (String part : mosaicParts()) parts.put(part);
        JSONArray methods = new JSONArray();
        methods.put("不打码");
        for (String method : LightMosaic.METHODS) methods.put(method);
        JSONArray partOptions = new JSONArray();
        for (String part : LightMosaic.PARTS) partOptions.put(part);
        JSONObject cfg = new JSONObject();
        cfg.put("auto_after_generate", autoAfterGenerate());
        cfg.put("save_to_gallery", true);
        cfg.put("upscale", upscaleEnabled());
        cfg.put("scale", scale());
        cfg.put("metadata", metadataEnabled());
        cfg.put("mosaic", mosaicEnabled());
        cfg.put("mosaic_optional", true);
        cfg.put("mosaic_available", true);
        cfg.put("mosaic_mode", OnnxCensor.available() ? "onnx" : "light");
        cfg.put("mosaic_model", "censor.onnx");
        cfg.put("mosaic_ready", OnnxCensor.available());
        cfg.put("mosaic_method", mosaicMethod());
        cfg.put("mosaic_intensity", mosaicIntensity());
        cfg.put("mosaic_sensitivity", mosaicSensitivity());
        cfg.put("mosaic_dilate", mosaicDilate());
        cfg.put("mosaic_parts", parts);
        cfg.put("mosaic_methods", methods);
        cfg.put("mosaic_part_options", partOptions);
        cfg.put("estimate_ms", estimateMs());
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("config", cfg);
        out.put("message", mosaicEnabled()
            ? (OnnxCensor.available()
                ? "出图先入库，最后才打码。机内 ONNX（理塘同款 censor.onnx）。"
                : OnnxCensor.status() + "。未就绪时先用肤色区域打码。也可选不打码。")
            : "默认不打码。出图先入库，要打码可在图库打开或对一组补打。部位：欧金金 / 欧芒果 / 欧派派 / 欧西利。");
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
            String method = LightMosaic.normalizeMethod(payload.optString("mosaic_method"));
            if ("不打码".equals(method)) {
                edit.putBoolean("mosaic", false);
            } else {
                edit.putString("mosaic_method", method);
            }
        }
        if (payload != null && payload.has("mosaic_intensity")) {
            edit.putInt("mosaic_intensity", LightMosaic.normalizeIntensity(payload.optInt("mosaic_intensity", 36)));
        }
        if (payload != null && payload.has("mosaic_sensitivity")) {
            edit.putInt("mosaic_sensitivity", LightMosaic.normalizeSensitivity(payload.optInt("mosaic_sensitivity", 8)));
        }
        if (payload != null && payload.has("mosaic_dilate")) {
            edit.putInt("mosaic_dilate", LightMosaic.normalizeDilate(payload.optInt("mosaic_dilate", 28)));
        }
        if (payload != null && payload.has("mosaic_parts")) {
            List<String> parts = LightMosaic.normalizeParts(payload.optJSONArray("mosaic_parts"));
            edit.putString("mosaic_parts", LightMosaic.joinParts(parts));
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
