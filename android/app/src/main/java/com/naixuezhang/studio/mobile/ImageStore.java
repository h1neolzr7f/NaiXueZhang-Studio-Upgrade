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
import java.util.ArrayList;
import java.util.List;

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
        write(new File(dir, id + ".png"), png);
        if (toGallery) saveToGallery(id, png);
        return id;
    }

    void saveFinal(String id, byte[] png) throws Exception {
        String name = safe(id);
        if (name.isEmpty() || png == null) return;
        write(new File(dir, name + "_final.png"), png);
    }

    byte[] read(String id) throws Exception {
        File found = file(id);
        if (found == null) return new byte[0];
        return readAll(found);
    }

    byte[] readOriginal(String id) throws Exception {
        File found = originalFile(id);
        if (found == null) return new byte[0];
        return readAll(found);
    }

    File file(String id) {
        String name = safe(id);
        if (name.isEmpty()) return null;
        File finalFile = new File(dir, name + "_final.png");
        if (finalFile.isFile()) return finalFile;
        File file = new File(dir, name + ".png");
        return file.isFile() ? file : null;
    }

    File originalFile(String id) {
        String name = safe(id);
        if (name.isEmpty()) return null;
        File file = new File(dir, name + ".png");
        return file.isFile() ? file : null;
    }

    boolean hasFinal(String id) {
        String name = safe(id);
        return !name.isEmpty() && new File(dir, name + "_final.png").isFile();
    }

    List<String> originalIds() {
        File[] files = dir.listFiles((d, name) -> name.endsWith(".png") && !name.contains("_final") && !name.contains("_up"));
        List<String> ids = new ArrayList<>();
        if (files == null) return ids;
        for (File file : files) {
            String name = file.getName();
            ids.add(name.substring(0, name.length() - 4));
        }
        return ids;
    }

    int pendingCount() {
        return originalIds().size();
    }

    int exportMissing() {
        int saved = 0;
        for (String id : originalIds()) {
            try {
                File prefer = file(id);
                if (prefer == null) continue;
                saveToGallery(prefer.getName().replace(".png", ""), readAll(prefer));
                saved += 1;
            } catch (Exception ignored) {}
        }
        return saved;
    }

    void exportOne(String id, byte[] png) throws Exception {
        saveToGallery(safe(id), png);
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

    private static void write(File file, byte[] png) throws Exception {
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(png == null ? new byte[0] : png);
        }
    }

    private static String safe(String id) {
        return String.valueOf(id == null ? "" : id).replaceAll("[^A-Za-z0-9_-]", "");
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
