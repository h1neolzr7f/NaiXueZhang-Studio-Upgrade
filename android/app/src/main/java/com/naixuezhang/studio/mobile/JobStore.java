package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class JobStore {
    private final Map<String, JSONObject> jobs = new ConcurrentHashMap<>();
    private final Map<String, JSONObject> payloads = new ConcurrentHashMap<>();
    private final Set<String> cancelled = ConcurrentHashMap.newKeySet();
    private final List<String> order = new ArrayList<>();
    private final ExecutorService pool = Executors.newSingleThreadExecutor();
    private final NaiGenerator generator;
    private final ImageStore images;
    private final PipelineStore pipeline;
    private final OutputCatalog catalog;
    private final FavoriteStore library;
    private final GalleryStore gallery;

    JobStore(
        NaiGenerator generator,
        ImageStore images,
        PipelineStore pipeline,
        OutputCatalog catalog,
        FavoriteStore library,
        GalleryStore gallery
    ) {
        this.generator = generator;
        this.images = images;
        this.pipeline = pipeline;
        this.catalog = catalog;
        this.library = library;
        this.gallery = gallery;
    }

    JSONObject start(JSONObject comment, boolean forceFree, int copies, JSONObject meta) throws Exception {
        int total = Math.max(1, Math.min(copies <= 0 ? 1 : copies, 8));
        String id = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        JSONObject source = meta == null ? new JSONObject() : meta;
        String title = JsonUtil.first(source, "title", "source_title");
        if (title.isEmpty() && comment != null) title = comment.optString("title");
        if (title.isEmpty()) title = "本机生成";
        if (gallery != null) gallery.create(id, title, source);
        JSONObject job = new JSONObject();
        synchronized (job) {
            job.put("task_id", id);
            job.put("album_id", id);
            job.put("status", "queued");
            job.put("terminal", false);
            job.put("done", 0);
            job.put("total", total);
            job.put("title", title);
            job.put("items", new JSONArray());
            job.put("queued_at", System.currentTimeMillis());
            job.put("cancellable", true);
            job.put("retryable", false);
        }
        jobs.put(id, job);
        JSONObject stored = new JSONObject();
        stored.put("comment", comment == null ? new JSONObject() : new JSONObject(comment.toString()));
        stored.put("force_free", forceFree);
        stored.put("copies", total);
        stored.put("source", source == null ? new JSONObject() : new JSONObject(source.toString()));
        payloads.put(id, stored);
        synchronized (order) {
            order.add(0, id);
            while (order.size() > 80) {
                String old = order.remove(order.size() - 1);
                jobs.remove(old);
                payloads.remove(old);
                cancelled.remove(old);
            }
        }
        pool.execute(() -> run(id, comment, forceFree, total, source));
        JSONObject started = new JSONObject();
        started.put("ok", true);
        started.put("task_id", id);
        started.put("album_id", id);
        started.put("queued", true);
        started.put("total", total);
        started.put("message", "已加入生成队列");
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

    JSONObject list() {
        JSONArray items = new JSONArray();
        synchronized (order) {
            for (String id : order) {
                JSONObject job = get(id);
                if (job != null) items.put(job);
            }
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("items", items);
            out.put("total", items.length());
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject cancel(String taskId) throws Exception {
        String id = String.valueOf(taskId == null ? "" : taskId).trim();
        JSONObject job = jobs.get(id);
        if (job == null) throw new IllegalArgumentException("队列里没有这个任务");
        cancelled.add(id);
        synchronized (job) {
            if (job.optBoolean("terminal", false)) {
                JSONObject out = new JSONObject(job.toString());
                out.put("ok", true);
                out.put("message", "这个任务已经结束");
                return out;
            }
            if ("queued".equals(job.optString("status"))) {
                job.put("status", "cancelled");
                job.put("terminal", true);
                job.put("cancellable", false);
                job.put("retryable", true);
                job.put("message", "已取消，未发出的张不会再生成");
            } else {
                job.put("cancellable", false);
                job.put("retryable", true);
                job.put("message", "正在取消，当前这张发出后停下");
            }
        }
        JSONObject out = get(id);
        out.put("ok", true);
        out.put("message", "已取消，未发出的张不会再生成");
        return out;
    }

    JSONObject retry(String taskId) throws Exception {
        String id = String.valueOf(taskId == null ? "" : taskId).trim();
        JSONObject job = jobs.get(id);
        JSONObject stored = payloads.get(id);
        if (job == null || stored == null) throw new IllegalArgumentException("没有可重试的任务");
        String status = "";
        synchronized (job) {
            status = job.optString("status");
            if (!"error".equals(status) && !"unknown".equals(status) && !"cancelled".equals(status)) {
                throw new IllegalStateException("只有失败、取消或结果不明的任务才能重试");
            }
        }
        cancelled.remove(id);
        JSONObject comment = stored.optJSONObject("comment");
        JSONObject source = stored.optJSONObject("source");
        boolean forceFree = stored.optBoolean("force_free", true);
        int total = Math.max(1, stored.optInt("copies", 1));
        JSONObject started = start(comment, forceFree, total, source);
        started.put("retried_from", id);
        started.put("message", "unknown".equals(status)
            ? "已重新入队。上次结果不明，可能已扣费，请先看 NovelAI 记录再决定要不要留这张"
            : "已重新入队");
        return started;
    }

    private void run(String id, JSONObject comment, boolean forceFree, int total, JSONObject source) {
        JSONObject job = jobs.get(id);
        if (job == null) return;
        JSONArray collected = new JSONArray();
        try {
            put(job, "status", "running");
            for (int i = 0; i < total; i++) {
                if (cancelled.contains(id)) {
                    synchronized (job) {
                        job.put("status", "cancelled");
                        job.put("terminal", true);
                        job.put("cancellable", false);
                        job.put("retryable", true);
                        job.put("done", i);
                        job.put("message", "已取消，完成 " + i + "/" + total + " 张");
                    }
                    return;
                }
                byte[] png = generator.generatePng(comment, forceFree);
                if (cancelled.contains(id)) {
                    String imageId = images.save(id + "p" + i, png, false);
                    byte[] processed = pipeline.process(png);
                    images.saveFinal(imageId, processed);
                    if (gallery != null) gallery.addImage(id, imageId, "/api/mobile/output/" + imageId + ".png", source);
                    synchronized (job) {
                        job.put("status", "cancelled");
                        job.put("terminal", true);
                        job.put("cancellable", false);
                        job.put("retryable", true);
                        job.put("done", i + 1);
                        job.put("message", "已取消，完成 " + (i + 1) + "/" + total + " 张");
                    }
                    return;
                }
                String imageId = images.save(id + "p" + i, png, false);
                byte[] processed = pipeline.process(png);
                images.saveFinal(imageId, processed);
                if (pipeline.autoAfterGenerate()) {
                    images.exportOne(imageId + "-final", processed);
                }
                String imageUrl = "/api/mobile/output/" + imageId + ".png";
                if (catalog != null) catalog.add(imageId, source);
                if (gallery != null) gallery.addImage(id, imageId, imageUrl, source);
                if (library != null) {
                    JSONObject record = comment == null ? new JSONObject() : new JSONObject(comment.toString());
                    record.put("title", JsonUtil.first(source, "title", "source_title"));
                    if (record.optString("title").isEmpty()) record.put("title", "本机生成");
                    library.importGeneratedPage(id, i, record, processed, total);
                }
                JSONObject item = new JSONObject();
                item.put("ok", true);
                item.put("image_url", imageUrl);
                item.put("gallery_url", imageUrl);
                item.put("album_id", id);
                item.put("library_id", "g" + id);
                item.put("page_index", i);
                item.put("message", pipeline.autoAfterGenerate()
                    ? "完成：已入图库、跑完 2x 拉伸/清元数据、存进相册"
                    : "完成：已入图库并跑完流水线");
                collected.put(item);
                synchronized (job) {
                    job.put("items", new JSONArray(collected.toString()));
                    job.put("done", i + 1);
                    job.put("status", i + 1 >= total ? "done" : "running");
                    job.put("message", "生成中 " + (i + 1) + "/" + total);
                }
            }
            synchronized (job) {
                job.put("status", "done");
                job.put("terminal", true);
                job.put("cancellable", false);
                job.put("retryable", false);
                job.put("done", total);
                job.put("message", "完成 " + total + " 张，已按同一任务收入图库");
            }
        } catch (NaiGenerator.NaiError error) {
            fail(job, error.getMessage(), error.billingUncertain, collected);
        } catch (IllegalStateException error) {
            boolean missing = "missing_token".equals(error.getMessage());
            fail(job, missing ? "NovelAI token is not configured" : error.getMessage(), false, collected);
        } catch (Exception error) {
            fail(job, error.getMessage() == null ? "生图失败" : error.getMessage(), false, collected);
        }
    }

    private void fail(JSONObject job, String message, boolean unknown, JSONArray collected) {
        try {
            JSONObject item = new JSONObject();
            item.put("ok", false);
            item.put("message", message);
            JSONArray items = collected == null ? new JSONArray() : new JSONArray(collected.toString());
            items.put(item);
            synchronized (job) {
                job.put("items", items);
                job.put("status", unknown ? "unknown" : "error");
                job.put("terminal", true);
                job.put("cancellable", false);
                job.put("retryable", true);
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
