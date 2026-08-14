package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class JobStore {
    private final Map<String, JSONObject> jobs = new ConcurrentHashMap<>();
    private final ExecutorService pool = Executors.newSingleThreadExecutor();
    private final NaiGenerator generator;
    private final ImageStore images;
    private final PipelineStore pipeline;

    JobStore(NaiGenerator generator, ImageStore images, PipelineStore pipeline) {
        this.generator = generator;
        this.images = images;
        this.pipeline = pipeline;
    }

    JSONObject start(JSONObject comment, boolean forceFree) throws Exception {
        String id = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        JSONObject job = new JSONObject();
        synchronized (job) {
            job.put("task_id", id);
            job.put("status", "queued");
            job.put("terminal", false);
            job.put("done", 0);
            job.put("total", 1);
            job.put("items", new JSONArray());
        }
        jobs.put(id, job);
        pool.execute(() -> run(id, comment, forceFree));
        JSONObject started = new JSONObject();
        started.put("ok", true);
        started.put("task_id", id);
        started.put("queued", true);
        started.put("message", "generation queued");
        return started;
    }

    JSONObject get(String taskId) {
        JSONObject job = jobs.get(String.valueOf(taskId == null ? "" : taskId).trim());
        if (job == null) return null;
        synchronized (job) {
            try {
                return new JSONObject(job.toString());
            } catch (Exception e) {
                return job;
            }
        }
    }

    private void run(String id, JSONObject comment, boolean forceFree) {
        JSONObject job = jobs.get(id);
        if (job == null) return;
        try {
            put(job, "status", "running");
            byte[] png = generator.generatePng(comment, forceFree);
            String imageId = images.save(id, png, pipeline.autoAfterGenerate());
            JSONObject item = new JSONObject();
            item.put("ok", true);
            item.put("image_url", "/api/mobile/output/" + imageId + ".png");
            item.put("gallery_url", item.optString("image_url"));
            item.put("message", pipeline.autoAfterGenerate() ? "完成，已保存到相册" : "完成");
            synchronized (job) {
                job.put("items", new JSONArray().put(item));
                job.put("done", 1);
                job.put("status", "done");
                job.put("terminal", true);
                job.put("message", item.optString("message"));
            }
        } catch (NaiGenerator.NaiError error) {
            fail(job, error.getMessage(), error.billingUncertain);
        } catch (IllegalStateException error) {
            boolean missing = "missing_token".equals(error.getMessage());
            fail(job, missing ? "NovelAI token is not configured" : error.getMessage(), false);
        } catch (Exception error) {
            fail(job, error.getMessage() == null ? "生图失败" : error.getMessage(), false);
        }
    }

    private void fail(JSONObject job, String message, boolean unknown) {
        try {
            JSONObject item = new JSONObject();
            item.put("ok", false);
            item.put("message", message);
            synchronized (job) {
                job.put("items", new JSONArray().put(item));
                job.put("status", unknown ? "unknown" : "error");
                job.put("terminal", true);
                job.put("message", unknown ? (message + "。这次可能已扣费，不要自动重试") : message);
            }
        } catch (Exception ignored) {}
    }

    private static void put(JSONObject job, String key, Object value) throws Exception {
        synchronized (job) {
            job.put(key, value);
        }
    }
}
