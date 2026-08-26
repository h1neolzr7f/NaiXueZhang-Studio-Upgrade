package com.naixuezhang.studio.mobile;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;

import java.io.ByteArrayOutputStream;

final class PhonePipeline {
    private PhonePipeline() {}

    static byte[] process(byte[] png, boolean upscale, int scale, boolean stripMetadata) {
        if (png == null || png.length == 0) return png;
        boolean needScale = upscale && scale > 1;
        if (!needScale && !stripMetadata) return png;
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inPreferredConfig = Bitmap.Config.ARGB_8888;
        Bitmap src = BitmapFactory.decodeByteArray(png, 0, png.length, opts);
        if (src == null) return png;
        Bitmap work = src;
        if (needScale) {
            int factor = Math.max(2, Math.min(scale, 4));
            int width = Math.max(1, src.getWidth() * factor);
            int height = Math.max(1, src.getHeight() * factor);
            Bitmap scaled = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(scaled);
            Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
            canvas.drawBitmap(src, null, new android.graphics.Rect(0, 0, width, height), paint);
            if (work != src) work.recycle();
            work = scaled;
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        work.compress(Bitmap.CompressFormat.PNG, 100, out);
        if (work != src) work.recycle();
        src.recycle();
        return out.toByteArray();
    }
}
