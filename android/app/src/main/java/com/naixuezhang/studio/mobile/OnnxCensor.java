package com.naixuezhang.studio.mobile;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.FloatBuffer;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

/**
 * In-APK mosaic detector: the same censor.onnx shipped in 理塘百宝箱's phone build.
 * YOLOv8 detect, 640 letterbox, classes nipple_f / penis / pussy.
 */
final class OnnxCensor {
    private static final String TAG = "NaiPhone";
    private static final String ASSET = "censor.onnx";
    private static final int SIZE = 640;
    private static final int BOXES = 8400;
    private static final int CHANNELS = 7;
    private static final String[] NAMES = {"nipple_f", "penis", "pussy"};
    private static final float DEFAULT_CONF = 0.15f;
    private static final float NMS_IOU = 0.45f;

    private static final AtomicBoolean ready = new AtomicBoolean(false);
    private static final CountDownLatch loaded = new CountDownLatch(1);
    private static volatile String lastError = "";
    private static OrtEnvironment env;
    private static OrtSession session;

    private OnnxCensor() {}

    static void init(Context context) {
        if (context == null) return;
        final Context app = context.getApplicationContext();
        new Thread(() -> {
            try {
                File model = copyAsset(app);
                env = OrtEnvironment.getEnvironment();
                OrtSession.SessionOptions opts = new OrtSession.SessionOptions();
                opts.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT);
                opts.setIntraOpNumThreads(Math.max(1, Math.min(2, Runtime.getRuntime().availableProcessors())));
                opts.setInterOpNumThreads(1);
                session = env.createSession(model.getAbsolutePath(), opts);
                ready.set(true);
                lastError = "";
                Log.i(TAG, "censor.onnx ready");
            } catch (Throwable error) {
                lastError = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
                Log.e(TAG, "censor.onnx load failed", error);
            } finally {
                loaded.countDown();
            }
        }, "onnx-censor").start();
    }

    static boolean available() {
        return ready.get() && session != null;
    }

    static String status() {
        if (available()) return "机内 ONNX 打码已就绪（censor.onnx）";
        if (lastError != null && !lastError.isEmpty()) return "打码模型未就绪：" + lastError;
        return "打码模型加载中";
    }

    static List<int[]> detectOrFallback(Bitmap src) {
        List<int[]> boxes = detect(src, DEFAULT_CONF);
        if (!boxes.isEmpty()) return boxes;
        return LightMosaic.detectBoxes(src);
    }

    static List<int[]> detect(Bitmap src, float conf) {
        if (src == null) return new ArrayList<int[]>();
        awaitReady();
        if (!available()) return new ArrayList<int[]>();
        float threshold = Math.max(0.06f, Math.min(conf, 0.40f));
        List<Det> raw = new ArrayList<Det>();
        raw.addAll(detectWindow(src, 0, 0, src.getWidth(), src.getHeight(), threshold));
        if (Math.min(src.getWidth(), src.getHeight()) >= 900) {
            int tw = Math.max(320, (int) (src.getWidth() * 0.64f));
            int th = Math.max(320, (int) (src.getHeight() * 0.64f));
            int[] xs = {0, Math.max(0, src.getWidth() - tw)};
            int[] ys = {0, Math.max(0, src.getHeight() - th)};
            for (int y : ys) {
                for (int x : xs) {
                    if (x == 0 && y == 0 && tw == src.getWidth() && th == src.getHeight()) continue;
                    raw.addAll(detectWindow(src, x, y, tw, th, Math.max(0.06f, threshold - 0.02f)));
                }
            }
        }
        List<Det> kept = nms(raw);
        List<int[]> boxes = new ArrayList<int[]>();
        for (Det det : kept) {
            float extra = ("penis".equals(det.name) || "pussy".equals(det.name)) ? 0.42f : 0.0f;
            boxes.add(LightMosaic.expandBox(
                Math.round(det.x1),
                Math.round(det.y1),
                Math.round(det.x2),
                Math.round(det.y2),
                src.getWidth(),
                src.getHeight(),
                0.32f + extra * 0.15f
            ));
            if (extra > 0) {
                int[] grown = LightMosaic.expandBox(
                    Math.round(det.x1),
                    Math.round(det.y1),
                    Math.round(det.x2),
                    Math.round(det.y2 + (det.y2 - det.y1) * extra),
                    src.getWidth(),
                    src.getHeight(),
                    0.28f
                );
                boxes.add(grown);
            }
        }
        return boxes;
    }

    private static void awaitReady() {
        if (ready.get()) return;
        try {
            loaded.await(10, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    private static File copyAsset(Context context) throws Exception {
        File dest = new File(context.getFilesDir(), ASSET);
        long assetSize = 0;
        try (InputStream in = context.getAssets().open(ASSET)) {
            assetSize = in.available();
        }
        if (dest.isFile() && dest.length() == assetSize && dest.length() > 1024 * 1024) {
            return dest;
        }
        File tmp = new File(context.getFilesDir(), ASSET + ".part");
        try (InputStream in = context.getAssets().open(ASSET);
             FileOutputStream out = new FileOutputStream(tmp)) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            out.flush();
        }
        if (dest.exists()) dest.delete();
        if (!tmp.renameTo(dest)) {
            throw new IllegalStateException("无法写入 censor.onnx");
        }
        return dest;
    }

    private static List<Det> detectWindow(Bitmap src, int left, int top, int width, int height, float conf) {
        List<Det> out = new ArrayList<Det>();
        if (width < 8 || height < 8) return out;
        int safeW = Math.min(width, src.getWidth() - left);
        int safeH = Math.min(height, src.getHeight() - top);
        if (safeW < 8 || safeH < 8) return out;
        Bitmap crop = (left == 0 && top == 0 && safeW == src.getWidth() && safeH == src.getHeight())
            ? src
            : Bitmap.createBitmap(src, left, top, safeW, safeH);
        Letterbox box = letterbox(crop, SIZE);
        FloatBuffer input = nchw(box.bitmap);
        if (box.bitmap != crop && box.bitmap != src) box.bitmap.recycle();
        if (crop != src) crop.recycle();
        OrtSession local = session;
        OrtEnvironment localEnv = env;
        if (local == null || localEnv == null) return out;
        try (OnnxTensor tensor = OnnxTensor.createTensor(localEnv, input, new long[]{1, 3, SIZE, SIZE});
             OrtSession.Result result = local.run(Map.of("images", tensor))) {
            float[] data = readOutput(result);
            if (data == null || data.length < CHANNELS * BOXES) return out;
            for (int i = 0; i < BOXES; i++) {
                float cx = data[i];
                float cy = data[BOXES + i];
                float w = data[BOXES * 2 + i];
                float h = data[BOXES * 3 + i];
                int cls = 0;
                float score = data[BOXES * 4 + i];
                for (int c = 1; c < 3; c++) {
                    float s = data[BOXES * (4 + c) + i];
                    if (s > score) {
                        score = s;
                        cls = c;
                    }
                }
                if (score < conf) continue;
                float x1 = (cx - w / 2f - box.padX) / box.scale + left;
                float y1 = (cy - h / 2f - box.padY) / box.scale + top;
                float x2 = (cx + w / 2f - box.padX) / box.scale + left;
                float y2 = (cy + h / 2f - box.padY) / box.scale + top;
                Det det = new Det();
                det.x1 = clamp(x1, 0, src.getWidth());
                det.y1 = clamp(y1, 0, src.getHeight());
                det.x2 = clamp(x2, 0, src.getWidth());
                det.y2 = clamp(y2, 0, src.getHeight());
                if (det.x2 - det.x1 < 4 || det.y2 - det.y1 < 4) continue;
                det.score = score;
                det.name = NAMES[cls];
                out.add(det);
            }
        } catch (Throwable error) {
            lastError = error.getMessage() == null ? "detect failed" : error.getMessage();
            Log.e(TAG, "censor detect failed", error);
        }
        return out;
    }

    private static float[] readOutput(OrtSession.Result result) throws Exception {
        Object value = null;
        if (result.get("output0").isPresent()) {
            value = result.get("output0").get().getValue();
        } else if (result.size() > 0) {
            value = result.get(0).getValue();
        }
        if (value instanceof float[]) return (float[]) value;
        if (value instanceof float[][][]) {
            float[][][] cube = (float[][][]) value;
            if (cube.length > 0 && cube[0].length >= CHANNELS && cube[0][0].length >= BOXES) {
                float[] flat = new float[CHANNELS * BOXES];
                for (int c = 0; c < CHANNELS; c++) {
                    System.arraycopy(cube[0][c], 0, flat, c * BOXES, BOXES);
                }
                return flat;
            }
        }
        if (value instanceof OnnxTensor) {
            FloatBuffer buf = ((OnnxTensor) value).getFloatBuffer();
            float[] flat = new float[CHANNELS * BOXES];
            buf.get(flat);
            return flat;
        }
        try {
            Object first = result.get(0);
            if (first instanceof OnnxTensor) {
                FloatBuffer buf = ((OnnxTensor) first).getFloatBuffer();
                float[] flat = new float[Math.min(buf.remaining(), CHANNELS * BOXES)];
                buf.get(flat);
                return flat;
            }
        } catch (Exception ignored) {}
        return null;
    }

    private static FloatBuffer nchw(Bitmap src) {
        int[] pixels = new int[SIZE * SIZE];
        src.getPixels(pixels, 0, SIZE, 0, 0, SIZE, SIZE);
        FloatBuffer buf = FloatBuffer.allocate(3 * SIZE * SIZE);
        int plane = SIZE * SIZE;
        for (int i = 0; i < pixels.length; i++) {
            int color = pixels[i];
            buf.put(i, ((color >> 16) & 0xff) / 255f);
            buf.put(plane + i, ((color >> 8) & 0xff) / 255f);
            buf.put(plane * 2 + i, (color & 0xff) / 255f);
        }
        buf.rewind();
        return buf;
    }

    private static Letterbox letterbox(Bitmap src, int size) {
        float scale = Math.min(size / (float) src.getWidth(), size / (float) src.getHeight());
        int nw = Math.max(1, Math.round(src.getWidth() * scale));
        int nh = Math.max(1, Math.round(src.getHeight() * scale));
        float padX = (size - nw) / 2f;
        float padY = (size - nh) / 2f;
        Bitmap out = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        out.eraseColor(Color.rgb(114, 114, 114));
        Canvas canvas = new Canvas(out);
        canvas.drawBitmap(
            src,
            null,
            new Rect(Math.round(padX), Math.round(padY), Math.round(padX) + nw, Math.round(padY) + nh),
            new Paint(Paint.FILTER_BITMAP_FLAG)
        );
        return new Letterbox(out, scale, padX, padY);
    }

    private static List<Det> nms(List<Det> raw) {
        Collections.sort(raw, new Comparator<Det>() {
            @Override
            public int compare(Det a, Det b) {
                return Float.compare(b.score, a.score);
            }
        });
        List<Det> kept = new ArrayList<Det>();
        boolean[] drop = new boolean[raw.size()];
        for (int i = 0; i < raw.size(); i++) {
            if (drop[i]) continue;
            Det a = raw.get(i);
            kept.add(a);
            for (int j = i + 1; j < raw.size(); j++) {
                if (drop[j]) continue;
                if (iou(a, raw.get(j)) >= NMS_IOU) drop[j] = true;
            }
        }
        return kept;
    }

    private static float iou(Det a, Det b) {
        float x1 = Math.max(a.x1, b.x1);
        float y1 = Math.max(a.y1, b.y1);
        float x2 = Math.min(a.x2, b.x2);
        float y2 = Math.min(a.y2, b.y2);
        float inter = Math.max(0f, x2 - x1) * Math.max(0f, y2 - y1);
        float union = Math.max(1f, (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter);
        return inter / union;
    }

    private static float clamp(float value, float min, float max) {
        return Math.max(min, Math.min(max, value));
    }

    private static final class Letterbox {
        final Bitmap bitmap;
        final float scale;
        final float padX;
        final float padY;

        Letterbox(Bitmap bitmap, float scale, float padX, float padY) {
            this.bitmap = bitmap;
            this.scale = scale;
            this.padX = padX;
            this.padY = padY;
        }
    }

    private static final class Det {
        float x1;
        float y1;
        float x2;
        float y2;
        float score;
        String name;
    }
}
