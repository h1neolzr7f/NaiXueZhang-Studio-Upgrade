package com.naixuezhang.studio.mobile;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

final class CharLibrary {
    private final JSONObject presets;
    private final JSONObject ark;
    private final JSONObject aliases;
    private final JSONObject seriesAliases;
    private final JSONObject tagDict;
    private final CustomCharStore custom;
    private final Context context;
    private List<String> danbooru;
    private Map<String, List<String>> prefixIndex;
    private Map<String, List<String>> seriesIndex;
    private Map<String, String> cnMap;
    private Set<String> copyrights;
    private final Map<String, JSONArray> searchCache = new HashMap<>();

    CharLibrary(Context context, CustomCharStore custom) {
        this.context = context.getApplicationContext();
        this.custom = custom;
        presets = readAssetObject(this.context, "data/char_presets.json");
        ark = readAssetObject(this.context, "data/ark_char_library.json");
        aliases = readAssetObject(this.context, "data/ark_cn_aliases.json");
        seriesAliases = readAssetObject(this.context, "data/phone_series_aliases.json");
        tagDict = readAssetObject(this.context, "data/tag_dict.json");
    }

    void warmup() {
        ensureDanbooru();
    }

    JSONObject listPresets(String gender) {
        JSONArray items = presets.optJSONArray(normalizeGender(gender, "female"));
        if (items == null) items = new JSONArray();
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("presets", items);
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject searchAll(String gender, String query, int limit) {
        return searchAll(gender, query, limit, "");
    }

    JSONObject searchAll(String gender, String query, int limit, String source) {
        String bucket = normalizeGender(gender, "female");
        String needle = String.valueOf(query == null ? "" : query).trim().toLowerCase(Locale.ROOT);
        String src = normalizeSource(source);
        int cap = Math.max(1, Math.min(limit <= 0 ? 24 : limit, 80));
        JSONArray items = new JSONArray();
        try {
            if ("all".equals(src) || "oc".equals(src)) {
                JSONArray customItems = custom == null ? new JSONArray() : custom.list(bucket).optJSONArray("items");
                if (customItems != null) {
                    for (int i = 0; i < customItems.length() && items.length() < cap; i++) {
                        JSONObject item = customItems.optJSONObject(i);
                        if (item == null) continue;
                        if (!needle.isEmpty() && !hay(item).contains(needle)) continue;
                        items.put(wrap(item, "custom:" + bucket + ":" + item.optString("id"), "OC"));
                    }
                }
            }
            if ("all".equals(src)) {
                JSONArray presets = this.presets.optJSONArray(bucket);
                if (presets != null) {
                    for (int i = 0; i < presets.length() && items.length() < cap; i++) {
                        JSONObject item = presets.optJSONObject(i);
                        if (item == null) continue;
                        if (!needle.isEmpty() && !hay(item).contains(needle)) continue;
                        items.put(wrap(item, "preset:" + bucket + ":" + item.optString("id"), "常用角色"));
                    }
                }
            }
            if ("all".equals(src) || "ark".equals(src)) {
                JSONArray arkItems = searchArk(bucket, query, cap).optJSONArray("items");
                if (arkItems != null) {
                    for (int i = 0; i < arkItems.length() && items.length() < cap; i++) {
                        JSONObject item = arkItems.optJSONObject(i);
                        if (item == null) continue;
                        items.put(wrap(item, "ark:" + bucket + ":" + item.optString("id"), "明日方舟库"));
                    }
                }
            }
            if (("all".equals(src) || "danbooru".equals(src)) && items.length() < cap && needle.length() >= 1) {
                int room = "danbooru".equals(src) ? cap : cap - items.length();
                JSONArray dan = searchDanbooru(bucket, needle, room);
                for (int i = 0; i < dan.length() && items.length() < cap; i++) {
                    items.put(dan.opt(i));
                }
            }
        } catch (Exception ignored) {}
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("q", query == null ? "" : query);
            out.put("gender", bucket);
            out.put("source", src);
            out.put("total", items.length());
            out.put("items", items);
        } catch (Exception ignored) {}
        return out;
    }

    private JSONObject wrap(JSONObject item, String referenceId, String source) throws Exception {
        JSONObject out = new JSONObject();
        out.put("reference_id", referenceId);
        out.put("label", JsonUtil.first(item, "label", "name", "id"));
        out.put("source", source);
        out.put("record", item);
        return out;
    }

    JSONObject searchArk(String gender, String query, int limit) {
        String bucket = normalizeGender(gender, "female");
        JSONArray pool = ark.optJSONArray(bucket);
        if (pool == null) pool = new JSONArray();
        String needle = String.valueOf(query == null ? "" : query).trim().toLowerCase(Locale.ROOT);
        int cap = Math.max(1, Math.min(limit <= 0 ? 20 : limit, 200));
        JSONArray items = new JSONArray();
        for (int i = 0; i < pool.length() && items.length() < cap; i++) {
            JSONObject item = pool.optJSONObject(i);
            if (item == null) continue;
            if (needle.isEmpty() || hay(item).contains(needle)) items.put(item);
        }
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("q", query == null ? "" : query);
            out.put("gender", bucket);
            out.put("total", items.length());
            out.put("items", items);
        } catch (Exception ignored) {}
        return out;
    }

    JSONObject resolve(String referenceId) {
        String[] parts = String.valueOf(referenceId == null ? "" : referenceId).split(":", 3);
        if (parts.length != 3) return null;
        String kind = parts[0];
        String gender = normalizeGender(parts[1], "");
        String id = parts[2];
        if (gender.isEmpty() || id.isEmpty()) return null;
        if ("custom".equals(kind) && custom != null) {
            return custom.get(gender, id);
        }
        if ("danbooru".equals(kind)) {
            return danbooruRecord(gender, id);
        }
        JSONArray pool;
        if ("preset".equals(kind)) {
            pool = presets.optJSONArray(gender);
        } else if ("ark".equals(kind)) {
            pool = ark.optJSONArray(gender);
        } else {
            return null;
        }
        if (pool == null) return null;
        for (int i = 0; i < pool.length(); i++) {
            JSONObject item = pool.optJSONObject(i);
            if (item != null && id.equals(JsonUtil.str(item, "id"))) return item;
        }
        return null;
    }

    private JSONArray searchDanbooru(String gender, String needle, int limit) {
        JSONArray items = new JSONArray();
        ensureDanbooru();
        if (danbooru == null || danbooru.isEmpty()) return items;
        String cacheKey = gender + "|" + needle + "|" + limit;
        synchronized (searchCache) {
            JSONArray cached = searchCache.get(cacheKey);
            if (cached != null) return cached;
        }
        String compact = needle.replace(' ', '_');
        String alias = resolveAlias(needle);
        String series = "";
        if (!alias.isEmpty()) {
            if (copyrights != null && copyrights.contains(alias)) series = alias;
            else compact = alias;
        }
        if (series.isEmpty()) series = seriesOfCopyright(compact);
        final String compactKey = compact;
        final String seriesKey = series;
        try {
            List<String> pool = candidates(compactKey, seriesKey);
            List<String> hits = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            int capHits = Math.max(80, limit * 8);
            for (String tag : pool) {
                if (!seen.add(tag)) continue;
                String name = nameOf(tag);
                boolean nameHit = !compactKey.isEmpty() && (
                    tag.equals(compactKey)
                    || tag.startsWith(compactKey + "_(")
                    || name.equals(compactKey)
                    || name.startsWith(compactKey)
                    || (compactKey.length() >= 3 && name.contains(compactKey))
                );
                boolean seriesHit = !seriesKey.isEmpty() && (tag.endsWith("_(" + seriesKey + ")") || tag.contains(seriesKey));
                if (nameHit || seriesHit) hits.add(tag);
                if (hits.size() >= capHits) break;
            }
            hits.sort((a, b) -> {
                int sa = rank(a, compactKey, seriesKey);
                int sb = rank(b, compactKey, seriesKey);
                if (sa != sb) return Integer.compare(sa, sb);
                int len = Integer.compare(nameOf(a).length(), nameOf(b).length());
                if (len != 0) return len;
                return a.compareTo(b);
            });
            for (int i = 0; i < hits.size() && items.length() < limit; i++) {
                String tag = hits.get(i);
                items.put(wrap(danbooruRecord(gender, tag), "danbooru:" + gender + ":" + tag, "D 站角色库"));
            }
            synchronized (searchCache) {
                if (searchCache.size() > 64) searchCache.clear();
                searchCache.put(cacheKey, items);
            }
        } catch (Exception ignored) {}
        return items;
    }

    private List<String> candidates(String compact, String series) {
        List<String> pool = new ArrayList<>();
        if (!series.isEmpty() && seriesIndex != null) {
            List<String> seriesHits = seriesIndex.get(series);
            if (seriesHits != null) pool.addAll(seriesHits);
        }
        if (compact.length() >= 2 && prefixIndex != null) {
            List<String> prefixHits = prefixIndex.get(compact.substring(0, 2));
            if (prefixHits != null) pool.addAll(prefixHits);
        } else if (compact.length() == 1 && prefixIndex != null) {
            List<String> prefixHits = prefixIndex.get(compact);
            if (prefixHits != null) pool.addAll(prefixHits);
        }
        if (pool.isEmpty() && compact.length() >= 4) return danbooru;
        return pool;
    }

    private String resolveAlias(String needle) {
        if (needle == null || needle.isEmpty()) return "";
        if (cnMap != null) {
            String mapped = cnMap.get(needle);
            if (mapped != null && !mapped.isEmpty()) return mapped;
        }
        String direct = seriesAliases.optString(needle);
        if (!direct.isEmpty()) return direct.toLowerCase(Locale.ROOT);
        boolean chinese = looksChinese(needle);
        String bestKey = "";
        String bestVal = "";
        Iterator<String> keys = seriesAliases.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            String lk = key.toLowerCase(Locale.ROOT);
            if (lk.isEmpty()) continue;
            boolean hit = needle.contains(lk)
                || ((chinese || needle.length() >= 2) && lk.startsWith(needle))
                || (chinese && lk.contains(needle));
            if (!hit) continue;
            if (lk.length() >= bestKey.length()) {
                bestKey = lk;
                bestVal = seriesAliases.optString(key).toLowerCase(Locale.ROOT);
            }
        }
        if (!bestVal.isEmpty()) return bestVal;
        if (cnMap != null && chinese) {
            for (Map.Entry<String, String> entry : cnMap.entrySet()) {
                String key = entry.getKey();
                if (key == null || key.isEmpty()) continue;
                if (key.contains(needle) || needle.contains(key)) {
                    if (key.length() >= bestKey.length()) {
                        bestKey = key;
                        bestVal = entry.getValue();
                    }
                }
            }
        }
        return bestVal == null ? "" : bestVal;
    }

    private String seriesOfCopyright(String compact) {
        if (copyrights != null && copyrights.contains(compact)) return compact;
        return "";
    }

    private static final String[] POPULAR = {
        "vocaloid", "genshin_impact", "arknights", "honkai:_star_rail", "honkai", "azur_lane",
        "fate", "pokemon", "umamusume", "girls'_frontline", "blue_archive", "zenless_zone_zero",
        "wuthering_waves", "nikke", "idolmaster", "love_live!", "bang_dream!", "kancolle"
    };

    private static int rank(String tag, String compact, String series) {
        String name = nameOf(tag);
        String ser = seriesOf(tag);
        int junk = (name.contains("abyss") || name.contains("slime") || name.contains("hilichurl")
            || name.contains("samachurl") || name.contains("mitachurl") || name.contains("spectator")
            || name.contains("npc") || name.contains("monster") || name.contains("enemy")
            || name.contains("cosplay") || ser.contains("meme")) ? 10 : 0;
        if (!compact.isEmpty() && tag.equals(compact)) return junk;
        if (!compact.isEmpty() && name.equals(compact) && isPopular(ser)) return 1 + junk;
        if (!compact.isEmpty() && (name.equals(compact) || tag.startsWith(compact + "_("))) return 2 + junk;
        if (!compact.isEmpty() && name.startsWith(compact)) return 3 + junk;
        int tokens = 0;
        for (int i = 0; i < name.length(); i++) if (name.charAt(i) == '_') tokens++;
        if (!series.isEmpty() && tag.endsWith("_(" + series + ")")) return 4 + junk + Math.min(tokens, 3);
        if (!series.isEmpty() && tag.contains(series)) return 7 + junk;
        return 8 + junk;
    }

    private static boolean isPopular(String series) {
        if (series == null || series.isEmpty()) return false;
        for (String item : POPULAR) {
            if (series.equals(item) || series.startsWith(item)) return true;
        }
        return false;
    }

    private static String nameOf(String tag) {
        String raw = String.valueOf(tag == null ? "" : tag);
        int open = raw.lastIndexOf("_(");
        return open > 0 ? raw.substring(0, open) : raw;
    }

    private static String seriesOf(String tag) {
        String raw = String.valueOf(tag == null ? "" : tag);
        int open = raw.lastIndexOf("_(");
        if (open > 0 && raw.endsWith(")")) return raw.substring(open + 2, raw.length() - 1);
        return "";
    }

    private JSONObject danbooruRecord(String gender, String tag) {
        JSONObject item = new JSONObject();
        try {
            String bucket = normalizeGender(gender, "female");
            String[] parts = splitTag(tag);
            item.put("id", tag);
            item.put("label", parts[0] + (parts[1].isEmpty() ? "" : " · " + parts[1]));
            item.put("gender", bucket);
            item.put("tag", tag);
            item.put("kind", "danbooru");
            item.put("source", "danbooru");
            JSONArray identity = new JSONArray();
            identity.put("male".equals(bucket) ? "1boy" : "1girl");
            identity.put(tag);
            item.put("identity", identity);
            item.put("appearance", new JSONArray());
            item.put("body", new JSONArray());
        } catch (Exception ignored) {}
        return item;
    }

    private static String[] splitTag(String tag) {
        String raw = String.valueOf(tag == null ? "" : tag);
        int open = raw.lastIndexOf("_(");
        if (open > 0 && raw.endsWith(")")) {
            String name = raw.substring(0, open).replace('_', ' ');
            String series = raw.substring(open + 2, raw.length() - 1).replace('_', ' ');
            return new String[]{name, series};
        }
        return new String[]{raw.replace('_', ' '), ""};
    }

    private synchronized void ensureDanbooru() {
        if (danbooru != null) return;
        List<String> tags = readLines("data/phone_char_index.txt");
        if (tags.isEmpty()) tags = readCharactersFromPack();
        Map<String, List<String>> prefixes = new HashMap<>();
        Map<String, List<String>> seriesMap = new HashMap<>();
        for (String tag : tags) {
            String name = nameOf(tag);
            if (name.length() >= 1) {
                String one = name.substring(0, 1);
                List<String> oneBucket = prefixes.get(one);
                if (oneBucket == null) {
                    oneBucket = new ArrayList<>();
                    prefixes.put(one, oneBucket);
                }
                if (oneBucket.size() < 400) oneBucket.add(tag);
            }
            if (name.length() >= 2) {
                String prefix = name.substring(0, 2);
                List<String> bucket = prefixes.get(prefix);
                if (bucket == null) {
                    bucket = new ArrayList<>();
                    prefixes.put(prefix, bucket);
                }
                bucket.add(tag);
            }
            String series = seriesOf(tag);
            if (!series.isEmpty()) {
                List<String> bucket = seriesMap.get(series);
                if (bucket == null) {
                    bucket = new ArrayList<>();
                    seriesMap.put(series, bucket);
                }
                bucket.add(tag);
            }
        }
        danbooru = tags;
        prefixIndex = prefixes;
        seriesIndex = seriesMap;
        cnMap = buildCnMap();
        copyrights = new HashSet<>(readLines("data/phone_copyright_index.txt"));
        if (copyrights.isEmpty()) {
            JSONObject pack = readAssetObject(context, "data/char_tag_index.json");
            JSONArray raw = pack.optJSONArray("copyrights");
            if (raw != null) {
                for (int i = 0; i < raw.length(); i++) copyrights.add(String.valueOf(raw.opt(i)).toLowerCase(Locale.ROOT));
            }
        }
    }

    private Map<String, String> buildCnMap() {
        Map<String, String> map = new HashMap<>();
        Iterator<String> keys = seriesAliases.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            String value = seriesAliases.optString(key);
            if (!key.isEmpty() && !value.isEmpty()) map.put(key.toLowerCase(Locale.ROOT), value.toLowerCase(Locale.ROOT));
        }
        if (tagDict != null) {
            Iterator<String> dictKeys = tagDict.keys();
            while (dictKeys.hasNext()) {
                String key = dictKeys.next();
                String cn = tagDict.optString(key).trim().toLowerCase(Locale.ROOT);
                if (cn.length() < 2 || cn.length() > 8) continue;
                if (!looksChinese(cn)) continue;
                map.putIfAbsent(cn, key.toLowerCase(Locale.ROOT).replace(' ', '_'));
            }
        }
        return map;
    }

    private static boolean looksChinese(String text) {
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch >= 0x4e00 && ch <= 0x9fff) return true;
        }
        return false;
    }

    private List<String> readCharactersFromPack() {
        List<String> tags = new ArrayList<>();
        JSONObject pack = readAssetObject(context, "data/char_tag_index.json");
        JSONArray raw = pack.optJSONArray("characters");
        if (raw == null) return tags;
        for (int i = 0; i < raw.length(); i++) {
            String tag = String.valueOf(raw.opt(i)).trim().toLowerCase(Locale.ROOT);
            if (!tag.isEmpty() && tag.length() <= 96) tags.add(tag);
        }
        return tags;
    }

    private List<String> readLines(String name) {
        List<String> tags = new ArrayList<>();
        try (InputStream in = context.getAssets().open(name);
             BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String tag = line.trim().toLowerCase(Locale.ROOT);
                if (!tag.isEmpty()) tags.add(tag);
            }
        } catch (Exception ignored) {}
        return tags;
    }

    private String hay(JSONObject item) {
        List<String> bits = new ArrayList<>();
        bits.add(JsonUtil.str(item, "label"));
        bits.add(JsonUtil.str(item, "tag"));
        bits.add(JsonUtil.str(item, "id"));
        String tag = JsonUtil.str(item, "tag");
        if (tag.endsWith("_(arknights)")) bits.add(tag.substring(0, tag.length() - "_(arknights)".length()));
        JSONArray identity = item.optJSONArray("identity");
        if (identity != null) {
            for (int i = 0; i < identity.length(); i++) bits.add(String.valueOf(identity.opt(i)));
        }
        JSONArray extra = aliases.optJSONArray(tag);
        if (extra != null) {
            for (int i = 0; i < extra.length(); i++) bits.add(String.valueOf(extra.opt(i)));
        }
        return String.join(" ", bits).toLowerCase(Locale.ROOT);
    }

    private static String normalizeGender(String gender, String fallback) {
        String value = String.valueOf(gender == null ? "" : gender).trim().toLowerCase(Locale.ROOT);
        if ("male".equals(value) || "female".equals(value)) return value;
        return fallback;
    }

    private static String normalizeSource(String source) {
        String value = String.valueOf(source == null ? "" : source).trim().toLowerCase(Locale.ROOT);
        if (value.isEmpty() || "all".equals(value) || "全部".equals(value)) return "all";
        if ("oc".equals(value) || "custom".equals(value) || "我的角色".equals(value)) return "oc";
        if ("ark".equals(value) || "arknights".equals(value) || "明日方舟".equals(value) || "明日方舟库".equals(value)) return "ark";
        if ("danbooru".equals(value) || "d".equals(value) || "d站".equals(value)) return "danbooru";
        return "all";
    }

    private static JSONObject readAssetObject(Context context, String name) {
        try (InputStream in = context.getAssets().open(name);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) >= 0) out.write(buf, 0, n);
            return new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            return new JSONObject();
        }
    }
}
