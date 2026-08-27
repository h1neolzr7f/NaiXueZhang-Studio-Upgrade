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
    static final String[] METHODS = {"像素", "模糊", "纯色"};

    private LightMosaic() {}

    static String normalizeMethod(String raw) {
        String method = raw == null ? "" : raw.trim();
        if ("模糊".equals(method) || "blur".equalsIgnoreCase(method)) return "模糊";
        if ("纯色".equals(method) || "solid".equalsIgnoreCase(method) || "color".equalsIgnoreCase(method)) {
            return "纯色";
        }
        return "像素";
    }

    static int normalizeIntensity(int intensity) {
        return Math.max(12, Math.min(intensity <= 0 ? 36 : intensity, 72));
    }

    static Result apply(Bitmap src, String method, int intensity) {
        if (src == null) return new Result(null, 0, normalizeMethod(method));
        String kind = normalizeMethod(method);
        int strength = normalizeIntensity(intensity);
        List<int[]> boxes = OnnxCensor.detectOrFallback(src);
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
        if ("纯色".equals(method)) {
            Canvas canvas = new Canvas(dest);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            paint.setColor(Color.argb(230, 128, 128, 128));
            canvas.drawRect(left, top, right, bottom, paint);
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
