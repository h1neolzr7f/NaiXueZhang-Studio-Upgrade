package com.naixuezhang.studio.mobile;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

final class JobStore {
    private final Map<String, JSONObject> jobs = new ConcurrentHashMap<>();
    private final Map<String, JSONObject> payloads = new ConcurrentHashMap<>();
    private final Set<String> cancelled = ConcurrentHashMap.newKeySet();
    private final List<String> order = new ArrayList<>();
    private final ExecutorService jobsPool = Executors.newCachedThreadPool();
    private final ExecutorService workers = Executors.newFixedThreadPool(8);
    private final NaiGenerator generator;
    private final ImageStore images;
    private final PipelineStore pipeline;
    private final OutputCatalog catalog;
    private final FavoriteStore library;
    private final GalleryStore gallery;
    private final AtomicInteger learnedMs = new AtomicInteger(14000);
    private final AtomicInteger learnedSamples = new AtomicInteger(0);

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
        JSONArray pages = new JSONArray();
        JSONObject page = new JSONObject();
        page.put("comment", comment == null ? new JSONObject() : comment);
        page.put("page_index", meta == null ? 0 : meta.optInt("page_index", 0));
        pages.put(page);
        return startPages(pages, forceFree, copies, meta);
    }

    JSONObject startPages(JSONArray pages, boolean forceFree, int copies, JSONObject meta) throws Exception {
        int copiesEach = Math.max(1, Math.min(copies <= 0 ? 1 : copies, 8));
        JSONArray storedPages = new JSONArray();
        List<JSONObject> units = new ArrayList<JSONObject>();
        JSONArray sourcePages = pages == null ? new JSONArray() : pages;
        for (int i = 0; i < sourcePages.length(); i++) {
            JSONObject page = sourcePages.optJSONObject(i);
            if (page == null) continue;
            JSONObject comment = page.optJSONObject("comment");
            if (comment == null) comment = page.optJSONObject("patched_comment");
            if (comment == null) continue;
            JSONObject kept = new JSONObject();
            kept.put("comment", new JSONObject(comment.toString()));
            kept.put("page_index", page.optInt("page_index", i));
            storedPages.put(kept);
            for (int copy = 0; copy < copiesEach; copy++) {
                JSONObject unit = new JSONObject();
                unit.put("comment", new JSONObject(comment.toString()));
                unit.put("page_index", page.optInt("page_index", i));
                unit.put("copy_index", copy);
                units.add(unit);
            }
        }
        if (units.isEmpty()) throw new IllegalArgumentException("没有可生成的页");
        if (units.size() > 40) throw new IllegalArgumentException("一次最多 40 张，先少选几页或少填张数");
        String id = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        JSONObject source = meta == null ? new JSONObject() : meta;
        String title = JsonUtil.first(source, "title", "source_title");
        if (title.isEmpty()) title = "本机生成";
        if (storedPages.length() > 1 && !title.contains("系列")) title = title + " · 全系列";
        if (gallery != null) gallery.create(id, title, source);
        JSONObject job = new JSONObject();
        synchronized (job) {
            job.put("task_id", id);
            job.put("album_id", id);
            job.put("status", "queued");
            job.put("terminal", false);
            job.put("done", 0);
            job.put("total", units.size());
            job.put("pages", storedPages.length());
            job.put("copies", copiesEach);
            job.put("title", title);
            job.put("items", new JSONArray());
            job.put("queued_at", System.currentTimeMillis());
            job.put("cancellable", true);
            job.put("retryable", false);
            job.put("running", 0);
            job.put("progress", 2);
            job.put("stage", "queued");
            job.put("stage_label", "排队等待");
            job.put("concurrency", generator.concurrency());
            attachEta(job, units.size(), generator.concurrency(), 0);
        }
        jobs.put(id, job);
        JSONObject stored = new JSONObject();
        stored.put("comment", storedPages.optJSONObject(0) == null
            ? new JSONObject()
            : storedPages.optJSONObject(0).optJSONObject("comment"));
        stored.put("pages", storedPages);
        stored.put("force_free", forceFree);
        stored.put("copies", copiesEach);
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
        jobsPool.execute(() -> run(id, units, forceFree, source));
        JSONObject started = new JSONObject();
        started.put("ok", true);
        started.put("task_id", id);
        started.put("album_id", id);
        started.put("queued", true);
        started.put("total", units.size());
        started.put("pages", storedPages.length());
        started.put("concurrency", generator.concurrency());
        JSONObject seeded = get(id);
        if (seeded != null) {
            started.put("progress", seeded.optInt("progress", 2));
            started.put("eta_seconds", seeded.optInt("eta_seconds", 0));
            started.put("eta_text", seeded.optString("eta_text"));
            started.put("stage", seeded.optString("stage", "queued"));
            started.put("stage_label", seeded.optString("stage_label", "排队等待"));
            started.put("expected_seconds", seeded.optInt("expected_seconds", seeded.optInt("eta_seconds", 0)));
        }
        String message = "已加入生成队列";
        if (storedPages.length() > 1) message = "已加入生成队列，" + storedPages.length() + " 页收进同一组";
        if (generator.concurrency() > 1 && units.size() > 1) message += "，" + generator.concurrency() + " 路并发";
        if (seeded != null && seeded.optInt("eta_seconds") > 0) {
            message += "，预计 " + seeded.optString("eta_text", "还要 " + seeded.optInt("eta_seconds") + " 秒");
        }
        started.put("message", message);
        return started;
    }

    JSONObject get(String taskId) {
        JSONObject job = jobs.get(String.valueOf(taskId == null ? "" : taskId).trim());
        if (job == null) return null;
        synchronized (job) {
            try {
                JSONObject copy = new JSONObject(job.toString());
                decorateLive(copy);
                return copy;
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
            out.put("concurrency", generator.concurrency());
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
        JSONArray pages = stored.optJSONArray("pages");
        JSONObject started = (pages != null && pages.length() > 0)
            ? startPages(pages, forceFree, total, source)
            : start(comment, forceFree, total, source);
        started.put("retried_from", id);
        started.put("message", "unknown".equals(status)
            ? "已重新入队。上次结果不明，可能已扣费，请先看 NovelAI 记录再决定要不要留这张"
            : "已重新入队");
        return started;
    }

    JSONObject delete(String taskId) throws Exception {
        String id = String.valueOf(taskId == null ? "" : taskId).trim();
        JSONObject job = jobs.get(id);
        if (job == null) throw new IllegalArgumentException("队列里没有这个任务");
        cancelled.add(id);
        jobs.remove(id);
        payloads.remove(id);
        synchronized (order) {
            order.remove(id);
        }
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("task_id", id);
        out.put("message", "已从队列删除");
        return out;
    }

    private void run(String id, List<JSONObject> units, boolean forceFree, JSONObject source) {
        JSONObject job = jobs.get(id);
        if (job == null) return;
        final int total = units.size();
        JSONArray collected = new JSONArray();
        AtomicInteger finished = new AtomicInteger(0);
        AtomicReference<NaiGenerator.NaiError> unknown = new AtomicReference<NaiGenerator.NaiError>();
        AtomicReference<Exception> lastError = new AtomicReference<Exception>();
        try {
            put(job, "status", "running");
            synchronized (job) {
                job.put("concurrency", generator.concurrency());
                job.put("started_at", System.currentTimeMillis());
                job.put("wave_started_at", System.currentTimeMillis());
                job.put("stage", "requesting");
                job.put("stage_label", "正在请求 NovelAI");
                job.put("stage_at", System.currentTimeMillis());
                job.put("running", 0);
                job.put("message", "生成中 0/" + total + (generator.concurrency() > 1 ? (" · " + generator.concurrency() + " 路并发") : ""));
            }
            CountDownLatch latch = new CountDownLatch(total);
            for (int i = 0; i < total; i++) {
                final int index = i;
                final JSONObject unit = units.get(i);
                workers.execute(() -> {
                    long unitStart = System.currentTimeMillis();
                    boolean charged = false;
                    try {
                        if (cancelled.contains(id) || unknown.get() != null) return;
                        JSONObject comment = unit.optJSONObject("comment");
                        JSONObject page = comment == null ? new JSONObject() : new JSONObject(comment.toString());
                        int copyIndex = unit.optInt("copy_index", index);
                        int pageIndex = unit.optInt("page_index", index);
                        if (page.has("seed") && !"".equals(String.valueOf(page.opt("seed")))) {
                            try {
                                int seed = Integer.parseInt(String.valueOf(page.opt("seed")));
                                if (seed >= 0) page.put("seed", seed + copyIndex);
                            } catch (Exception ignored) {}
                        }
                        bumpRunning(job, 1);
                        charged = true;
                        markStage(job, "generating", "正在出图");
                        byte[] png = generator.generatePng(page, forceFree);
                        markStage(job, "saving", "先写入图库");
                        String imageId = images.save(id + "p" + index, png, false);
                        String imageUrl = "/api/mobile/output/" + imageId + ".png";
                        if (catalog != null) catalog.add(imageId, source);
                        if (gallery != null) gallery.addImage(id, imageId, imageUrl, source);
                        if (library != null) {
                            JSONObject record = new JSONObject(page.toString());
                            record.put("title", JsonUtil.first(source, "title", "source_title"));
                            if (record.optString("title").isEmpty()) record.put("title", "本机生成");
                            library.importGeneratedPage(id, index, record, png, total);
                        }
                        byte[] processed = png;
                        boolean changed = false;
                        if (pipeline.upscaleEnabled() || pipeline.metadataEnabled()) {
                            markStage(job, "upscale", pipeline.upscaleEnabled() ? "本机超分" : "清元数据");
                            processed = pipeline.processWithoutMosaic(png);
                            changed = true;
                        }
                        if (pipeline.mosaicEnabled()) {
                            markStage(job, "mosaic", "机内打码：" + pipeline.mosaicMethod());
                            processed = pipeline.processMosaicOnly(processed);
                            changed = true;
                        }
                        if (changed) images.saveFinal(imageId, processed);
                        if (pipeline.autoAfterGenerate()) {
                            images.exportOne(imageId + (changed ? "-final" : ""), processed);
                        }
                        JSONObject item = new JSONObject();
                        item.put("ok", true);
                        item.put("image_url", imageUrl);
                        item.put("gallery_url", imageUrl);
                        item.put("album_id", id);
                        item.put("library_id", "g" + id);
                        item.put("page_index", pageIndex);
                        item.put("mosaic", pipeline.mosaicEnabled());
                        item.put("message", pipeline.mosaicEnabled()
                            ? (pipeline.autoAfterGenerate()
                                ? ("完成：已先入库，最后打码（" + pipeline.summary() + "），存进相册")
                                : ("完成：已先入库，最后打码（" + pipeline.summary() + "）"))
                            : (pipeline.autoAfterGenerate()
                                ? "完成：已入库，未打码，原图已进图库和相册"
                                : "完成：已入库，未打码"));
                        rememberDuration((int) (System.currentTimeMillis() - unitStart));
                        int done = finished.incrementAndGet();
                        synchronized (job) {
                            collected.put(item);
                            job.put("items", new JSONArray(collected.toString()));
                            job.put("done", done);
                            job.put("status", done >= total ? "done" : "running");
                            job.put("wave_started_at", System.currentTimeMillis());
                            job.put("message", "生成中 " + done + "/" + total
                                + (generator.concurrency() > 1 ? (" · " + generator.concurrency() + " 路并发") : ""));
                            if (done >= total) {
                                job.put("stage", "done");
                                job.put("stage_label", "完成");
                                job.put("progress", 100);
                                job.put("eta_seconds", 0);
                                job.put("eta_text", "已完成");
                            }
                        }
                    } catch (NaiGenerator.NaiError error) {
                        lastError.set(error);
                        if (error.billingUncertain) {
                            unknown.set(error);
                            cancelled.add(id);
                        }
                        synchronized (job) {
                            JSONObject item = new JSONObject();
                            try {
                                item.put("ok", false);
                                item.put("page_index", unit.optInt("page_index", index));
                                item.put("message", error.getMessage());
                                collected.put(item);
                                job.put("items", new JSONArray(collected.toString()));
                            } catch (Exception ignored) {}
                        }
                    } catch (Exception error) {
                        lastError.set(error);
                        synchronized (job) {
                            JSONObject item = new JSONObject();
                            try {
                                item.put("ok", false);
                                item.put("page_index", unit.optInt("page_index", index));
                                item.put("message", error.getMessage() == null ? "生图失败" : error.getMessage());
                                collected.put(item);
                                job.put("items", new JSONArray(collected.toString()));
                            } catch (Exception ignored) {}
                        }
                    } finally {
                        if (charged) bumpRunning(job, -1);
                        latch.countDown();
                    }
                });
            }
            latch.await();
            NaiGenerator.NaiError uncertain = unknown.get();
            if (uncertain != null) {
                fail(job, uncertain.getMessage(), true, collected);
                return;
            }
            if (cancelled.contains(id)) {
                synchronized (job) {
                    job.put("status", "cancelled");
                    job.put("terminal", true);
                    job.put("cancellable", false);
                    job.put("retryable", true);
                    job.put("done", finished.get());
                    job.put("message", "已取消，完成 " + finished.get() + "/" + total + " 张");
                }
                return;
            }
            Exception error = lastError.get();
            if (error != null && finished.get() < total) {
                fail(job, friendlyGenerateError(error.getMessage()), false, collected);
                return;
            }
            synchronized (job) {
                job.put("status", "done");
                job.put("terminal", true);
                job.put("cancellable", false);
                job.put("retryable", false);
                job.put("done", finished.get());
                job.put("message", "完成 " + finished.get() + " 张，已按同一任务收入图库"
                    + (generator.concurrency() > 1 ? (" · " + generator.concurrency() + " 路并发") : ""));
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            fail(job, "生成被中断", false, collected);
        } catch (Exception error) {
            fail(job, friendlyGenerateError(error.getMessage()), false, collected);
        }
    }

    static String friendlyGenerateError(String raw) {
        String message = raw == null ? "" : raw.trim();
        String lower = message.toLowerCase(java.util.Locale.ROOT);
        if (lower.contains("connection closed") || lower.contains("connection reset")
            || lower.contains("broken pipe") || lower.contains("unexpected end")
            || lower.contains("failed to connect") || lower.contains("生成连接被掐断")) {
            return "生成连接被掐断。没看到成功回执，先看 NovelAI 记录有没有扣费，再手动重试";
        }
        if ("missing_token".equals(message) || lower.contains("not configured")) {
            return "先在设置里填 NovelAI Token";
        }
        return message.isEmpty() ? "生图失败" : message;
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

    private void bumpRunning(JSONObject job, int delta) {
        synchronized (job) {
            try {
                int next = Math.max(0, job.optInt("running", 0) + delta);
                job.put("running", next);
                if (delta > 0 && job.optLong("wave_started_at", 0L) <= 0L) {
                    job.put("wave_started_at", System.currentTimeMillis());
                }
            } catch (Exception ignored) {}
        }
    }

    private static void markStage(JSONObject job, String stage, String label) {
        synchronized (job) {
            try {
                job.put("stage", stage);
                job.put("stage_label", label);
                job.put("stage_at", System.currentTimeMillis());
                if (!job.optBoolean("terminal", false)) {
                    job.put("message", label);
                }
            } catch (Exception ignored) {}
        }
    }

    private void rememberDuration(int elapsedMs) {
        if (elapsedMs < 800) return;
        int samples = learnedSamples.incrementAndGet();
        int prev = learnedMs.get();
        int next = samples <= 1 ? elapsedMs : (int) (prev * 0.72 + elapsedMs * 0.28);
        learnedMs.set(Math.max(3500, Math.min(90000, next)));
    }

    private void attachEta(JSONObject job, int leftover, int concurrency, int running) {
        try {
            int conc = Math.max(1, concurrency);
            int wait = Math.max(0, leftover);
            int avg = Math.max(3500, learnedMs.get() + (pipeline == null ? 1200 : pipeline.estimateMs()));
            int waves = wait <= 0 ? 0 : (wait + conc - 1) / conc;
            long eta = (long) waves * avg;
            if (running > 0) {
                long waveAt = job.optLong("wave_started_at", job.optLong("started_at", 0L));
                if (waveAt > 0L) eta = Math.max(800L, eta - (System.currentTimeMillis() - waveAt));
            }
            int seconds = wait <= 0 ? 0 : Math.max(1, (int) Math.ceil(eta / 1000.0));
            job.put("expected_seconds", Math.max(seconds, (wait + conc - 1) / conc * Math.max(1, avg / 1000)));
            job.put("eta_seconds", seconds);
            job.put("eta_text", formatEta(seconds));
            job.put("sec_per_image", Math.round(learnedMs.get() / 100.0) / 10.0);
        } catch (Exception ignored) {}
    }

    private void decorateLive(JSONObject job) {
        try {
            String status = job.optString("status");
            boolean terminal = job.optBoolean("terminal", false)
                || "done".equals(status) || "error".equals(status)
                || "cancelled".equals(status) || "unknown".equals(status);
            int done = job.optInt("done");
            int total = Math.max(1, job.optInt("total"));
            int running = job.optInt("running");
            String stage = job.optString("stage", status);
            long now = System.currentTimeMillis();
            double frac = done;
            if ("queued".equals(status)) {
                frac = 0.02;
            } else if (!terminal && running > 0) {
                double unit = stageWeight(stage);
                if ("generating".equals(stage) || "requesting".equals(stage)) {
                    long stageAt = job.optLong("stage_at", now);
                    double t = Math.min(1.0, (now - stageAt) / 14000.0);
                    unit = 0.12 + t * 0.50;
                }
                frac += running * unit;
            }
            int progress = terminal && "done".equals(status)
                ? 100
                : Math.max(2, Math.min(99, (int) Math.round(frac * 100.0 / total)));
            if (terminal && !"done".equals(status)) {
                progress = Math.max(progress, (int) Math.round(done * 100.0 / total));
            }
            job.put("progress", progress);
            if (job.optString("stage_label").isEmpty()) {
                job.put("stage_label", stageLabel(stage, status));
            }
            long started = job.optLong("started_at", job.optLong("queued_at", 0L));
            if (started > 0L) job.put("elapsed_ms", now - started);
            if (terminal) {
                job.put("eta_seconds", 0);
                if ("done".equals(status)) job.put("eta_text", "已完成");
                else if (job.optString("eta_text").isEmpty()) job.put("eta_text", "");
                return;
            }
            attachEta(job, Math.max(0, total - done), Math.max(1, job.optInt("concurrency", generator.concurrency())), running);
        } catch (Exception ignored) {}
    }

    private static double stageWeight(String stage) {
        if ("mosaic".equals(stage)) return 0.94;
        if ("upscale".equals(stage) || "pipeline".equals(stage)) return 0.84;
        if ("saving".equals(stage)) return 0.72;
        if ("generating".equals(stage)) return 0.55;
        if ("requesting".equals(stage)) return 0.16;
        return 0.08;
    }

    static String stageLabel(String stage, String status) {
        if ("done".equals(status) || "done".equals(stage)) return "完成";
        if ("error".equals(status)) return "失败";
        if ("cancelled".equals(status)) return "已取消";
        if ("unknown".equals(status)) return "结果不明";
        if ("queued".equals(stage) || "queued".equals(status)) return "排队等待";
        if ("requesting".equals(stage)) return "正在请求 NovelAI";
        if ("generating".equals(stage) || "running".equals(stage)) return "正在出图";
        if ("upscale".equals(stage)) return "本机超分";
        if ("mosaic".equals(stage)) return "机内打码";
        if ("pipeline".equals(stage)) return "本机后处理";
        if ("saving".equals(stage)) return "写入图库";
        return "生成中";
    }

    static String formatEta(int seconds) {
        if (seconds <= 0) return "即将完成";
        if (seconds < 60) return "预计还要 " + seconds + " 秒";
        int minutes = seconds / 60;
        int rest = seconds % 60;
        if (rest == 0) return "预计还要 " + minutes + " 分钟";
        return "预计还要 " + minutes + " 分 " + rest + " 秒";
    }
}