package com.naixuezhang.studio.mobile;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;

final class DemoWorks {
    static final String WORK_ID = "demo-ark-amiya";

    private DemoWorks() {}

    static boolean isDemo(String workId) {
        return WORK_ID.equals(String.valueOf(workId == null ? "" : workId).trim());
    }

    static JSONObject searchHit() throws Exception {
        JSONObject item = payload().optJSONObject("work");
        if (item == null) item = new JSONObject();
        item.put("local", false);
        item.put("demo", true);
        item.put("title", "内置样例 · 阿米娅换角");
        return item;
    }

    static JSONObject payload() throws Exception {
        JSONObject page0 = page(
            WORK_ID + "_p0",
            0,
            "2girls, rhodes island infirmary, soft lighting, official art",
            "amiya_(arknights), 1girl, brown_hair, blue_eyes, rabbit_ears, standing",
            "kaltsit_(arknights), 1girl, white_hair, green_eyes, labcoat"
        );
        JSONObject page1 = page(
            WORK_ID + "_p1",
            1,
            "1girl, moonlight rooftop, city lights",
            "amiya_(arknights), 1girl, brown_hair, blue_eyes, looking_at_viewer, sitting",
            null
        );
        JSONArray images = new JSONArray().put(page0).put(page1);
        JSONObject work = new JSONObject();
        work.put("work_id", WORK_ID);
        work.put("id", WORK_ID);
        work.put("title", "内置样例 · 阿米娅换角");
        work.put("creator", "phone-demo");
        work.put("ai_type", "NovelAI");
        work.put("image_count", 2);
        work.put("tags", new JSONArray().put("明日方舟").put("阿米娅").put("NovelAI"));
        work.put("images", images);
        work.put("external_url", "");
        work.put("demo", true);
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("work", work);
        out.put("images", images);
        out.put("source", "phone-demo");
        out.put("demo", true);
        out.put("generation_calls", 0);
        out.put("character_candidates", new JSONArray());
        return out;
    }

    static byte[] png(int index) {
        Bitmap bitmap = Bitmap.createBitmap(640, 960, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(index == 0 ? 0xFF3D2A78 : 0xFF1A3A5C);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(0xFFF4D27A);
        paint.setTextSize(42);
        canvas.drawText(index == 0 ? "样例 P1" : "样例 P2", 48, 140, paint);
        paint.setColor(0xFFFFF4E8);
        paint.setTextSize(28);
        canvas.drawText("不连网也能换角", 48, 200, paint);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, out);
        bitmap.recycle();
        return out.toByteArray();
    }

    private static JSONObject page(String imageId, int index, String base, String slot0, String slot1) throws Exception {
        JSONArray slots = new JSONArray();
        JSONObject first = new JSONObject();
        first.put("char_caption", slot0);
        first.put("centers", new JSONArray().put(new JSONObject().put("x", 0.32).put("y", 0.5)));
        slots.put(first);
        if (slot1 != null) {
            JSONObject second = new JSONObject();
            second.put("char_caption", slot1);
            second.put("centers", new JSONArray().put(new JSONObject().put("x", 0.68).put("y", 0.5)));
            slots.put(second);
        }
        JSONObject caption = new JSONObject();
        caption.put("base_caption", base);
        caption.put("char_captions", slots);
        JSONObject v4 = new JSONObject();
        v4.put("caption", caption);
        v4.put("use_coords", true);
        JSONObject comment = new JSONObject();
        comment.put("prompt", base);
        comment.put("width", 832);
        comment.put("height", 1216);
        comment.put("steps", 28);
        comment.put("scale", 5);
        comment.put("sampler", "k_euler_ancestral");
        comment.put("model", "nai-diffusion-4-5-full");
        comment.put("Source", "nai-diffusion-4-5-full");
        comment.put("negative_prompt", "lowres, bad anatomy, worst quality");
        comment.put("v4_prompt", v4);
        JSONObject image = new JSONObject();
        image.put("image_id", imageId);
        image.put("id", imageId);
        image.put("page_index", index);
        image.put("work_id", WORK_ID);
        image.put("width", 832);
        image.put("height", 1216);
        image.put("model", "nai-diffusion-4-5-full");
        image.put("prompt_text", base);
        image.put("ai_json", new JSONObject().put("Comment", comment));
        image.put("url", "/api/mobile/demo/image/" + index);
        image.put("thumbnail_url", "/api/mobile/demo/image/" + index);
        return image;
    }
}
