package com.genchang.player;

import android.content.Context;
import android.content.res.AssetManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/** 歌曲库：内置歌曲（assets/songs） + 用户导入（filesDir/songs）。 */
public class Songs {

    /** 用户导入歌曲的存放目录 */
    public static File dir(Context c) {
        File d = new File(c.getFilesDir(), "songs");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    private static List<String> assetSongIds(Context c) {
        List<String> out = new ArrayList<>();
        try {
            String[] kids = c.getAssets().list("songs");
            if (kids != null) for (String k : kids) out.add(k);
        } catch (IOException ignored) {}
        return out;
    }

    private static List<String> fileSongIds(File dir) {
        List<String> out = new ArrayList<>();
        File[] fs = dir.listFiles();
        if (fs != null) for (File f : fs) if (f.isDirectory()) out.add(f.getName());
        return out;
    }

    public static String listJson(Context c, File dir) {
        TreeSet<String> ids = new TreeSet<>();
        ids.addAll(assetSongIds(c));
        ids.addAll(fileSongIds(dir));
        JSONArray arr = new JSONArray();
        String[] exts = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".opus"};
        for (String id : ids) {
            File d = new File(dir, id);
            JSONObject files = new JSONObject();
            boolean hasInst = false;
            for (String stem : new String[]{"original", "instrumental", "vocals"}) {
                String found = null;
                if (d.isDirectory()) {
                    for (String e : exts) if (new File(d, stem + e).isFile()) { found = stem + e; break; }
                }
                if (found == null) {
                    for (String e : exts)
                        if (assetExists(c, "songs/" + id + "/" + stem + e)) { found = stem + e; break; }
                }
                if (found != null) {
                    try { files.put(stem, found); } catch (Exception ignored) {}
                    if (stem.equals("instrumental")) hasInst = true;
                }
            }
            if (!hasInst) continue;

            double dur = 0;
            String sub = "";
            JSONObject meta = d.isDirectory() ? readJson(new File(d, "song.json")) : null;
            if (meta == null) meta = readJsonAsset(c, "songs/" + id + "/song.json");
            if (meta != null) { dur = meta.optDouble("duration", 0); sub = meta.optString("sub", ""); }
            String durs = dur > 0 ? String.format("%d:%02d", (int) (dur / 60), (int) (dur % 60)) : "";
            try {
                JSONObject o = new JSONObject();
                o.put("id", id);
                o.put("name", id);
                o.put("sub", (durs + (sub.isEmpty() ? "" : "　" + sub)).trim());
                o.put("duration", dur);
                o.put("files", files);
                arr.put(o);
            } catch (Exception ignored) {}
        }
        return arr.toString();
    }

    /** 打开某个 stem；优先用户目录，其次内置。 */
    public static MiniHttp.Stream open(Context c, File dir, String songId, String file) {
        File f = new File(new File(dir, songId), file);
        if (f.isFile()) {
            try {
                MiniHttp.Stream s = new MiniHttp.Stream();
                s.raf = new RandomAccessFile(f, "r");
                s.length = s.raf.length();
                return s;
            } catch (IOException e) { return null; }
        }
        try {
            InputStream is = c.getAssets().open("songs/" + songId + "/" + file);
            MiniHttp.Stream s = new MiniHttp.Stream();
            s.asset = is;
            s.length = assetLength(c, "songs/" + songId + "/" + file);
            if (s.length <= 0) { s.asset.close(); return null; }
            return s;
        } catch (IOException e) { return null; }
    }

    private static long assetLength(Context c, String path) {
        try (InputStream is = c.getAssets().open(path)) {
            long n = 0;
            byte[] b = new byte[65536];
            int r;
            while ((r = is.read(b)) > 0) n += r;
            return n;
        } catch (IOException e) { return -1; }
    }

    private static boolean assetExists(Context c, String path) {
        try (InputStream is = c.getAssets().open(path)) { return true; }
        catch (IOException e) { return false; }
    }

    private static JSONObject readJson(File f) {
        if (!f.isFile()) return null;
        try (FileInputStream in = new FileInputStream(f)) {
            byte[] b = new byte[(int) f.length()];
            int off = 0, r;
            while (off < b.length && (r = in.read(b, off, b.length - off)) > 0) off += r;
            return new JSONObject(new String(b, "UTF-8"));
        } catch (Exception e) { return null; }
    }

    private static JSONObject readJsonAsset(Context c, String path) {
        try (InputStream in = c.getAssets().open(path)) {
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int r;
            while ((r = in.read(b)) > 0) bos.write(b, 0, r);
            return new JSONObject(new String(bos.toByteArray(), "UTF-8"));
        } catch (Exception e) { return null; }
    }
}
