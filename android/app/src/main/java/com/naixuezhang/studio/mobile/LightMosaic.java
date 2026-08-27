package com.naixuezhang.studio.mobile;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * Mosaic paint + fallback detector. Prefer OnnxCensor (bundled censor.onnx).
 * Heuristic skin boxes are only used if the ONNX session is not ready.
 */
final class LightMosaic {
    static final String[] METHODS = {"像素", "模糊", "线条", "纯色", "黑条", "表情"};
    static final String[] PARTS = {"欧金金", "欧芒果", "欧派派", "欧西利"};

    private LightMosaic() {}

    static String normalizeMethod(String raw) {
        String method = raw == null ? "" : raw.trim();
        if ("模糊".equals(method) || "blur".equalsIgnoreCase(method)) return "模糊";
        if ("线条".equals(method) || "line".equalsIgnoreCase(method) || "hatch".equalsIgnoreCase(method)) {
            return "线条";
        }
        if ("纯色".equals(method) || "solid".equalsIgnoreCase(method) || "color".equalsIgnoreCase(method)) {
            return "纯色";
        }
        if ("黑条".equals(method) || "bar".equalsIgnoreCase(method) || "black".equalsIgnoreCase(method)) {
            return "黑条";
        }
        if ("表情".equals(method) || "emoji".equalsIgnoreCase(method)) return "表情";
        if ("不打码".equals(method) || "off".equalsIgnoreCase(method) || "none".equalsIgnoreCase(method)) {
            return "不打码";
        }
        return "像素";
    }

    static int normalizeIntensity(int intensity) {
        return Math.max(8, Math.min(intensity <= 0 ? 36 : intensity, 80));
    }

    static int normalizeSensitivity(int level) {
        return Math.max(1, Math.min(level <= 0 ? 8 : level, 10));
    }

    static int normalizeDilate(int dilate) {
        return Math.max(0, Math.min(dilate < 0 ? 28 : dilate, 64));
    }

    static float confFromSensitivity(int level) {
        int n = normalizeSensitivity(level);
        return Math.max(0.06f, Math.min(0.32f - (n - 1) * 0.03f, 0.40f));
    }

    static List<String> normalizeParts(org.json.JSONArray raw) {
        List<String> out = new ArrayList<String>();
        if (raw != null) {
            for (int i = 0; i < raw.length(); i++) {
                String part = normalizePart(raw.optString(i));
                if (!part.isEmpty() && !out.contains(part)) out.add(part);
            }
        }
        if (out.isEmpty()) {
            for (String part : PARTS) out.add(part);
        }
        return out;
    }

    static List<String> parseParts(String raw) {
        List<String> out = new ArrayList<String>();
        String text = raw == null ? "" : raw.trim();
        if (text.isEmpty()) {
            for (String part : PARTS) out.add(part);
            return out;
        }
        for (String item : text.split("[,，|\\s]+")) {
            String part = normalizePart(item);
            if (!part.isEmpty() && !out.contains(part)) out.add(part);
        }
        if (out.isEmpty()) {
            for (String part : PARTS) out.add(part);
        }
        return out;
    }

    static String joinParts(List<String> parts) {
        if (parts == null || parts.isEmpty()) return String.join(",", PARTS);
        return String.join(",", parts);
    }

    static String normalizePart(String raw) {
        String part = raw == null ? "" : raw.trim();
        if ("欧金金".equals(part) || "penis".equalsIgnoreCase(part)) return "欧金金";
        if ("欧芒果".equals(part) || "pussy".equalsIgnoreCase(part)) return "欧芒果";
        if ("欧派派".equals(part) || "nipple".equalsIgnoreCase(part) || "nipple_f".equalsIgnoreCase(part)) {
            return "欧派派";
        }
        if ("欧西利".equals(part) || "anus".equalsIgnoreCase(part)) return "欧西利";
        return "";
    }

    static Result apply(Bitmap src, String method, int intensity) {
        return apply(src, method, intensity, parseParts(""), 8, 28);
    }

    static Result apply(Bitmap src, String method, int intensity, List<String> parts, int sensitivity, int dilate) {
        if (src == null) return new Result(null, 0, normalizeMethod(method));
        String kind = normalizeMethod(method);
        if ("不打码".equals(kind)) return new Result(src, 0, kind);
        int strength = normalizeIntensity(intensity);
        List<int[]> boxes = OnnxCensor.detectOrFallback(src, parts, sensitivity, dilate);
        if (boxes.isEmpty()) return new Result(src, 0, kind);
        Bitmap out = src.copy(Bitmap.Config.ARGB_8888, true);
        if (out == null) return new Result(src, 0, kind);
        int block = Math.max(8, Math.min(40, strength / 2));
        for (int[] box : boxes) {
            paintBox(out, box[0], box[1], box[2], box[3], kind, block);
        }
        return new Result(out, boxes.size(), kind);
    }

    static boolean isSkin(int color) {
        int r = (color >> 16) & 0xff;
        int g = (color >> 8) & 0xff;
        int b = color & 0xff;
        int y = (299 * r + 587 * g + 114 * b) / 1000;
        int cb = 128 + (-169 * r - 331 * g + 500 * b) / 1000;
        int cr = 128 + (500 * r - 419 * g - 81 * b) / 1000;
        if (y < 40 || y > 245) return false;
        if (cb < 77 || cb > 127 || cr < 133 || cr > 173) return false;
        int max = Math.max(r, Math.max(g, b));
        int min = Math.min(r, Math.min(g, b));
        return r > g && r > 70 && (max - min) > 12;
    }

    static List<int[]> detectBoxes(Bitmap src) {
        int width = src.getWidth();
        int height = src.getHeight();
        int cell = Math.max(8, Math.min(width, height) / 24);
        int cols = Math.max(1, width / cell);
        int rows = Math.max(1, height / cell);
        boolean[][] skin = new boolean[rows][cols];
        for (int row = 0; row < rows; row++) {
            for (int col = 0; col < cols; col++) {
                int x = Math.min(width - 1, col * cell + cell / 2);
                int y = Math.min(height - 1, row * cell + cell / 2);
                float yn = height <= 1 ? 0f : (float) y / (float) height;
                float xn = width <= 1 ? 0f : (float) x / (float) width;
                boolean chest = yn >= 0.20f && yn <= 0.52f && xn >= 0.16f && xn <= 0.84f;
                boolean lower = yn >= 0.46f && yn <= 0.90f && xn >= 0.20f && xn <= 0.80f;
                if ((chest || lower) && isSkin(src.getPixel(x, y))) skin[row][col] = true;
            }
        }
        boolean[][] seen = new boolean[rows][cols];
        List<int[]> boxes = new ArrayList<int[]>();
        int[][] dirs = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
        for (int row = 0; row < rows; row++) {
            for (int col = 0; col < cols; col++) {
                if (!skin[row][col] || seen[row][col]) continue;
                int r0 = row;
                int r1 = row;
                int c0 = col;
                int c1 = col;
                int count = 0;
                ArrayDeque<int[]> queue = new ArrayDeque<int[]>();
                queue.add(new int[]{row, col});
                seen[row][col] = true;
                while (!queue.isEmpty()) {
                    int[] at = queue.poll();
                    count += 1;
                    r0 = Math.min(r0, at[0]);
                    r1 = Math.max(r1, at[0]);
                    c0 = Math.min(c0, at[1]);
                    c1 = Math.max(c1, at[1]);
                    for (int[] dir : dirs) {
                        int nr = at[0] + dir[0];
                        int nc = at[1] + dir[1];
                        if (nr < 0 || nc < 0 || nr >= rows || nc >= cols) continue;
                        if (seen[nr][nc] || !skin[nr][nc]) continue;
                        seen[nr][nc] = true;
                        queue.add(new int[]{nr, nc});
                    }
                }
                if (count < 3) continue;
                boxes.add(expandBox(c0 * cell, r0 * cell, Math.min(width, (c1 + 1) * cell), Math.min(height, (r1 + 1) * cell), width, height, 0.32f));
            }
        }
        return boxes;
    }

    static int[] expandBox(int x1, int y1, int x2, int y2, int width, int height, float ratio) {
        float boxW = Math.max(1f, x2 - x1);
        float boxH = Math.max(1f, y2 - y1);
        int left = Math.max(0, (int) (x1 - boxW * ratio));
        int top = Math.max(0, (int) (y1 - boxH * ratio));
        int right = Math.min(width, (int) (x2 + boxW * ratio));
        int bottom = Math.min(height, (int) (y2 + boxH * (ratio + 0.18f)));
        return new int[]{left, top, right, bottom};
    }

    private static void paintBox(Bitmap dest, int x1, int y1, int x2, int y2, String method, int block) {
        int left = Math.max(0, Math.min(x1, x2));
        int top = Math.max(0, Math.min(y1, y2));
        int right = Math.min(dest.getWidth(), Math.max(x1, x2));
        int bottom = Math.min(dest.getHeight(), Math.max(y1, y2));
        if (right - left < 4 || bottom - top < 4) return;
        if ("黑条".equals(method)) {
            Canvas canvas = new Canvas(dest);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            paint.setColor(Color.BLACK);
            canvas.drawRect(left, top, right, bottom, paint);
            return;
        }
        if ("纯色".equals(method)) {
            Canvas canvas = new Canvas(dest);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            paint.setColor(Color.argb(230, 128, 128, 128));
            canvas.drawRect(left, top, right, bottom, paint);
            return;
        }
        if ("线条".equals(method)) {
            Canvas canvas = new Canvas(dest);
            Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
            fill.setColor(Color.argb(70, 20, 20, 20));
            canvas.drawRect(left, top, right, bottom, fill);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            paint.setColor(Color.argb(220, 28, 28, 28));
            paint.setStrokeWidth(Math.max(2f, block / 6f));
            int step = Math.max(6, block / 2);
            int height = bottom - top;
            for (int x = left - height; x < right; x += step) {
                canvas.drawLine(x, top, x + height, bottom, paint);
            }
            return;
        }
        if ("表情".equals(method)) {
            Canvas canvas = new Canvas(dest);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            paint.setColor(Color.argb(200, 16, 16, 16));
            canvas.drawRect(left, top, right, bottom, paint);
            paint.setColor(Color.WHITE);
            paint.setTextAlign(Paint.Align.CENTER);
            float size = Math.max(18f, Math.min(right - left, bottom - top) * 0.58f);
            paint.setTextSize(size);
            canvas.drawText("😶", (left + right) / 2f, (top + bottom) / 2f + size / 3f, paint);
            return;
        }
        if ("模糊".equals(method)) {
            int sw = Math.max(2, (right - left) / Math.max(6, block / 2));
            int sh = Math.max(2, (bottom - top) / Math.max(6, block / 2));
            Bitmap slice = Bitmap.createBitmap(dest, left, top, right - left, bottom - top);
            Bitmap small = Bitmap.createScaledBitmap(slice, sw, sh, true);
            Bitmap blur = Bitmap.createScaledBitmap(small, right - left, bottom - top, true);
            Canvas canvas = new Canvas(dest);
            canvas.drawBitmap(blur, left, top, new Paint(Paint.FILTER_BITMAP_FLAG));
            if (slice != dest) slice.recycle();
            if (small != blur) small.recycle();
            if (blur != dest) blur.recycle();
            return;
        }
        int step = Math.max(6, block);
        for (int y = top; y < bottom; y += step) {
            int bh = Math.min(step, bottom - y);
            for (int x = left; x < right; x += step) {
                int bw = Math.min(step, right - x);
                int sample = dest.getPixel(x + bw / 2, y + bh / 2);
                int[] pixels = new int[bw * bh];
                for (int i = 0; i < pixels.length; i++) pixels[i] = sample;
                dest.setPixels(pixels, 0, bw, x, y, bw, bh);
            }
        }
    }

    static final class Result {
        final Bitmap bitmap;
        final int boxes;
        final String method;

        Result(Bitmap bitmap, int boxes, String method) {
            this.bitmap = bitmap;
            this.boxes = boxes;
            this.method = method;
        }
    }
}
