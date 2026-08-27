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
        String message = "已加入生成队列";
        if (storedPages.length() > 1) message = "已加入生成队列，" + storedPages.length() + " 页收进同一组";
        if (generator.concurrency() > 1 && units.size() > 1) message += "，" + generator.concurrency() + " 路并发";
        started.put("message", message);
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
                job.put("message", "生成中 0/" + total + (generator.concurrency() > 1 ? (" · " + generator.concurrency() + " 路并发") : ""));
            }
            CountDownLatch latch = new CountDownLatch(total);
            for (int i = 0; i < total; i++) {
                final int index = i;
                final JSONObject unit = units.get(i);
                workers.execute(() -> {
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
                        byte[] png = generator.generatePng(page, forceFree);
                        String imageId = images.save(id + "p" + index, png, false);
                        byte[] processed = pipeline.process(png);
                        images.saveFinal(imageId, processed);
                        if (pipeline.autoAfterGenerate()) {
                            images.exportOne(imageId + "-final", processed);
                        }
                        String imageUrl = "/api/mobile/output/" + imageId + ".png";
                        if (catalog != null) catalog.add(imageId, source);
                        if (gallery != null) gallery.addImage(id, imageId, imageUrl, source);
                        if (library != null) {
                            JSONObject record = new JSONObject(page.toString());
                            record.put("title", JsonUtil.first(source, "title", "source_title"));
                            if (record.optString("title").isEmpty()) record.put("title", "本机生成");
                            library.importGeneratedPage(id, index, record, processed, total);
                        }
                        JSONObject item = new JSONObject();
                        item.put("ok", true);
                        item.put("image_url", imageUrl);
                        item.put("gallery_url", imageUrl);
                        item.put("album_id", id);
                        item.put("library_id", "g" + id);
                        item.put("page_index", pageIndex);
                        item.put("message", pipeline.autoAfterGenerate()
                            ? "完成：已入图库、跑完 2x 拉伸/清元数据、存进相册"
                            : "完成：已入图库并跑完流水线");
                        int done = finished.incrementAndGet();
                        synchronized (job) {
                            collected.put(item);
                            job.put("items", new JSONArray(collected.toString()));
                            job.put("done", done);
                            job.put("status", done >= total ? "done" : "running");
                            job.put("message", "生成中 " + done + "/" + total
                                + (generator.concurrency() > 1 ? (" · " + generator.concurrency() + " 路并发") : ""));
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
}