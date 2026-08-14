package com.naixuezhang.studio.mobile;

import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.OutputStream;

final class ImageStore {
    private final Context context;
    private final File dir;

    ImageStore(Context context) {
        this.context = context.getApplicationContext();
        this.dir = new File(this.context.getFilesDir(), "outputs");
        if (!dir.exists()) dir.mkdirs();
    }

    String save(String jobId, byte[] png, boolean toGallery) throws Exception {
        String id = String.valueOf(jobId == null ? System.currentTimeMillis() : jobId);
        File file = new File(dir, id + ".png");
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(png);
        }
        if (toGallery) saveToGallery(id, png);
        return id;
    }

    File file(String id) {
        String name = String.valueOf(id == null ? "" : id).replaceAll("[^A-Za-z0-9_-]", "");
        if (name.isEmpty()) return null;
        File file = new File(dir, name + ".png");
        return file.isFile() ? file : null;
    }

    int pendingCount() {
        File[] files = dir.listFiles((d, name) -> name.endsWith(".png"));
        return files == null ? 0 : files.length;
    }

    int exportMissing() {
        File[] files = dir.listFiles((d, name) -> name.endsWith(".png"));
        if (files == null) return 0;
        int saved = 0;
        for (File file : files) {
            try {
                byte[] data = readAll(file);
                saveToGallery(file.getName().replace(".png", ""), data);
                saved += 1;
            } catch (Exception ignored) {}
        }
        return saved;
    }

    private void saveToGallery(String id, byte[] png) throws Exception {
        ContentValues values = new ContentValues();
        values.put(MediaStore.Images.Media.DISPLAY_NAME, "nai-" + id + ".png");
        values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
        if (Build.VERSION.SDK_INT >= 29) {
            values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/NaiXueZhang");
            values.put(MediaStore.Images.Media.IS_PENDING, 1);
        }
        Uri uri = context.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
        if (uri == null) throw new IllegalStateException("无法写入系统相册");
        try (OutputStream out = context.getContentResolver().openOutputStream(uri)) {
            if (out == null) throw new IllegalStateException("无法写入系统相册");
            out.write(png);
        }
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues done = new ContentValues();
            done.put(MediaStore.Images.Media.IS_PENDING, 0);
            context.getContentResolver().update(uri, done, null, null);
        }
    }

    private static byte[] readAll(File file) throws Exception {
        byte[] data = new byte[(int) file.length()];
        try (FileInputStream in = new FileInputStream(file)) {
            int n = in.read(data);
            if (n != data.length) throw new IllegalStateException("read failed");
        }
        return data;
    }
}
