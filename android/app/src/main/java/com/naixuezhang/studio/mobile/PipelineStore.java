package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

final class PipelineStore {
    private static final String PREFS = "nai_phone_pipeline";
    private static final String KEY_AUTO = "auto_after_generate";
    private final SharedPreferences prefs;
    private final ImageStore images;

    PipelineStore(Context context, ImageStore images) {
        this.prefs = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        this.images = images;
    }

    boolean autoAfterGenerate() {
        return prefs.getBoolean(KEY_AUTO, true);
    }

    JSONObject config() throws Exception {
        JSONObject cfg = new JSONObject();
        cfg.put("auto_after_generate", autoAfterGenerate());
        cfg.put("save_to_gallery", true);
        cfg.put("upscale", false);
        cfg.put("mosaic", false);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("config", cfg);
        return out;
    }

    JSONObject setConfig(JSONObject payload) throws Exception {
        if (payload != null && payload.has("auto_after_generate")) {
            prefs.edit().putBoolean(KEY_AUTO, payload.optBoolean("auto_after_generate")).apply();
        }
        return config();
    }

    JSONObject status() throws Exception {
        JSONObject job = new JSONObject();
        job.put("status", "idle");
        JSONObject backlog = new JSONObject();
        backlog.put("count", 0);
        backlog.put("pending", 0);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("job", job);
        out.put("backlog", backlog);
        out.put("saved", images.pendingCount());
        return out;
    }

    JSONObject runMissing() throws Exception {
        int saved = images.exportMissing();
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("message", "已把 " + saved + " 张本地生成图补存到相册");
        return out;
    }
}
